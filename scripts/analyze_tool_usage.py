"""Análisis cualitativo del uso de tools: qué piden los modelos y qué reciben.

Para cada tool top, samplea N ejemplos representativos:
- args del tool call (qué pidió el modelo)
- payload_to_model (qué recibió, EXACTAMENTE)
- thinking inmediatamente posterior (cómo reaccionó)
- contexto: cid, modelo, step

Output: markdown estructurado por tool, con ejemplos concretos.

Uso:
    python scripts/analyze_tool_usage.py --output research/notes/tool_usage_audit.md
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


TOOL_FIELDS = {
    "web_search": ["query", "top_results", "payload_to_model"],
    "image_search": ["query", "visible_images", "payload_to_model"],
    "crop_image_relative": ["region", "payload_to_model"],
    "crop_image": ["region", "payload_to_model"],
    "geocode": ["args", "top_results", "payload_to_model"],
    "reverse_geocode": ["args", "top_results", "payload_to_model"],
    "static_map": ["args", "lat", "lon", "map_type", "payload_to_model"],
    "street_view": ["args", "actual_lat", "actual_lon", "distance_to_pano_m", "payload_to_model"],
    "fetch_url": ["url", "title", "text_snippet", "payload_to_model"],
    "fetch_url_with_images": ["url", "title", "n_images", "target_match", "payload_to_model"],
    "historical_query": ["args", "n_features", "payload_to_model"],
}


def collect_events() -> list[dict]:
    """Recolecta TODOS los tool events con su contexto (thinking before/after)."""
    all_files = []
    for pat in [
        "experiments/E005_react_pilot/results_*.json",
        "experiments/E009_multimodel/results_*.json",
        "experiments/E010_iteration_pilot/results_*.json",
        "experiments/E012_min_steps/results_*.json",
    ]:
        all_files.extend(sorted(glob.glob(pat)))

    events = []
    for f in all_files:
        exp = Path(f).parent.name
        data = json.loads(open(f, encoding="utf-8").read())
        for r in data:
            rk = r.get("react") or {}
            model = rk.get("model", "?")
            cid = r["cid"]
            zone = r.get("zone", "?")
            year = r.get("year", "?")
            trace = rk.get("trace", []) or []
            # Indexar trace por step para sacar thinking before/after
            for i, ev in enumerate(trace):
                t = ev.get("type", "")
                if t not in TOOL_FIELDS:
                    continue
                # Buscar thinking en mismo step o previo
                thinking_before = ""
                for j in range(i - 1, max(-1, i - 5), -1):
                    if trace[j].get("type") in ("thinking", "thinking_block"):
                        thinking_before = trace[j].get("content", "")[:500]
                        break
                # Buscar thinking en step siguiente
                thinking_after = ""
                cur_step = ev.get("step", -1)
                for j in range(i + 1, min(len(trace), i + 8)):
                    if trace[j].get("type") in ("thinking", "thinking_block"):
                        if trace[j].get("step") > cur_step:
                            thinking_after = trace[j].get("content", "")[:500]
                            break

                events.append({
                    "experiment": exp, "model": model, "cid": cid, "zone": zone, "year": year,
                    "step": cur_step,
                    "tool": t,
                    "event": ev,
                    "thinking_before": thinking_before,
                    "thinking_after": thinking_after,
                })
    return events


def render_event_md(ev: dict) -> str:
    e = ev["event"]
    t = ev["tool"]
    out = []
    out.append(f"#### {ev['experiment']} · {ev['model']} · cid={ev['cid']} ({ev['zone']} {ev['year']}) · step {ev['step']}")
    if ev["thinking_before"]:
        out.append("")
        out.append("**Thinking antes:**")
        out.append("```")
        out.append(ev["thinking_before"])
        out.append("```")

    out.append("")
    out.append("**Tool call args:**")
    out.append("```")
    if t in ("web_search", "image_search"):
        out.append(f'query: {e.get("query", "?")}')
    elif t in ("crop_image", "crop_image_relative"):
        out.append(f'region: {json.dumps(e.get("region", {}), ensure_ascii=False)}')
    elif t in ("geocode", "reverse_geocode", "static_map", "street_view", "historical_query"):
        args = e.get("args", {})
        out.append(json.dumps(args, ensure_ascii=False, indent=2))
    elif t in ("fetch_url", "fetch_url_with_images"):
        out.append(f'url: {e.get("url", "?")}')
    out.append("```")

    payload = e.get("payload_to_model", "")
    if payload:
        out.append("")
        out.append(f"**Lo que el modelo recibió (payload, {len(payload)} chars):**")
        out.append("```")
        # Truncar si es muy largo
        truncated = payload[:1500]
        out.append(truncated)
        if len(payload) > 1500:
            out.append(f"... [+{len(payload)-1500} chars truncados]")
        out.append("```")

    if ev["thinking_after"]:
        out.append("")
        out.append("**Thinking después:**")
        out.append("```")
        out.append(ev["thinking_after"])
        out.append("```")

    out.append("")
    out.append("---")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("research/notes/tool_usage_audit.md"))
    parser.add_argument("--per-tool", type=int, default=4, help="N ejemplos por tool")
    args = parser.parse_args()

    print("Collecting events...")
    events = collect_events()
    print(f"Total events: {len(events)}")

    by_tool = defaultdict(list)
    for ev in events:
        by_tool[ev["tool"]].append(ev)

    # Stats globales
    out = ["# Tool usage audit — análisis cualitativo (E005 + E009 + E010 + E012)\n"]
    out.append(f"> Generado automáticamente con `scripts/analyze_tool_usage.py`. Total events analizados: {len(events)}.\n")
    out.append("## Resumen cuantitativo\n")
    out.append("| Tool | Calls | % |")
    out.append("|---|---|---|")
    total = sum(len(v) for v in by_tool.values())
    for tool, evs in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        out.append(f"| `{tool}` | {len(evs)} | {100*len(evs)/total:.1f}% |")
    out.append("")

    # Para cada tool top: ejemplos diversos
    out.append("## Ejemplos por tool (sample diverso de modelos × experimentos)\n")
    for tool, evs in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        if len(evs) == 0:
            continue
        out.append(f"\n## `{tool}` — {len(evs)} calls\n")
        # Samplear 1 ejemplo por (experimento, modelo) único hasta llegar a per-tool
        seen = set()
        picks = []
        for ev in evs:
            key = (ev["experiment"], ev["model"])
            if key not in seen:
                picks.append(ev)
                seen.add(key)
            if len(picks) >= args.per_tool:
                break
        for p in picks:
            out.append(render_event_md(p))

    args.output.write_text("\n".join(out), encoding="utf-8")
    size_kb = args.output.stat().st_size / 1024
    print(f"\nWrote {args.output} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
