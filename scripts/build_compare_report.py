"""Genera un reporte HTML de comparación cruzada del pilot E005.

UI:
- Selector de foto (6 botones, sticky arriba).
- Tres columnas lado a lado: v1 / v2 / v3 (o las versiones que existan).
- Cada columna muestra: predicción, distancia, confianza, contadores de tools, key reasoning, errores.
- Mapa central abajo con: pin verde (truth) + pin distinto por versión.

Carga TODOS los results_*.json que encuentra en experiments/E005_react_pilot/.

Uso:
    python scripts/build_compare_report.py
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

EXP = Path("experiments/E005_react_pilot")
PHOTOS_DIR = Path("experiments/E004_attacker_filter/photos")

VERSION_COLORS = {
    "v1_mechanical": ("#dc2626", "v1"),
    "v2_descriptive": ("#9333ea", "v2"),
    "v3_thinking_visible": ("#2563eb", "v3"),
}
DEFAULT_VERSION_COLOR = ("#6b7280", "?")


def img_b64(path: Path) -> str:
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode()


def load_versions() -> dict[str, list[dict]]:
    out = {}
    for p in sorted(EXP.glob("results_*.json")):
        version = p.stem.replace("results_", "")
        try:
            data = json.loads(p.read_text())
            out[version] = data
        except json.JSONDecodeError:
            continue
    return out


def render_version_column(version: str, r: dict | None) -> str:
    color, short = VERSION_COLORS.get(version, DEFAULT_VERSION_COLOR)
    if r is None:
        return f'<div class="ver-col" style="border-top-color: {color}"><div class="ver-tag" style="background:{color}">{short}</div><p class="missing">— no hay datos —</p></div>'
    rr = r["react"]
    fa = rr.get("final_answer") or {}
    dist = rr.get("distance_km")
    dist_s = f"{dist:.1f} km" if dist is not None else "N/A"
    dist_class = "win" if dist is not None and dist < 10 else ("close" if dist is not None and dist < 100 else "off")

    tools_html = []
    for k, label in [
        ("web_search_count", "ws"),
        ("fetch_url_count", "fu"),
        ("image_search_count", "is"),
        ("crop_count", "crop"),
        ("geocode_count", "geo"),
        ("historical_query_count", "HQ"),
        ("static_map_count", "SM"),
        ("street_view_count", "SV"),
    ]:
        v = rr.get(k, 0)
        if v:
            cls = "pill-diff" if k in ("historical_query_count", "static_map_count", "street_view_count") else "pill"
            tools_html.append(f'<span class="{cls}">{label}={v}</span>')

    # Top 3 thinking lines if present
    thinking_events = [ev for ev in rr.get("trace", []) if ev.get("type") == "thinking"]
    thinking_html = ""
    if thinking_events:
        thinking_html = '<div class="ver-thinking"><strong>💭 Razonamiento (steps con thinking):</strong><ol>'
        for ev in thinking_events[:5]:
            c = (ev.get("content") or "")[:200]
            thinking_html += f'<li><span class="step-num">step {ev.get("step")}</span> {html.escape(c)}{"…" if len(ev.get("content") or "") > 200 else ""}</li>'
        thinking_html += '</ol></div>'

    reasoning = (fa.get("reasoning") or "")[:300]
    rej = fa.get("rejected_alternatives") or []
    rej_html = ""
    if rej:
        rej_html = '<details><summary>Rechazó</summary><ul>'
        for x in rej[:3]:
            rej_html += f'<li>{html.escape(str(x)[:150])}</li>'
        rej_html += '</ul></details>'

    return f"""
