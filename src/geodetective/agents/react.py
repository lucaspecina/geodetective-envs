"""ReAct agent multi-paso con tool calling vía OpenAI function calling format.

Tools disponibles:
- web_search: búsqueda de texto con filtros anti-shortcut.
- fetch_url: leer una página específica (texto).
- fetch_url_with_images: leer una página específica + ver sus imágenes embebidas.
- image_search: buscar imágenes (con hash perceptual flag de match con target).
- submit_answer: terminar y devolver respuesta estructurada.

Cuando una tool devuelve imágenes (image_search o fetch_url_with_images), las imágenes
se inyectan como user message después del tool result, para que el modelo las pueda VER.
"""
from __future__ import annotations
import os
import json
import base64
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field
from openai import OpenAI

from ..corpus.blacklist import compute_excluded_domains
from ..tools.web_search import web_search, TOOL_SCHEMA as WEB_SEARCH_SCHEMA
from ..tools.fetch_url import fetch_url, TOOL_SCHEMA_TEXT as FETCH_URL_SCHEMA, TOOL_SCHEMA_WITH_IMAGES as FETCH_URL_IMG_SCHEMA
from ..tools.image_search import image_search, TOOL_SCHEMA as IMAGE_SEARCH_SCHEMA
from ..tools.geocode import geocode, reverse_geocode, TOOL_SCHEMA_GEOCODE, TOOL_SCHEMA_REVERSE
from ..tools.historical_query import historical_query, TOOL_SCHEMA as HISTORICAL_QUERY_SCHEMA
from ..tools.crop_image import crop_image, crop_image_relative, TOOL_SCHEMA_CROP, TOOL_SCHEMA_CROP_RELATIVE
from ..tools.static_map import static_map, StaticMapError, TOOL_SCHEMA as STATIC_MAP_SCHEMA
from ..tools.street_view import street_view, StreetViewError, TOOL_SCHEMA as STREET_VIEW_SCHEMA


SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "Submit tu respuesta final con coordenadas, año y razonamiento estructurado.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Descripción humana del lugar."},
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "year": {"type": "string", "description": "Año o rango (ej '1965', '1960-1970')."},
                "reasoning": {"type": "string", "description": "Resumen breve del razonamiento general."},
                "confidence": {"type": "string", "enum": ["alta", "media", "baja"]},
                "visual_clues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pistas visuales concretas que extrajiste de la foto target (arquitectura, idioma de carteles, vehículos, vestimenta, vegetación, etc.).",
                },
                "external_evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidencia externa que recolectaste vía tools (URL + qué confirma). Vacío si solo razonaste sin tools.",
                },
                "rejected_alternatives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Hipótesis alternativas que consideraste y descartaste, con la razón.",
                },
                "verification_checks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Chequeos independientes que hiciste (ej: 'comparé Street View con foto y matchea fachada', 'historical_query confirmó iglesia existía en año X'). Vacío si NO hiciste verificación.",
                },
                "uncertainty_reason": {
                    "type": "string",
                    "description": "Si confidence != alta, explicá qué información falta o por qué dudás.",
                },
            },
            "required": ["location", "lat", "lon", "reasoning", "confidence"],
        },
    },
}


