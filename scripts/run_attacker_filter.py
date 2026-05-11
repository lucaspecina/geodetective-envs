"""Atacante adversarial barato: filtro per-foto del sample diverso (#24).

Para cada foto del sample (#17 → E007), corre N=3 llamadas a GPT-4o sin tools,
solo con la imagen + prompt mínimo. Si en ALGUNA de las 3 el modelo predice a
menos de 10 km del lugar real con confianza media o alta, la foto se considera
"trampeable" (el modelo la sabe de memoria) y se descarta del corpus.

Threshold canon (epic #21, decisión 2026-05-11):
    dist_min < 10 km AND confidence >= media → reject_attacker

Output:
- `experiments/E004_attacker_filter/results.json`: lista completa con runs.
- `experiments/E004_attacker_filter/photos/`: imágenes limpiadas (cache).

Uso:
    python scripts/run_attacker_filter.py
    N_WORKERS=8 python scripts/run_attacker_filter.py
    MAX_PHOTOS=10 python scripts/run_attacker_filter.py   # smoke test
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from geopy.distance import geodesic
from openai import OpenAI

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.corpus import CLEAN_VERSION, clean_image

# === Config ===
INPUT = Path("experiments/E007_sample_diverso/candidates.json")
EXP = Path("experiments/E004_attacker_filter")
PHOTOS = EXP / "photos"
OUT_JSON = EXP / "results.json"

N_RUNS = int(os.environ.get("N_RUNS", "3"))
ATTACKER_MODEL = os.environ.get("ATTACKER_MODEL", "gpt-4o")
N_WORKERS = int(os.environ.get("N_WORKERS", "5"))
MAX_PHOTOS = int(os.environ.get("MAX_PHOTOS", "0"))  # 0 = todas
DIST_THRESHOLD_KM = 10.0
CONF_TRAMPEABLE = {"media", "alta"}
ATTACKER_PROMPT_VERSION = "v1"

# === Load .env ===
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

PHOTOS.mkdir(parents=True, exist_ok=True)

PROMPT = """Ubicá esta fotografía con la mayor precisión posible.

Decime:
1. ¿Dónde fue tomada? (ciudad, país, año aproximado, coordenadas si podés)
2. ¿Qué pistas usaste para llegar a eso?
3. ¿Qué tan confiada estás de tu respuesta? (alta/media/baja)
4. ¿Hay info faltante que necesitarías para estar más segura?

