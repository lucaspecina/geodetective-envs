"""Audit del dump de metadata de PastVu (`pastvu.jsonl.zst`).

Streamea el archivo comprimido sin cargar todo en RAM. Calcula distribuciones
clave para decidir buckets de #17 y validar afirmaciones de `genesis-intro.md`
y `research/notes/pastvu_deep_dive.md`.

Uso:
    python scripts/audit_pastvu_metadata.py
"""

from __future__ import annotations

import io
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import zstandard as zstd

DATA_PATH = Path("experiments/E006_pastvu_audit/data/pastvu.jsonl.zst")
OUT_JSON = Path("experiments/E006_pastvu_audit/results.json")

YEAR_MIN_FOCUS = 1850
YEAR_MAX_FOCUS = 1950


def decade(year: int) -> str:
    return f"{(year // 10) * 10}s"


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"missing: {DATA_PATH}")

    t0 = time.time()
    total = 0
    by_type: Counter[int] = Counter()
    has_geo = 0
    has_year = 0
    has_country = 0
    by_decade: Counter[str] = Counter()
    by_country: Counter[str] = Counter()
    year_min = 9999
    year_max = 0
    waterh_stats = Counter()
    has_waterh = 0
    type1_pre1950_geo_year = 0
    cross_country_decade: dict[str, Counter[str]] = defaultdict(Counter)

    # Round 2: campos adicionales sugeridos por Codex review
    regions_depth_hist: Counter[int] = Counter()
    s_status_hist: Counter = Counter()
    has_year2_diff_year = 0
    has_dir = 0
    has_title = 0
    has_desc = 0
    has_user_login = 0
    dim_buckets: Counter[str] = Counter()  # 'tiny', 'small', 'medium', 'large'

    with open(DATA_PATH, "rb") as f:
        dctx = zstd.ZstdDecompressor()
        reader = io.TextIOWrapper(dctx.stream_reader(f), encoding="utf-8")
        for line in reader:
            total += 1
            try:
                rec = json.loads(line)["photo"]
            except (json.JSONDecodeError, KeyError):
                continue

            t = rec.get("type")
            by_type[t] += 1

            geo = rec.get("geo")
            year = rec.get("year")
            regions = rec.get("regions") or []

            geo_ok = isinstance(geo, list) and len(geo) == 2 and all(isinstance(v, (int, float)) for v in geo)
            year_ok = isinstance(year, int) and 1700 <= year <= 2030
            country = regions[0].get("title_en") if regions else None

            if geo_ok: has_geo += 1
            if year_ok: has_year += 1
            if country: has_country += 1

            if year_ok:
                year_min = min(year_min, year)
                year_max = max(year_max, year)
                by_decade[decade(year)] += 1

            if country:
                by_country[country] += 1

            wh = rec.get("waterh")
            if isinstance(wh, int) and wh > 0:
                has_waterh += 1
                waterh_stats[wh] += 1

            if (
                t == 1
                and geo_ok
                and year_ok
                and YEAR_MIN_FOCUS <= year <= YEAR_MAX_FOCUS
            ):
                type1_pre1950_geo_year += 1
                if country:
                    cross_country_decade[country][decade(year)] += 1

            # Round 2 extras (sobre TODOS los records, no solo eligibles)
            regions_depth_hist[len(regions)] += 1
            s = rec.get("s")
            if s is not None:
                s_status_hist[s] += 1
            year2 = rec.get("year2")
            if year_ok and isinstance(year2, int) and year2 != year:
                has_year2_diff_year += 1
            if rec.get("dir"): has_dir += 1
            if rec.get("title"): has_title += 1
            if rec.get("desc"): has_desc += 1
            user = rec.get("user")
            if isinstance(user, dict) and user.get("login"):
                has_user_login += 1
            w = rec.get("w") or 0
            h = rec.get("h") or 0
            longest = max(w, h)
            if longest == 0: dim_buckets["unknown"] += 1
            elif longest < 400: dim_buckets["tiny (<400px)"] += 1
            elif longest < 800: dim_buckets["small (400-800px)"] += 1
            elif longest < 1600: dim_buckets["medium (800-1600px)"] += 1
            else: dim_buckets["large (>=1600px)"] += 1

            if total % 200_000 == 0:
                print(f"  {total:,} records ({time.time()-t0:.1f}s)")

    elapsed = time.time() - t0

    decades_sorted = sorted(by_decade.items())
    countries_top = by_country.most_common(40)
    waterh_top = waterh_stats.most_common(15)

    top_countries_for_cross = [c for c, _ in by_country.most_common(15)]
    cross_table = {}
    for c in top_countries_for_cross:
        cross_table[c] = dict(sorted(cross_country_decade[c].items()))

    out = {
        "data_path": str(DATA_PATH),
        "elapsed_seconds": round(elapsed, 1),
        "total_records": total,
        "by_type": dict(by_type),
        "completeness": {
            "has_geo": has_geo,
            "has_year": has_year,
            "has_country": has_country,
            "has_geo_pct": round(100 * has_geo / total, 2) if total else 0,
            "has_year_pct": round(100 * has_year / total, 2) if total else 0,
            "has_country_pct": round(100 * has_country / total, 2) if total else 0,
        },
        "year_range": {"min": year_min, "max": year_max},
        "by_decade": dict(decades_sorted),
        "by_country_top40": dict(countries_top),
        "watermark": {
            "has_waterh_count": has_waterh,
            "has_waterh_pct": round(100 * has_waterh / total, 2) if total else 0,
            "waterh_height_top15": dict(waterh_top),
        },
        "corpus_eligible": {
            "criteria": f"type==1 AND has_geo AND has_year AND {YEAR_MIN_FOCUS}<=year<={YEAR_MAX_FOCUS}",
            "count": type1_pre1950_geo_year,
            "pct_of_total": round(100 * type1_pre1950_geo_year / total, 2) if total else 0,
        },
        "cross_country_decade_top15": cross_table,
        "regions_depth_hist": dict(sorted(regions_depth_hist.items())),
        "s_status_hist": dict(s_status_hist.most_common()),
        "year2_diff_year_count": has_year2_diff_year,
        "has_dir_count": has_dir,
        "has_title_count": has_title,
        "has_desc_count": has_desc,
        "has_user_login_count": has_user_login,
        "image_dimension_buckets": dict(dim_buckets),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {OUT_JSON} ({elapsed:.1f}s, {total:,} records)")


if __name__ == "__main__":
    main()
