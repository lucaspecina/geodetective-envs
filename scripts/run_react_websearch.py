"""Correr el agente ReAct con web_search sobre fotos del corpus.

Uso: python scripts/run_react_websearch.py [cid] [cid] ...
Si no se pasan cids, usa la lista default (las que sobrevivieron al filtro).
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

results = []
for cid in cids:
    if cid not in by_cid:
        print(f"⚠️  cid {cid} no está en candidates.json")
        continue
    c = by_cid[cid]
    print(f"\n{'=' * 80}")
    print(f"#{cid} [{c['zone']}, {c['year']}] — {c['title'][:60]}")
    print(f"  Ground truth: {c['geo']}, year {c['year']}")
    print(f"{'=' * 80}")

    img_path = PHOTOS / f"{cid}_nowm.jpg"
    if not img_path.exists():
        print(f"  ⚠️  imagen no encontrada en {img_path}")
        continue

    res = run_react_agent(image_path=img_path, model="gpt-5.4", max_steps=10, verbose=True)

    # Compute distance + year error
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
        # year parsing simple
        import re
        y_str = str(res.final_answer.get("year", ""))
        years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20\d{2})\b", y_str)]
        if years:
            pred_year = sum(years) / len(years)
            year_err = abs(c["year"] - pred_year)

    print(f"\n=== Resumen #{cid} ===")
    print(f"  steps usados: {res.steps_used} / 10")
    print(f"  web_search calls: {res.web_search_count}")
    print(f"  submit_called: {res.submit_called}")
    if res.error:
        print(f"  ERROR: {res.error}")
    if res.final_answer:
        print(f"  → final: {res.final_answer.get('location')}")
        print(f"  → coords: ({res.final_answer.get('lat')}, {res.final_answer.get('lon')})")
        print(f"  → year: {res.final_answer.get('year')}")
        print(f"  → confidence: {res.final_answer.get('confidence')}")
        print(f"  📏 distancia: {dist_km:.1f} km" if dist_km is not None else "  📏 distancia: N/A")
        print(f"  📅 year error: {year_err:.0f}" if year_err is not None else "  📅 year error: N/A")

    results.append(
        {
            "cid": cid,
            "candidate": c,
            "final_answer": res.final_answer,
            "distance_km": dist_km,
            "year_error": year_err,
            "steps_used": res.steps_used,
            "web_search_count": res.web_search_count,
            "submit_called": res.submit_called,
            "error": res.error,
            "trace": res.trace,
        }
    )

# Save
(OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"\n✓ Saved {len(results)} resultados a {OUT / 'results.json'}")

# Tabla resumen
print("\n=== TABLA FINAL ===")
print(f"{'CID':>8} {'Zone':22} {'YR':>5} {'Steps':>6} {'WS':>3} {'Dist (km)':>10} {'YE':>4}")
print("-" * 80)
for r in results:
    c = r["candidate"]
    d = r.get("distance_km")
    d_s = f"{d:.0f}" if d is not None else "N/A"
    ye = r.get("year_error")
    ye_s = f"{ye:.0f}" if ye is not None else "N/A"
    print(f"{r['cid']:>8} {c['zone'][:22]:22} {c['year']:>5} {r['steps_used']:>6} {r['web_search_count']:>3} {d_s:>10} {ye_s:>4}")