SYSTEM_PROMPT = """Recibís una fotografía. Tu tarea es descubrir DÓNDE fue tomada (coords lat/lon) y CUÁNDO (año aproximado), y devolver la respuesta vía `submit_answer`.

## Herramientas disponibles (qué hace cada una)

**`web_search(query, max_results)`**
Busca texto en la web vía Tavily. Devuelve lista de resultados con `url`, `title`, `content` (snippet largo en modo advanced, ~1000-3000 chars).

**`fetch_url(url)`**
Baja una página web específica. Devuelve `title` + `text` (hasta 12000 chars del contenido principal de la página).

**`fetch_url_with_images(url)`**
Igual que `fetch_url` pero ADEMÁS baja hasta 5 imágenes embebidas en la página. Las imágenes que NO son la foto target se muestran en el siguiente turn; las que coinciden visualmente con la foto target se cuentan pero no se exponen (ni bytes ni URL).

**`image_search(query, max_results)`**
Busca imágenes en la web (estilo Google Images). Las imágenes que NO son la foto target vienen en el siguiente turn con metadata: `url` de origen y `hamming_distance`. Las imágenes que coinciden visualmente con la foto target se cuentan pero no se exponen.

**`crop_image(x, y, width, height)`**
Recorta una región rectangular de la foto target con coordenadas en pixels. La región recortada se muestra ampliada en el siguiente turn.

**`crop_image_relative(region)`**
Igual pero con regiones nombradas: `top_left`, `top_right`, `top_center`, `bottom_left`, `bottom_right`, `bottom_center`, `middle`, `center`, `left_half`, `right_half`, `top_half`, `bottom_half`.

**`geocode(query, language)`**
Convierte un nombre o dirección a coordenadas usando Nominatim (OSM). Ej: "Plaza Mayor Madrid" devuelve coords + dirección estructurada + tipo (residential/city/street/etc).

**`reverse_geocode(lat, lon, zoom)`**
Convierte coords a dirección. `zoom` controla el detalle: 3=país, 10=ciudad, 17=edificio, 18=calle.

**`historical_query(south, west, north, east, preset, year, require_dated, max_features)`**
Busca features de OpenHistoricalMap en un bounding box. `preset` puede ser: `buildings`, `churches`, `schools`, `factories`, `railway_stations`, `monuments`, `houses`, `all_named`. Si `year` está dado, filtra features que existían en ese año. Cada feature trae `temporal_confidence`: `high` si tiene `start_date`/`end_date` confirmados; `low` si no tiene tags temporales (asumido pero no confirmado). OHM tiene cobertura DESIGUAL: ausencia de resultados no prueba ausencia histórica.

**`static_map(lat, lon, zoom, map_type)`**
Pide imagen de mapa de Google Maps. `map_type`: `roadmap`, `satellite`, `terrain` (relieve 2D con curvas de nivel), `hybrid`. La imagen se muestra en el siguiente turn.

**`street_view(lat, lon, heading, pitch, fov, contact_sheet)`**
Pide imagen(es) de Google Street View. Modo single (1 imagen al heading dado) o `contact_sheet=true` (4 imágenes en N/E/S/W). Devuelve fecha del panorama y distancia entre coords pedidas y panorama real. Si no hay cobertura, devuelve error `no_coverage`.

**`submit_answer(...)`**
Devolver respuesta. Campos: `location`, `lat`, `lon`, `year`, `reasoning`, `confidence` (alta/media/baja), `visual_clues`, `external_evidence`, `rejected_alternatives`, `verification_checks`, `uncertainty_reason`.

## Filtros automáticos (no podés desactivarlos)

- En `web_search`, `fetch_url`, `fetch_url_with_images`, `image_search` se bloquean automáticamente algunos dominios para evitar shortcuts: reverse image search engines, agregadores masivos con metadata estructurada (caption + geotag), hosting/sharing platforms con propensión a re-publicar archivos, y la fuente específica de la foto que estás investigando. La lista exacta depende de cada foto; no necesitás conocerla.
- Cuando una imagen tiene hash perceptual coincidente con la foto target, la ocultamos: te informamos su cantidad pero no te mostramos los bytes (la foto objetivo no es evidencia sobre dónde fue tomada).

## Idioma

Las queries pueden estar en cualquier idioma. Tus respuestas y razonamiento, en español."""


@dataclass
class ReActResult:
    final_answer: Optional[dict] = None
    trace: list[dict] = field(default_factory=list)
    web_search_count: int = 0
    fetch_url_count: int = 0
    image_search_count: int = 0
    geocode_count: int = 0
    historical_query_count: int = 0
    crop_count: int = 0
    static_map_count: int = 0
    street_view_count: int = 0
    target_match_count: int = 0
    submit_called: bool = False
    steps_used: int = 0
    error: Optional[str] = None


