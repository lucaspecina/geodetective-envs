"""Viewer HTML focused: muestra paso-a-paso lo que recibe el modelo en cada step.

Para una sola foto / una sola corrida, expone:
- Thinking del modelo (lo que verbalizó)
- Tool call: nombre + args
- Payload exacto recibido como tool_result (lo que el modelo VE)
- Imagen inyectada al user message si la tool produce imagen
- Estado: tokens del payload, si fue truncado

Diseñado para iteración: vos abrís una trace, ves cómo el modelo razona
a partir de la info que realmente le llega, y detectás patrones / problemas.

Uso:
    python scripts/build_iteration_viewer.py experiments/E010_iteration_pilot/results_gpt-5_4-mini.json
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    from geodetective.tools.crop_image import crop_image as _do_crop
    from geodetective.corpus import CLEAN_VERSION as _CLEAN_VERSION
    _CROP_AVAILABLE = True
except Exception:
    _CROP_AVAILABLE = False
    _CLEAN_VERSION = 1


def esc(s: str) -> str:
    return html.escape(str(s) if s is not None else "")


def fmt_payload(payload: str, full_len: int | None = None) -> str:
    """Render payload con header + body monospace + indicator de tamaño."""
    if not payload:
        return '<div class="payload"><span class="muted">(no payload)</span></div>'
    p = esc(payload)
    if full_len and full_len > len(payload):
        size_note = f"<span class='size'>payload {full_len} chars total ({len(payload)} mostrados)</span>"
    else:
        size_note = f"<span class='size'>payload {len(payload)} chars</span>"
    return f'<div class="payload">{size_note}<pre>{p}</pre></div>'


def render_image(b64: str | None, label: str = "") -> str:
    if not b64:
        return ""
    return f'<div class="img-block"><div class="img-label">{esc(label)}</div><img src="data:image/jpeg;base64,{b64}"/></div>'


def reconstruct_crop_b64(cid: int | str, region: dict, photos_dir: Path) -> str | None:
    """Re-crop on the fly desde la foto original. Trace no almacena base64 (size)."""
    if not _CROP_AVAILABLE or not region:
        return None
    img_path = photos_dir / f"{cid}_clean_v{_CLEAN_VERSION}.jpg"
    if not img_path.exists():
        return None
    try:
        cr = _do_crop(
            image_path=img_path,
            x=int(region.get("x", 0)),
            y=int(region.get("y", 0)),
            width=int(region.get("w", 0)),
            height=int(region.get("h", 0)),
        )
        return cr.base64_jpeg
    except Exception:
        return None


def render_event(ev: dict, cid: int | str | None = None, photos_dir: Path | None = None) -> str:
    """Render un evento del trace como una card."""
    t = ev.get("type", "?")
    step = ev.get("step", "?")

    # Thinking eventos: solo content
    if t in ("thinking", "thinking_block"):
        content = esc(ev.get("content", ""))
        cls = "thinking" if t == "thinking" else "thinking-block"
        kind = "thinking" if t == "thinking" else "thinking_block (Anthropic separate)"
        return f"""
<div class="event {cls}">
  <div class="ev-head">
    <span class="step">step {step}</span>
    <span class="type">{kind}</span>
  </div>
  <pre class="thinking-text">{content}</pre>
</div>
"""

    # No tool call: model emitió texto sin invocar tool
    if t == "no_tool_call_in_response":
        content = esc(ev.get("content", ""))
        attempt = ev.get("attempt", "?")
        return f"""
<div class="event no-tool-call">
  <div class="ev-head">
    <span class="step">step {step}</span>
    <span class="type">no_tool_call (attempt {attempt})</span>
  </div>
  <pre class="thinking-text">{content}</pre>
</div>
"""

    # Submit eventos
    if t in ("submit", "submit_rejected"):
        ans = ev.get("answer", {}) or {}
        ans_str = esc(json.dumps(ans, ensure_ascii=False, indent=2))
        cls = "submit" if t == "submit" else "submit-rejected"
        return f"""
