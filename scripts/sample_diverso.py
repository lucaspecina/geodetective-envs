"""Sample diverso de PastVu desde la metadata completa (#17).

Lee el dump bajado en #3 (`experiments/E006_pastvu_audit/data/pastvu.jsonl.zst`),
filtra eligibles (type=1 + geo + year + 1890-1949), asigna cada foto a una
celda `(bucket_pais, bucket_decada)` (6x6 = 36 celdas), de-duplica por
geohash5 dentro de cada celda y muestrea K_PER_CELL fotos por celda con
seed fijo.

Output:
- `experiments/E007_sample_diverso/candidates.json`: lista de fotos sampleadas.
- `experiments/E007_sample_diverso/audit_summary.json`: parametros + tabla
  de cobertura por celda (available vs sampled).

Uso:
    python scripts/sample_diverso.py
"""

from __future__ import annotations

import io
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import pygeohash
import zstandard as zstd

DATA_PATH = Path("experiments/E006_pastvu_audit/data/pastvu.jsonl.zst")
OUT_DIR = Path("experiments/E007_sample_diverso")
OUT_CANDIDATES = OUT_DIR / "candidates.json"
OUT_AUDIT = OUT_DIR / "audit_summary.json"

YEAR_MIN = 1890
YEAR_MAX = 1949  # 1940s inclusive
K_PER_CELL = 5
SEED = 42
GEOHASH_PRECISION = 5

EX_URSS = frozenset({
    "Ukraine", "Belarus", "Georgia", "Uzbekistan", "Latvia", "Lithuania",
    "Kazakhstan", "Armenia", "Azerbaijan", "Moldova", "Estonia",
    "Tajikistan", "Kyrgyzstan", "Turkmenistan",
})
EUROPA_NO_URSS = frozenset({
    "Germany", "France", "Denmark", "Netherlands", "Czech Republic", "Italy",
    "United Kingdom", "Switzerland", "Sweden", "Poland", "Hungary", "Romania",
    "Bulgaria", "Spain", "Portugal", "Austria", "Belgium", "Norway", "Finland",
    "Greece", "Ireland", "Iceland", "Serbia", "Croatia", "Slovakia", "Slovenia",
    "Bosnia and Herzegovina", "Montenegro", "North Macedonia", "Albania",
    "Luxembourg", "Malta", "Cyprus",
    # Microestados (Codex review):
    "Monaco", "Vatican City", "San Marino", "Andorra", "Liechtenstein",
})
NORTEAMERICA = frozenset({"USA", "Canada"})

DECADES = ["1890s", "1900s", "1910s", "1920s", "1930s", "1940s"]
PAIS_BUCKETS = [
    "Russia-EU", "Russia-Asia", "Ex-URSS",
    "Europa-no-URSS", "Norteamerica", "Resto",
]


def country_bucket(country: str, lon: float) -> str:
    if country == "Russia":
        return "Russia-EU" if lon < 60 else "Russia-Asia"
    if country in EX_URSS:
        return "Ex-URSS"
    if country in EUROPA_NO_URSS:
        return "Europa-no-URSS"
    if country in NORTEAMERICA:
        return "Norteamerica"
    return "Resto"


def decade_bucket(year: int) -> str:
    return f"{(year // 10) * 10}s"


def rec_to_candidate(rec: dict, lat: float, lon: float, year: int,
                     country: str, gh5: str, bucket_pais: str,
                     bucket_decada: str) -> dict:
    cid = rec["cid"]
    return {
        "cid": cid,
        "provider": "pastvu",
        "provenance_source": "",  # dump no incluye `source`; blacklist usa GLOBAL + per-provider
        "page_url": f"https://pastvu.com/p/{cid}",
        "file_url": rec.get("file"),
        "title": rec.get("title", ""),
        "year": year,
        "year2": rec.get("year2", year),
        "country": country,
        "bucket_pais": bucket_pais,
        "bucket_decada": bucket_decada,
        "geo": [lat, lon],
        "geohash5": gh5,
        "type": 1,
        "h": rec.get("h"),
        "w": rec.get("w"),
        "waterh": rec.get("waterh", 0),
        "dir": rec.get("dir"),
    }


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"missing: {DATA_PATH}. Run #3 audit script first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)

    print(f"streaming {DATA_PATH} ...")
    t0 = time.time()
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    total = 0

    with open(DATA_PATH, "rb") as f:
        dctx = zstd.ZstdDecompressor()
        reader = io.TextIOWrapper(dctx.stream_reader(f), encoding="utf-8")
        for line in reader:
            try:
                rec = json.loads(line)["photo"]
            except (json.JSONDecodeError, KeyError):
                continue
            if rec.get("type") != 1:
                continue
            geo = rec.get("geo")
            if not isinstance(geo, list) or len(geo) != 2:
                continue
            lat, lon = geo
            if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
                continue
            year = rec.get("year")
            if not isinstance(year, int) or not (YEAR_MIN <= year <= YEAR_MAX):
                continue
            regions = rec.get("regions") or []
            country = regions[0].get("title_en") if regions else None
            if not country:
                continue

            pais = country_bucket(country, lon)
            dec = decade_bucket(year)
            gh5 = pygeohash.encode(lat, lon, precision=GEOHASH_PRECISION)
            cand = rec_to_candidate(rec, lat, lon, year, country, gh5, pais, dec)
            by_cell[(pais, dec)].append(cand)
            total += 1

    print(f"total eligibles: {total:,} ({time.time()-t0:.1f}s)")

    # Per-cell: shuffle (seeded), dedupe by geohash5, take K_PER_CELL.
    sample: list[dict] = []
    cell_summary: dict[str, dict] = {}
    for pais in PAIS_BUCKETS:
        for dec in DECADES:
            cell = (pais, dec)
            cands = by_cell.get(cell, [])
            random.shuffle(cands)
            seen_gh = set()
            unique = []
            for c in cands:
                if c["geohash5"] in seen_gh:
                    continue
                seen_gh.add(c["geohash5"])
                unique.append(c)
            picked = unique[:K_PER_CELL]
            sample.extend(picked)
            cell_summary[f"{pais} x {dec}"] = {
                "available_raw": len(cands),
                "available_unique_gh5": len(unique),
                "sampled": len(picked),
            }

    OUT_CANDIDATES.write_text(json.dumps(sample, indent=2, ensure_ascii=False))
    print(f"\nwrote {OUT_CANDIDATES} ({len(sample)} fotos)")

    audit = {
        "seed": SEED,
        "year_range": [YEAR_MIN, YEAR_MAX],
        "k_per_cell": K_PER_CELL,
        "geohash_precision": GEOHASH_PRECISION,
        "total_eligibles": total,
        "final_sample_size": len(sample),
        "pais_buckets": PAIS_BUCKETS,
        "decade_buckets": DECADES,
        "cell_distribution": cell_summary,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2))
    print(f"wrote {OUT_AUDIT}")

    print("\n=== Distribución final por celda ===")
    print(f"  {'cell':<33} {'raw':>10} {'uniq':>8} {'samp':>6}")
    for pais in PAIS_BUCKETS:
        row_total = 0
        for dec in DECADES:
            key = f"{pais} x {dec}"
            s = cell_summary[key]
            row_total += s["sampled"]
            print(f"  {key:<33} {s['available_raw']:>10,} {s['available_unique_gh5']:>8,} {s['sampled']:>6}")
        print(f"  {pais + ' TOTAL':<33} {'':<10} {'':<8} {row_total:>6}")


if __name__ == "__main__":
    main()
