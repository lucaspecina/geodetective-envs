"""Viewer HTML de trayectorias belief-mode: timeline completo + mapa sincronizado (E016, #47).

Para cada foto de un results JSON con belief_reports genera:
- TIMELINE completo step-a-step: thinking del modelo, cada tool call con args,
  la observación que recibió (payload expandible), imágenes que vio (crops,
  static maps, street view, imágenes de páginas), reports de creencia, nudges,
  bloqueos de budget y el submit.
- SIDEBAR sticky sincronizado por step: mapa (Leaflet/OSM) con la creencia
  VIGENTE en ese step (la del último report <= step), curva de información
  ganada, belief de año (línea roja = truth year), rationale.
- Navegación: slider por step, click en cualquier card del timeline, ▶ play.

Si el JSON no trae scores, los recomputa con eval.belief_scoring.

Uso:
    python scripts/build_belief_viewer.py experiments/E016_belief_pilot/smoke_gpt-5_4-mini.json
    # Output: mismo dir, belief_viewer_{stem}.html
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geodetective.corpus import CLEAN_VERSION
from geodetective.eval.belief_scoring import Belief, score_belief

PHOTOS_DIR = Path("corpus/photos")


def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def img_tag(b64: str, label: str = "") -> str:
    if not b64:
        return ""
    lab = f'<div class="img-label">{esc(label)}</div>' if label else ""
    return f'<div class="img-block">{lab}<img loading="lazy" src="data:image/jpeg;base64,{b64}"/></div>'


def details(summary: str, body: str) -> str:
    return f"<details><summary>{summary}</summary><pre>{esc(body)}</pre></details>"


def render_event(ev: dict) -> str:
    """Render un evento del trace como bloque del timeline."""
    t = ev.get("type", "?")

    if t in ("thinking", "thinking_block"):
        return f'<div class="ev thinking"><pre>{esc(ev.get("content", ""))}</pre></div>'

    if t == "report_belief":
        b = ev.get("belief", {})
        rows = "".join(
            f"<tr><td>{esc(c.get('name'))}</td><td>{c.get('weight')}</td>"
            f"<td>{c.get('radius_km')} km</td><td>({c.get('lat')}, {c.get('lon')})</td></tr>"
            for c in b.get("location_belief", [])
        )
        yrows = " · ".join(f"[{y.get('from')}-{y.get('to')}] w={y.get('weight')}"
                           for y in b.get("year_belief", []))
        return (
            '<div class="ev belief"><div class="ev-title">🧠 report_belief</div>'
            f'<table><tr><th>candidato</th><th>w</th><th>radio</th><th>coords</th></tr>{rows}</table>'
            f'<div class="muted">year: {esc(yrows) or "—"}</div>'
            f'<div class="rationale">{esc(b.get("rationale", ""))}</div></div>'
        )

    if t == "report_belief_rejected":
        return f'<div class="ev error"><div class="ev-title">🧠 report_belief RECHAZADO</div><div>{esc(ev.get("error"))}</div></div>'

    if t == "belief_nudge":
        return f'<div class="ev note">⏰ nudge: {ev.get("steps_since_belief")} steps sin report_belief</div>'

    if t == "tool_blocked_budget":
        return f'<div class="ev error">🚫 <b>{esc(ev.get("tool"))}</b> bloqueada por budget (cuesta {ev.get("cost")}, quedan {ev.get("remaining")})</div>'

    if t in ("submit", "submit_rejected", "submit_blocked_min_steps"):
        ans = ev.get("answer", {}) or {}
        title = {"submit": "✅ submit_answer", "submit_rejected": "❌ submit RECHAZADO",
                 "submit_blocked_min_steps": "🚫 submit bloqueado (min_steps)"}[t]
        err = f'<div class="muted">{esc(ev.get("error"))}</div>' if ev.get("error") else ""
        return (f'<div class="ev submit"><div class="ev-title">{title}</div>{err}'
                f'<pre>{esc(json.dumps(ans, ensure_ascii=False, indent=2))}</pre></div>')

    if t == "web_search":
        tops = "".join(
            f'<li><a href="{esc(r.get("url"))}" target="_blank">{esc(r.get("title"))}</a>'
            f'<div class="snippet">{esc((r.get("snippet") or "")[:280])}</div></li>'
            for r in (ev.get("top_results") or [])
        )
        body = details("payload completo (lo que el modelo vio)", ev.get("payload_to_model", "")) if ev.get("payload_to_model") else ""
        return (f'<div class="ev tool"><div class="ev-title">🔎 web_search(<code>{esc(ev.get("query"))}</code>)'
                f' <span class="muted">{ev.get("result_count")} results, {ev.get("blocked")} bloqueados</span></div>'
                f'<ul class="results">{tops}</ul>{body}</div>')

    if t in ("image_search", "image_search_pick"):
        if t == "image_search":
            head = (f'🖼️ image_search(<code>{esc(ev.get("query"))}</code>) '
                    f'<span class="muted">página {ev.get("page")}/{ev.get("n_pages_total")}, '
                    f'{ev.get("n_cells")} celdas, target_match={ev.get("target_match_count")}</span>')
            cells = ev.get("cells_metadata") or []
            body = "".join(
                f'<div class="cellmeta">#{c.get("cell")} {esc((c.get("alt_text") or "")[:90])} '
                f'<span class="muted">{esc((c.get("url") or "")[:70])}</span></div>' for c in cells[:16])
        else:
            head = f'🖼️ image_search pick {[p.get("cell") for p in ev.get("picks", [])]}'
            body = "".join(
                f'<div class="cellmeta">#{p.get("cell")} {esc((p.get("alt_text") or "")[:90])}</div>'
                for p in ev.get("picks", []))
        return f'<div class="ev tool"><div class="ev-title">{head}</div>{body}</div>'

    if t in ("geocode", "reverse_geocode"):
        tops = "".join(f'<li>({r.get("lat")}, {r.get("lon")}) — {esc(r.get("display_name"))}</li>'
                       for r in (ev.get("top_results") or []))
        return (f'<div class="ev tool"><div class="ev-title">📍 {t}(<code>{esc(json.dumps(ev.get("args", {}), ensure_ascii=False))}</code>)'
                f' <span class="muted">{ev.get("n_results")} results</span></div><ul class="results">{tops}</ul></div>')

    if t in ("historical_query", "historical_query_at"):
        body = details("payload OHM", ev.get("payload_to_model", "")) if ev.get("payload_to_model") else ""
        return (f'<div class="ev tool"><div class="ev-title">🏛️ {t}(<code>{esc(json.dumps(ev.get("args", {}), ensure_ascii=False))}</code>)'
                f' <span class="muted">{ev.get("n_features")} features</span></div>{body}</div>')

    if t in ("crop_image", "crop_image_relative"):
        return (f'<div class="ev tool"><div class="ev-title">✂️ {t} <span class="muted">region={esc(json.dumps(ev.get("region")))}</span></div>'
                f'{img_tag(ev.get("base64_jpeg", ""), "crop que vio el modelo")}</div>')

    if t == "static_map":
        pois = ", ".join(f'{esc(p.get("name"))} ({p.get("distance_m", 0):.0f}m)'
                         for p in (ev.get("nearby_pois") or [])[:4])
        elev = ev.get("elevation") or {}
        meta = f'POIs: {pois or "—"} · elev {elev.get("elevation_m", "?")}m {esc(elev.get("terrain_category", ""))}'
        return (f'<div class="ev tool"><div class="ev-title">🗺️ static_map(<code>{esc(json.dumps(ev.get("args", {}), ensure_ascii=False))}</code>)</div>'
                f'<div class="muted">{meta}</div>{img_tag(ev.get("base64_jpeg", ""), "mapa que vio el modelo")}</div>')

    if t == "street_view":
        imgs = "".join(img_tag(im.get("base64_jpeg", ""), f'heading {im.get("heading")}')
                       for im in (ev.get("images") or []))
        return (f'<div class="ev tool"><div class="ev-title">👁️ street_view(<code>{esc(json.dumps(ev.get("args", {}), ensure_ascii=False))}</code>)'
                f' <span class="muted">pano {esc(ev.get("pano_date"))} a {ev.get("distance_to_pano_m") or "?"}m</span></div>'
                f'<div class="imgrow">{imgs}</div></div>')

    if t in ("fetch_url", "fetch_url_with_images"):
        imgs = "".join(img_tag(im.get("base64_jpeg", ""), (im.get("url") or "")[:70])
                       for im in (ev.get("visible_images") or []) if im.get("base64_jpeg"))
        body = details("payload", ev.get("payload_to_model", "")) if ev.get("payload_to_model") else ""
        return (f'<div class="ev tool"><div class="ev-title">📄 {t}(<code>{esc((ev.get("url") or "")[:90])}</code>)'
                f' <span class="muted">{esc(ev.get("title") or "")}</span></div>'
                f'<div class="snippet">{esc((ev.get("text_snippet") or "")[:300])}</div>'
                f'<div class="imgrow">{imgs}</div>{body}</div>')

    if t == "image_context_cleanup":
        return f'<div class="ev note">🧹 cleanup de contexto: {ev.get("images_removed")} imágenes viejas eliminadas</div>'

    if t.endswith("_error"):
        return f'<div class="ev error">⚠️ {esc(t)}: {esc(ev.get("error"))}</div>'

    if t == "no_tool_call_in_response":
        return f'<div class="ev note">💬 texto sin tool call (attempt {ev.get("attempt")})</div>'

    return f'<div class="ev note">{esc(t)}: {details("raw", json.dumps(ev, ensure_ascii=False, indent=2)[:3000])}</div>'


def build_photo_card(record: dict, idx: int) -> tuple[str, dict] | None:
    rk = record.get("react") or {}
    reports = rk.get("belief_reports") or []
    trace = rk.get("trace") or []
    if not reports and not trace:
        return None
    truth = record.get("geo")
    truth_year = record.get("year")
    final = rk.get("final_answer") or {}
    steps_used = rk.get("steps_used") or max((ev.get("step", 1) for ev in trace), default=1)

    # Datos de beliefs para el mapa (scores recomputados — fuente única: el scorer)
    prior_score = None
    js_beliefs = []
    for rep in reports:
        b = Belief.from_dict(rep["belief"])
        score = None
        if truth:
            ty = float(truth_year) if truth_year else None
            score = score_belief(b, truth[0], truth[1], truth_year=ty).total
            if prior_score is None:
                prior_score = score_belief(Belief(), truth[0], truth[1], truth_year=ty).total
        js_beliefs.append({
            "step": rep["step"],
            "candidates": [{"name": c.name, "lat": c.lat, "lon": c.lon, "w": c.weight, "r": c.radius_km}
                           for c in b.location],
            "years": [{"f": y.year_from, "t": y.year_to, "w": y.weight} for y in b.year],
            "rationale": b.rationale,
            "score": score,
        })

    # Timeline: agrupar eventos por step
    by_step: dict[int, list[dict]] = {}
    for ev in trace:
        by_step.setdefault(int(ev.get("step", 0)), []).append(ev)
    timeline = []
    for s in range(1, steps_used + 1):
        evs = "".join(render_event(ev) for ev in by_step.get(s, []))
        has_belief = any(ev.get("type") == "report_belief" for ev in by_step.get(s, []))
        badge = ' <span class="badge">belief</span>' if has_belief else ""
        timeline.append(
            f'<div class="stepcard" id="p{idx}-step-{s}" data-step="{s}">'
            f'<div class="stephead">step {s}{badge}</div>{evs or "<span class=muted>(sin eventos)</span>"}</div>'
        )

    photo_b64 = None
    img_path = PHOTOS_DIR / f"{record.get('cid')}_clean_v{CLEAN_VERSION}.jpg"
    if img_path.exists():
        photo_b64 = base64.b64encode(img_path.read_bytes()).decode()

    dist = rk.get("distance_km")
    chain = "".join(
        f'<li>[step {c.get("step")}, {esc(c.get("tool"))}] {esc(c.get("claim"))}</li>'
        for c in (final.get("evidence_chain") or [])
    ) or '<span class="muted">no reportada</span>'
    budget_s = (f'<span class="stat">budget {rk.get("budget_spent")}/{rk.get("budget_total")}</span>'
                if rk.get("budget_total") is not None else "")

    card_html = f"""