<div class="event {cls}">
  <div class="ev-head">
    <span class="step">step {step}</span>
    <span class="type">{t}</span>
  </div>
  <pre>{ans_str}</pre>
</div>
"""

    # Errores
    if t == "empty_response_diagnosis":
        return f"""
<div class="event error">
  <div class="ev-head">
    <span class="step">step {step}</span>
    <span class="type">EMPTY RESPONSE</span>
  </div>
  <div class="ev-detail">finish_reason={esc(ev.get('finish_reason'))} thinking_blocks={ev.get('thinking_blocks_count')}</div>
</div>
"""
    if t.endswith("_error"):
        return f"""
<div class="event error">
  <div class="ev-head">
    <span class="step">step {step}</span>
    <span class="type">{t}</span>
  </div>
  <div class="ev-detail">{esc(ev.get('error', '?'))}</div>
</div>
"""

    # Tool events normales — esto es el grueso de lo que el modelo "recibe"
    # Cada evento tiene: tool args + payload_to_model (qué recibe el modelo)
    # + posibles imágenes inyectadas
    tool_args_parts = []
    if "query" in ev: tool_args_parts.append(f"query: {esc(ev.get('query'))}")
    if "url" in ev: tool_args_parts.append(f"url: {esc(ev.get('url'))}")
    if "args" in ev: tool_args_parts.append(f"args: {esc(json.dumps(ev.get('args'), ensure_ascii=False))}")
    if "region" in ev: tool_args_parts.append(f"region: {esc(json.dumps(ev.get('region'), ensure_ascii=False))}")

    tool_args_html = "<br/>".join(tool_args_parts) or "<i>(no args)</i>"

    payload = ev.get("payload_to_model", "")
    payload_html = fmt_payload(payload, ev.get("payload_full_len"))

    # Imágenes (si la tool inyecta imagen al next user message)
    images_html = ""
    image_inject = ev.get("image_inject_kind")
    if image_inject:
        # Reconstruir las imágenes del trace event
        if t == "static_map":
            images_html = render_image(ev.get("base64_jpeg"), f"static_map {ev.get('map_type', '?')}")
        elif t == "street_view":
            for im in (ev.get("images") or [])[:4]:
                images_html += render_image(im.get("base64_jpeg"), f"heading {im.get('heading')}")
        elif t in ("crop_image", "crop_image_relative"):
            # Trace no almacena base64 (size), re-cropeamos sobre la marcha
            b64 = ev.get("base64_jpeg")
            if not b64 and cid is not None and photos_dir is not None:
                b64 = reconstruct_crop_b64(cid, ev.get("region") or {}, photos_dir)
            if b64:
                region = ev.get("region") or {}
                images_html = render_image(b64, f"crop {region}")
            else:
                images_html = '<span class="muted">[crop image — could not reconstruct]</span>'
    elif t == "image_search":
        # image_search devuelve visible_images con base64
        for im in (ev.get("visible_images") or [])[:5]:
            images_html += render_image(im.get("base64_jpeg"), f"hamming={im.get('hamming_distance')} ({im.get('url','')[:50]})")
    elif t == "fetch_url_with_images":
        for im in (ev.get("visible_images") or [])[:5]:
            images_html += render_image(im.get("base64_jpeg"), f"hamming={im.get('hamming_distance')} ({im.get('url','')[:50]})")

    return f"""
<div class="event tool-event tool-{t}">
  <div class="ev-head">
    <span class="step">step {step}</span>
    <span class="type">{t}</span>
  </div>
  <div class="tool-args">
    <div class="label">→ TOOL CALL args:</div>
    <div class="args-body">{tool_args_html}</div>
  </div>
  <div class="tool-result">
    <div class="label">← MODEL RECEIVED (tool_result message content):</div>
    {payload_html}
  </div>
  {f'<div class="injected-images"><div class="label">+ INJECTED to user message next turn (image_url content):</div>{images_html}</div>' if images_html else ''}