<div class="ver-col" style="border-top-color: {color}">
  <div class="ver-tag" style="background:{color}">{short}: {html.escape(version)}</div>
  <div class="ver-pred">
    <p class="pred-loc">{html.escape(str(fa.get('location', 'NO ANSWER'))[:120])}</p>
    <p class="pred-coords">({fa.get('lat')}, {fa.get('lon')})</p>
  </div>
  <div class="ver-stats">
    <div><span class="lbl">Dist</span><span class="val dist {dist_class}">{dist_s}</span></div>
    <div><span class="lbl">Conf</span><span class="val">{fa.get('confidence', '—')}</span></div>
    <div><span class="lbl">Steps</span><span class="val">{rr.get('steps_used')}/{rr.get('max_steps')}</span></div>
    <div><span class="lbl">Submit</span><span class="val">{'✓' if rr.get('submit_called') else '✗'}</span></div>
  </div>
  <div class="ver-tools">{' '.join(tools_html)}</div>
  {thinking_html}
  <div class="ver-reasoning"><strong>Reasoning:</strong> {html.escape(reasoning)}{"…" if len(fa.get("reasoning") or "") > 300 else ""}</div>
  {rej_html}
</div>
"""


def render_compare_panel(cid: int, versions: dict[str, list[dict]]) -> str:
    by_v: dict[str, dict] = {}
    representative = None
    for v, data in versions.items():
        for r in data:
            if r["cid"] == cid:
                by_v[v] = r
                if representative is None:
                    representative = r
                break

    if representative is None:
        return ""

    rep = representative
    truth = rep["geo"]
    img_path = PHOTOS_DIR / f"{cid}_clean_v1.jpg"
    img_data = img_b64(img_path)
    map_id = f"cmap_{cid}"

    # Map markers JS: truth (green) + each version's pred (per-version color)
    markers_js_parts = [
        f"var pts = [[{truth[0]}, {truth[1]}]];",
        f"L.marker([{truth[0]}, {truth[1]}], {{icon: greenIcon}}).addTo(map).bindPopup('TRUTH');",
    ]
    for v, r in by_v.items():
        rr = r["react"]
        fa = rr.get("final_answer") or {}
        if fa and fa.get("lat") is not None and fa.get("lon") is not None:
            color, short = VERSION_COLORS.get(v, DEFAULT_VERSION_COLOR)
            markers_js_parts.append(
                f"var ic_{short} = L.divIcon({{html: '<div style=\"background:{color};width:18px;height:18px;border-radius:50%;border:2px solid white;box-shadow:0 0 4px rgba(0,0,0,0.4);text-align:center;color:white;font-size:11px;font-weight:bold;line-height:14px\">{short}</div>', className: 'div-icon', iconSize: [22,22], iconAnchor: [11,11]}});"
            )
            markers_js_parts.append(
                f"L.marker([{fa['lat']}, {fa['lon']}], {{icon: ic_{short}}}).addTo(map).bindPopup('{short}: {html.escape(str(fa.get('location', ''))[:60])}');"
            )
            markers_js_parts.append(f"L.polyline([[{truth[0]}, {truth[1]}], [{fa['lat']}, {fa['lon']}]], {{color: '{color}', dashArray: '4, 4', opacity: 0.6}}).addTo(map);")
            markers_js_parts.append(f"pts.push([{fa['lat']}, {fa['lon']}]);")
    markers_js_parts.append("if (pts.length === 1) {{ map.setView(pts[0], 5); }} else {{ map.fitBounds(L.latLngBounds(pts).pad(0.3)); }}".replace("{{", "{").replace("}}", "}"))
    markers_js = "\n".join(markers_js_parts)

    cols_html = "".join(render_version_column(v, by_v.get(v)) for v in VERSION_COLORS)

    return f"""
<section class="compare-panel" id="cpanel-{cid}">
  <header class="cpanel-header">
    <h2>#{cid} · <span class="muted">{rep['country']} {rep['year']} · {rep['bucket_pais']}/{rep['bucket_decada']}</span></h2>
    <p class="photo-title">«{html.escape(rep['title'])}» @ ({truth[0]:.4f}, {truth[1]:.4f})</p>
  </header>

  <div class="compare-hero">
    <div class="hero-photo-compare">
      <img src="data:image/jpeg;base64,{img_data}" alt="target" />
    </div>
    <div id="{map_id}" class="hero-map-compare"></div>
  </div>

  <div class="compare-cols">{cols_html}</div>

  <script>
  (function() {{
    var map = L.map('{map_id}');
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
      {{attribution: '© OSM', maxZoom: 18}}).addTo(map);
    var greenIcon = L.icon({{iconUrl: 'https://cdn.jsdelivr.net/gh/pointhi/leaflet-color-markers@master/img/marker-icon-2x-green.png', iconSize: [25, 41], iconAnchor: [12, 41]}});
    {markers_js}
    if (!window._cmaps) window._cmaps = {{}};
    window._cmaps['{cid}'] = map;
  }})();
  </script>
