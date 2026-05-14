"""CLI: corre el process eval annotator sobre un results.json de pilot.

Para cada trace válida en el input:
1. Serializa el trace.
2. Stage 1 LLM call → nodes H/T/E/J/U/C.
3. Stage 2 LLM call → edges.
4. Stage 3a Python deterministic → patterns structural.
5. Guarda el AnnotatorResult.

Uso:
    python scripts/run_annotator.py experiments/E005_react_pilot/results_v3_thinking_visible.json
    python scripts/run_annotator.py path/to/results.json --output path/to/annotated.json
    JUDGE_MODEL=claude-opus-4-6 python scripts/run_annotator.py results.json
    MAX_TRACES=2 python scripts/run_annotator.py results.json  # smoke test rápido
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# UTF-8 stdout en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Cargar .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.judge import annotate_trace


def _build_ground_truth(r: dict) -> dict:
    return {
        "geo": r.get("geo"),
        "year": r.get("year"),
        "country": r.get("country"),
        "title": r.get("title"),
    }


def _result_filename(input_path: Path) -> str:
    """`results_v3_thinking_visible.json` → `annotated_v3_thinking_visible.json`."""
    name = input_path.stem
    if name.startswith("results_"):
        name = "annotated_" + name[len("results_"):]
    else:
        name = "annotated_" + name
    return name + ".json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="results.json del pilot")
    parser.add_argument("--output", type=Path, default=None, help="output annotated.json")
    parser.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "claude-opus-4-6"))
    parser.add_argument("--max-traces", type=int, default=int(os.environ.get("MAX_TRACES", "999")))
    parser.add_argument("--cids", help="solo estos cids (comma-separated)", default=None)
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--quiet", dest="verbose", action="store_false")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"not found: {args.input}")

    data = json.loads(args.input.read_text(encoding="utf-8"))
    cids_filter = None
    if args.cids:
        cids_filter = {int(c.strip()) for c in args.cids.split(",")}

    output = args.output or (args.input.parent / _result_filename(args.input))

    # Resume support: si existe output, no re-anotar trace_ids ya hechos.
    annotated: list[dict] = []
    already_done: set[str] = set()
    if output.exists():
        try:
            annotated = json.loads(output.read_text(encoding="utf-8"))
            already_done = {a.get("trace_id") for a in annotated if a.get("trace_id") and not a.get("error")}
            print(f"[resume] {len(already_done)} traces already annotated in {output}")
        except Exception:
            annotated = []

    to_run = []
    for r in data:
        if "react" not in r or not r.get("react"):
            continue
        cid = r.get("cid")
        if cids_filter and cid not in cids_filter:
            continue
        rk = r["react"]
        if not rk.get("trace"):
            continue
        model = rk.get("model") or args.input.stem
        pv = rk.get("prompt_version") or "v3_thinking_visible"
        trace_id = f"{cid}_{pv}_{model}"
        if trace_id in already_done:
            continue
        to_run.append((r, rk, trace_id))

    if not to_run:
        print("nothing to annotate (all done or no valid traces)")
        return
    to_run = to_run[: args.max_traces]

    print(f"Annotating {len(to_run)} traces with judge={args.judge_model}")
    print(f"Output: {output}")
    print()

    t0_all = time.time()
    for i, (r, rk, trace_id) in enumerate(to_run, 1):
        cid = r["cid"]
        model = rk.get("model")
        pv = rk.get("prompt_version") or "v3_thinking_visible"
        trace = rk.get("trace") or []
        print(f"[{i}/{len(to_run)}] {trace_id} ({len(trace)} events)")
        t0 = time.time()
        try:
            ar = annotate_trace(
                cid=cid,
                model=model,
                prompt_version=pv,
                trace=trace,
                ground_truth=_build_ground_truth(r),
                final_answer=rk.get("final_answer"),
                distance_km=rk.get("distance_km"),
                year_error=rk.get("year_error"),
                judge_model=args.judge_model,
                verbose=args.verbose,
            )
            elapsed = time.time() - t0
            d = ar.to_dict()
            d["elapsed_seconds"] = round(elapsed, 1)
            annotated.append(d)
            output.write_text(json.dumps(annotated, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"    done in {elapsed:.1f}s, saved.")
        except Exception as e:
            import traceback
            err = {
                "trace_id": trace_id, "cid": cid, "model": model, "prompt_version": pv,
                "judge_model": args.judge_model,
                "error": f"{type(e).__name__}: {str(e)[:500]}",
                "traceback": traceback.format_exc()[:2000],
                "elapsed_seconds": round(time.time() - t0, 1),
            }
            annotated.append(err)
            output.write_text(json.dumps(annotated, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"    FAILED: {err['error'][:160]}")

    print(f"\nDone in {time.time() - t0_all:.0f}s. Wrote {output}")


if __name__ == "__main__":
    main()
