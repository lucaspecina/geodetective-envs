"""Dossier HTML del experimento: análisis agregado + expedientes navegables.

UN documento autocontenido (sin servidor) con dos vistas:
1. ANÁLISIS — perfil conductual por modelo: señales agrupadas por familia de
   vicio (regulación de creencias, parada, procedencia, estilo, recursos), con
   comparación visual entre modelos y lectura.
2. EXPEDIENTES — cada corrida (modelo × foto × run): ficha de comportamiento
   (los flags que disparó, resaltados) + timeline de razonamiento paso a paso
   (thinking + tool calls + creencias + submit) + mapa de la trayectoria de
   creencias sincronizado.

Liviano por diseño: NO embebe las imágenes crudas que vio el modelo (eso es el
belief_viewer detallado). Corre sobre results crudos o .slim.

Uso:
    python scripts/build_dossier.py --dir experiments/E016_belief_pilot
    # Output: experiments/E016_belief_pilot/dossier.html
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geodetective.eval.belief_scoring import Belief, great_circle_km, score_belief
try:
    from geodetective.corpus import CLEAN_VERSION
    from geodetective.tools.crop_image import crop_image as _do_crop
    _CROP_OK = True
except Exception:
    CLEAN_VERSION = 1
    _CROP_OK = False

# Reusar el perfilador
sys.path.insert(0, str(Path(__file__).resolve().parent))
from behavior_profile import profile_run  # noqa: E402

PHOTOS_DIR = Path("corpus/photos")


def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def img_b64(b64: str | None, label: str = "") -> str:
    """Imagen embebida en el HTML (data URI) — autocontenido, abre con doble click."""
    if not b64:
        return ""
    lab = f'<div class="il">{esc(label)}</div>' if label else ""
    return f'<div class="ib">{lab}<img loading="lazy" src="data:image/jpeg;base64,{b64}"/></div>'


def reconstruct_crop(cid, region: dict) -> str | None:
    """Re-generar el crop desde la foto original (el trace slim no guarda el base64)."""
    if not _CROP_OK or not region:
        return None
    p = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
    if not p.exists():
        return None
    try:
        cr = _do_crop(image_path=p, x=int(region.get("x", 0)), y=int(region.get("y", 0)),
                      width=int(region.get("w", 0)), height=int(region.get("h", 0)))
        return cr.base64_jpeg
    except Exception:
        return None


# Señales booleanas agrupadas por familia (con etiqueta humana y polaridad:
# True=malo salvo las marcadas good=True)
SIGNAL_GROUPS = {
    "Regulación de creencias": [
        ("wrong_persistence", "Persiste en candidato equivocado", False),
        ("wrong_entrenchment", "Se atrinchera (persiste + sube la fe)", False),
        ("correct_mass_abandonment", "Abandona la respuesta correcta", False),
        ("confidence_ratchet_wrong", "Confianza solo sube estando mal", False),
        ("first_hypothesis_dominance_wrong", "Se queda con 1ª hipótesis (errada)", False),
        ("recovery_from_wrong_start", "Se recupera de arranque malo", True),
        ("top_return_aba", "Vuelve sobre un candidato abandonado", True),
        ("never_correct", "Nunca pisa la zona correcta", False),
    ],
    "Regulación de parada": [
        ("early_uncertain_commit", "Corta rápido e inseguro (y falla)", False),
        ("early_overconfident_wrong", "Corta rápido, muy confiado (y falla)", False),
        ("correct_top_deterioration", "Estuvo bien y terminó mal", False),
        ("stale_confidence_at_submit", "Confianza vencida al entregar", False),
    ],
    "Integridad / coherencia": [
        ("last_belief_submit_mismatch", "Entrega algo distinto a lo que creía", False),
        ("revision_without_new_evidence", "Cambia sin evidencia nueva", False),
        ("low_evidence_submit", "Entrega casi sin investigar", False),
        ("decorative_alternatives", "Nombra alternativas que no investiga", False),
    ],
    "Estilo": [
        ("used_nonlatin_queries", "Busca en el idioma del lugar", True),
        ("single_track", "Un solo carril (sin rivales)", False),
        ("year_belief_frozen", "Creencia de fecha congelada", False),
    ],
}

MEAN_SIGNALS = [
    ("steps_frac_used", "Fracción del presupuesto usada"),
    ("visual_share", "Proporción de verificación visual"),
    ("tool_kind_diversity", "Tipos de herramienta distintos"),
    ("avg_query_words", "Palabras por búsqueda"),
    ("script_switches", "Cambios de alfabeto (idioma)"),
    ("dead_ends", "Callejones sin salida por corrida"),
    ("unassigned_mass_mean", 'Masa de "no sé" (honestidad)'),
    ("max_update_shift", "Salto máx. de creencia"),
    ("unique_top_clusters", "Hipótesis top distintas"),
]


def cell_pct(rows, key, good):
    vals = [r[key] for r in rows if key in r and r[key] is not None]
    if not vals:
        return "—", ""
    pct = 100 * sum(bool(v) for v in vals) / len(vals)
    # color: rojo si malo y alto; verde si bueno y alto
    hot = pct / 100
    if good:
        col = f"rgba(60,180,90,{0.15 + 0.5*hot:.2f})"
    else:
        col = f"rgba(220,70,70,{0.10 + 0.6*hot:.2f})"
    return f"{pct:.0f}%", col


def cell_mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None and isinstance(r[key], (int, float))]
    return f"{sum(vals)/len(vals):.2f}" if vals else "—"


def build_analysis(by_model_arm: dict) -> str:
    # columnas = (modelo, arm) con belief-on primero
    cols = sorted(by_model_arm.keys(), key=lambda k: (k[1] != "on", k[0]))
    on_cols = [c for c in cols if c[1] == "on"]

    def header_row():
        ths = "".join(f'<th>{esc(m)}<br><span class="muted">belief-{a} · n={len(by_model_arm[(m,a)])}</span></th>'
                      for m, a in on_cols)
        return f"<tr><th style='text-align:left'>señal</th>{ths}</tr>"

    html_out = ['<h2>Perfil conductual por modelo</h2>',
                '<p class="muted">Sobre corridas belief-on (las que reportan creencias). '
                'Rojo = frecuencia del patrón problemático; verde = patrón deseable. '
                'Cada celda es el % de corridas donde apareció.</p>']

    for group, sigs in SIGNAL_GROUPS.items():
        html_out.append(f'<h3>{esc(group)}</h3><table class="profile"><thead>{header_row()}</thead><tbody>')
        for key, label, good in sigs:
            tds = []
            for c in on_cols:
                txt, col = cell_pct(by_model_arm[c], key, good)
                tds.append(f'<td style="background:{col}">{txt}</td>')
            arrow = "↑ bueno" if good else ""
            html_out.append(f'<tr><td style="text-align:left">{esc(label)} '
                            f'<span class="muted">{arrow}</span></td>{"".join(tds)}</tr>')
        html_out.append("</tbody></table>")

    # Medias
    html_out.append('<h3>Estilo y recursos (medias)</h3><table class="profile"><thead>'
                    + header_row() + "</thead><tbody>")
    for key, label in MEAN_SIGNALS:
        tds = "".join(f'<td>{cell_mean(by_model_arm[c], key)}</td>' for c in on_cols)
        html_out.append(f'<tr><td style="text-align:left">{esc(label)}</td>{tds}</tr>')
    html_out.append("</tbody></table>")
    return "\n".join(html_out)


# === Timeline liviano (sin base64) ===

def render_event_light(ev: dict, cid=None) -> str:
    """Variante sin imágenes (dossier liviano): sustituye la imagen por una nota."""
    out = render_event(ev, cid, embed=False)
    return out


def render_event(ev: dict, cid, embed: bool = True) -> str:
    """Evento del timeline CON imágenes embebidas (foto, crops, street, mapas, páginas).
    Con embed=False, las imágenes se reemplazan por '[vio: ...]'."""
    def _img(b64, label=""):
        if not embed:
            return f'<span class="muted">[vio: {esc(label) or "imagen"}]</span>' if (b64 or label) else ""
        return img_b64(b64, label)
    t = ev.get("type", "")
    if t in ("thinking", "thinking_block"):
        return f'<div class="ev think"><pre>{esc(ev.get("content",""))}</pre></div>'
    if t == "report_belief":
        b = ev.get("belief", {})
        rows = "".join(f'<tr><td>{esc(c.get("name"))}</td><td>{c.get("weight")}</td>'
                       f'<td>{c.get("radius_km")}km</td></tr>'
                       for c in b.get("location_belief", []))
        yr = " · ".join(f'[{y.get("from")}-{y.get("to")}] {y.get("weight")}'
                        for y in b.get("year_belief", []))
        return ('<div class="ev belief"><b>🧠 creencia</b>'
                f'<table>{rows}</table><div class="muted">año: {esc(yr) or "—"}</div>'
                f'<div class="rat">{esc(b.get("rationale",""))}</div></div>')
    if t == "probe_injection":
        return (f'<div class="ev probe"><b>⚡ intervención ({esc(ev.get("arm"))})</b>'
                f'<pre>{esc((ev.get("bulletin") or "")[:600])}</pre></div>')
    if t == "report_verification":
        a = ev.get("args", {})
        return f'<div class="ev probe"><b>🔎 verificación reportada:</b> {esc(a.get("status"))} — {esc(a.get("reasoning",""))}</div>'
    if t == "submit":
        a = ev.get("answer", {}) or {}
        return (f'<div class="ev submit"><b>✅ entrega</b> {esc(a.get("location"))} '
                f'({a.get("lat")}, {a.get("lon")}) · año {esc(a.get("year"))} · conf {esc(a.get("confidence"))}'
                f'<div class="rat">{esc(a.get("reasoning",""))}</div></div>')
    if t == "web_search":
        tops = "".join(f'<li><a href="{esc(r.get("url"))}" target="_blank">{esc((r.get("title") or "")[:90])}</a>'
                       f'<div class="snip">{esc((r.get("snippet") or "")[:220])}</div></li>'
                       for r in (ev.get("top_results") or [])[:3])
        return (f'<div class="ev tool">🔎 <b>web_search</b> <code>{esc(ev.get("query"))}</code> '
                f'<span class="muted">{ev.get("result_count")} res, {ev.get("blocked",0)} bloq</span><ul>{tops}</ul></div>')
    if t == "image_search":
        cells = "".join(f'<div class="cm">#{c.get("cell")} {esc((c.get("alt_text") or "")[:70])}</div>'
                        for c in (ev.get("cells_metadata") or [])[:16])
        grid = _img(ev.get("grid_image_b64"), "grilla de resultados")
        return (f'<div class="ev tool">🖼️ <b>image_search</b> <code>{esc(ev.get("query"))}</code> '
                f'<span class="muted">{ev.get("n_cells","")} celdas</span>{grid}{cells}</div>')
    if t == "image_search_pick":
        picks = "".join(_img(p.get("image_b64"), f'celda #{p.get("cell")}: {esc((p.get("alt_text") or "")[:60])}')
                        for p in (ev.get("picks") or []))
        return f'<div class="ev tool">🖼️ <b>image_search pick</b><div class="imgrow">{picks}</div></div>'
    if t in ("geocode", "reverse_geocode"):
        tops = "".join(f'<li>({r.get("lat")}, {r.get("lon")}) — {esc((r.get("display_name") or "")[:80])}</li>'
                       for r in (ev.get("top_results") or [])[:3])
        return (f'<div class="ev tool">📍 <b>{t}</b> <code>{esc(json.dumps(ev.get("args",{}),ensure_ascii=False))[:80]}</code>'
                f'<ul>{tops}</ul></div>')
    if t == "static_map":
        pois = ", ".join(f'{esc(p.get("name"))}({p.get("distance_m",0):.0f}m)' for p in (ev.get("nearby_pois") or [])[:3])
        return (f'<div class="ev tool">🗺️ <b>static_map</b> <code>{esc(json.dumps(ev.get("args",{}),ensure_ascii=False))[:70]}</code>'
                f'<div class="muted">{pois}</div>{_img(ev.get("base64_jpeg"), "mapa que vio")}</div>')
    if t == "street_view":
        imgs = "".join(_img(im.get("base64_jpeg"), f'heading {im.get("heading")}') for im in (ev.get("images") or []))
        return (f'<div class="ev tool">👁️ <b>street_view</b> <code>{esc(json.dumps(ev.get("args",{}),ensure_ascii=False))[:70]}</code>'
                f' <span class="muted">pano {esc(ev.get("pano_date"))}</span><div class="imgrow">{imgs}</div></div>')
    if t in ("crop_image", "crop_image_relative"):
        b64 = ev.get("base64_jpeg") or (reconstruct_crop(cid, ev.get("region") or {}) if embed else None)
        return (f'<div class="ev tool">✂️ <b>crop</b> {esc(json.dumps(ev.get("region",{})))}'
                f'{_img(b64, "recorte que vio")}</div>')
    if t in ("fetch_url", "fetch_url_with_images"):
        imgs = "".join(_img(im.get("base64_jpeg"), (im.get("url") or "")[:60])
                       for im in (ev.get("visible_images") or []) if im.get("base64_jpeg"))
        return (f'<div class="ev tool">📄 <b>{t}</b> <span class="muted">{esc((ev.get("title") or "")[:70])}</span>'
                f'<div class="snip">{esc((ev.get("text_snippet") or "")[:250])}</div><div class="imgrow">{imgs}</div></div>')
    if t in ("historical_query", "historical_query_at"):
        return f'<div class="ev tool">🏛️ <b>{t}</b> <span class="muted">{ev.get("n_features","")} features</span></div>'
    if t == "belief_nudge":
        return '<div class="ev note">⏰ recordatorio de reportar creencia</div>'
    if t.endswith("_error"):
        return f'<div class="ev err">⚠️ {esc(t)}: {esc((str(ev.get("error")) or "")[:120])}</div>'
    return ""


def build_dossier_run(record: dict, idx: int, with_images: bool = True) -> tuple[dict, str, dict]:
    """Devuelve (meta, timeline_html, mapdata) para una corrida."""
    rk = record.get("react") or {}
    prof = profile_run(record)
    truth = record.get("geo")
    reports = rk.get("belief_reports") or []
    trace = rk.get("trace") or []
    fa = rk.get("final_answer") or {}

    cid = record.get("cid")
    # foto target embebida al inicio del expediente
    photo_html = ""
    if with_images:
        pp = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
        if pp.exists():
            b64 = base64.b64encode(pp.read_bytes()).decode()
            photo_html = f'<div class="targetphoto">{img_b64(b64, "📷 FOTO A INVESTIGAR")}</div>'

    # timeline por step
    by_step = defaultdict(list)
    for ev in trace:
        by_step[int(ev.get("step", 0))].append(ev)
    steps_used = rk.get("steps_used") or max(by_step.keys() or [1])
    cards = [photo_html] if photo_html else []
    render = render_event if with_images else render_event_light
    for s in range(1, steps_used + 1):
        evs = "".join(render(ev, cid) for ev in by_step.get(s, []))
        if evs:
            cards.append(f'<div class="stepcard"><div class="sh">paso {s}</div>{evs}</div>')
    timeline = "\n".join(cards)

    # mapdata: puntos de creencia por report + truth + submit
    js_reports = []
    for rep in reports:
        b = Belief.from_dict(rep["belief"])
        js_reports.append({
            "step": rep["step"],
            "cands": [{"name": c.name, "lat": c.lat, "lon": c.lon, "w": c.weight, "r": c.radius_km}
                      for c in b.location],
        })
    mapdata = {
        "idx": idx, "truth": truth, "reports": js_reports,
        "final": {"lat": fa.get("lat"), "lon": fa.get("lon"), "loc": fa.get("location")} if fa else None,
    }

    dist = rk.get("distance_km")
    meta = {
        "idx": idx, "cid": record.get("cid"), "model": rk.get("model"),
        "arm": prof.get("arm"), "run": record.get("run_idx"),
        "title": record.get("title", ""), "bucket": record.get("bucket_pais", ""),
        "dist": round(dist, 1) if dist is not None else None,
        "year_truth": record.get("year"), "year_pred": fa.get("year"),
        "prof": prof,
    }
    return meta, timeline, mapdata


def render_ficha(prof: dict) -> str:
    """Ficha de comportamiento: los flags que disparó, agrupados."""
    out = []
    for group, sigs in SIGNAL_GROUPS.items():
        chips = []
        for key, label, good in sigs:
            v = prof.get(key)
            if v is True:
                cls = "chip-good" if good else "chip-bad"
                chips.append(f'<span class="{cls}">{esc(label)}</span>')
        if chips:
            out.append(f'<div class="fgroup"><span class="muted">{esc(group)}:</span> {"".join(chips)}</div>')
    # métricas clave
    mk = []
    for key, label in [("steps_frac_used", "budget usado"), ("dead_ends", "callejones"),
                       ("used_nonlatin_queries", "idioma local"), ("unassigned_mass_mean", "masa no-sé")]:
        v = prof.get(key)
        if v is not None:
            vs = f"{v:.2f}" if isinstance(v, float) else ("sí" if v is True else ("no" if v is False else v))
            mk.append(f'<span class="metric">{esc(label)}: <b>{vs}</b></span>')
    if mk:
        out.append(f'<div class="fgroup">{"".join(mk)}</div>')
    return "\n".join(out) or '<div class="muted">sin flags problemáticos</div>'


PAGE = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"/>
<title>Dossier — {title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0f0f10;color:#e0e0e0;margin:0}}
 header{{background:#17171a;padding:12px 20px;border-bottom:1px solid #333;position:sticky;top:0;z-index:500}}
 h1{{font-size:17px;margin:0;display:inline-block}} h2{{font-size:16px}} h3{{font-size:14px;color:#e8934a;margin:14px 0 6px}}
 .tab-btn{{background:#242428;border:1px solid #444;color:#ccc;padding:6px 16px;border-radius:6px;cursor:pointer;margin-left:6px}}
 .tab-btn.active{{background:#2e2415;border-color:#e8934a;color:#fff}}
 .view{{display:none;padding:18px 24px;max-width:1400px}} .view.on{{display:block}}
 .muted{{color:#888}} code{{color:#7aa7e8;font-size:11.5px}}
 table.profile{{border-collapse:collapse;font-size:12.5px;margin:4px 0 12px}}
 table.profile th,table.profile td{{border:1px solid #2c2c30;padding:4px 12px;text-align:center}}
 table.profile th{{background:#1c1c20;font-weight:600}}
 .layout{{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:16px;align-items:start}}
 .sidebar{{position:sticky;top:70px}} #dmap{{height:340px;border-radius:8px}}
 select{{background:#242428;color:#e0e0e0;border:1px solid #555;border-radius:6px;padding:6px;font-size:13px;width:100%;margin-bottom:10px}}
 .ficha{{background:#17171a;border:1px solid #333;border-radius:8px;padding:10px;margin-bottom:10px;font-size:12px}}
 .fgroup{{margin:4px 0}}
 .chip-bad{{background:#3a1a1a;color:#f0a0a0;border:1px solid #6a2a2a;border-radius:12px;padding:1px 9px;font-size:11px;margin:2px;display:inline-block}}
 .chip-good{{background:#16301c;color:#8fdca0;border:1px solid #2a5a35;border-radius:12px;padding:1px 9px;font-size:11px;margin:2px;display:inline-block}}
 .metric{{background:#242428;border-radius:5px;padding:1px 8px;font-size:11px;margin:2px;display:inline-block}}
 .stepcard{{border:1px solid #2a2a2e;border-radius:8px;padding:6px 10px;margin-bottom:9px}}
 .sh{{font-weight:600;color:#e8934a;margin-bottom:4px;font-size:12px}}
 .ev{{margin:5px 0;padding:5px 8px;border-radius:6px;background:#1d1d20;font-size:12.5px;overflow-wrap:anywhere}}
 .ev.think{{background:#1a2130;border-left:3px solid #5b8def}}
 .ev.belief{{background:#16231c;border-left:3px solid #19c37d}}
 .ev.submit{{background:#261a26;border-left:3px solid #c36ac3}}
 .ev.probe{{background:#2a2410;border-left:3px solid #e8c34a}}
 .ev.err{{background:#2a1717;border-left:3px solid #e84c4c;color:#e0a0a0}}
 .ev.tool{{background:#202024}}
 .ev pre{{white-space:pre-wrap;margin:3px 0;font-size:12px}}
 .ev table{{border-collapse:collapse;font-size:11.5px}} .ev td{{border:1px solid #333;padding:1px 6px}}
 .ev ul{{margin:3px 0 2px 16px;padding:0;font-size:11.5px;color:#aaa}}
 .rat{{color:#9fb0c8;font-size:11.5px;margin-top:3px}}
 .snip{{color:#8a8a8a;font-size:11px;margin:2px 0}}
 .cm{{font-size:11px;color:#999}}
 .ib{{display:inline-block;margin:4px 6px 4px 0;vertical-align:top}}
 .ib img{{max-height:210px;max-width:100%;border-radius:5px;display:block}}
 .il{{font-size:10.5px;color:#888;margin-bottom:2px}}
 .imgrow{{display:flex;flex-wrap:wrap}}
 .targetphoto{{margin-bottom:10px;padding:8px;background:#17171a;border:1px solid #333;border-radius:8px}}
 .targetphoto img{{max-height:340px}}
 .runhead{{font-size:14px;margin-bottom:8px}} .badge{{background:#242428;border-radius:5px;padding:2px 8px;font-size:11.5px;margin-right:4px}}
 ul.idx{{font-size:14px;line-height:1.9}} ul.idx a{{color:#7aa7e8;text-decoration:none}} ul.idx a:hover{{text-decoration:underline}}
</style></head><body>
<header>
 <h1>🗂️ Dossier — {title}</h1>
 <span style="float:right">
  <button class="tab-btn active" onclick="showTab('analysis',this)">📊 Análisis</button>
  <button class="tab-btn" onclick="showTab('files',this)">🗂️ Expedientes</button>
 </span>
</header>
<div id="analysis" class="view on">
 <p class="muted">{subtitle}</p>
 {analysis}
</div>
<div id="files" class="view">
 <div class="layout">
  <div>
   <select id="runsel" onchange="selectRun(this.value)"></select>
   <div id="runhead" class="runhead"></div>
   <div id="ficha" class="ficha"></div>
   <div id="timeline"></div>
  </div>
  <div class="sidebar">
   <div id="dmap"></div>
   <div class="muted" style="font-size:11.5px;margin-top:6px">🟢 verdad · 🔵 entrega · 🟠 creencias (tamaño=radio, opacidad=peso). Del report más cercano al paso.</div>
  </div>
 </div>
</div>
<script>
const RUNS = {runs_json};
const MAPS = {maps_json};
let map, layer;

function showTab(id, btn){{
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  if(id==='files' && !map) initMap();
}}

function initMap(){{
  map = L.map('dmap',{{worldCopyJump:true}});
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OSM',opacity:0.75}}).addTo(map);
  layer = L.layerGroup().addTo(map);
  selectRun(0);
}}

function selectRun(i){{
  i = +i;
  const r = RUNS[i], md = MAPS[i];
  document.getElementById('runhead').innerHTML =
    `<b>${{r.model}}</b> · ${{r.title}} <span class="muted">(${{r.bucket}})</span><br>`+
    `<span class="badge">dist: ${{r.dist!=null?r.dist+' km':'NA'}}</span>`+
    `<span class="badge">año: ${{r.year_pred||'—'}} (real ${{r.year_truth}})</span>`+
    `<span class="badge">belief-${{r.arm}}</span>`;
  document.getElementById('ficha').innerHTML = r.ficha;
  document.getElementById('timeline').innerHTML = r.timeline;
  drawMap(md);
}}

function drawMap(md){{
  if(!map) return;
  layer.clearLayers();
  const pts=[];
  (md.reports||[]).forEach(rp=>rp.cands.forEach(c=>pts.push([c.lat,c.lon])));
  if(md.truth) pts.push(md.truth);
  if(pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.3)); else map.setView([20,0],2);
  // creencias: unir por report, opacidad por peso
  (md.reports||[]).forEach((rp,ri)=>{{
    const op = 0.12 + 0.5*ri/Math.max(1,(md.reports.length-1));
    rp.cands.forEach(c=>{{
      L.circle([c.lat,c.lon],{{radius:(c.r||20)*1000,color:'#ff8a3d',weight:1,
        fillColor:'#ff8a3d',fillOpacity:Math.min(0.5,0.08+c.w*0.4)}}).addTo(layer)
        .bindTooltip(`paso ${{rp.step}}: ${{c.name}} (w=${{c.w}})`);
    }});
  }});
  if(md.truth) L.circleMarker(md.truth,{{radius:7,color:'#19c37d',fillColor:'#19c37d',fillOpacity:0.95}}).addTo(layer).bindTooltip('VERDAD');
  if(md.final&&md.final.lat!=null) L.circleMarker([md.final.lat,md.final.lon],{{radius:6,color:'#5b8def',fillColor:'#5b8def',fillOpacity:0.9}}).addTo(layer).bindTooltip('entrega');
}}

// llenar el selector
const sel=document.getElementById('runsel');
RUNS.forEach((r,i)=>{{
  const o=document.createElement('option'); o.value=i;
  o.textContent=`${{r.model}} · ${{r.title.slice(0,40)}} · ${{r.dist!=null?r.dist+'km':'NA'}} (belief-${{r.arm}})`;
  sel.appendChild(o);
}});
</script>
</body></html>"""