</div>
"""


def render_trace(entry: dict, photos_dir: Path | None = None) -> str:
    """Render UNA trace (1 foto, 1 modelo) entera."""
    cid = entry.get("cid")
    zone = entry.get("zone", "?")
    year = entry.get("year")
    geo = entry.get("geo")
    title = entry.get("title", "")
    rk = entry.get("react", {}) or {}
    model = rk.get("model", "?")
    dist = rk.get("distance_km")
    steps = rk.get("steps_used")
    submit = rk.get("submit_called")
    terminal = rk.get("terminal_state")
    elapsed = rk.get("elapsed_seconds")
    final = rk.get("final_answer") or {}
    trace = rk.get("trace", []) or []

    # Counts
    counts = {k: rk.get(f"{k}_count", 0) for k in
              ("web_search", "fetch_url", "image_search", "geocode", "historical_query",
               "crop", "static_map", "street_view")}
    counts_str = " ".join(f"{k}={v}" for k, v in counts.items() if v)

    events_html = "".join(render_event(ev, cid=cid, photos_dir=photos_dir) for ev in trace)

    dist_str = f"{dist:.0f} km" if dist is not None else "N/A"
    final_loc = (final.get("location", "") or "")[:120]
    final_lat = final.get("lat")
    final_lon = final.get("lon")
    final_year = final.get("year", "?")

    # Foto target original (la misma que ve el modelo en el primer user message)
    target_img_html = ""
    if photos_dir is not None and cid is not None:
        target_path = photos_dir / f"{cid}_clean_v{_CLEAN_VERSION}.jpg"
        if target_path.exists():
            try:
                b64 = base64.b64encode(target_path.read_bytes()).decode()
                target_img_html = (
                    f'<div class="target-img">'
                    f'<div class="img-label">Foto target (la que recibe el modelo en el primer user message)</div>'
                    f'<img src="data:image/jpeg;base64,{b64}"/>'
                    f'</div>'
                )
            except Exception:
                pass

    return f"""
<section class="trace" id="trace-{cid}">
  <header>
    <h2>cid={cid} — {esc(zone)} {year}</h2>
    <div class="meta">
      <b>Truth:</b> geo={esc(geo)} year={year} title={esc(title[:80])} <br/>
      <b>Model:</b> {esc(model)} | steps={steps} max | submit={submit} terminal={esc(terminal)} | t={elapsed}s <br/>
      <b>Tools used:</b> {counts_str or '(none)'} <br/>
      <b>Final answer:</b> {esc(final_loc)} <br/>
      <b>Predicted:</b> lat={final_lat} lon={final_lon} year={esc(final_year)} | <b>distance: {dist_str}</b>
    </div>
    {target_img_html}
  </header>
  <div class="events">
    {events_html}
  </div>
