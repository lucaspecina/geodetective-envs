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
# v2 (#46): output a candidates_v2.json para no pisar el original (180 fotos sesgadas a Rusia)
OUT_CANDIDATES = OUT_DIR / "candidates_v2.json"
OUT_AUDIT = OUT_DIR / "audit_v2_summary.json"

YEAR_MIN = 1890
YEAR_MAX = 1949  # 1940s inclusive
SEED = 42
GEOHASH_PRECISION = 5

# === v2 (#46): buckets más desagregados para reducir sesgo geográfico ===
#
# Antes: 6 buckets, "Resto" comoduplicado catch-all → LatAm/África/Asia-noCN/Oceanía
# quedaban con migajas. Ahora: 13 buckets explícitos con cuotas distintas.

EX_URSS = frozenset({
    "Ukraine", "Belarus", "Georgia", "Uzbekistan", "Latvia", "Lithuania",
    "Kazakhstan", "Armenia", "Azerbaijan", "Moldova", "Estonia",
    "Tajikistan", "Kyrgyzstan", "Turkmenistan",
})
EUROPA_OCCIDENTAL = frozenset({
    "Germany", "France", "Netherlands", "Belgium", "Luxembourg",
    "Austria", "Switzerland", "Liechtenstein", "Monaco",
})
EUROPA_MEDITERRANEA = frozenset({
    "Italy", "Spain", "Portugal", "Greece", "Malta", "Cyprus",
    "Vatican City", "San Marino",
})
EUROPA_NORDICA = frozenset({
    "Sweden", "Norway", "Denmark", "Finland", "Iceland",
})
EUROPA_BRITANICA = frozenset({"United Kingdom", "Ireland"})
EUROPA_CENTRO_ESTE = frozenset({
    "Poland", "Czech Republic", "Slovakia", "Hungary", "Romania", "Bulgaria",
    "Serbia", "Croatia", "Slovenia", "Bosnia and Herzegovina", "Montenegro",
    "North Macedonia", "Albania", "Andorra",
})
NORTEAMERICA = frozenset({"USA", "Canada"})
LATINOAMERICA = frozenset({
    "Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Venezuela",
    "Uruguay", "Paraguay", "Bolivia", "Ecuador", "Cuba", "Dominican Republic",
    "Puerto Rico", "Guatemala", "Honduras", "Nicaragua", "Costa Rica", "Panama",
    "El Salvador", "Haiti", "Jamaica", "Trinidad and Tobago",
})
ASIA_NON_URSS = frozenset({
    "China", "Japan", "India", "Indonesia", "Turkey", "Iran", "Iraq", "Pakistan",
    "Bangladesh", "Thailand", "Vietnam", "Philippines", "South Korea", "North Korea",
    "Malaysia", "Singapore", "Myanmar", "Cambodia", "Laos", "Sri Lanka", "Nepal",
    "Afghanistan", "Mongolia", "Taiwan", "Hong Kong",
})
AFRICA_ME = frozenset({
    "Egypt", "Morocco", "South Africa", "Algeria", "Tunisia", "Libya", "Sudan",
    "Ethiopia", "Kenya", "Nigeria", "Ghana", "Tanzania", "Uganda", "Senegal",
    "Israel", "Saudi Arabia", "Jordan", "Lebanon", "Syria", "UAE", "Yemen", "Oman",
    "Qatar", "Kuwait", "Bahrain", "Palestine",
})
OCEANIA = frozenset({
    "Australia", "New Zealand", "Fiji", "Papua New Guinea", "Samoa",
})

DECADES = ["1890s", "1900s", "1910s", "1920s", "1930s", "1940s"]

# Cuotas por bucket (total = 250 al sumarlas)
QUOTAS = {
    "Russia-EU":           15,
    "Russia-Asia":         15,
    "Ex-URSS":             20,
    "Europa-Occidental":   12,
    "Europa-Mediterranea": 12,
    "Europa-Nordica":      12,
    "Europa-Britanica":    12,
    "Europa-CentroEste":   12,
    "Norteamerica":        20,
    "LatinoAmerica":       30,
    "Asia-non-URSS":       40,
    "Africa-ME":           30,
    "Oceania":             20,
}
PAIS_BUCKETS = list(QUOTAS.keys())


