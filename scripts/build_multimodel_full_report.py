"""Genera un reporte HTML CON TRAYECTORIA COMPLETA cross-modelo (E008).

UI:
- Selector de **modelo** sticky arriba.
- Selector de **foto** sticky abajo del de modelo.
- Vista detallada para la combinación seleccionada: foto + mapa + trayectoria
  step-by-step con crops/imágenes/queries + final answer estructurado.

Diferencia con build_multimodel_report.py (compare view):
- compare view: tarjetas summary lado a lado (1 vistazo de N modelos).
- este (full view): UNA combinación (modelo, foto) a la vez, con todo el detalle.

Uso:
    python scripts/build_multimodel_full_report.py
"""
from __future__ import annotations

import base64
import colorsys
import html
import io
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

# Path del experimento puede pasarse por CLI arg o env var.
if len(sys.argv) > 1:
    EXP = Path(sys.argv[1])
else:
    EXP = Path(os.environ.get("EXP_DIR", "experiments/E008_multimodel"))
PHOTOS_DIR = Path("experiments/E004_attacker_filter/photos")

MODEL_COLORS = {
    "gpt-5_4": ("#1d4ed8", "gpt-5.4"),
    "gpt-5_4-pro": ("#2563eb", "gpt-5.4-pro"),
    "gpt-5": ("#3b82f6", "gpt-5"),
    "gpt-5-mini": ("#60a5fa", "gpt-5-mini"),
    "gpt-5-nano": ("#93c5fd", "gpt-5-nano"),
    "gpt-4o": ("#7c3aed", "gpt-4o"),
    "gpt-4o-mini": ("#a78bfa", "gpt-4o-mini"),
    "gpt-4_1": ("#6366f1", "gpt-4.1"),
    "gpt-4_1-mini": ("#a5b4fc", "gpt-4.1-mini"),
    "claude-opus-4-6": ("#b45309", "claude-opus-4-6"),
    "claude-sonnet-4-6": ("#ea580c", "claude-sonnet-4-6"),
    "claude-haiku-4-5": ("#f97316", "claude-haiku-4-5"),
    "DeepSeek-V3_2": ("#dc2626", "DeepSeek-V3.2"),
    "Kimi-K2_5": ("#e11d48", "Kimi-K2.5"),
    "grok-4-1-fast-reasoning": ("#0f766e", "grok-4-1-fast-reasoning"),
    "Phi-4": ("#7e22ce", "Phi-4"),
}


def color_for_model(key: str) -> tuple[str, str]:
    if key in MODEL_COLORS:
        return MODEL_COLORS[key]
    h = abs(hash(key)) % 360
    r, g, b = colorsys.hls_to_rgb(h / 360.0, 0.4, 0.6)
    hex_c = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
    return hex_c, key.replace("_", ".")


def img_b64(path: Path) -> str:
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode()