</section>
"""


def render_selector(cids: list[int], by_cid_meta: dict[int, dict]) -> str:
    out = []
    for cid in cids:
        meta = by_cid_meta[cid]
        bucket = meta["bucket_pais"].split("-")[0][:6]
        out.append(
            f'<button data-cid="{cid}">#{cid} · {bucket}/{meta["bucket_decada"]}</button>'
        )
    return "".join(out)


HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>GeoDetective — Pilot E005 — Comparación</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {{ --bg: #f9fafb; --card: #ffffff; --border: #e5e7eb; --text: #1f2937; --muted: #6b7280; --accent: #1e3a8a; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; background: var(--bg); color: var(--text); line-height: 1.45; }}
.top {{ position: sticky; top: 0; background: white; border-bottom: 2px solid var(--border); padding: .75rem 1.5rem; z-index: 200; box-shadow: 0 2px 4px rgba(0,0,0,0.04); }}
.top h1 {{ margin: 0 0 .5rem 0; font-size: 1.1rem; color: var(--accent); }}
.top .versions-info {{ margin: 0 0 .5rem 0; font-size: .85rem; color: var(--muted); }}
.top .versions-info .vchip {{ display: inline-block; padding: 1px 8px; border-radius: 10px; color: white; margin-right: 6px; font-weight: bold; font-size: .8em; }}
.selector {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.selector button {{ border: 1px solid var(--border); background: var(--card); padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: .85rem; font-family: inherit; transition: all 0.15s; }}
.selector button:hover {{ background: #eff6ff; border-color: #3b82f6; }}
.selector button.active {{ background: var(--accent); color: white; border-color: var(--accent); }}

main {{ max-width: 1500px; margin: 1rem auto; padding: 0 1.5rem; }}

.compare-panel {{ display: none; }}
.compare-panel.active {{ display: block; }}

.cpanel-header h2 {{ margin: .25rem 0; color: var(--accent); }}
.cpanel-header .muted {{ color: var(--muted); font-weight: normal; font-size: .9em; }}
.photo-title {{ font-style: italic; color: #4b5563; margin: .25rem 0 1rem; }}

.compare-hero {{ display: grid; grid-template-columns: 1fr 1.2fr; gap: 1.5rem; margin-bottom: 1.5rem; }}
.hero-photo-compare img {{ width: 100%; height: auto; max-height: 380px; object-fit: contain; background: black; border-radius: 6px; }}
.hero-map-compare {{ height: 380px; border-radius: 6px; border: 1px solid var(--border); }}

.compare-cols {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }}
.ver-col {{ background: var(--card); border: 1px solid var(--border); border-top-width: 4px; border-radius: 6px; padding: .75rem 1rem; font-size: .85rem; min-height: 200px; }}
.ver-tag {{ display: inline-block; color: white; padding: 2px 8px; border-radius: 4px; font-size: .7rem; margin-bottom: .5rem; font-weight: bold; }}
.ver-pred .pred-loc {{ margin: .25rem 0; font-weight: 500; }}
.ver-pred .pred-coords {{ margin: .15rem 0 .5rem 0; font-size: .82em; color: var(--muted); font-family: ui-monospace, monospace; }}
.ver-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: .35rem .75rem; margin: .5rem 0 .75rem 0; padding: .5rem; background: #f9fafb; border-radius: 4px; }}
.ver-stats > div {{ display: flex; flex-direction: column; }}
.ver-stats .lbl {{ font-size: .7em; text-transform: uppercase; color: var(--muted); letter-spacing: .03em; }}
.ver-stats .val {{ font-weight: 500; font-size: .9em; }}
.dist.win {{ color: #059669; font-weight: bold; }}
.dist.close {{ color: #d97706; font-weight: bold; }}
.dist.off {{ color: #dc2626; font-weight: bold; }}
.ver-tools {{ display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: .5rem; }}
.ver-tools .pill {{ background: #e5e7eb; color: #374151; padding: 2px 6px; border-radius: 3px; font-size: .75em; }}
.ver-tools .pill-diff {{ background: #fef3c7; color: #78350f; font-weight: bold; padding: 2px 6px; border-radius: 3px; font-size: .75em; }}
.ver-thinking {{ background: #f5f3ff; border-left: 3px solid #8b5cf6; padding: .35rem .5rem; margin: .5rem 0; font-size: .8rem; }}
.ver-thinking .step-num {{ background: #ddd6fe; color: #5b21b6; padding: 1px 5px; border-radius: 3px; font-size: .85em; }}
.ver-thinking ol {{ margin: .25rem 0 .25rem 1rem; padding: 0; }}
.ver-thinking li {{ margin: .25rem 0; }}
.ver-reasoning {{ font-size: .82rem; line-height: 1.4; margin: .5rem 0; color: #374151; }}
details {{ font-size: .82rem; margin: .35rem 0; }}
details summary {{ cursor: pointer; color: #1e40af; }}
details ul {{ margin: .25rem 0 .25rem 1rem; padding: 0; }}
.missing {{ color: var(--muted); font-style: italic; }}

@media (max-width: 1200px) {{
  .compare-hero {{ grid-template-columns: 1fr; }}
  .compare-cols {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header class="top">
  <h1>GeoDetective — Comparación cruzada de versiones del prompt</h1>
  <p class="versions-info">Versiones disponibles: {versions_chips}</p>
  <div class="selector">{selector}</div>
</header>
<main>{panels}</main>
<script>
(function() {{
  function show(cid) {{
    document.querySelectorAll('.compare-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.selector button').forEach(b => b.classList.remove('active'));
    var p = document.getElementById('cpanel-' + cid);
    if (p) p.classList.add('active');
    var b = document.querySelector('.selector button[data-cid="' + cid + '"]');
    if (b) b.classList.add('active');
    setTimeout(function() {{ if (window._cmaps && window._cmaps[cid]) window._cmaps[cid].invalidateSize(); }}, 60);
    history.replaceState(null, '', '#' + cid);
  }}
  document.querySelectorAll('.selector button').forEach(b => {{
    b.addEventListener('click', function() {{ show(this.dataset.cid); }});
  }});
  var initial = location.hash.replace('#', '') || document.querySelector('.selector button')?.dataset.cid;
  if (initial) show(initial);
}})();
</script>
</body>
</html>
"""