def country_bucket(country: str, lon: float) -> str | None:
    if country == "Russia":
        return "Russia-EU" if lon < 60 else "Russia-Asia"
    if country in EX_URSS:                return "Ex-URSS"
    if country in EUROPA_OCCIDENTAL:      return "Europa-Occidental"
    if country in EUROPA_MEDITERRANEA:    return "Europa-Mediterranea"
    if country in EUROPA_NORDICA:         return "Europa-Nordica"
    if country in EUROPA_BRITANICA:       return "Europa-Britanica"
    if country in EUROPA_CENTRO_ESTE:     return "Europa-CentroEste"
    if country in NORTEAMERICA:           return "Norteamerica"
    if country in LATINOAMERICA:          return "LatinoAmerica"
    if country in ASIA_NON_URSS:          return "Asia-non-URSS"
    if country in AFRICA_ME:              return "Africa-ME"
    if country in OCEANIA:                return "Oceania"
    return None  # país no mapeado → descartar


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
            if pais is None:
                continue  # país no mapeado, descartar
            dec = decade_bucket(year)
            gh5 = pygeohash.encode(lat, lon, precision=GEOHASH_PRECISION)
            cand = rec_to_candidate(rec, lat, lon, year, country, gh5, pais, dec)
            by_cell[(pais, dec)].append(cand)
            total += 1

    print(f"total eligibles: {total:,} ({time.time()-t0:.1f}s)")

    # Per-bucket: distribuir cuota target entre 6 décadas (ceil), redistribuir si una década escasa.
    # Estrategia: K_per_cell base = ceil(quota / 6). Sobrecuota se rellena con sobrantes de otras décadas.
    import math
    sample: list[dict] = []
    cell_summary: dict[str, dict] = {}
    for pais in PAIS_BUCKETS:
        target = QUOTAS[pais]
        base_k = math.ceil(target / len(DECADES))  # cuota base por década
        # Primera pasada: tomar base_k por década (con dedupe gh5)
        picked_by_dec = {}
        leftover_by_dec = {}
        for dec in DECADES:
            cands = by_cell.get((pais, dec), [])
            random.shuffle(cands)
            seen_gh = set()
            unique = []
            for c in cands:
                if c["geohash5"] in seen_gh:
                    continue
                seen_gh.add(c["geohash5"])
                unique.append(c)
            picked_by_dec[dec] = unique[:base_k]
            leftover_by_dec[dec] = unique[base_k:]
            cell_summary[f"{pais} x {dec}"] = {
                "available_raw": len(cands),
                "available_unique_gh5": len(unique),
                "sampled_base": len(picked_by_dec[dec]),
            }
        # Segunda pasada: rellenar hasta target con leftovers (de cualquier década del mismo bucket)
        total_picked = sum(len(v) for v in picked_by_dec.values())
        if total_picked < target:
            need = target - total_picked
            # Mezclar leftovers de todas las décadas, tomar `need`
            all_leftovers = []
            for dec in DECADES:
                all_leftovers.extend(leftover_by_dec[dec])
            random.shuffle(all_leftovers)
            extras = all_leftovers[:need]
            # Distribuir extras y actualizar summary
            for ex in extras:
                picked_by_dec[ex["bucket_decada"]].append(ex)
                cell_summary[f"{pais} x {ex['bucket_decada']}"]["sampled_extra"] = \
                    cell_summary[f"{pais} x {ex['bucket_decada']}"].get("sampled_extra", 0) + 1
        # Acumular en el sample final
        for dec in DECADES:
            sample.extend(picked_by_dec[dec])
            cell_summary[f"{pais} x {dec}"]["sampled_total"] = len(picked_by_dec[dec])

    OUT_CANDIDATES.write_text(json.dumps(sample, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT_CANDIDATES} ({len(sample)} fotos)")

    audit = {
        "seed": SEED,
        "year_range": [YEAR_MIN, YEAR_MAX],
        "quotas": QUOTAS,
        "geohash_precision": GEOHASH_PRECISION,
        "total_eligibles": total,
        "final_sample_size": len(sample),
        "pais_buckets": PAIS_BUCKETS,
        "decade_buckets": DECADES,
        "cell_distribution": cell_summary,
    }
    OUT_AUDIT.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"wrote {OUT_AUDIT}")

    print("\n=== Distribución final por celda ===")
    print(f"  {'cell':<33} {'raw':>10} {'uniq':>8} {'samp':>6}")
    for pais in PAIS_BUCKETS:
        row_total = 0
        for dec in DECADES:
            key = f"{pais} x {dec}"
            s = cell_summary[key]
            n = s.get("sampled_total", 0)
            row_total += n
            print(f"  {key:<33} {s['available_raw']:>10,} {s['available_unique_gh5']:>8,} {n:>6}")
        print(f"  {pais + ' TOTAL':<33} {'':<10} {'':<8} {row_total:>6} (target {QUOTAS[pais]})")


if __name__ == "__main__":
    main()