NO intentes buscar la imagen en internet, solo razoná con lo que ves.
Respondé en español y en JSON con keys: location, lat, lon, year, reasoning, confidence, missing_info.
"""


def make_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
    )


def download_photo(c: dict) -> Path | None:
    """Bajar la foto y limpiarla (strip EXIF + crop watermark)."""
    url = c["file_url"]
    out_raw = PHOTOS / f"{c['cid']}_raw.jpg"
    out_clean = PHOTOS / f"{c['cid']}_clean_v{CLEAN_VERSION}.jpg"
    if out_clean.exists():
        return out_clean
    try:
        r = httpx.get(url, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        out_raw.write_bytes(r.content)
        result = clean_image(
            raw_path=out_raw,
            provider=c.get("provider", "pastvu"),
            provider_meta={"waterh": c.get("waterh"), "h": c.get("h")},
            out_dir=PHOTOS,
        )
        if result.path is None:
            print(f"  ⚠️  clean_image descartó #{c['cid']}: {result.notes}")
            return None
        return result.path
    except Exception as e:
        print(f"  ⚠️  download failed #{c['cid']}: {e}")
        return None


def call_model(client: OpenAI, image_path: Path) -> str:
    img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=ATTACKER_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }],
                max_completion_tokens=2000,
                timeout=60.0,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            if attempt == 2:
                return f"ERROR: {e}"
            time.sleep(2 ** attempt)
    return "ERROR: exhausted"


def parse_response(content: str) -> dict:
    if not content or content.startswith("ERROR"):
        return {}
    m = re.search(r"\{[\s\S]*\}", content)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def process_one(c: dict, client: OpenAI) -> dict:
    img_path = download_photo(c)
    if not img_path:
        return {**c, "decision": "skip",
                "reject_reason": "download_or_clean_failed",
                "runs": [], "stats": {},
                "attacker_model": ATTACKER_MODEL,
                "attacker_prompt_version": ATTACKER_PROMPT_VERSION}

    truth = c["geo"]
    runs = []
    for _ in range(N_RUNS):
        raw = call_model(client, img_path)
        parsed = parse_response(raw)
        pred_lat = parsed.get("lat")
        pred_lon = parsed.get("lon")
        dist_km = None
        if pred_lat is not None and pred_lon is not None:
            try:
                dist_km = geodesic(truth, (float(pred_lat), float(pred_lon))).km
            except (ValueError, TypeError):
                pass
        conf = (parsed.get("confidence") or "").strip().lower()
        runs.append({
            "raw_response": raw,
            "parsed": parsed,
            "distance_km": dist_km,
            "confidence": conf,
        })

    dists = [r["distance_km"] for r in runs if r["distance_km"] is not None]
    confs = [r["confidence"] for r in runs if r["confidence"]]
    stats = {
        "dist_min": min(dists) if dists else None,
        "dist_median": sorted(dists)[len(dists) // 2] if dists else None,
        "dist_max": max(dists) if dists else None,
        "n_with_coords": len(dists),
        "confidences": confs,
    }

    # Decisión: trampeable si CUALQUIER run cumple (dist<10 AND conf>=media).
    # Guardamos qué runs dispararon (Codex review): si una sola corrida la
    # clava confiando, eso ya es señal — pero también informativo si las 3 sí.
    triggering = []
    for idx, r in enumerate(runs):
        d, conf = r["distance_km"], r["confidence"]
        if d is not None and d < DIST_THRESHOLD_KM and conf in CONF_TRAMPEABLE:
            triggering.append({"run_idx": idx, "dist_km": d, "confidence": conf})
    if triggering:
        decision = "reject_attacker"
        first = triggering[0]
        reject_reason = (
            f"dist={first['dist_km']:.1f}km AND conf={first['confidence']}; "
            f"{len(triggering)}/{N_RUNS} runs triggered"
        )
    else:
        decision = "keep"
        reject_reason = None

    return {
        **c,
        "runs": runs,
        "stats": stats,
        "decision": decision,
        "reject_reason": reject_reason,
        "triggering_runs": triggering,
        "attacker_model": ATTACKER_MODEL,
        "attacker_prompt_version": ATTACKER_PROMPT_VERSION,
    }


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f"missing input: {INPUT}. Run sample_diverso.py first.")
    candidates = json.loads(INPUT.read_text())
    if MAX_PHOTOS > 0:
        candidates = candidates[:MAX_PHOTOS]
    print(f"loaded {len(candidates)} candidates")
    print(f"config: model={ATTACKER_MODEL} N_RUNS={N_RUNS} N_WORKERS={N_WORKERS}")
    print(f"threshold: dist<{DIST_THRESHOLD_KM}km AND conf in {sorted(CONF_TRAMPEABLE)}")
    print()

    t0 = time.time()
    client = make_client()  # thread-safe per OpenAI SDK
    results: list[dict] = []
    cid_to_idx = {c["cid"]: i for i, c in enumerate(candidates)}

    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = [pool.submit(process_one, c, client) for c in candidates]
        done = 0
        for fut in as_completed(futures):
            done += 1
            res = fut.result()
            results.append(res)
            s = res.get("stats", {})
            d = s.get("dist_min")
            d_s = f"{d:>5.0f}km" if d is not None else "  N/A"
            confs = s.get("confidences", [])
            cs = "/".join(confs) if confs else "-"
            tag = "❌" if res["decision"] == "reject_attacker" else (
                "⏭️" if res["decision"] == "skip" else "✓"
            )
            bucket = f"{res['bucket_pais']:<15}/{res['bucket_decada']:<6}"
            print(f"[{done:>3}/{len(candidates)}] {tag} #{res['cid']:<8} {bucket} dist={d_s} conf={cs:<22} {res['decision']}")

    # Reorder by original index
    results.sort(key=lambda r: cid_to_idx.get(r["cid"], 99999))

    OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    elapsed = time.time() - t0
    print(f"\nwrote {OUT_JSON} ({elapsed:.0f}s for {len(results)} fotos)")

    decisions = Counter(r["decision"] for r in results)
    kept = decisions.get("keep", 0)
    rejected = decisions.get("reject_attacker", 0)
    skipped = decisions.get("skip", 0)

    print(f"\n=== Decisiones ===")
    print(f"  keep:            {kept:>3} ({100*kept/len(results):.1f}%)")
    print(f"  reject_attacker: {rejected:>3} ({100*rejected/len(results):.1f}%)")
    print(f"  skip (download): {skipped:>3} ({100*skipped/len(results):.1f}%)")

    print(f"\n=== Por bucket pais ===")
    by_p_total: Counter[str] = Counter()
    by_p_keep: Counter[str] = Counter()
    by_p_rej: Counter[str] = Counter()
    for r in results:
        p = r["bucket_pais"]
        by_p_total[p] += 1
        if r["decision"] == "keep": by_p_keep[p] += 1
        elif r["decision"] == "reject_attacker": by_p_rej[p] += 1
    for p in sorted(by_p_total):
        n = by_p_total[p]
        print(f"  {p:<18} total={n:>3}  keep={by_p_keep[p]:>3}  reject={by_p_rej[p]:>3}  reject_rate={100*by_p_rej[p]/n:>5.1f}%")

    print(f"\n=== Por bucket decada ===")
    by_d_total: Counter[str] = Counter()
    by_d_keep: Counter[str] = Counter()
    by_d_rej: Counter[str] = Counter()
    for r in results:
        d = r["bucket_decada"]
        by_d_total[d] += 1
        if r["decision"] == "keep": by_d_keep[d] += 1
        elif r["decision"] == "reject_attacker": by_d_rej[d] += 1
    for d in sorted(by_d_total):
        n = by_d_total[d]
        print(f"  {d:<8} total={n:>3}  keep={by_d_keep[d]:>3}  reject={by_d_rej[d]:>3}  reject_rate={100*by_d_rej[d]/n:>5.1f}%")


if __name__ == "__main__":
    main()
