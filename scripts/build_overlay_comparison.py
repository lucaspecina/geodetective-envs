"""Compara detecciones de overlay de varios modelos sobre las MISMAS fotos.

Lee N directorios de detección (output de detect_text_overlays.py) y para cada
cid común genera una fila con:
  - foto original (1 columna)
  - viz + tabla de regiones, por modelo (N columnas, una por modelo)
  - blur post, por modelo

Uso:
    python scripts/build_overlay_comparison.py \\
        --runs gpt-5.4:experiments/E011_text_overlay_detection/sample30 \\
               claude-opus-4-6:experiments/E011_text_overlay_detection/sample30_claude \\
        --output experiments/E011_text_overlay_detection/compare.html
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def to_data_url(path: Path) -> str | None:
    if not path or not path.exists():
        return None
    return f"data:image/jpeg;base64,{base64.b64encode(path.read_bytes()).decode()}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True,
                        help="label:path/to/run, ej: gpt-5.4:experiments/.../sample30")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only-overlay", action="store_true",
                        help="solo fotos donde al menos UN modelo detectó archive_overlay")
    args = parser.parse_args()

    runs: list[tuple[str, Path]] = []
    for r in args.runs:
        label, _, path = r.partition(":")
        runs.append((label, Path(path)))

    by_cid: dict[str, dict[str, dict]] = {}  # cid -> label -> detection
    photo_path_by_cid: dict[str, str] = {}
    for label, run_dir in runs:
        det_file = run_dir / "detections.json"
        if not det_file.exists():
            print(f"[warn] no detections in {run_dir}")
            continue
        dets = json.loads(det_file.read_text(encoding="utf-8"))
        for d in dets:
            cid = str(d.get("cid"))
            by_cid.setdefault(cid, {})[label] = d
            if d.get("photo"):
                photo_path_by_cid[cid] = d["photo"]

    cids = sorted(by_cid.keys(), key=lambda c: int(c) if c.isdigit() else 0)
    if args.only_overlay:
        cids = [
            c for c in cids
            if any(
                any(r.get("classification") == "archive_overlay" for r in (by_cid[c].get(lbl, {}).get("regions") or []))
                for lbl, _ in runs
            )
        ]

    print(f"comparing {len(runs)} runs over {len(cids)} cids")

    sections = []
    for cid in cids:
        orig_url = to_data_url(Path(photo_path_by_cid.get(cid, "")))
        orig_html = f"<div class='col'><div class='lbl'>Original</div><img src='{orig_url}'/></div>" if orig_url else "<div class='col'><i>orig missing</i></div>"

        cols = [orig_html]
        for label, run_dir in runs:
            d = by_cid[cid].get(label)
            if not d:
                cols.append(f"<div class='col'><div class='lbl'>{esc(label)}</div><i>(no det)</i></div>")
                continue
            viz_url = to_data_url(run_dir / "viz" / f"{cid}.jpg")
            blur_url = to_data_url(run_dir / "blurred" / f"{cid}.jpg")
            regions = d.get("regions", []) or []
            n_overlay = sum(1 for r in regions if r.get("classification") == "archive_overlay")
            n_scene = sum(1 for r in regions if r.get("classification") == "in_scene")
            n_unc = sum(1 for r in regions if r.get("classification") == "uncertain")
            rows = []
            for r in regions:
                cls = r.get("classification", "?")
                rows.append(
                    f"<tr><td><span class='pill {cls}'>{cls[:6]}</span></td>"
                    f"<td title='{esc(r.get('reasoning',''))}'>{esc((r.get('text_snippet','') or '')[:40])}</td></tr>"
                )
            table = f"<table>{''.join(rows)}</table>" if rows else "<i>(sin regiones)</i>"
            viz_html = f"<img src='{viz_url}'/>" if viz_url else "<i>(no viz)</i>"
            blur_html = f"<img src='{blur_url}'/>" if blur_url else "<i>(no blur)</i>"
            cols.append(f"""<div class='col'>
  <div class='lbl'>{esc(label)} · scene={n_scene} overlay={n_overlay} unc={n_unc}</div>
  {viz_html}
  <div class='blur-wrap'><div class='lbl-sub'>post-blur</div>{blur_html}</div>
  {table}
</div>""")

        sections.append(f"""<section><h2>cid={cid}</h2><div class='grid' style='grid-template-columns:repeat({len(cols)},1fr)'>{''.join(cols)}</div></section>""")

    n_cols = len(runs) + 1
    html_str = f"""<!doctype html><html><head><meta charset="utf-8"/>
<title>Overlay detection comparison</title>
<style>
  body{{font-family:-apple-system,Segoe UI,sans-serif;margin:0;background:#f5f5f7}}
  section{{max-width:{n_cols*350+200}px;margin:24px auto;background:#fff;border-radius:8px;padding:18px;box-shadow:0 2px 6px rgba(0,0,0,0.06)}}
  h2{{margin:0 0 12px;color:#1f2937;font-size:14px}}
  .grid{{display:grid;gap:12px}}
  .col{{min-width:0}}
  .col img{{width:100%;border:1px solid #ddd;border-radius:4px;display:block}}
  .col .lbl{{font-size:11px;font-weight:600;color:#1f2937;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.3px}}
  .col .lbl-sub{{font-size:10px;color:#666;margin:6px 0 2px}}
  .col .blur-wrap{{margin-top:8px}}
  table{{width:100%;font-size:11px;margin-top:6px;border-collapse:collapse}}
  td{{padding:3px 6px;border-bottom:1px solid #eee;vertical-align:top}}
  .pill{{display:inline-block;padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600;color:white}}
  .pill.in_scene{{background:#22c55e}}
  .pill.archive_overlay{{background:#dc2626}}
  .pill.uncertain{{background:#f59e0b}}
</style></head><body>
{''.join(sections)}
</body></html>"""

    args.output.write_text(html_str, encoding="utf-8")
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"wrote {args.output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