</section>
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>E010 Iteration Viewer — {model_label}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", system-ui, sans-serif; margin: 0; background: #f5f5f7; }}
  nav.sticky {{ position: sticky; top: 0; background: white; border-bottom: 1px solid #ddd; padding: 12px 20px; z-index: 10; }}
  nav.sticky h1 {{ margin: 0 0 8px; font-size: 16px; }}
  nav.sticky .photos a {{ margin-right: 12px; color: #2563eb; text-decoration: none; font-size: 13px; }}
  nav.sticky .photos a:hover {{ text-decoration: underline; }}

  section.trace {{ margin: 24px auto; max-width: 1200px; background: white; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); padding: 24px; }}
  section.trace header h2 {{ margin: 0 0 8px; color: #1f2937; }}
  section.trace .meta {{ font-size: 13px; color: #4b5563; line-height: 1.7; background: #f9fafb; padding: 12px; border-radius: 6px; margin-bottom: 16px; }}
  section.trace .target-img {{ margin: 0 0 20px; padding: 14px; background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 6px; }}
  section.trace .target-img .img-label {{ font-size: 12px; color: #3730a3; font-weight: 600; margin-bottom: 8px; }}
  section.trace .target-img img {{ max-width: 100%; max-height: 500px; border: 1px solid #a5b4fc; border-radius: 4px; display: block; }}

  .event {{ border-left: 4px solid #ddd; padding: 12px 16px; margin: 12px 0; border-radius: 4px; background: #fafafa; }}
  .event .ev-head {{ display: flex; gap: 12px; align-items: baseline; margin-bottom: 8px; }}
  .event .ev-head .step {{ background: #1f2937; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
  .event .ev-head .type {{ color: #1f2937; font-weight: 600; font-size: 13px; }}

  .event.thinking, .event.thinking-block {{ border-left-color: #8b5cf6; background: #faf5ff; }}
  .event.thinking .thinking-text, .event.thinking-block .thinking-text {{ font-family: inherit; white-space: pre-wrap; color: #4c1d95; font-size: 13px; line-height: 1.55; margin: 0; }}

  .event.tool-event {{ border-left-color: #0ea5e9; background: #f0f9ff; }}
  .event .tool-args {{ margin: 8px 0; }}
  .event .tool-args .label {{ font-size: 11px; color: #0369a1; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .event .tool-args .args-body {{ font-family: ui-monospace, "Cascadia Mono", monospace; font-size: 12px; color: #075985; background: #e0f2fe; padding: 8px 10px; border-radius: 4px; word-break: break-all; }}

  .event .tool-result {{ margin: 8px 0; }}
  .event .tool-result .label {{ font-size: 11px; color: #166534; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
  .event .payload {{ background: #f0fdf4; padding: 8px 10px; border-radius: 4px; }}
  .event .payload .size {{ display: block; font-size: 11px; color: #166534; margin-bottom: 4px; }}
  .event .payload pre {{ font-family: ui-monospace, "Cascadia Mono", monospace; font-size: 11.5px; line-height: 1.45; color: #14532d; white-space: pre-wrap; word-break: break-word; max-height: 600px; overflow-y: auto; margin: 0; }}

  .event .injected-images {{ margin: 12px 0 4px; padding: 10px; background: #fefce8; border: 1px dashed #ca8a04; border-radius: 4px; }}
  .event .injected-images .label {{ font-size: 11px; color: #854d0e; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .img-block {{ display: inline-block; margin: 4px 8px 4px 0; vertical-align: top; }}
  .img-block .img-label {{ font-size: 10px; color: #713f12; margin-bottom: 2px; }}
  .img-block img {{ max-width: 280px; max-height: 200px; border: 1px solid #d4d4d8; border-radius: 4px; }}

  .event.submit {{ border-left-color: #16a34a; background: #f0fdf4; }}
  .event.submit-rejected {{ border-left-color: #dc2626; background: #fef2f2; }}
  .event.error {{ border-left-color: #dc2626; background: #fef2f2; }}
  .event.no-tool-call {{ border-left-color: #f59e0b; background: #fffbeb; }}

  .event pre {{ white-space: pre-wrap; font-family: ui-monospace, "Cascadia Mono", monospace; font-size: 12px; line-height: 1.5; margin: 0; }}
  .muted {{ color: #9ca3af; font-style: italic; }}
</style>
</head>
<body>
<nav class="sticky">
  <h1>E010 Iteration Viewer — {model_label} ({n_traces} traces)</h1>
  <div class="photos">
    {nav_links}
  </div>
</nav>
{traces_html}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="results_*.json del pilot")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--photos-dir", type=Path, default=None,
                        help="dir con {cid}_clean_v{N}.jpg para reconstruir crops. "
                             "Default: <input_parent>/photos/")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"not found: {args.input}")

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not data:
        raise SystemExit("empty results")

    model_label = (data[0].get("react") or {}).get("model", "?")

    nav_links = " | ".join(
        f'<a href="#trace-{r["cid"]}">{r.get("zone", "?")} {r.get("year", "?")} (cid={r["cid"]})</a>'
        for r in data
    )

    photos_dir = args.photos_dir or (args.input.parent / "photos")
    traces_html = "\n".join(render_trace(r, photos_dir=photos_dir) for r in data)

    html_str = HTML_TEMPLATE.format(
        model_label=esc(model_label),
        n_traces=len(data),
        nav_links=nav_links,
        traces_html=traces_html,
    )

    out = args.output or (args.input.parent / f"viewer_{args.input.stem.replace('results_', '')}.html")
    out.write_text(html_str, encoding="utf-8")
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"wrote {out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
