"""Pilot E010: iteration single-model con payload_to_model capture.

Para iterar/debuggear el comportamiento de UN modelo (default gpt-5.4-mini)
sobre fotos nuevas y diversas. Salida con payloads completos para análisis
de qué recibe el modelo en cada tool call.

Uso:
    python scripts/run_e010_iteration.py                       # gpt-5.4-mini × 5 fotos
    MODEL=gpt-4o python scripts/run_e010_iteration.py
    MAX_STEPS=30 python scripts/run_e010_iteration.py
    CIDS="1248470,2165013" python scripts/run_e010_iteration.py  # subset

Output: experiments/E010_iteration_pilot/results_{model}.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# UTF-8 stdout en Windows
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
EXP_DIR = Path("experiments/E010_iteration_pilot")
PHOTOS_DIR = EXP_DIR / "photos"
PICKED = EXP_DIR / "picked_photos.json"

MODEL = os.environ.get("MODEL", "gpt-5.4-mini")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "50"))
N_WORKERS = int(os.environ.get("N_WORKERS", "3"))
PROMPT_VERSION = "v3_thinking_visible"


def process_one(candidate: dict) -> dict:
    cid = candidate["cid"]
    img_path = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
    if not img_path.exists():
        return {**candidate, "react": {"error": f"image not found: {img_path}", "model": MODEL}}

    t0 = time.time()
    try:
        res = run_react_agent(
            image_path=img_path,
            model=MODEL,
            max_steps=MAX_STEPS,
            verbose=False,
            provider=candidate.get("provider"),
            provenance_source=candidate.get("provenance_source"),
        )
    except Exception as e:
        return {**candidate, "react": {
            "model": MODEL, "max_steps": MAX_STEPS,
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

    return {**candidate, "react": {
        "model": MODEL, "max_steps": MAX_STEPS,
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
        "error": res.error,
        "trace": res.trace,
    }}


def main() -> None:
    if not PICKED.exists():
        raise SystemExit(f"missing: {PICKED}. Sample photos first.")
    photos = json.loads(PICKED.read_text(encoding="utf-8"))

    cids_filter = None
    if os.environ.get("CIDS"):
        cids_filter = {int(c.strip()) for c in os.environ["CIDS"].split(",")}
        photos = [p for p in photos if p["cid"] in cids_filter]

    out_path = EXP_DIR / f"results_{MODEL.replace('.','_').replace('/','_')}.json"
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    done_cids = {r["cid"] for r in existing if r.get("react", {}).get("final_answer") or r.get("react", {}).get("error")}
    to_run = [p for p in photos if p["cid"] not in done_cids]

    print("=" * 70)
    print(f"E010 ITERATION PILOT")
    print(f"  Model: {MODEL}")
    print(f"  MAX_STEPS: {MAX_STEPS}")
    print(f"  Workers: {N_WORKERS}")
    print(f"  Photos: {len(photos)} total, {len(to_run)} to run, {len(done_cids)} done")
    print("=" * 70)
    print()

    if not to_run:
        print("nothing to run — all done")
        return

    results = list(existing)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(process_one, p): p for p in to_run}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            rk = r.get("react", {})
            d = rk.get("distance_km")
            d_s = f"{d:.0f}km" if d is not None else "N/A"
            err = rk.get("error")
            tag = "[FAIL]" if err else "[OK]"
            print(f"  {tag} cid={r['cid']} dist={d_s} steps={rk.get('steps_used')}/{rk.get('max_steps')} t={rk.get('elapsed_seconds')}s")
            if err:
                print(f"    ERR: {err[:140]}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s. Wrote {out_path}")

    print(f"\n{'CID':>10} {'zone':<22} {'year':>5} {'dist_km':>10} {'steps':>6} {'submit':>7} loc")
    for r in results:
        rk = r.get("react", {}) or {}
        ans = rk.get("final_answer") or {}
        loc = (ans.get("location", "") or "")[:60]
        d_s = f"{rk['distance_km']:.0f}" if rk.get("distance_km") is not None else "NA"
        print(f"{r['cid']:>10} {r.get('zone','?'):<22} {r.get('year'):>5} {d_s:>10} {rk.get('steps_used','?'):>6} {rk.get('submit_called','?'):>7} {loc}")


if __name__ == "__main__":
    main()