<div class="card" id="card-{idx}">
  <h2>cid={esc(record.get("cid"))} — {esc(record.get("title", ""))}</h2>
  <div>
    <span class="stat">{esc(rk.get("model", "?"))}</span>
    <span class="stat">dist final: <b>{f"{dist:.1f} km" if dist is not None else "NA"}</b></span>
    <span class="stat">year: {esc(final.get("year", "—"))} (truth {esc(truth_year)})</span>
    <span class="stat">{steps_used} steps · {len(reports)} beliefs</span>{budget_s}
  </div>
  <div class="layout">
    <div class="timeline" id="timeline-{idx}">
      <div class="photo">{img_tag(photo_b64 or "", "FOTO TARGET")}</div>
      <div class="chain"><b>Evidence chain del submit</b><ol>{chain}</ol></div>
      {"".join(timeline)}
    </div>
    <div class="sidebar">
      <div id="map-{idx}" class="map"></div>
      <div class="controls">
        <button id="play-{idx}">▶</button>
        <input type="range" id="slider-{idx}" min="1" max="{steps_used}" value="1" step="1"/>
        <span id="steplabel-{idx}" class="stat"></span>
      </div>
      <div id="beliefinfo-{idx}" class="muted" style="font-size:12px"></div>
      <b>Info ganada (nats vs ignorancia)</b>
      <div id="curve-{idx}"></div>
      <b>Belief de año</b> <span class="muted">(rojo = truth)</span>
      <div id="years-{idx}"></div>
      <div class="rationale" id="rationale-{idx}"></div>
    </div>
  </div>
