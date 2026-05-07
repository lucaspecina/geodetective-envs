"""Correr el agente ReAct multi-tool sobre fotos del corpus.

Uso:
  python scripts/run_react_websearch.py [cid1] [cid2] ...    # N=1 run
  N_RUNS=3 python scripts/run_react_websearch.py             # N=3 runs (default fotos)

Si no se pasan cids, usa la lista default (sobrevivientes E001).
"""
from __future__ import annotations
import os
import sys
import json
from pathlib import Path
from geopy.distance import geodesic

# Cargar .env primero
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

# Path setup para src/
sys.path.insert(0, str(Path("src").resolve()))
from geodetective.agents.react import run_react_agent

EXP = Path("experiments/E001_test3_pastvu")
OUT = Path("experiments/E002_react_websearch")
OUT.mkdir(parents=True, exist_ok=True)
PHOTOS = EXP / "photos"

candidates = json.loads((EXP / "candidates.json").read_text())
by_cid = {c["cid"]: c for c in candidates}

# CIDs por default: las que sobrevivieron al filtro v2 (foco en sweet spot)
DEFAULT_CIDS = [
    1748874,  # SP barrio anónimo (642 km off sin tools)
    1101385,  # Volga deep rural (12000 km off)
    1459395,  # iglesia rural Volga (103 km off)
    216313,   # Lima 1868 (3307 km off)
    2000504,  # Bogotá 1930 (726 km off)
]

cids = [int(c) for c in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_CIDS
N_RUNS = int(os.environ.get("N_RUNS", "1"))

import re

def parse_year(year_field):
    if year_field is None:
        return None
    if isinstance(year_field, (int, float)):
        return float(year_field)
    s = str(year_field)
    years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20\d{2})\b", s)]
    if years:
        return sum(years) / len(years)
    return None


results = []
for cid in cids:
    if cid not in by_cid:
        print(f"⚠️  cid {cid} no está en candidates.json")
        continue
    c = by_cid[cid]
    img_path = PHOTOS / f"{cid}_nowm.jpg"
    if not img_path.exists():
        print(f"  ⚠️  imagen no encontrada en {img_path}")
        continue

    runs = []
    for run_idx in range(N_RUNS):
        print(f"\n{'=' * 80}")
        print(f"#{cid} [{c['zone']}, {c['year']}] — {c['title'][:60]} (run {run_idx + 1}/{N_RUNS})")
        print(f"  Ground truth: {c['geo']}, year {c['year']}")
        print(f"{'=' * 80}")

        res = run_react_agent(image_path=img_path, model="gpt-5.4", max_steps=12, verbose=True)

        truth = c["geo"]
        dist_km = None
        year_err = None
        if res.final_answer:
            try:
                pred_lat = float(res.final_answer.get("lat"))
                pred_lon = float(res.final_answer.get("lon"))
                dist_km = geodesic((truth[0], truth[1]), (pred_lat, pred_lon)).km
            except (TypeError, ValueError):
                pass
            pred_year = parse_year(res.final_answer.get("year"))
            if pred_year and c["year"]:
                year_err = abs(c["year"] - pred_year)

        print(f"\n--- Run {run_idx + 1} resumen ---")
        print(f"  steps={res.steps_used} ws={res.web_search_count} fu={res.fetch_url_count} is={res.image_search_count} target_match={res.target_match_count}")
        if res.final_answer:
            print(f"  → loc: {res.final_answer.get('location', '?')[:70]}")
            print(f"  → coords ({res.final_answer.get('lat')}, {res.final_answer.get('lon')}) conf={res.final_answer.get('confidence')}")
            print(f"  📏 dist: {dist_km:.1f} km" if dist_km is not None else "  📏 dist: N/A")
            print(f"  📅 year err: {year_err:.0f}" if year_err is not None else "  📅 year err: N/A")
        if res.error:
            print(f"  ERROR: {res.error}")

        runs.append({
            "run_idx": run_idx,
            "final_answer": res.final_answer,
            "distance_km": dist_km,
            "year_error": year_err,
            "steps_used": res.steps_used,
            "web_search_count": res.web_search_count,
            "fetch_url_count": res.fetch_url_count,
            "image_search_count": res.image_search_count,
            "target_match_count": res.target_match_count,
            "submit_called": res.submit_called,
            "error": res.error,
            "trace": res.trace,
        })

    # Stats sobre los N runs
    dists = [r["distance_km"] for r in runs if r["distance_km"] is not None]
    yerrs = [r["year_error"] for r in runs if r["year_error"] is not None]
    stats = {
        "dist_min": min(dists) if dists else None,
        "dist_median": sorted(dists)[len(dists) // 2] if dists else None,
        "dist_max": max(dists) if dists else None,
        "year_err_min": min(yerrs) if yerrs else None,
        "year_err_median": sorted(yerrs)[len(yerrs) // 2] if yerrs else None,
        "n_with_coords": len(dists),
    }
    print(f"\n📊 #{cid} stats over {N_RUNS} runs: dist min={stats['dist_min']}, med={stats['dist_median']}, max={stats['dist_max']}")
    results.append({"cid": cid, "candidate": c, "runs": runs, "stats": stats})

# Save
(OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"\n✓ Saved {len(results)} resultados a {OUT / 'results.json'}")

# Tabla final
print("\n=== TABLA FINAL ===")
print(f"{'CID':>8} {'Zone':22} {'YR':>5} {'min/med/max km':>20} {'YE_med':>6}")
print("-" * 90)
for r in results:
    c = r["candidate"]
    s = r["stats"]
    dmin = f"{s['dist_min']:.0f}" if s.get('dist_min') is not None else "N/A"
    dmed = f"{s['dist_median']:.0f}" if s.get('dist_median') is not None else "N/A"
    dmax = f"{s['dist_max']:.0f}" if s.get('dist_max') is not None else "N/A"
    ds = f"{dmin}/{dmed}/{dmax}"
    ye = s.get('year_err_median')
    ye_s = f"{ye:.0f}" if ye is not None else "N/A"
    print(f"{r['cid']:>8} {c['zone'][:22]:22} {c['year']:>5} {ds:>20} {ye_s:>6}")
