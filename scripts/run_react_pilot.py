"""Pilot E005: ReAct agent (12 tools, gpt-5.4) sobre el corpus piloto filtrado (#26).

Lee `experiments/E004_attacker_filter/results.json`, filtra fotos con
`decision=='keep'`, samplea 1 por bucket país con seed fijo, y corre el agente
ReAct completo sobre cada una para comparar con ground truth.

Las imágenes ya están descargadas y limpiadas por el atacante (#24), reutilizamos
el cache en `experiments/E004_attacker_filter/photos/`.

Uso:
    python scripts/run_react_pilot.py                     # 1 por bucket país, seed=42
    SEED=7 N_PER_BUCKET=2 python scripts/run_react_pilot.py
    python scripts/run_react_pilot.py 1748874 1101385     # cids específicos
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from collections import defaultdict
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
from geodetective.corpus import CLEAN_VERSION

# === Config ===
INPUT = Path("experiments/E004_attacker_filter/results.json")
PHOTOS_DIR = Path("experiments/E004_attacker_filter/photos")
OUT_DIR = Path("experiments/E005_react_pilot")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = OUT_DIR / "results.json"

MODEL = os.environ.get("REACT_MODEL", "gpt-5.4")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "12"))
N_PER_BUCKET = int(os.environ.get("N_PER_BUCKET", "1"))
SEED = int(os.environ.get("SEED", "42"))


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


def select_pilot_candidates(all_keep: list[dict], cli_cids: list[int]) -> list[dict]:
    """Si hay cids en CLI, usarlos. Si no, samplear N_PER_BUCKET por bucket país."""
    if cli_cids:
        by_cid = {c["cid"]: c for c in all_keep}
        out = []
        for cid in cli_cids:
            if cid in by_cid:
                out.append(by_cid[cid])
            else:
                print(f"⚠️  cid {cid} no es 'keep' en E004, salteado")
        return out

    random.seed(SEED)
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for c in all_keep:
        by_bucket[c["bucket_pais"]].append(c)

    pilot = []
    for bucket in sorted(by_bucket):  # orden estable
        pool = by_bucket[bucket][:]
        random.shuffle(pool)
        pilot.extend(pool[:N_PER_BUCKET])
    return pilot


def main():
    if not INPUT.exists():
        raise SystemExit(f"missing input: {INPUT}. Run #24 atacker filter first.")

    data = json.loads(INPUT.read_text())
    keep = [r for r in data if r.get("decision") == "keep"]
    print(f"loaded {len(data)} candidates, {len(keep)} con decision=keep")

    cli_cids = [int(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else []
    pilot = select_pilot_candidates(keep, cli_cids)
    print(f"pilot: {len(pilot)} fotos (1 por bucket país, seed={SEED})")
    for c in pilot:
        print(f"  - #{c['cid']:<8} [{c['bucket_pais']:<14}/{c['bucket_decada']:<6}] {c['year']} {c['country']:<12} — {c['title'][:55]}")
    print()

    results = []
    t0_all = time.time()
    for i, c in enumerate(pilot, 1):
        cid = c["cid"]
        img_path = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
        if not img_path.exists():
            print(f"⚠️  imagen no encontrada en {img_path} — salteo #{cid}")
            continue

        print(f"\n{'=' * 80}")
        print(f"[{i}/{len(pilot)}] #{cid} [{c['bucket_pais']}/{c['bucket_decada']}, {c['year']}]")
        print(f"  {c['country']} — {c['title'][:60]}")
        print(f"  Ground truth: {c['geo']}, year {c['year']}")
        print(f"{'=' * 80}")

        t0 = time.time()
        try:
            res = run_react_agent(
                image_path=img_path,
                model=MODEL,
                max_steps=MAX_STEPS,
                verbose=True,
                provider=c.get("provider"),
                provenance_source=c.get("provenance_source"),
            )
        except Exception as e:
            print(f"  💥 ERROR: {e}")
            results.append({**c, "error": str(e)})
            continue
        elapsed = time.time() - t0

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

        print(f"\n--- Run resumen ({elapsed:.0f}s) ---")
        print(f"  steps={res.steps_used} ws={res.web_search_count} fu={res.fetch_url_count} is={res.image_search_count} "
              f"hq={res.historical_query_count} crop={res.crop_count} sm={res.static_map_count} sv={res.street_view_count} "
              f"geocode={res.geocode_count} target_match={res.target_match_count}")
        if res.final_answer:
            print(f"  → loc: {res.final_answer.get('location', '?')[:70]}")
            print(f"  → coords ({res.final_answer.get('lat')}, {res.final_answer.get('lon')}) conf={res.final_answer.get('confidence')}")
            print(f"  📏 dist: {dist_km:.1f} km" if dist_km is not None else "  📏 dist: N/A")
            print(f"  📅 year err: {year_err:.0f}" if year_err is not None else "  📅 year err: N/A")
        if res.error:
            print(f"  ERROR: {res.error}")

        results.append({
            **c,
            "react": {
                "model": MODEL,
                "max_steps": MAX_STEPS,
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
                "error": res.error,
                "trace": res.trace,
            },
        })

    OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    elapsed_all = time.time() - t0_all
    print(f"\n✓ Saved {len(results)} resultados a {OUT_JSON} ({elapsed_all:.0f}s total)")

    print("\n=== TABLA FINAL ===")
    print(f"{'CID':>8} {'Bucket':22} {'YR':>5} {'dist_km':>10} {'YE':>5} {'steps':>5} {'tools_total':>11} {'confidence':<10}")
    print("-" * 105)
    for r in results:
        if "react" not in r:
            print(f"{r['cid']:>8} ERROR: {r.get('error', '?')}")
            continue
        rr = r["react"]
        bucket = f"{r['bucket_pais'][:13]}/{r['bucket_decada']}"
        d = f"{rr['distance_km']:.0f}" if rr.get('distance_km') is not None else "N/A"
        ye = f"{rr['year_error']:.0f}" if rr.get('year_error') is not None else "N/A"
        tools_total = (rr['web_search_count'] + rr['fetch_url_count'] + rr['image_search_count'] +
                       rr['geocode_count'] + rr['historical_query_count'] + rr['crop_count'] +
                       rr['static_map_count'] + rr['street_view_count'])
        conf = (rr.get('final_answer') or {}).get('confidence', '?')
        print(f"{r['cid']:>8} {bucket:22} {r['year']:>5} {d:>10} {ye:>5} {rr['steps_used']:>5} {tools_total:>11} {conf:<10}")


if __name__ == "__main__":
    main()