def main():
    versions = load_versions()
    if not versions:
        raise SystemExit(f"no results_*.json in {EXP}")

    # CIDs (union across versions, ordered by first encounter)
    cids_in_order: list[int] = []
    by_cid_meta: dict[int, dict] = {}
    for v, data in versions.items():
        for r in data:
            cid = r["cid"]
            if cid not in by_cid_meta:
                cids_in_order.append(cid)
                by_cid_meta[cid] = r

    print(f"loaded {len(versions)} versions: {list(versions)}")
    print(f"cids in common (or union): {cids_in_order}")

    panels_html = "\n".join(render_compare_panel(cid, versions) for cid in cids_in_order)
    selector_html = render_selector(cids_in_order, by_cid_meta)
    versions_chips = " ".join(
        f'<span class="vchip" style="background:{VERSION_COLORS.get(v, DEFAULT_VERSION_COLOR)[0]}">{VERSION_COLORS.get(v, DEFAULT_VERSION_COLOR)[1]}</span> {v}'
        for v in versions
    )

    out = EXP / "report_compare.html"
    out.write_text(HTML.format(
        panels=panels_html,
        selector=selector_html,
        versions_chips=versions_chips,
    ))
    size_kb = out.stat().st_size / 1024
    print(f"✓ wrote {out} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
