"""Analizador de trayectorias del pilot E005 (#26).

Para cada foto del pilot, imprime paso a paso qué tools llamó el agente,
qué argumentos pasó (queries de search en idioma original), qué encontró,
y el reasoning final estructurado del submit_answer.

Uso:
    python scripts/analyze_pilot_trajectories.py            # todas
    python scripts/analyze_pilot_trajectories.py 2126812    # solo una foto
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

RESULTS = Path("experiments/E005_react_pilot/results.json")


def fmt_event(ev: dict, idx: int) -> str:
    """Formato compacto de un evento del trace."""
    step = ev.get("step", "?")
    typ = ev.get("type", "?")
    if typ == "web_search":
        q = ev.get("query", "")[:120]
        return f"  step {step}  web_search  ({ev.get('result_count', 0)} res, {ev.get('blocked', 0)} bloq)  →  {q!r}"
    if typ in ("crop_image", "crop_image_relative"):
        r = ev.get("region")
        if isinstance(r, dict):
            r_s = f"x={r['x']},y={r['y']},w={r['w']},h={r['h']}"
        else:
            r_s = str(r)
        return f"  step {step}  crop        ({r_s})"
    if typ == "image_search":
        q = ev.get("query", "")[:120]
        return f"  step {step}  image_search  ({ev.get('n_images', 0)} imgs, target_match={ev.get('target_match', 0)})  →  {q!r}"
    if typ in ("fetch_url", "fetch_url_with_images"):
        url = ev.get("url", "")
        tl = ev.get("text_len", 0)
        err = ev.get("error")
        return f"  step {step}  {typ}  ({tl}c, err={err})  →  {url[:120]}"
    if typ in ("geocode", "reverse_geocode"):
        args = ev.get("args", {})
        q = args.get("query") or f"lat={args.get('lat')},lon={args.get('lon')}"
        return f"  step {step}  {typ}  ({ev.get('n_results', 0)} res)  →  {q[:120]!r}"
    if typ == "historical_query":
        args = ev.get("args", {})
        return f"  step {step}  historical_query  ({ev.get('n_features', 0)} feat)  →  preset={args.get('preset')}, year={args.get('year')}"
    if typ in ("static_map", "street_view"):
        args = ev.get("args", {})
        return f"  step {step}  {typ}  →  lat={args.get('lat')},lon={args.get('lon')}"
    if typ == "submit":
        return f"  step {step}  *** SUBMIT ***"
    return f"  step {step}  {typ}  {ev}"


def print_photo(r: dict) -> None:
    cid = r["cid"]
    rr = r.get("react", {})
    trace = rr.get("trace", [])
    final = rr.get("final_answer") or {}
    dist = rr.get("distance_km")
    truth = r["geo"]
    truth_year = r["year"]

    print("=" * 110)
    print(f"#{cid}  [{r['bucket_pais']} / {r['bucket_decada']}]  {r['country']}  {truth_year}")
    print(f"  Title (ground truth): {r['title']}")
    print(f"  Truth coords: lat={truth[0]:.4f}, lon={truth[1]:.4f}")
    print(f"  Pred coords:  lat={final.get('lat')}, lon={final.get('lon')}  (conf={final.get('confidence')})")
    print(f"  Pred location: {final.get('location', 'NO ANSWER')[:100]}")
    print(f"  Distance: {dist:.1f} km" if dist is not None else "  Distance: N/A (max_steps reached)")
    print(f"  Steps used: {rr.get('steps_used')}/{rr.get('max_steps')}  |  Submit called: {rr.get('submit_called')}")
    tool_counts = []
    for k, label in [
        ("web_search_count", "ws"),
        ("fetch_url_count", "fu"),
        ("image_search_count", "is"),
        ("crop_count", "crop"),
        ("geocode_count", "geocode"),
        ("historical_query_count", "hq"),
        ("static_map_count", "sm"),
        ("street_view_count", "sv"),
        ("target_match_count", "target_match"),
    ]:
        n = rr.get(k, 0)
        if n:
            tool_counts.append(f"{label}={n}")
    print(f"  Tool usage: {', '.join(tool_counts)}  |  elapsed: {rr.get('elapsed_seconds')}s")
    print()
    print("  --- TRAJECTORY ---")
    for i, ev in enumerate(trace):
        print(fmt_event(ev, i))

    if final:
        print()
        print("  --- FINAL ANSWER (estructura del submit_answer) ---")
        for k in ["reasoning", "uncertainty_reason"]:
            v = final.get(k)
            if v:
                print(f"  [{k}]")
                print(f"    {v}")
                print()
        for k in ["visual_clues", "external_evidence", "rejected_alternatives", "verification_checks"]:
            v = final.get(k) or []
            if v:
                print(f"  [{k}]  ({len(v)} items)")
                for item in v:
                    print(f"    - {item[:200]}")
                print()
    print()


def main():
    data = json.loads(RESULTS.read_text())
    cli_cids = [int(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else None
    if cli_cids:
        data = [r for r in data if r["cid"] in cli_cids]
    for r in data:
        print_photo(r)


if __name__ == "__main__":
    main()
