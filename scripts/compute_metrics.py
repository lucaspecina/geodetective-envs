"""Computar métricas post-hoc sobre results.json (refs #32).

Uso:
    python scripts/compute_metrics.py experiments/E010_iteration_pilot/results_gpt-5_4-mini.json
    python scripts/compute_metrics.py --all  # todos los results de E005, E009, E010, E012
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geodetective.eval.metrics import compute_metrics_for_file


def fmt_pct(v):
    return f"{100*v:.0f}%" if v is not None else "NA"


def fmt_num(v, fmt=".0f"):
    return format(v, fmt) if v is not None else "NA"


def print_aggregated(label: str, agg: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"  runs: {agg['n_runs']}, submitted: {agg['n_submitted']}/{agg['n_runs']}")
    d = agg.get("dist", {})
    print(f"  distance:  mean={fmt_num(d.get('mean'))} std={fmt_num(d.get('std'))} median={fmt_num(d.get('median'))} km")
    if d.get("hit_rates"):
        hr = " | ".join(f"{k}={fmt_pct(v)}" for k, v in d["hit_rates"].items())
        print(f"             {hr}")
    y = agg.get("year", {})
    if y.get("mae") is not None:
        print(f"  year:      MAE={fmt_num(y['mae'], '.1f')} yrs")
        if y.get("hit_rates"):
            hr = " | ".join(f"{k}={fmt_pct(v)}" for k, v in y["hit_rates"].items())
            print(f"             {hr}")
    c = agg.get("calibration", {})
    if c.get("overconfidence_rate") is not None:
        print(f"  overconfidence (conf=alta + dist>100km): {fmt_pct(c['overconfidence_rate'])}")
        if c.get("confidence_dist"):
            print(f"  confidence dist: {c['confidence_dist']}")
        if c.get("avg_dist_by_confidence"):
            adb = c["avg_dist_by_confidence"]
            print(f"  avg dist by conf: " + ", ".join(f"{k}={fmt_num(v)}km" for k, v in adb.items()))
    v = agg.get("verification", {})
    if v.get("visual_before_submit_rate") is not None:
        print(f"  visual verification before submit: {fmt_pct(v['visual_before_submit_rate'])}")
    print(f"  avg steps: {fmt_num(agg.get('avg_steps'), '.1f')}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", type=Path, help="results.json")
    parser.add_argument("--all", action="store_true", help="todos los results_*.json")
    parser.add_argument("--save", type=Path, default=None, help="guardar JSON agregado")
    args = parser.parse_args()

    if args.all:
        files = sorted(
            glob.glob("experiments/E005_react_pilot/results_*.json")
            + glob.glob("experiments/E009_multimodel/results_*.json")
            + glob.glob("experiments/E010_iteration_pilot/results_*.json")
            + glob.glob("experiments/E012_min_steps/results_*.json")
        )
    else:
        if not args.input:
            raise SystemExit("dame un archivo o usá --all")
        files = [str(args.input)]

    all_agg = {}
    for f in files:
        f_path = Path(f)
        print(f"\n{'='*70}")
        print(f"  {f_path.relative_to(Path.cwd()) if f_path.is_absolute() else f_path}")
        print(f"{'='*70}")
        try:
            per_runs, by_model = compute_metrics_for_file(f_path)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        for model, agg in by_model.items():
            print_aggregated(f"{f_path.stem} · {model}", agg)
            all_agg[f"{f_path.name}:{model}"] = agg

    if args.save:
        args.save.write_text(json.dumps(all_agg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {args.save}")


if __name__ == "__main__":
    main()