</div>"""

    js_data = {
        "idx": idx,
        "cid": record.get("cid"),
        "title": record.get("title", ""),
        "model": rk.get("model", "?"),
        "distanceKm": round(dist, 1) if dist is not None else None,
        "stepsUsed": steps_used,
        "truth": truth,
        "truthYear": truth_year,
        "final": {"lat": final.get("lat"), "lon": final.get("lon"), "location": final.get("location")} if final else None,
        "priorScore": prior_score,
        "beliefs": js_beliefs,
    }
    return card_html, js_data


CSS_JS_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>Belief Trajectory Viewer</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; background: #111; color: #ddd; margin: 0; padding: 16px; }
  h1 { font-size: 18px; } h2 { font-size: 15px; margin: 4px 0; }
  a { color: #7aa7e8; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 10px; padding: 14px; margin-bottom: 28px; display: none; }
  .card.visible { display: block; }
  #selector { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .tab { background: #232323; border: 1px solid #444; border-radius: 7px; padding: 6px 12px; cursor: pointer; font-size: 12.5px; color: #ccc; }
  .tab.active { background: #2e2415; border-color: #e8842c; color: #fff; }
  .tab .muted { font-size: 11px; }
  .layout { display: grid; grid-template-columns: minmax(0,1fr) 420px; gap: 14px; margin-top: 10px; align-items: start; }
  .sidebar { position: sticky; top: 10px; }
  .map { height: 380px; border-radius: 8px; }
  .controls { margin: 8px 0; display: flex; gap: 8px; align-items: center; }
  .controls input[type=range] { flex: 1; }
  button { background: #333; color: #ddd; border: 1px solid #555; border-radius: 5px; padding: 4px 10px; cursor: pointer; }
  .stat { display: inline-block; background: #252525; border-radius: 5px; padding: 2px 8px; margin: 2px; font-size: 12px; }
  .badge { background: #5b8def; color: #fff; border-radius: 4px; font-size: 10px; padding: 1px 6px; }
  .stepcard { border: 1px solid #2e2e2e; border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; cursor: pointer; }
  .stepcard.active { border-color: #e8842c; background: #201a14; }
  .stephead { font-weight: 600; color: #e8842c; margin-bottom: 6px; }
  .ev { margin: 6px 0; padding: 6px 8px; border-radius: 6px; background: #202020; font-size: 12.5px; overflow-wrap: anywhere; }
  .ev.thinking { background: #1c2230; border-left: 3px solid #5b8def; }
  .ev.belief { background: #16231c; border-left: 3px solid #19c37d; }
  .ev.submit { background: #261a26; border-left: 3px solid #c36ac3; }
  .ev.error { background: #2a1717; border-left: 3px solid #e84c4c; }
  .ev.note { background: #1d1d1d; color: #999; }
  .ev pre { white-space: pre-wrap; margin: 4px 0; font-size: 12px; }
  .ev-title { font-weight: 600; margin-bottom: 3px; }
  .ev table { border-collapse: collapse; font-size: 12px; margin: 4px 0; }
  .ev th, .ev td { border: 1px solid #333; padding: 2px 7px; text-align: left; }
  .results { margin: 4px 0 2px 16px; padding: 0; font-size: 12px; }
  .snippet { color: #999; font-size: 11.5px; margin: 2px 0; }
  .cellmeta { font-size: 11.5px; color: #aaa; }
  .img-block { display: inline-block; margin: 4px 6px 4px 0; vertical-align: top; }
  .img-block img { max-height: 200px; max-width: 100%; border-radius: 5px; display: block; }
  .photo .img-block img { max-height: 320px; }
  .img-label { font-size: 10.5px; color: #888; margin-bottom: 2px; }
  .imgrow { display: flex; flex-wrap: wrap; }
  .rationale { background: #20242c; border-left: 3px solid #5b8def; padding: 6px 8px; border-radius: 4px; min-height: 34px; margin-top: 8px; font-size: 12.5px; }
  .chain { background: #1f2a1f; border-left: 3px solid #6fbf6f; padding: 6px 8px; border-radius: 6px; font-size: 12px; margin-bottom: 12px; }
  details summary { cursor: pointer; color: #888; font-size: 11.5px; }
  details pre { max-height: 320px; overflow: auto; background: #161616; padding: 6px; border-radius: 4px; }
  svg text { fill: #aaa; font-size: 10px; }
  .muted { color: #888; }
</style>
</head>
<body>
<h1>🌍 Belief Trajectory Viewer <span class="muted">— timeline completo + mapa de creencias por step (E016)</span></h1>
<div id="selector"></div>
__CARDS__
<script>
const DATA = __DATA__;
const initialized = {};
const mapRefs = {};

function initCard(d) {
  const idx = d.idx;
  const map = L.map('map-' + idx, { worldCopyJump: true });
  mapRefs[idx] = map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OSM', opacity: 0.75 }).addTo(map);
  const pts = [];
  d.beliefs.forEach(r => r.candidates.forEach(c => pts.push([c.lat, c.lon])));
  if (d.truth) pts.push(d.truth);
  map.fitBounds(pts.length ? L.latLngBounds(pts).pad(0.3) : [[-60, -120], [70, 120]]);
  if (d.truth) L.circleMarker(d.truth, { radius: 7, color: '#19c37d', fillColor: '#19c37d', fillOpacity: 0.95 }).addTo(map).bindTooltip('GROUND TRUTH');
  if (d.final && d.final.lat != null) L.circleMarker([d.final.lat, d.final.lon], { radius: 6, color: '#5b8def', fillColor: '#5b8def', fillOpacity: 0.9 }).addTo(map).bindTooltip('submit: ' + (d.final.location || ''));
  const layer = L.layerGroup().addTo(map);

  const beliefAt = s => { let cur = null; for (const b of d.beliefs) if (b.step <= s) cur = b; return cur; };
  const gain = b => (d.priorScore == null || b.score == null) ? null : d.priorScore - b.score;

  function drawYears(b) {
    const el = document.getElementById('years-' + idx);
    if (!b) { el.innerHTML = '<span class="muted">sin belief todavía</span>'; return; }
    const yMin = 1840, yMax = 2010, W = 380, H = 70;
    const x = y => (y - yMin) / (yMax - yMin) * W;
    const bars = (b.years || []).map(yr => {
      const h = Math.max(4, yr.w * (H - 18));
      return `<rect x="${x(yr.f)}" y="${H - 14 - h}" width="${Math.max(2, x(yr.t) - x(yr.f))}" height="${h}" fill="#e8842c" opacity="0.65"/>`;
    }).join('');
    const ticks = [1850, 1900, 1950, 2000].map(y => `<line x1="${x(y)}" y1="0" x2="${x(y)}" y2="${H - 14}" stroke="#333"/><text x="${x(y) - 12}" y="${H - 2}">${y}</text>`).join('');
    const tl = d.truthYear ? `<line x1="${x(d.truthYear)}" y1="0" x2="${x(d.truthYear)}" y2="${H - 14}" stroke="#e84c4c" stroke-width="2"/>` : '';
    el.innerHTML = `<svg width="${W}" height="${H}">${ticks}${bars}${tl}</svg>`;
  }

  function drawCurve(activeStep) {
    const el = document.getElementById('curve-' + idx);
    const gains = d.beliefs.map(gain);
    if (!d.beliefs.length || gains.some(g => g == null)) { el.innerHTML = '<span class="muted">—</span>'; return; }
    const W = 380, H = 110, pad = 20;
    const all = [0, ...gains];
    const gMin = Math.min(...all, 0), gMax = Math.max(...all, 1);
    const x = s => pad + (s / d.stepsUsed) * (W - 2 * pad);
    const y = g => H - pad - (g - gMin) / (gMax - gMin) * (H - 2 * pad);
    let svg = `<line x1="${pad}" y1="${y(0)}" x2="${W - pad}" y2="${y(0)}" stroke="#444" stroke-dasharray="3"/>`;
    let prev = [x(0), y(0)];
    svg += `<circle cx="${prev[0]}" cy="${prev[1]}" r="3" fill="#888"/>`;
    d.beliefs.forEach((b, i) => {
      const cx = x(b.step), cy = y(gains[i]);
      svg += `<line x1="${prev[0]}" y1="${prev[1]}" x2="${cx}" y2="${cy}" stroke="#e8842c" stroke-width="2"/>`;
      const active = beliefAt(activeStep) === b;
      svg += `<circle cx="${cx}" cy="${cy}" r="${active ? 6 : 3.5}" fill="${active ? '#fff' : '#e8842c'}"/>`;
      svg += `<text x="${cx - 10}" y="${cy - 8}">s${b.step}: ${gains[i].toFixed(1)}</text>`;
      prev = [cx, cy];
    });
    el.innerHTML = `<svg width="${W}" height="${H}">${svg}</svg>`;
  }

  function show(s, scroll) {
    const b = beliefAt(s);
    layer.clearLayers();
    if (b) b.candidates.forEach(c => {
      L.circle([c.lat, c.lon], { radius: c.r * 1000, color: '#ff5722', weight: 1, fillColor: '#ff5722', fillOpacity: Math.min(0.75, 0.12 + c.w * 0.6) }).addTo(layer).bindTooltip(`${c.name} — w=${c.w}, r=${c.r}km`);
      L.circle([c.lat, c.lon], { radius: c.r * 2000, color: '#ff5722', weight: 0.5, fillColor: '#ff5722', fillOpacity: Math.min(0.3, c.w * 0.2), opacity: 0.4 }).addTo(layer);
    });
    document.getElementById('steplabel-' + idx).textContent = `step ${s}/${d.stepsUsed}`;
    const info = document.getElementById('beliefinfo-' + idx);
    if (b) {
      const un = Math.max(0, 1 - b.candidates.reduce((a, c) => a + c.w, 0));
      const g = gain(b);
      info.innerHTML = `belief vigente: del step ${b.step} · masa "no sé": ${un.toFixed(2)}` + (g != null ? ` · S=${b.score.toFixed(2)} · <b>+${g.toFixed(2)} nats</b>` : '');
      document.getElementById('rationale-' + idx).textContent = b.rationale || '';
    } else {
      info.textContent = 'sin belief reportada todavía (prior de ignorancia)';
      document.getElementById('rationale-' + idx).textContent = '';
    }
    drawCurve(s); drawYears(b);
    document.querySelectorAll(`#timeline-${idx} .stepcard`).forEach(el => {
      const active = +el.dataset.step === s;
      el.classList.toggle('active', active);
      if (active && scroll) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }

  const slider = document.getElementById('slider-' + idx);
  slider.addEventListener('input', () => show(+slider.value, true));
  document.querySelectorAll(`#timeline-${idx} .stepcard`).forEach(el => {
    el.addEventListener('click', () => { slider.value = el.dataset.step; show(+el.dataset.step, false); });
  });
  let timer = null;
  document.getElementById('play-' + idx).addEventListener('click', e => {
    if (timer) { clearInterval(timer); timer = null; e.target.textContent = '▶'; return; }
    e.target.textContent = '⏸';
    timer = setInterval(() => {
      const next = (+slider.value % d.stepsUsed) + 1;
      slider.value = next; show(next, true);
      if (next === d.stepsUsed) { clearInterval(timer); timer = null; document.getElementById('play-' + idx).textContent = '▶'; }
    }, 1600);
  });
  show(1, false);
}

function select(i) {
  DATA.forEach(d => {
    document.getElementById('card-' + d.idx).classList.toggle('visible', d.idx === i);
  });
  document.querySelectorAll('#selector .tab').forEach((el, j) => el.classList.toggle('active', j === i));
  if (!initialized[i]) { initCard(DATA[i]); initialized[i] = true; }
  else if (mapRefs[i]) { setTimeout(() => mapRefs[i].invalidateSize(), 50); }
}

// Selector de trayectorias
const sel = document.getElementById('selector');
DATA.forEach((d, i) => {
  const tab = document.createElement('div');
  tab.className = 'tab';
  const dist = d.distanceKm != null ? d.distanceKm + ' km' : 'NA';
  tab.innerHTML = `<b>${d.cid}</b> — ${(d.title || '').slice(0, 45)}<br/><span class="muted">${d.model} · ${dist} · ${d.stepsUsed} steps</span>`;
  tab.addEventListener('click', () => select(i));
  sel.appendChild(tab);
});
select(0);
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_json", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    records = json.loads(args.results_json.read_text(encoding="utf-8"))
    if isinstance(records, dict):
        records = records.get("records") or records.get("results") or []

    cards, js_data = [], []
    for r in records:
        built = build_photo_card(r, len(cards))
        if built:
            cards.append(built[0])
            js_data.append(built[1])
    if not cards:
        raise SystemExit("ningún record tiene trace/belief_reports — ¿corriste con belief_mode=True?")

    out = args.out or args.results_json.parent / f"belief_viewer_{args.results_json.stem}.html"
    page = CSS_JS_PAGE.replace("__CARDS__", "\n".join(cards)).replace(
        "__DATA__", json.dumps(js_data, ensure_ascii=False))
    out.write_text(page, encoding="utf-8")
    print(f"OK: {len(cards)} fotos -> {out}")


if __name__ == "__main__":
    main()
