"""E012: ablation de min_steps. Comparar el agente libre vs forzado a hacer >=N steps.

Samplea N fotos random del corpus blurreado, corre el agente con varios valores de
min_steps y guarda los resultados separados para comparar.

Uso:
    # Sample 10 fotos random, run con min_steps in [0, 15, 30]
    python scripts/run_e012_min_steps.py

    # Custom
    MODEL=gpt-5.4-mini N=10 MIN_STEPS_LIST="0,30" SEED=42 python scripts/run_e012_min_steps.py

Output: experiments/E012_min_steps/results_{model}_min{N}.json
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path("src").resolve()))
from geopy.distance import geodesic

from geodetective.agents.react import run_react_agent
from geodetective.corpus import CLEAN_VERSION


# === Config ===
EXP_DIR = Path("experiments/E012_min_steps")
PHOTOS_SOURCE_BLURRED = Path("experiments/E011_text_overlay_detection/sample185_sonnet/blurred")
PHOTOS_STAGED = EXP_DIR / "photos"  # cid_clean_v1.jpg aquí (naming-compatible con react agent)
CANDIDATES_SOURCE = Path("experiments/E007_sample_diverso/candidates.json")
PICKED_FILE = EXP_DIR / "picked_photos.json"

MODEL = os.environ.get("MODEL", "gpt-5.4-mini")
N_PHOTOS = int(os.environ.get("N", "10"))
SEED = int(os.environ.get("SEED", "42"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "50"))
MIN_STEPS_LIST = [int(x) for x in os.environ.get("MIN_STEPS_LIST", "0,15,30").split(",")]
N_WORKERS = int(os.environ.get("N_WORKERS", "3"))
PROMPT_VERSION = "v3_thinking_visible"


def stage_photos(picked: list[dict]) -> None:
    """Copia las fotos seleccionadas del pool blurreado al dir staged con naming compatible."""
    PHOTOS_STAGED.mkdir(parents=True, exist_ok=True)
    for c in picked:
        cid = c["cid"]
        src = PHOTOS_SOURCE_BLURRED / f"{cid}.jpg"
        dst = PHOTOS_STAGED / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
        if not src.exists():
            print(f"  [warn] missing source: {src}")
            continue
        if not dst.exists():
            dst.write_bytes(src.read_bytes())


def pick_random_photos() -> list[dict]:
    """Samplea N cids random del candidates.json, filtrando los que tienen foto en el pool."""
    if PICKED_FILE.exists():
        print(f"reusing picked: {PICKED_FILE}")
        return json.loads(PICKED_FILE.read_text(encoding="utf-8"))

    candidates = json.loads(CANDIDATES_SOURCE.read_text(encoding="utf-8"))
    # Solo fotos que tienen su versión blureada en el pool
    pool_cids = {p.stem for p in PHOTOS_SOURCE_BLURRED.glob("*.jpg")}
    available = [c for c in candidates if str(c["cid"]) in pool_cids]
    print(f"available in blurred pool: {len(available)}/{len(candidates)}")

    random.seed(SEED)
    picked = random.sample(available, min(N_PHOTOS, len(available)))

    # Normalizar metadata para react agent
    out = []
    for c in picked:
        out.append({
            "cid": c["cid"],
            "geo": c.get("geo"),
            "year": c.get("year"),
            "year2": c.get("year2"),
            "country": c.get("country"),
            "zone": c.get("title", "")[:50] or c.get("country", "?"),
            "title": c.get("title", ""),
            "provider": c.get("provider"),
            "provenance_source": c.get("provenance_source", ""),
            "bucket_pais": c.get("bucket_pais"),
            "bucket_decada": c.get("bucket_decada"),
        })

    EXP_DIR.mkdir(parents=True, exist_ok=True)
    PICKED_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {PICKED_FILE} with {len(out)} fotos")
    return out


def process_one(candidate: dict, min_steps: int) -> dict:
    cid = candidate["cid"]
    img_path = PHOTOS_STAGED / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
    if not img_path.exists():
        return {**candidate, "react": {"error": f"image not found: {img_path}", "model": MODEL}}

    t0 = time.time()
    try:
        res = run_react_agent(
            image_path=img_path,
            model=MODEL,
            max_steps=MAX_STEPS,
            min_steps=min_steps,
            verbose=False,
            provider=candidate.get("provider"),
            provenance_source=candidate.get("provenance_source"),
        )
    except Exception as e:
        return {**candidate, "react": {
            "model": MODEL, "max_steps": MAX_STEPS, "min_steps": min_steps,
            "prompt_version": PROMPT_VERSION,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "traceback": traceback.format_exc()[:2000],
        }}

    elapsed = time.time() - t0
    truth = candidate.get("geo")
    dist_km = None
    if res.final_answer and truth:
        try:
            pred_lat = float(res.final_answer.get("lat"))
            pred_lon = float(res.final_answer.get("lon"))
            dist_km = geodesic((truth[0], truth[1]), (pred_lat, pred_lon)).km
        except (TypeError, ValueError):
            pass

    # Year error si fue dado y es numérico
    year_err = None
    truth_year = candidate.get("year")
    if res.final_answer and truth_year is not None:
        pred_year_raw = res.final_answer.get("year", "")
        try:
            # Acepta "1965" o "1960-1970" → tomamos punto medio
            s = str(pred_year_raw).strip()
            if "-" in s:
                a, b = s.split("-", 1)
                pred_year = (int(a) + int(b)) / 2
            else:
                pred_year = int(s)
            year_err = abs(pred_year - int(truth_year))
        except (ValueError, TypeError):
            pass

    return {**candidate, "react": {
        "model": MODEL, "max_steps": MAX_STEPS, "min_steps": min_steps,
        "prompt_version": PROMPT_VERSION,
        "elapsed_seconds": round(elapsed, 1),
        "final_answer": res.final_answer,
        "distance_km": dist_km,
        "year_error": year_err,
        "steps_used": res.steps_used,
        "web_search_count": res.web_search_count,
        "fetch_url_count": res.fetch_url_count,
        "image_search_count": res.image_search_count,
        "geocode_count": res.geocode_count,
        "historical_query_count": res.historical_query_count,
        "crop_count": res.crop_count,
        "static_map_count": res.static_map_count,
        "street_view_count": res.street_view_count,
        "target_match_count": res.target_match_count,
        "submit_called": res.submit_called,
        "terminal_state": res.terminal_state,
        "error": res.error,
        "trace": res.trace,
    }}


def run_one_setting(picked: list[dict], min_steps: int) -> Path:
    out_path = EXP_DIR / f"results_{MODEL.replace('.','_')}_min{min_steps}.json"
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    done_cids = {r["cid"] for r in existing if r.get("react", {}).get("final_answer") or r.get("react", {}).get("error")}
    to_run = [p for p in picked if p["cid"] not in done_cids]

    print(f"\n{'='*70}")
    print(f"  Setting: min_steps={min_steps}")
    print(f"  to_run: {len(to_run)}, done: {len(done_cids)}")
    print(f"{'='*70}")

    if not to_run:
        print("  nothing to run")
        return out_path

    results = list(existing)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(process_one, p, min_steps): p for p in to_run}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            rk = r.get("react", {})
            d = rk.get("distance_km")
            d_s = f"{d:.0f}km" if d is not None else "N/A"
            ye = rk.get("year_error")
            ye_s = f"y±{ye:.0f}" if ye is not None else "y:NA"
            err = rk.get("error")
            tag = "[FAIL]" if err else "[OK]"
            print(f"  {tag} cid={r['cid']} dist={d_s} {ye_s} steps={rk.get('steps_used')}/{rk.get('max_steps')} t={rk.get('elapsed_seconds')}s")

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.0f}s. Wrote {out_path}")
    return out_path


def main() -> None:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"E012 min_steps ablation")
    print(f"  Model: {MODEL}")
    print(f"  N photos: {N_PHOTOS}, seed: {SEED}")
    print(f"  MAX_STEPS: {MAX_STEPS}")
    print(f"  MIN_STEPS_LIST: {MIN_STEPS_LIST}")
    print()

    picked = pick_random_photos()
    stage_photos(picked)
    print(f"staged {sum(1 for _ in PHOTOS_STAGED.glob('*.jpg'))} photos")
    print()

    out_paths = []
    for ms in MIN_STEPS_LIST:
        out_paths.append(run_one_setting(picked, ms))

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for ms, p in zip(MIN_STEPS_LIST, out_paths):
        data = json.loads(p.read_text(encoding="utf-8"))
        dists = [r["react"].get("distance_km") for r in data if r["react"].get("distance_km") is not None]
        yerrs = [r["react"].get("year_error") for r in data if r["react"].get("year_error") is not None]
        steps = [r["react"].get("steps_used", 0) for r in data]
        submit = sum(1 for r in data if r["react"].get("submit_called"))
        avg_d = sum(dists) / len(dists) if dists else 0
        avg_y = sum(yerrs) / len(yerrs) if yerrs else 0
        avg_s = sum(steps) / len(steps) if steps else 0
        print(f"  min_steps={ms}: submit={submit}/{len(data)} avg_dist={avg_d:.0f}km avg_year_err={avg_y:.1f} avg_steps={avg_s:.1f}")


if __name__ == "__main__":
    main()
