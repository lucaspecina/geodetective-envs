"""Compara dos corridas del pilot E005 (mismas fotos, prompts distintos).

Lee `results_v1_mechanical.json` y `results_v2_descriptive.json` y produce:
- Tabla side-by-side con distancia + tool counts por foto.
- Stats agregadas (uso de sv/sm/hq, web_search saturation, submit rate).
- Quién mejoró / empeoró / sin cambio.

Uso:
    python scripts/compare_pilots.py
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

EXP = Path("experiments/E005_react_pilot")
V1 = EXP / "results_v1_mechanical.json"
V2 = EXP / "results_v2_descriptive.json"


def by_cid(data: list[dict]) -> dict[int, dict]:
    return {r["cid"]: r for r in data}


def fmt_dist(d):
    return f"{d:.0f}km" if d is not None else "N/A"


def main():
    if not V1.exists() or not V2.exists():
        raise SystemExit(f"missing: {V1.exists()=} {V2.exists()=}")

    a = by_cid(json.loads(V1.read_text()))
    b = by_cid(json.loads(V2.read_text()))
    cids = sorted(a.keys() & b.keys())

    print("=" * 130)
    print(f"COMPARACIÓN — {len(cids)} fotos en común")
    print(f"  v1: prompt mecánico (descripciones puras de la signature)")
    print(f"  v2: prompt descriptivo (mecánica + qué aporta cada tool, sin prescribir cuándo)")
    print("=" * 130)

    print()
    print(f"{'CID':>8}  {'bucket':<20}  {'v1 dist':>8}  {'v2 dist':>8}  {'v1 steps':>8}  {'v2 steps':>8}  {'v1 conf':>10}  {'v2 conf':>10}  {'verdict':<30}")
    print("-" * 130)

    deltas = []
    for cid in cids:
        ra = a[cid]["react"]
        rb = b[cid]["react"]
        bucket = f"{a[cid]['bucket_pais']}/{a[cid]['bucket_decada']}"
        da = ra.get("distance_km")
        db_ = rb.get("distance_km")
        ca = (ra.get("final_answer") or {}).get("confidence", "-")
        cb = (rb.get("final_answer") or {}).get("confidence", "-")
        sa = ra.get("submit_called")
        sb = rb.get("submit_called")

        if not sa and sb:
            verdict = "V2 RECUPERÓ submit"
        elif sa and not sb:
            verdict = "V2 perdió submit"
        elif da is None and db_ is None:
            verdict = "ambos N/A"
        elif da is None:
            verdict = "v2 dió respuesta"
        elif db_ is None:
            verdict = "v2 perdió respuesta"
        elif db_ < da * 0.5:
            verdict = "V2 MEJOR (≥50% más cerca)"
        elif db_ > da * 2:
            verdict = "v2 peor (≥2x off)"
        else:
            verdict = "similar"
        deltas.append((cid, da, db_, sa, sb, verdict))
        print(f"{cid:>8}  {bucket:<20}  {fmt_dist(da):>8}  {fmt_dist(db_):>8}  {ra['steps_used']:>8}  {rb['steps_used']:>8}  {ca:>10}  {cb:>10}  {verdict:<30}")

    print()
    print(f"{'CID':>8}  TOOL USE v1 vs v2 (ws/fu/is/crop/geo/HQ/SM/SV)")
    print("-" * 130)
    diff_uses = Counter()
    diff_uses_v1 = Counter()
    diff_uses_v2 = Counter()
    for cid in cids:
        ra = a[cid]["react"]
        rb = b[cid]["react"]
        v1_tools = {
            "ws": ra["web_search_count"],
            "fu": ra["fetch_url_count"],
            "is": ra["image_search_count"],
            "crop": ra["crop_count"],
            "geo": ra["geocode_count"],
            "HQ": ra["historical_query_count"],
            "SM": ra["static_map_count"],
            "SV": ra["street_view_count"],
        }
        v2_tools = {
            "ws": rb["web_search_count"],
            "fu": rb["fetch_url_count"],
            "is": rb["image_search_count"],
            "crop": rb["crop_count"],
            "geo": rb["geocode_count"],
            "HQ": rb["historical_query_count"],
            "SM": rb["static_map_count"],
            "SV": rb["street_view_count"],
        }
        def fmt(d):
            return "/".join(f"{d[k]}" for k in ["ws","fu","is","crop","geo","HQ","SM","SV"])
        for k in v1_tools:
            diff_uses_v1[k] += v1_tools[k]
            diff_uses_v2[k] += v2_tools[k]
        print(f"{cid:>8}  v1={fmt(v1_tools):<30}  v2={fmt(v2_tools)}")

    print()
    print("=== AGREGADO — uso de tools sumado sobre las 6 fotos ===")
    print(f"{'tool':<12} {'v1':>6} {'v2':>6} {'delta':>8}")
    for k in ["ws", "fu", "is", "crop", "geo", "HQ", "SM", "SV"]:
        v1c = diff_uses_v1[k]
        v2c = diff_uses_v2[k]
        delta = v2c - v1c
        marker = ""
        if k in ("HQ", "SM", "SV"):
            if v1c == 0 and v2c > 0:
                marker = "  ← TOOLS DIFERENCIALES APARECIERON"
            elif v1c == 0 and v2c == 0:
                marker = "  ← (siguen sin usarse)"
        print(f"{k:<12} {v1c:>6} {v2c:>6} {delta:>+8}{marker}")

    submit_v1 = sum(1 for cid in cids if a[cid]["react"].get("submit_called"))
    submit_v2 = sum(1 for cid in cids if b[cid]["react"].get("submit_called"))
    print()
    print(f"Submit rate:  v1={submit_v1}/{len(cids)}  v2={submit_v2}/{len(cids)}")

    answered_v1 = [a[cid]["react"]["distance_km"] for cid in cids if a[cid]["react"].get("distance_km") is not None]
    answered_v2 = [b[cid]["react"]["distance_km"] for cid in cids if b[cid]["react"].get("distance_km") is not None]
    print(f"Con respuesta: v1={len(answered_v1)}/{len(cids)}  v2={len(answered_v2)}/{len(cids)}")
    if answered_v1: print(f"  v1 distancias: min={min(answered_v1):.0f}km median={sorted(answered_v1)[len(answered_v1)//2]:.0f}km")
    if answered_v2: print(f"  v2 distancias: min={min(answered_v2):.0f}km median={sorted(answered_v2)[len(answered_v2)//2]:.0f}km")


if __name__ == "__main__":
    main()