def write_dossier(records: list[dict], out: Path, title: str, analysis: str,
                  subtitle: str, with_images: bool) -> float:
    on_records = [r for r in records if (r.get("react") or {}).get("belief_reports")]
    on_records.sort(key=lambda r: ((r.get("react") or {}).get("model") or "", r.get("cid") or 0,
                                   r.get("run_idx") or 0))
    runs_json, maps_json = [], []
    for i, rec in enumerate(on_records):
        meta, timeline, mapdata = build_dossier_run(rec, i, with_images=with_images)
        runs_json.append({
            "idx": i, "cid": meta["cid"], "model": meta["model"], "arm": meta["arm"],
            "title": meta["title"], "bucket": meta["bucket"], "dist": meta["dist"],
            "year_truth": meta["year_truth"], "year_pred": meta["year_pred"],
            "ficha": render_ficha(meta["prof"]), "timeline": timeline,
        })
        maps_json.append(mapdata)
    page = PAGE.format(title=esc(title), subtitle=esc(subtitle), analysis=analysis,
                       runs_json=json.dumps(runs_json, ensure_ascii=False),
                       maps_json=json.dumps(maps_json, ensure_ascii=False))
    out.write_text(page, encoding="utf-8")
    return out.stat().st_size / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("experiments/E016_belief_pilot"))
    ap.add_argument("--title", default=None)
    ap.add_argument("--split-by-model", action="store_true",
                    help="un dossier CON imágenes por modelo (recomendado si hay muchas corridas)")
    ap.add_argument("--no-images", action="store_true", help="dossier único liviano sin imágenes")
    args = ap.parse_args()

    records = []
    for p in sorted(args.dir.glob("results_*_belief-*.json")):
        if ".slim" in p.name and (args.dir / p.name.replace(".slim", "")).exists():
            continue
        try:
            for rec in json.loads(p.read_text(encoding="utf-8")):
                if not (rec.get("react") or {}).get("error"):
                    records.append(rec)
        except Exception:
            continue
    if not records:
        raise SystemExit(f"sin corridas en {args.dir}")

    by_ma = defaultdict(list)
    for rec in records:
        prof = profile_run(rec)
        by_ma[(prof.get("model"), prof.get("arm"))].append(prof)
    analysis = build_analysis(by_ma)
    n_models = len({m for m, a in by_ma})
    n_runs = sum(len(v) for v in by_ma.values())
    n_fotos = len(set(r.get("cid") for r in records))
    base_title = args.title or args.dir.name

    # Auto-split: si hay >1 modelo y no se pidió --no-images, partir por modelo
    # (un dossier con las 89 corridas + imágenes pesa ~500MB y cuelga el browser).
    do_split = args.split_by_model or (n_models > 1 and not args.no_images)

    if not do_split:
        sub = f"{n_models} modelos · {n_fotos} fotos · {n_runs} corridas"
        mb = write_dossier(records, args.dir / "dossier.html", base_title, analysis, sub,
                           with_images=not args.no_images)
        print(f"OK: {args.dir/'dossier.html'} ({mb:.0f} MB)")
        return

    # Un dossier CON imágenes por modelo + índice
    print(f"Partiendo por modelo ({n_models} modelos, imágenes embebidas)...")
    links = []
    for model in sorted({m for m, a in by_ma}):
        recs_m = [r for r in records if (r.get("react") or {}).get("model") == model]
        by_ma_m = {k: v for k, v in by_ma.items() if k[0] == model}
        an_m = build_analysis(by_ma_m)
        n_on = sum(1 for r in recs_m if (r.get("react") or {}).get("belief_reports"))
        sub = f"{model} · {n_fotos} fotos · {len(recs_m)} corridas · {n_on} expedientes"
        fname = f"dossier_{model.replace('.', '_').replace('/', '_')}.html"
        mb = write_dossier(recs_m, args.dir / fname, f"{base_title} — {model}", an_m, sub, with_images=True)
        print(f"  {fname} ({mb:.0f} MB)")
        links.append((model, fname, n_on, mb))

    # índice liviano con el análisis global comparativo + links
    linkhtml = "".join(
        f'<li><a href="{esc(f)}"><b>{esc(m)}</b></a> — {n} expedientes con imágenes ({mb:.0f} MB)</li>'
        for m, f, n, mb in links)
    idx_page = PAGE.format(
        title=esc(base_title), analysis=(
            f'<h2>Dossier por modelo</h2><p class="muted">Cada uno con la foto, los recortes y '
            f'todas las imágenes que vio el modelo. Abrilos con doble click.</p><ul class="idx">{linkhtml}</ul>'
            f'<hr style="border-color:#333;margin:18px 0">{analysis}'),
        subtitle=esc(f"{n_models} modelos · {n_fotos} fotos · {n_runs} corridas"),
        runs_json="[]", maps_json="[]")
    (args.dir / "dossier.html").write_text(idx_page, encoding="utf-8")
    print(f"OK: índice {args.dir/'dossier.html'} + {len(links)} dossiers por modelo")


if __name__ == "__main__":
    main()
