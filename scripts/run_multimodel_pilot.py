"""Pilot E008: cross-model smoke test (#TBD).

Corre el agente ReAct (prompt v3 canónico) sobre las MISMAS 3 fotos con
distintos modelos vía Azure Foundry. Output: 1 archivo JSON por modelo.

Diseño:
- Health check por modelo ANTES del loop principal (1 call simple).
  Modelos que fallan health → skipped. Saves time si claude/deepseek
  rompen vía la API OpenAI-compatible.
- Serial entre modelos (sequencial), paralelo dentro de modelo
  (ThreadPoolExecutor con N_WORKERS=3 → las 3 fotos en paralelo).
- Save after each photo → resume support: si una foto ya está hecha,
  se saltea.

Uso:
    python scripts/run_multimodel_pilot.py
    MODELS="gpt-5.4,gpt-4o" python scripts/run_multimodel_pilot.py
    CIDS="2126812,2328833" python scripts/run_multimodel_pilot.py
    SKIP_HEALTH=1 python scripts/run_multimodel_pilot.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from geopy.distance import geodesic
from openai import OpenAI

# Cargar .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.agents.react import run_react_agent
from geodetective.corpus import CLEAN_VERSION

# === Config ===
INPUT_CORPUS = Path("experiments/E004_attacker_filter/results.json")
PHOTOS_DIR = Path("experiments/E004_attacker_filter/photos")
OUT_DIR = Path("experiments/E008_multimodel")
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MODELS = [
    "gpt-5.4",
    "gpt-4o",
    "DeepSeek-V3.2",
    "Kimi-K2.5",
    "grok-4-1-fast-reasoning",
    # Claude pendiente: requiere adapter (Anthropic Messages API, no OpenAI Chat).
    # Ver task #6.
]
DEFAULT_CIDS = [2126812, 2328833, 2034885]  # Tomsk, Dealey Plaza, Basel

MAX_STEPS = int(os.environ.get("MAX_STEPS", "50"))
SEED = int(os.environ.get("SEED", "42"))
N_WORKERS_PER_MODEL = int(os.environ.get("N_WORKERS_PER_MODEL", "3"))
SKIP_HEALTH = os.environ.get("SKIP_HEALTH", "0") == "1"
PROMPT_VERSION = "v3_thinking_visible"


def make_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
    )


def model_to_filename(model: str) -> str:
    """Normalizar nombre de modelo a un nombre de archivo válido."""
    return model.replace(".", "_").replace("/", "_").replace(":", "_")


def health_check(model: str) -> tuple[bool, str]:
    """Verifica que el modelo responda a una llamada minimal sin tools."""
    try:
        client = make_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply 'ok' in one word."}],
            max_completion_tokens=20,
            timeout=20.0,
        )
        msg = (resp.choices[0].message.content or "")[:60]
        return True, msg
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


def process_one(cid: int, candidate: dict, model: str) -> dict:
    """Corre el agente ReAct para una foto con un modelo dado."""
    img_path = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
    if not img_path.exists():
        return {**candidate, "decision": "skip",
                "react": {"error": f"image not found: {img_path}", "model": model}}

    t0 = time.time()
    try:
        res = run_react_agent(
            image_path=img_path,
            model=model,
            max_steps=MAX_STEPS,
            verbose=False,  # no spam stdout per-call
            provider=candidate.get("provider"),
            provenance_source=candidate.get("provenance_source"),
        )
    except Exception as e:
        return {**candidate, "react": {
            "model": model, "max_steps": MAX_STEPS,
            "prompt_version": PROMPT_VERSION,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "traceback": traceback.format_exc()[:2000],
        }}

    elapsed = time.time() - t0
    truth = candidate["geo"]
    dist_km = None
    if res.final_answer:
        try:
            pred_lat = float(res.final_answer.get("lat"))
            pred_lon = float(res.final_answer.get("lon"))
            dist_km = geodesic((truth[0], truth[1]), (pred_lat, pred_lon)).km
        except (TypeError, ValueError):
            pass

    return {**candidate, "react": {
        "model": model,
        "max_steps": MAX_STEPS,
        "prompt_version": PROMPT_VERSION,
        "elapsed_seconds": round(elapsed, 1),
        "final_answer": res.final_answer,
        "distance_km": dist_km,
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
        "submit_retry_count": res.submit_retry_count,
        "text_only_attempts": res.text_only_attempts,
        "error": res.error,
        "trace": res.trace,
    }}


def run_for_model(model: str, candidates: list[dict]) -> dict:
    """Corre todas las fotos de un modelo. Soporta resume."""
    out_path = OUT_DIR / f"results_{model_to_filename(model)}.json"
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            existing = []
    done_cids = {r["cid"] for r in existing if r.get("react", {}).get("final_answer") or r.get("react", {}).get("error")}

    to_run = [c for c in candidates if c["cid"] not in done_cids]
    if not to_run:
        print(f"  [{model}] all {len(candidates)} cids already done")
        return {"model": model, "skipped": True, "results": existing}

    print(f"  [{model}] running {len(to_run)} / {len(candidates)} cids (resume from {len(existing)} done)")

    results = list(existing)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=N_WORKERS_PER_MODEL) as pool:
        futures = {pool.submit(process_one, c["cid"], c, model): c for c in to_run}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            # Save after each (resume support)
            out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
            rr = r.get("react", {})
            d = rr.get("distance_km")
            d_s = f"{d:.0f}km" if d is not None else "N/A"
            err = rr.get("error")
            tag = "❌" if err else "✓"
            print(f"    {tag} {model} #{r['cid']} dist={d_s} steps={rr.get('steps_used')}/{rr.get('max_steps')} t={rr.get('elapsed_seconds')}s {('ERR: ' + err[:120]) if err else ''}")
    elapsed = time.time() - t0
    print(f"  [{model}] done in {elapsed:.0f}s, wrote {out_path}")
    return {"model": model, "skipped": False, "results": results, "elapsed_seconds": elapsed}


def main() -> None:
    models = os.environ.get("MODELS", ",".join(DEFAULT_MODELS)).split(",")
    models = [m.strip() for m in models if m.strip()]
    cids = [int(c) for c in os.environ.get("CIDS", ",".join(str(c) for c in DEFAULT_CIDS)).split(",")]

    if not INPUT_CORPUS.exists():
        raise SystemExit(f"missing input: {INPUT_CORPUS}")

    corpus = {r["cid"]: r for r in json.loads(INPUT_CORPUS.read_text()) if r.get("decision") == "keep"}
    candidates = []
    for cid in cids:
        if cid not in corpus:
            print(f"⚠️  cid {cid} no está en corpus 'keep'. Saltado.")
            continue
        candidates.append(corpus[cid])

    if not candidates:
        raise SystemExit("no candidates resolved")

    print("=" * 70)
    print(f"MULTI-MODEL SMOKE TEST — E008")
    print(f"Models: {models}")
    print(f"CIDs: {[c['cid'] for c in candidates]}")
    print(f"Workers per model: {N_WORKERS_PER_MODEL}")
    print(f"Skip health: {SKIP_HEALTH}")
    print("=" * 70)
    print()

    # === Health check phase ===
    healthy = []
    unhealthy = []
    if not SKIP_HEALTH:
        print("[Phase 1] Health check por modelo...")
        for model in models:
            ok, msg = health_check(model)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {model:<30}  {msg[:120]}")
            (healthy if ok else unhealthy).append((model, msg))
        print()
        if unhealthy:
            print(f"⚠️  {len(unhealthy)} modelos fallaron health, skipping:")
            for m, e in unhealthy:
                print(f"  - {m}: {e[:200]}")
            print()
    else:
        healthy = [(m, "skip-check") for m in models]

    if not healthy:
        raise SystemExit("no healthy models, aborting")

    # === Main loop ===
    print(f"[Phase 2] Corriendo agente sobre {len(candidates)} fotos × {len(healthy)} modelos...")
    print()
    summary = []
    t_all = time.time()
    for model, _ in healthy:
        print(f"[model] {model}")
        try:
            res = run_for_model(model, candidates)
            summary.append(res)
        except Exception as e:
            print(f"  💥 model {model} crashed mid-run: {e}")
            summary.append({"model": model, "crashed": True, "error": str(e)})
        print()

    print("=" * 70)
    print(f"DONE. Total {time.time()-t_all:.0f}s for {len(healthy)} modelos × {len(candidates)} fotos.")
    print()
    print(f"{'Model':<30} {'Done':<6} {'Submit':<7} {'Avg dist':>12} {'Status':<10}")
    for s in summary:
        if s.get("crashed"):
            print(f"{s['model']:<30} CRASHED")
            continue
        results = s.get("results", [])
        submitted = [r for r in results if (r.get("react") or {}).get("submit_called")]
        with_dist = [r for r in results if (r.get("react") or {}).get("distance_km") is not None]
        if with_dist:
            avg = sum(r["react"]["distance_km"] for r in with_dist) / len(with_dist)
            avg_s = f"{avg:.0f}km"
        else:
            avg_s = "N/A"
        status = "SKIPPED" if s.get("skipped") else "ran"
        print(f"{s['model']:<30} {len(results):<6} {len(submitted):<7} {avg_s:>12} {status:<10}")


if __name__ == "__main__":
    main()