def crop_b64(source: Path, region: dict, max_width: int = 600) -> str:
    if not source.exists():
        return ""
    try:
        with Image.open(source) as im:
            x = max(0, int(region.get("x", 0)))
            y = max(0, int(region.get("y", 0)))
            w = max(1, int(region.get("w", im.width)))
            h = max(1, int(region.get("h", im.height)))
            x2 = min(im.width, x + w)
            y2 = min(im.height, y + h)
            cropped = im.crop((x, y, x2, y2))
            if cropped.mode != "RGB":
                cropped = cropped.convert("RGB")
            if cropped.width > max_width:
                ratio = max_width / cropped.width
                new_h = int(cropped.height * ratio)
                cropped = cropped.resize((max_width, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            cropped.save(buf, "JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


TOOL_COLOR = {
    "thinking": "#f5f3ff",
    "web_search": "#fef3c7", "fetch_url": "#fef3c7", "fetch_url_with_images": "#fef3c7",
    "image_search": "#dbeafe", "crop_image": "#dbeafe", "crop_image_relative": "#dbeafe",
    "geocode": "#d1fae5", "reverse_geocode": "#d1fae5",
    "historical_query": "#fce7f3",
    "static_map": "#e0e7ff", "street_view": "#e0e7ff",
    "submit": "#fee2e2",
}
TOOL_ICON = {
    "thinking": "💭",
    "web_search": "🌐", "fetch_url": "📄", "fetch_url_with_images": "📄🖼",
    "image_search": "🖼", "crop_image": "🔍", "crop_image_relative": "🔍",
    "geocode": "📍", "reverse_geocode": "📍",
    "historical_query": "🏛",
    "static_map": "🗺", "street_view": "📷",
    "submit": "★",
}


def render_event_body(ev: dict, source_img: Path) -> str:
    t = ev.get("type", "")
    if t == "thinking":
        c = ev.get("content", "")
        return f'<div class="thinking-text">{html.escape(c)}</div>'
    if t == "web_search":
        q = ev.get("query", "")
        out = [f'<div class="query">{html.escape(q)}</div>',
               f'<div class="meta">{ev.get("result_count", 0)} resultados · {ev.get("blocked", 0)} bloqueados por filtro</div>']
        top = ev.get("top_results") or []
        if top:
            out.append('<details class="results"><summary>Top resultados</summary>')
            for r in top:
                out.append(
                    f'<div class="result-item">'
                    f'<a href="{html.escape(r.get("url", ""))}" target="_blank" rel="noopener"><strong>{html.escape(r.get("title", ""))}</strong></a><br>'
                    f'<span class="result-url">{html.escape((r.get("url") or "")[:100])}</span><br>'
                    f'<span class="result-snippet">{html.escape((r.get("snippet") or ""))}</span>'
                    f'</div>'
                )
            out.append('</details>')
        return "".join(out)
    if t == "image_search":
        q = ev.get("query", "")
        out = [f'<div class="query">{html.escape(q)}</div>',
               f'<div class="meta">{ev.get("n_images", 0)} imágenes · target_match={ev.get("target_match", 0)}</div>']
        imgs = ev.get("visible_images") or []
        if imgs:
            out.append('<div class="img-grid">')
            for im in imgs[:5]:
                b64 = im.get("base64_jpeg", "")
                u = im.get("url", "")
                hd = im.get("hamming_distance")
                if b64:
                    out.append(
                        f'<a href="{html.escape(u)}" target="_blank" rel="noopener" title="{html.escape(u)}">'
                        f'<img src="data:image/jpeg;base64,{b64}" alt="img"/></a>'
                        f'<span class="img-meta">hamming={hd}</span>'
                    )
            out.append('</div>')
        return "".join(out)
    if t in ("crop_image", "crop_image_relative"):
        r = ev.get("region") or {}
        out = [f'<div class="meta">región x={r.get("x")}, y={r.get("y")}, w={r.get("w")}, h={r.get("h")}</div>']
        cb = crop_b64(source_img, r)
        if cb:
            out.append(f'<img class="crop-preview" src="data:image/jpeg;base64,{cb}" alt="crop"/>')
        return "".join(out)
    if t in ("fetch_url", "fetch_url_with_images"):
        url = ev.get("url", "")
        title = ev.get("title", "")
        snippet = ev.get("text_snippet", "")
        out = [f'<div class="query"><a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(url[:120])}</a></div>']
        if title:
            out.append(f'<div class="result-item"><strong>{html.escape(title)}</strong></div>')
        if snippet:
            out.append(f'<div class="result-snippet">{html.escape(snippet)}…</div>')
        out.append(f'<div class="meta">{ev.get("text_len", 0)} chars · err={ev.get("error")}</div>')
        if t == "fetch_url_with_images":
            imgs = ev.get("visible_images") or []
            if imgs:
                out.append('<div class="img-grid">')
                for im in imgs[:5]:
                    b64 = im.get("base64_jpeg", "")
                    u = im.get("url", "")
                    if b64:
                        out.append(
                            f'<a href="{html.escape(u)}" target="_blank" rel="noopener">'
                            f'<img src="data:image/jpeg;base64,{b64}" alt="img"/></a>'
                        )
                out.append('</div>')
        return "".join(out)
    if t in ("geocode", "reverse_geocode"):
        args = ev.get("args") or {}
        q = args.get("query") or f"({args.get('lat')}, {args.get('lon')})"
        return (
            f'<div class="query">{html.escape(str(q))}</div>'
            f'<div class="meta">{ev.get("n_results", 0)} resultados</div>'
        )
    if t == "historical_query":
        args = ev.get("args") or {}
        return (
            f'<div class="meta">preset=<code>{html.escape(str(args.get("preset")))}</code> '
            f'year=<code>{args.get("year")}</code> → <strong>{ev.get("n_features", 0)} features</strong></div>'
        )
    if t == "static_map":
        args = ev.get("args") or {}
        out = [f'<div class="meta">({args.get("lat")}, {args.get("lon")}) · zoom={args.get("zoom")} · type={args.get("map_type", "roadmap")}</div>']
        b64 = ev.get("base64_jpeg")
        if b64:
            out.append(f'<img class="map-preview" src="data:image/jpeg;base64,{b64}" alt="static map"/>')
        return "".join(out)
    if t == "street_view":
        args = ev.get("args") or {}
        out = [f'<div class="meta">solicitado ({args.get("lat")}, {args.get("lon")})']
        if ev.get("pano_date"):
            out.append(f' · panorama {ev["pano_date"]}')
        if ev.get("distance_to_pano_m"):
            out.append(f' · dist al pano real: {ev["distance_to_pano_m"]:.0f}m')
        out.append('</div>')
        imgs = ev.get("images") or []
        if imgs:
            out.append('<div class="img-grid">')
            for im in imgs:
                b64 = im.get("base64_jpeg", "")
                heading = im.get("heading", 0)
                if b64:
                    out.append(
                        f'<div class="sv-card">'
                        f'<img src="data:image/jpeg;base64,{b64}" alt="sv heading={heading}"/>'
                        f'<span class="img-meta">heading {heading}</span>'
                        f'</div>'
                    )
            out.append('</div>')
        return "".join(out)
    if t == "submit":
        ans = ev.get("answer") or {}
        return (
            f'<div class="query">{html.escape(str(ans.get("location", "")))}</div>'
            f'<div class="meta">({ans.get("lat")}, {ans.get("lon")}) · conf={ans.get("confidence")} · año={ans.get("year")}</div>'
        )
    if t.endswith("_error"):
        return f'<div class="meta error">ERROR: {html.escape(str(ev.get("error", "")))}</div>'
    return f'<div class="meta">{html.escape(json.dumps(ev, ensure_ascii=False)[:250])}</div>'


def render_trajectory(trace: list[dict], source_img: Path) -> str:
    by_step: dict[int, list[dict]] = defaultdict(list)
    for ev in trace:
        by_step[ev.get("step", 0)].append(ev)
    steps = sorted(by_step)
    out = ['<div class="trace">']
    for step in steps:
        events = by_step[step]
        out.append(f'<div class="step-group"><div class="step-label">Step {step}</div><div class="step-events">')
        for ev in events:
            t = ev.get("type", "?")
            color = TOOL_COLOR.get(t, "#f3f4f6")
            if t.endswith("_error"):
                color = "#fee2e2"
            icon = TOOL_ICON.get(t, "•")
            cls = "ev-thinking" if t == "thinking" else "ev"
            out.append(
                f'<div class="{cls}" style="background:{color}">'
                f'<div class="ev-head"><span class="ev-icon">{icon}</span><code>{html.escape(t)}</code></div>'
                f'{render_event_body(ev, source_img)}'
                f'</div>'
            )
        out.append('</div></div>')
    out.append('</div>')
    return "".join(out)


TERMINAL_LABELS = {
    "submitted": ("✓ Submitted", "#059669"),
    "max_steps_no_submit": ("⚠ NO ANSWER — el agente agotó max_steps sin submit", "#dc2626"),
    "no_submit_early_text": ("⚠ NO ANSWER — el modelo describió la acción en texto pero NO invocó la tool (función calling fallida)", "#dc2626"),
    "empty_response": ("⚠ Respuesta vacía del modelo", "#dc2626"),
    "api_error": ("⚠ Error en API del modelo", "#dc2626"),
    "invalid_submit": ("⚠ submit_answer inválido tras 3 reintentos", "#dc2626"),
}


def render_final(fa: dict | None, err: str | None = None, terminal_state: str | None = None) -> str:
    if err and not fa:
        label = TERMINAL_LABELS.get(terminal_state, (f"⚠ ERROR del modelo: {err[:200]}", "#dc2626"))[0]
        return f'<p class="no-answer"><strong>{html.escape(label)}</strong><br><code>{html.escape(err[:500])}</code></p>'
    if not fa:
        label = TERMINAL_LABELS.get(terminal_state, ("⚠ NO ANSWER — estado terminal desconocido", "#dc2626"))[0]
        return f'<p class="no-answer"><strong>{html.escape(label)}</strong></p>'
    parts = ['<div class="final-grid">']
    parts.append(f'<div class="final-cell"><span class="lbl">Location</span><span class="val">{html.escape(str(fa.get("location", "")))}</span></div>')
    parts.append(f'<div class="final-cell"><span class="lbl">Coords</span><span class="val">({fa.get("lat")}, {fa.get("lon")})</span></div>')
    parts.append(f'<div class="final-cell"><span class="lbl">Año</span><span class="val">{html.escape(str(fa.get("year", "")))}</span></div>')
    parts.append(f'<div class="final-cell"><span class="lbl">Confidence</span><span class="val">{html.escape(str(fa.get("confidence", "")))}</span></div>')
    parts.append('</div>')
    if r := fa.get("reasoning"):
        parts.append(f'<div class="final-section"><h4>Reasoning</h4><p>{html.escape(r)}</p></div>')
    for k, label in [
        ("visual_clues", "Visual clues"),
        ("external_evidence", "Evidencia externa"),
        ("rejected_alternatives", "Alternativas rechazadas"),
        ("verification_checks", "Verification checks"),
    ]:
        v = fa.get(k) or []
        if v:
            items = "".join(f"<li>{html.escape(str(x))}</li>" for x in v)
            parts.append(f'<div class="final-section"><h4>{label} ({len(v)})</h4><ul>{items}</ul></div>')
    if u := fa.get("uncertainty_reason"):
        parts.append(f'<div class="final-section"><h4>Uncertainty</h4><p><em>{html.escape(u)}</em></p></div>')
    return "".join(parts)


def render_panel(r: dict, model_key: str) -> str:
    cid = r["cid"]
    rr = r.get("react", {})
    fa = rr.get("final_answer") or {}
    err = rr.get("error")
    truth = r["geo"]
    pred_lat = fa.get("lat") if fa else None
    pred_lon = fa.get("lon") if fa else None
    dist = rr.get("distance_km")
    dist_s = f"{dist:.1f} km" if dist is not None else "N/A"
    dist_class = "win" if dist is not None and dist < 10 else ("close" if dist is not None and dist < 100 else "off")
    img_path = PHOTOS_DIR / f"{cid}_clean_v1.jpg"
    img_data = img_b64(img_path)
    map_id = f"map_{model_key}_{cid}"
    color, display = color_for_model(model_key)

    if pred_lat is not None and pred_lon is not None:
        markers_js = (
            f"var t = L.marker([{truth[0]}, {truth[1]}], {{icon: greenIcon}}).addTo(map).bindPopup('TRUTH<br>{html.escape(r['title'][:60])}');\n"
            f"var p = L.marker([{pred_lat}, {pred_lon}], {{icon: redIcon}}).addTo(map).bindPopup('PRED<br>{html.escape(str(fa.get('location', ''))[:60])}');\n"
            f"var group = L.featureGroup([t, p]); map.fitBounds(group.getBounds().pad(0.3));\n"
            f"L.polyline([[{truth[0]}, {truth[1]}], [{pred_lat}, {pred_lon}]], {{color: '#888', dashArray: '6, 4'}}).addTo(map);"
        )
    else:
        markers_js = (
            f"L.marker([{truth[0]}, {truth[1]}], {{icon: greenIcon}}).addTo(map).bindPopup('TRUTH');\n"
            f"map.setView([{truth[0]}, {truth[1]}], 7);"
        )

    tool_pills = []
    for k, label in [
        ("web_search_count", "ws"), ("fetch_url_count", "fu"),
        ("image_search_count", "is"), ("crop_count", "crop"),
        ("geocode_count", "geo"),
        ("historical_query_count", "HQ"), ("static_map_count", "SM"), ("street_view_count", "SV"),
    ]:
        v = rr.get(k, 0)
        if v:
            cls = "pill-diff" if k in ("historical_query_count", "static_map_count", "street_view_count") else "pill"
            tool_pills.append(f'<span class="{cls}">{label}={v}</span>')

    return f"""
<section class="photo-panel" data-model="{model_key}" data-cid="{cid}" id="panel-{model_key}-{cid}">
  <header class="panel-header">
    <h2><span class="model-badge" style="background:{color}">{display}</span> #{cid} · <span class="muted">{r['country']} {r['year']} · {r['bucket_pais']}/{r['bucket_decada']}</span></h2>
    <p class="photo-title">«{html.escape(r['title'])}»</p>
  </header>

  <div class="hero-row">
    <div class="hero-photo">
      <img src="data:image/jpeg;base64,{img_data}" alt="target #{cid}" />
    </div>
    <div class="hero-summary">
      <div id="{map_id}" class="map"></div>
      <div class="summary-stats">
        <div><span class="lbl">Truth coords</span><span class="val">({truth[0]:.4f}, {truth[1]:.4f})</span></div>
        <div><span class="lbl">Pred coords</span><span class="val">{f"({pred_lat}, {pred_lon})" if pred_lat is not None else "N/A"}</span></div>
        <div><span class="lbl">Distancia</span><span class="val dist {dist_class}">{dist_s}</span></div>
        <div><span class="lbl">Steps usados</span><span class="val">{rr.get('steps_used', '—')}/{rr.get('max_steps', '—')}</span></div>
        <div><span class="lbl">Submit</span><span class="val">{'✓ sí' if rr.get('submit_called') else '✗ no'}</span></div>
        <div><span class="lbl">Tiempo</span><span class="val">{rr.get('elapsed_seconds', '—')}s</span></div>
      </div>
      <div class="tool-pills">{' '.join(tool_pills) if tool_pills else '<em class="muted">— sin tools —</em>'}</div>
    </div>
  </div>

  <div class="detail-row">
    <div class="trace-col">
      <h3>Trayectoria paso a paso ({len(rr.get('trace', []))} acciones)</h3>
      {render_trajectory(rr.get('trace', []), img_path)}
    </div>
    <div class="final-col">
      <h3>Respuesta final</h3>
      {render_final(fa, err, rr.get("terminal_state"))}
    </div>
  </div>

  <script>
  (function() {{
    var map = L.map('{map_id}');
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
      {{attribution: '© OSM', maxZoom: 18}}).addTo(map);
    var greenIcon = L.icon({{iconUrl: 'https://cdn.jsdelivr.net/gh/pointhi/leaflet-color-markers@master/img/marker-icon-2x-green.png', iconSize: [25, 41], iconAnchor: [12, 41]}});
    var redIcon = L.icon({{iconUrl: 'https://cdn.jsdelivr.net/gh/pointhi/leaflet-color-markers@master/img/marker-icon-2x-red.png', iconSize: [25, 41], iconAnchor: [12, 41]}});
    {markers_js}
    if (!window._maps) window._maps = {{}};
    window._maps['{model_key}_{cid}'] = map;
  }})();
  </script>
</section>
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>GeoDetective — E008 Full Multi-model</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {{ --bg: #f9fafb; --card: #fff; --border: #e5e7eb; --text: #1f2937; --muted: #6b7280; --accent: #1e3a8a; --thinking-bg: #f5f3ff; --thinking-border: #8b5cf6; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; background: var(--bg); color: var(--text); line-height: 1.45; }}

.top {{ position: sticky; top: 0; background: white; border-bottom: 2px solid var(--border); padding: .75rem 1.5rem; z-index: 200; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
.top h1 {{ margin: 0 0 .5rem 0; font-size: 1.05rem; color: var(--accent); }}
.selectors {{ display: flex; flex-direction: column; gap: .5rem; }}
.selector-row {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
.selector-row strong {{ font-size: .8rem; text-transform: uppercase; color: var(--muted); letter-spacing: .04em; min-width: 70px; }}
.selector-row button {{ border: 1px solid var(--border); background: var(--card); padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: .8rem; font-family: inherit; transition: all .15s; color: var(--text); }}
.selector-row button:hover {{ background: #eff6ff; border-color: #3b82f6; }}
.selector-row button.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
.selector-row button.model-btn .pill-dist, .selector-row button.photo-btn .pill-dist {{ display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 10px; font-size: .7em; }}
.selector-row button.model-btn.active .pill-dist, .selector-row button.photo-btn.active .pill-dist {{ background: rgba(255,255,255,0.25); color: white; }}
.pill-dist.win {{ background: #d1fae5; color: #065f46; }}
.pill-dist.close {{ background: #fed7aa; color: #9a3412; }}
.pill-dist.off {{ background: #fecaca; color: #991b1b; }}
.pill-dist.na {{ background: #e5e7eb; color: #4b5563; }}

main {{ max-width: 1400px; margin: 1rem auto; padding: 0 1.5rem; }}

.photo-panel {{ display: none; }}
.photo-panel.active {{ display: block; }}

.panel-header h2 {{ margin: .25rem 0; color: var(--accent); font-size: 1.3rem; display: flex; align-items: center; gap: .5rem; }}
.panel-header .muted {{ color: var(--muted); font-weight: normal; font-size: 1rem; }}
.model-badge {{ color: white; padding: 3px 10px; border-radius: 4px; font-size: .8rem; font-weight: bold; }}
.photo-title {{ font-style: italic; color: #4b5563; margin: .25rem 0 1rem; }}

.hero-row {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.5rem; margin-bottom: 1.5rem; }}
.hero-photo img {{ width: 100%; height: auto; max-height: 500px; object-fit: contain; background: black; border-radius: 6px; }}
.hero-summary {{ display: flex; flex-direction: column; gap: 1rem; }}
.map {{ height: 320px; border-radius: 6px; border: 1px solid var(--border); }}
.summary-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: .5rem 1rem; background: var(--card); padding: .75rem 1rem; border-radius: 6px; border: 1px solid var(--border); font-size: .9rem; }}
.summary-stats > div {{ display: flex; flex-direction: column; }}
.summary-stats .lbl {{ font-size: .75em; text-transform: uppercase; color: var(--muted); letter-spacing: .03em; }}
.summary-stats .val {{ font-weight: 500; }}
.dist.win {{ color: #059669; font-weight: bold; }}
.dist.close {{ color: #d97706; font-weight: bold; }}
.dist.off {{ color: #dc2626; font-weight: bold; }}
.tool-pills {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.tool-pills .pill {{ background: #e5e7eb; color: #374151; padding: 3px 8px; border-radius: 4px; font-size: .8rem; }}
.tool-pills .pill-diff {{ background: #fef3c7; color: #78350f; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: .8rem; }}

.detail-row {{ display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 1.5rem; }}
.detail-row h3 {{ margin: 0 0 .75rem 0; font-size: 1rem; text-transform: uppercase; letter-spacing: .04em; color: #374151; }}

.trace {{ display: flex; flex-direction: column; gap: .75rem; }}
.step-group {{ display: grid; grid-template-columns: 60px 1fr; gap: .5rem; align-items: start; }}
.step-label {{ font-size: .85rem; font-weight: bold; color: var(--muted); padding-top: .25rem; text-align: right; padding-right: .5rem; border-right: 2px solid var(--border); }}
.step-events {{ display: flex; flex-direction: column; gap: .35rem; }}
.ev {{ border-radius: 4px; padding: .5rem .75rem; font-size: .85rem; border-left: 3px solid rgba(0,0,0,0.15); }}
.ev-thinking {{ border-radius: 4px; padding: .75rem 1rem; font-size: .9rem; border-left: 4px solid var(--thinking-border); background: var(--thinking-bg) !important; }}
.ev-head {{ display: flex; align-items: center; gap: .5rem; margin-bottom: .15rem; }}
.ev-icon {{ font-size: 1.1em; }}
.ev code, .ev-thinking code {{ background: rgba(0,0,0,0.08); padding: 1px 5px; border-radius: 3px; font-size: .9em; }}
.query {{ font-weight: 500; margin: .15rem 0; word-break: break-word; }}
.thinking-text {{ font-style: italic; color: #4c1d95; white-space: pre-wrap; font-weight: 500; }}
.meta {{ font-size: .8em; color: var(--muted); }}
.meta.error {{ color: #991b1b; font-weight: bold; }}
.meta code {{ background: rgba(0,0,0,0.08); padding: 0 4px; border-radius: 2px; }}

details.results {{ margin-top: .4rem; font-size: .8rem; }}
details.results summary {{ cursor: pointer; color: #1e40af; font-size: .8rem; }}
.result-item {{ background: rgba(255,255,255,0.7); padding: .3rem .5rem; margin: .25rem 0; border-radius: 3px; border-left: 2px solid #fbbf24; }}
.result-url {{ color: var(--muted); font-size: .85em; word-break: break-all; }}
.result-snippet {{ font-size: .85em; color: #4b5563; display: block; margin-top: .15rem; }}
.crop-preview {{ max-width: 100%; max-height: 250px; display: block; margin-top: .4rem; border: 1px solid var(--border); border-radius: 3px; }}
.map-preview {{ max-width: 100%; max-height: 300px; display: block; margin-top: .4rem; border-radius: 4px; }}
.img-grid {{ display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .4rem; }}
.img-grid img {{ width: 110px; height: 110px; object-fit: cover; border-radius: 3px; border: 1px solid var(--border); }}
.img-grid a {{ display: block; }}
.img-meta {{ font-size: .7em; color: var(--muted); display: block; text-align: center; }}
.sv-card {{ display: flex; flex-direction: column; align-items: center; }}
.sv-card img {{ width: 140px; height: 110px; object-fit: cover; }}

.final-col {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; position: sticky; top: 130px; max-height: calc(100vh - 150px); overflow-y: auto; }}
.final-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: .5rem 1rem; margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border); }}
.final-cell {{ display: flex; flex-direction: column; }}
.final-cell .lbl {{ font-size: .7em; text-transform: uppercase; color: var(--muted); letter-spacing: .04em; }}
.final-cell .val {{ font-weight: 500; word-break: break-word; }}
.final-section {{ margin: 1rem 0; }}
.final-section h4 {{ margin: 0 0 .5rem 0; font-size: .85rem; color: var(--accent); text-transform: uppercase; letter-spacing: .03em; }}
.final-section p {{ margin: .25rem 0; font-size: .9rem; }}
.final-section ul {{ margin: .25rem 0 .25rem 1rem; padding: 0; font-size: .9rem; }}
.final-section li {{ margin: .2rem 0; }}
.no-answer {{ background: #fee2e2; padding: 1rem; border-radius: 4px; color: #991b1b; }}

@media (max-width: 1100px) {{
  .hero-row, .detail-row {{ grid-template-columns: 1fr; }}
  .final-col {{ position: static; max-height: none; }}
}}
</style>
</head>
<body>
<header class="top">
  <h1>GeoDetective — E008 Cross-modelo (vista completa)</h1>
  <div class="selectors">
    <div class="selector-row"><strong>Modelo:</strong>{model_selector}</div>
    <div class="selector-row"><strong>Foto:</strong>{photo_selector}</div>
  </div>
</header>
<main>{panels}</main>
<script>
(function() {{
  var state = {{ model: null, cid: null }};

  function show() {{
    document.querySelectorAll('.photo-panel').forEach(p => p.classList.remove('active'));
    if (!state.model || !state.cid) return;
    var sel = '.photo-panel[data-model="' + state.model + '"][data-cid="' + state.cid + '"]';
    var panel = document.querySelector(sel);
    if (panel) {{
      panel.classList.add('active');
      setTimeout(function() {{
        var key = state.model + '_' + state.cid;
        if (window._maps && window._maps[key]) window._maps[key].invalidateSize();
      }}, 60);
    }}
    history.replaceState(null, '', '#m=' + state.model + '&c=' + state.cid);
  }}

  function setModel(m) {{
    state.model = m;
    document.querySelectorAll('button.model-btn').forEach(b => b.classList.toggle('active', b.dataset.model === m));
    show();
  }}

  function setCid(c) {{
    state.cid = c;
    document.querySelectorAll('button.photo-btn').forEach(b => b.classList.toggle('active', b.dataset.cid === c));
    show();
  }}

  document.querySelectorAll('button.model-btn').forEach(b => b.addEventListener('click', function() {{ setModel(this.dataset.model); }}));
  document.querySelectorAll('button.photo-btn').forEach(b => b.addEventListener('click', function() {{ setCid(this.dataset.cid); }}));

  // Initial: from hash or first available
  var hash = location.hash.replace('#', '');
  var initM = null, initC = null;
  hash.split('&').forEach(function(p) {{
    var kv = p.split('='); if (kv[0]==='m') initM = kv[1]; if (kv[0]==='c') initC = kv[1];
  }});
  initM = initM || document.querySelector('button.model-btn')?.dataset.model;
  initC = initC || document.querySelector('button.photo-btn')?.dataset.cid;
  if (initM) setModel(initM);
  if (initC) setCid(initC);
}})();
</script>
</body>
</html>
"""


def render_selectors(models: list[str], cids_meta: dict) -> tuple[str, str]:
    # Model selector
    model_btns = []
    for m in models:
        color, display = color_for_model(m)
        model_btns.append(
            f'<button class="model-btn" data-model="{m}" style="border-left:4px solid {color}">{display}</button>'
        )

    # Photo selector
    photo_btns = []
    for cid, meta in cids_meta.items():
        bucket = meta["bucket_pais"].split("-")[0][:6]
        photo_btns.append(
            f'<button class="photo-btn" data-cid="{cid}">#{cid} · {bucket}/{meta["bucket_decada"]}</button>'
        )

    return "".join(model_btns), "".join(photo_btns)


def main():
    files = sorted(EXP.glob("results_*.json"))
    if not files:
        raise SystemExit(f"no results_*.json in {EXP}")

    data_by_model: dict[str, list[dict]] = {}
    for p in files:
        key = p.stem.replace("results_", "")
        try:
            data_by_model[key] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  ⚠️  skip {p}: bad JSON")
            continue

    # cids in order of first encounter
    cids_in_order: list[int] = []
    cids_meta: dict[int, dict] = {}
    for data in data_by_model.values():
        for r in data:
            cid = r["cid"]
            if cid not in cids_meta:
                cids_in_order.append(cid)
                cids_meta[cid] = r

    print(f"loaded {len(data_by_model)} modelos: {list(data_by_model)}")
    print(f"cids: {cids_in_order}")

    # Render panels for each (model, cid)
    panels_html_parts = []
    for model_key, data in data_by_model.items():
        for r in data:
            panels_html_parts.append(render_panel(r, model_key))
    panels_html = "\n".join(panels_html_parts)

    model_selector, photo_selector = render_selectors(list(data_by_model), cids_meta)

    out = EXP / "report_multimodel_full.html"
    out.write_text(HTML_TEMPLATE.format(
        model_selector=model_selector,
        photo_selector=photo_selector,
        panels=panels_html,
    ), encoding="utf-8")
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"wrote {out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