def run_react_agent(
    image_path: Path,
    model: str = "gpt-5.4",
    max_steps: int = 12,
    verbose: bool = True,
    user_prompt: str = "Investigá esta foto y devolvé las coordenadas (lat, lon) y año con submit_answer.",
    provider: Optional[str] = None,
    provenance_source: Optional[str] = None,
) -> ReActResult:
    """Correr el agente ReAct con todas las tools.

    Anti-shortcut runtime:
    - `provider`: identifica la fuente del corpus (pastvu, smapshot, ...). Sus dominios
      van al excluido per-photo además del GLOBAL.
    - `provenance_source`: campo `source` del candidate (free-text con URLs originales).
      Se extraen hosts y se agregan al excluido.
    """
    client = OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
    )
    excluded_domains = compute_excluded_domains(provider=provider, source=provenance_source)
    if verbose and excluded_domains:
        print(f"[run_react_agent] excluded_domains per-photo: {excluded_domains}")
    image_path = Path(image_path)
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"
    # Tamaño de la foto target (para que el modelo sepa coords máximas para crop_image)
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(image_path) as _im:
            img_w, img_h = _im.size
    except Exception:
        img_w, img_h = 0, 0

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt + f"\n\nFoto target: {img_w}x{img_h} pixels (ancho x alto). Crop coordinates deben estar dentro de ese rango.\n\n[Foto target abajo]"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    tools = [
        WEB_SEARCH_SCHEMA,
        FETCH_URL_SCHEMA,
        FETCH_URL_IMG_SCHEMA,
        IMAGE_SEARCH_SCHEMA,
        TOOL_SCHEMA_GEOCODE,
        TOOL_SCHEMA_REVERSE,
        HISTORICAL_QUERY_SCHEMA,
        TOOL_SCHEMA_CROP,
        TOOL_SCHEMA_CROP_RELATIVE,
        STATIC_MAP_SCHEMA,
        STREET_VIEW_SCHEMA,
        SUBMIT_TOOL_SCHEMA,
    ]
    result = ReActResult()
    target_path_str = str(image_path)  # para hash perceptual

    for step in range(max_steps):
        result.steps_used = step + 1
        if verbose:
            print(f"\n--- Step {step + 1}/{max_steps} ---")
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_completion_tokens=3000,
            )
        except Exception as e:
            result.error = f"API call failed at step {step + 1}: {e}"
            if verbose:
                print(f"[ERROR] {e}")
            break

        msg = response.choices[0].message
        assistant_turn: dict[str, Any] = {"role": "assistant"}
        if msg.content:
            assistant_turn["content"] = msg.content
            if verbose:
                print(f"[assistant] {msg.content[:300]}")
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        if msg.content is None and msg.tool_calls is None:
            result.error = "Empty response."
            break
        messages.append(assistant_turn)

        if not msg.tool_calls:
            result.trace.append({"step": step + 1, "type": "final_text_no_submit", "content": msg.content})
            if verbose:
                print("[no tool call] modelo terminó sin submit_answer")
            break

        # Pending images to inject as user message after tool results
        pending_image_injections: list[tuple[str, list[dict]]] = []  # (label, content_parts)

        for tc in msg.tool_calls:
            fname = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            if verbose:
                preview = json.dumps(args, ensure_ascii=False)[:250]
                print(f"  ⚙ {fname}({preview})")

            if fname == "web_search":
                result.web_search_count += 1
                try:
                    sr = web_search(
                        query=args.get("query", ""),
                        max_results=int(args.get("max_results", 5)),
                        excluded_domains=excluded_domains,
                    )
                    if verbose:
                        print(f"     → {len(sr.results)} results (filtered {sr.blocked_count}/{sr.total_raw})")
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(sr.to_dict(), ensure_ascii=False)[:8000]})
                    result.trace.append({"step": step + 1, "type": "web_search", "query": args.get("query"), "result_count": len(sr.results), "blocked": sr.blocked_count})
                except Exception as e:
                    err = f"web_search error: {e}"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": err})
                    result.trace.append({"step": step + 1, "type": "web_search_error", "error": str(e)})

            elif fname == "fetch_url":
                result.fetch_url_count += 1
                url = args.get("url", "")
                try:
                    fp = fetch_url(url, include_images=False, excluded_domains=excluded_domains)
                    if verbose:
                        size = len(fp.text)
                        print(f"     → status={fp.status_code} text={size}c err={fp.error}")
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(fp.to_dict(include_images_b64=False), ensure_ascii=False)[:10000]})
                    result.trace.append({"step": step + 1, "type": "fetch_url", "url": url, "text_len": len(fp.text), "error": fp.error})
                except Exception as e:
                    err = f"fetch_url error: {e}"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": err})
                    result.trace.append({"step": step + 1, "type": "fetch_url_error", "url": url, "error": str(e)})

            elif fname == "fetch_url_with_images":
                result.fetch_url_count += 1
                url = args.get("url", "")
                try:
                    fp = fetch_url(
                        url,
                        include_images=True,
                        target_image_path=target_path_str,
                        excluded_domains=excluded_domains,
                    )
                    n_imgs = len(fp.images)
                    n_target = sum(1 for i in fp.images if i.is_likely_target)
                    result.target_match_count += n_target
                    if verbose:
                        print(f"     → status={fp.status_code} text={len(fp.text)}c imgs={n_imgs} target_match={n_target}")
                    # Tool result: solo metadata + texto, NO base64. Para target matches
                    # ocultamos también la URL — el dominio puede ser shortcut (#24 review Codex).
                    summary = fp.to_dict(include_images_b64=False)
                    if "images" in summary:
                        summary["images"] = [
                            ({"hidden_reason": "hash_match_target", "hamming_distance": im_d.get("hamming_distance")}
                             if im_d.get("is_likely_target") else
                             {"url": im_d.get("url"), "hamming_distance": im_d.get("hamming_distance")})
                            for im_d in summary["images"]
                        ]
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(summary, ensure_ascii=False)[:10000]})
                    result.trace.append({"step": step + 1, "type": "fetch_url_with_images", "url": url, "n_images": n_imgs, "target_match": n_target})

                    # Build user message with images for next turn.
                    # Hard reject images where hash perceptual matches target (#21 / #24 deuda):
                    # listamos metadata pero NO inyectamos los bytes. La política canon es
                    # "descartar" (PROJECT.md), no "flaggear" como el comportamiento previo.
                    if fp.images:
                        visible = [im for im in fp.images if not im.is_likely_target]
                        hidden = [im for im in fp.images if im.is_likely_target]
                        parts: list[dict] = [{"type": "text", "text": f"[Imágenes encontradas en {url}. Mostradas en orden. {len(hidden)} imágenes ocultadas porque coinciden visualmente con la foto target (hash perceptual match — no son evidencia válida)]"}]
                        for im in visible:
                            label = f"[img: hamming={im.hamming_distance}]"
                            parts.append({"type": "text", "text": label})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im.base64_jpeg}"}})
                        if visible:
                            pending_image_injections.append(("fetch_url_images", parts))
                except Exception as e:
                    err = f"fetch_url_with_images error: {e}"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": err})
                    result.trace.append({"step": step + 1, "type": "fetch_url_with_images_error", "url": url, "error": str(e)})

            elif fname == "image_search":
                result.image_search_count += 1
                try:
                    isr = image_search(
                        query=args.get("query", ""),
                        max_results=int(args.get("max_results", 3)),
                        target_image_path=target_path_str,
                        excluded_domains=excluded_domains,
                    )
                    result.target_match_count += isr.target_match_count
                    if verbose:
                        print(f"     → {len(isr.images)} imgs target_match={isr.target_match_count} blocked_dom={isr.blocked_domain_count} dl_failed={isr.download_failed_count}")
                    # Tool result: metadata only. Para target matches ocultamos URL también
                    # — el dominio del match puede ser shortcut por sí solo (#24 review Codex).
                    def _redact(im) -> dict:
                        if im.is_likely_target:
                            return {"hidden_reason": "hash_match_target", "hamming_distance": im.hamming_distance}
                        return im.metadata_only()
                    meta = {
                        "query": isr.query,
                        "n_images": len(isr.images),
                        "target_match_count": isr.target_match_count,
                        "blocked_domain_count": isr.blocked_domain_count,
                        "images_metadata": [_redact(im) for im in isr.images],
                    }
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(meta, ensure_ascii=False)})
                    result.trace.append({"step": step + 1, "type": "image_search", "query": args.get("query"), "n_images": len(isr.images), "target_match": isr.target_match_count})

                    # Inject images as user message in next turn.
                    # Hard reject images where hash perceptual matches target (#21 / #24 deuda):
                    # listamos metadata pero NO inyectamos bytes — no son evidencia válida.
                    if isr.images:
                        visible = [im for im in isr.images if not im.is_likely_target]
                        hidden = [im for im in isr.images if im.is_likely_target]
                        parts = [{"type": "text", "text": f"[Imágenes encontradas para image_search '{isr.query}'. {len(hidden)} imágenes ocultadas porque coinciden visualmente con la foto target (hash perceptual match)]"}]
                        for im in visible:
                            label = f"[img: hamming={im.hamming_distance}, source={im.url[:80]}]"
                            parts.append({"type": "text", "text": label})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im.base64_jpeg}"}})
                        if visible:
                            pending_image_injections.append(("image_search", parts))
                except Exception as e:
                    err = f"image_search error: {e}"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": err})
                    result.trace.append({"step": step + 1, "type": "image_search_error", "error": str(e)})

            elif fname in ("geocode", "reverse_geocode"):
                result.geocode_count += 1
                try:
                    if fname == "geocode":
                        results_list = geocode(
                            query=args.get("query", ""),
                            max_results=int(args.get("max_results", 3)),
                            language=args.get("language", "en"),
                        )
                        out = [r.to_dict() for r in results_list]
                        if verbose:
                            print(f"     → {len(results_list)} results")
                    else:
                        gr = reverse_geocode(float(args["lat"]), float(args["lon"]), zoom=int(args.get("zoom", 18)))
                        out = gr.to_dict() if gr else None
                        if verbose:
                            print(f"     → {gr.display_name[:80] if gr else 'no result'}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, ensure_ascii=False)[:4000]})
                    result.trace.append({"step": step + 1, "type": fname, "args": args, "n_results": len(out) if isinstance(out, list) else (1 if out else 0)})
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"{fname} error: {e}"})
                    result.trace.append({"step": step + 1, "type": f"{fname}_error", "error": str(e)})

            elif fname == "historical_query":
                result.historical_query_count += 1
                try:
                    hq = historical_query(
                        south=float(args["south"]),
                        west=float(args["west"]),
                        north=float(args["north"]),
                        east=float(args["east"]),
                        preset=args.get("preset"),
                        year=args.get("year"),
                        max_features=int(args.get("max_features", 30)),
                    )
                    if verbose:
                        print(f"     → {hq.n_features} features (truncated={hq.truncated}, err={hq.error})")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(hq.to_dict(), ensure_ascii=False)[:8000]})
                    result.trace.append({"step": step + 1, "type": "historical_query", "args": args, "n_features": hq.n_features})
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"historical_query error: {e}"})
                    result.trace.append({"step": step + 1, "type": "historical_query_error", "error": str(e)})

            elif fname in ("crop_image", "crop_image_relative"):
                result.crop_count += 1
                try:
                    if fname == "crop_image":
                        cr = crop_image(
                            image_path=target_path_str,
                            x=int(args["x"]),
                            y=int(args["y"]),
                            width=int(args["width"]),
                            height=int(args["height"]),
                        )
                    else:
                        cr = crop_image_relative(image_path=target_path_str, region=args["region"])
                    if verbose:
                        print(f"     → cropped {cr.width}x{cr.height} from region={cr.region}")
                    summary = {"width": cr.width, "height": cr.height, "region": cr.region, "note": cr.note}
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(summary, ensure_ascii=False)})
                    # Inyectar imagen en next user message
                    parts = [
                        {"type": "text", "text": f"[Crop de la foto target. region={cr.region}, mostrado a {cr.width}x{cr.height}]"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{cr.base64_jpeg}"}},
                    ]
                    pending_image_injections.append(("crop", parts))
                    result.trace.append({"step": step + 1, "type": fname, "region": cr.region})
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"{fname} error: {e}"})
                    result.trace.append({"step": step + 1, "type": f"{fname}_error", "error": str(e)})

            elif fname == "static_map":
                result.static_map_count += 1
                try:
                    sm = static_map(
                        lat=float(args["lat"]),
                        lon=float(args["lon"]),
                        zoom=int(args.get("zoom", 14)),
                        map_type=args.get("map_type", "roadmap"),
                    )
                    if isinstance(sm, StaticMapError):
                        if verbose:
                            print(f"     → static_map error: {sm.error}")
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": sm.error, "detail": sm.detail})})
                        result.trace.append({"step": step + 1, "type": "static_map_error", "error": sm.error})
                    else:
                        if verbose:
                            print(f"     → static_map ok type={sm.type}")
                        meta = {"lat": sm.lat, "lon": sm.lon, "zoom": sm.zoom, "type": sm.type, "size": list(sm.size), "note": sm.note}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(meta, ensure_ascii=False)})
                        parts = [
                            {"type": "text", "text": f"[Static map {sm.type} en ({sm.lat}, {sm.lon}) zoom {sm.zoom}]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sm.base64_jpeg}"}},
                        ]
                        pending_image_injections.append(("static_map", parts))
                        result.trace.append({"step": step + 1, "type": "static_map", "args": args})
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"static_map error: {e}"})
                    result.trace.append({"step": step + 1, "type": "static_map_error", "error": str(e)})

            elif fname == "street_view":
                result.street_view_count += 1
                try:
                    sv = street_view(
                        lat=float(args["lat"]),
                        lon=float(args["lon"]),
                        heading=float(args.get("heading", 0)),
                        pitch=float(args.get("pitch", 0)),
                        fov=int(args.get("fov", 90)),
                        contact_sheet=bool(args.get("contact_sheet", False)),
                    )
                    if isinstance(sv, StreetViewError):
                        if verbose:
                            print(f"     → street_view error: {sv.error}")
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": sv.error, "detail": sv.detail})})
                        result.trace.append({"step": step + 1, "type": "street_view_error", "error": sv.error})
                    else:
                        n_imgs = len(sv.images)
                        if verbose:
                            print(f"     → street_view ok n_images={n_imgs} pano={sv.panorama_id} dist={sv.distance_to_pano_m:.0f}m" if sv.distance_to_pano_m else f"     → street_view ok n_images={n_imgs}")
                        meta = {
                            "lat": sv.lat, "lon": sv.lon,
                            "n_images": n_imgs,
                            "headings": [im.heading for im in sv.images],
                            "panorama_id": sv.panorama_id,
                            "pano_date": sv.pano_date,
                            "actual_lat": sv.actual_lat,
                            "actual_lon": sv.actual_lon,
                            "distance_to_pano_m": sv.distance_to_pano_m,
                            "note": sv.note,
                        }
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(meta, ensure_ascii=False)})
                        parts = [{"type": "text", "text": f"[Street View en ({sv.lat}, {sv.lon}). {sv.note or ''}]"}]
                        for im in sv.images:
                            parts.append({"type": "text", "text": f"[heading={im.heading} pitch={im.pitch} fov={im.fov}]"})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im.base64_jpeg}"}})
                        pending_image_injections.append(("street_view", parts))
                        result.trace.append({"step": step + 1, "type": "street_view", "args": args, "n_images": n_imgs})
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"street_view error: {e}"})
                    result.trace.append({"step": step + 1, "type": "street_view_error", "error": str(e)})

            elif fname == "submit_answer":
                result.final_answer = args
                result.submit_called = True
                if verbose:
                    print(f"     → SUBMIT: {args.get('location', '?')[:60]} ({args.get('lat')}, {args.get('lon')})")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "answer_submitted"})
                result.trace.append({"step": step + 1, "type": "submit", "answer": args})

            else:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Unknown tool: {fname}"})

        # After all tool results are appended, inject pending image messages
        for label, parts in pending_image_injections:
            messages.append({"role": "user", "content": parts})

        if result.submit_called:
            break

    return result
