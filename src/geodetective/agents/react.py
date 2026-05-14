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

from ..corpus.blacklist import compute_excluded_domains
from ..llm_adapter import complete as llm_complete, get_provider
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
                "lat": {"type": "number", "minimum": -90, "maximum": 90, "description": "Latitud decimal en grados, rango [-90, 90]."},
                "lon": {"type": "number", "minimum": -180, "maximum": 180, "description": "Longitud decimal en grados, rango [-180, 180]."},
                "year": {"type": "string", "description": "Año o rango (ej '1965', '1960-1970'). Si realmente no podés inferir el año, usá 'unknown' y explicá en uncertainty_reason."},
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
            "required": ["location", "lat", "lon", "year", "reasoning", "confidence"],
        },
    },
}


def _validate_submit(args: dict) -> tuple[bool, Optional[str]]:
    """Valida que el submit_answer sea aceptable. Devuelve (ok, error_msg).

    Si error_msg, se le devuelve al modelo y se le pide retry.
    """
    required = ["location", "lat", "lon", "year", "reasoning", "confidence"]
    missing = [k for k in required if k not in args or args[k] in (None, "")]
    if missing:
        return False, f"Faltan campos requeridos en submit_answer: {missing}. Por favor llamá submit_answer de nuevo con TODOS los campos."
    # Type/range check
    try:
        lat = float(args["lat"])
        lon = float(args["lon"])
    except (ValueError, TypeError):
        return False, f"lat/lon deben ser numéricos. Recibidos lat={args.get('lat')!r} lon={args.get('lon')!r}. Re-submit con números válidos."
    if not (-90.0 <= lat <= 90.0):
        return False, f"lat={lat} fuera de rango [-90, 90]. Re-submit con coords válidas."
    if not (-180.0 <= lon <= 180.0):
        return False, f"lon={lon} fuera de rango [-180, 180]. Re-submit con coords válidas."
    conf = str(args.get("confidence", "")).strip().lower()
    if conf not in {"alta", "media", "baja"}:
        return False, f"confidence='{conf}' inválida. Tiene que ser exactamente 'alta', 'media' o 'baja'. Re-submit."
    return True, None


SYSTEM_PROMPT = """Recibís una fotografía. Tu tarea es descubrir DÓNDE fue tomada (coords lat/lon) y CUÁNDO (año aproximado), y devolver la respuesta vía `submit_answer`.

## Herramientas disponibles

Para cada tool: qué hace mecánicamente + qué tipo de información te aporta. NO te decimos cuándo usar cada una — vos decidís según el caso.

**`web_search(query, max_results)`**
Busca texto en la web vía Tavily. Devuelve resultados con `url`, `title`, `content` (snippet ~1000-3000 chars en modo advanced).
*Aporta*: información textual disponible en internet — descripciones de lugares, fechas de eventos, biografías, archivos digitalizados con catalog text, blogs, papers académicos. Lo que la web "dice" sobre una consulta.

**`fetch_url(url)`**
Baja una página web específica. Devuelve `title` + `text` (hasta 12000 chars del contenido principal).
*Aporta*: el contenido completo de una página identificada por URL.

**`fetch_url_with_images(url)`**
Igual que `fetch_url` pero además baja hasta 5 imágenes embebidas. Las que NO coincidan visualmente con la foto target se muestran en el siguiente turn con metadata; las que sí coincidan se cuentan pero no se exponen.
*Aporta*: además del texto, las imágenes ilustrativas de la página — fotos de archivo, mapas, fachadas, retratos.

**`image_search(query, max_results)`**
Busca imágenes en la web (estilo Google Images). Las imágenes vienen en el siguiente turn con `url` de origen y `hamming_distance`. Las que coincidan visualmente con la foto target se cuentan pero no se exponen.
*Aporta*: colección de imágenes que internet asocia con tu query — fotos de tipos de edificio, fachadas, plazas, vehículos de época, vestimenta, vegetación, paisajes.

**`crop_image(x, y, width, height)` / `crop_image_relative(region)`**
Recorta una región de la foto target. La región se muestra ampliada en el siguiente turn. `crop_image_relative` acepta regiones nombradas: `top_left`, `top_right`, `top_center`, `bottom_left`, `bottom_right`, `bottom_center`, `middle`, `center`, `left_half`, `right_half`, `top_half`, `bottom_half`.
*Aporta*: detalle visual a alta resolución de una zona de la foto target — texto en carteles, fachadas, vehículos, vestimenta, vegetación, postes, idiomas. Detalles que se pierden al ver la foto entera.

**`geocode(query, language)`**
Convierte un nombre o dirección a coords vía Nominatim (OSM). Ej: "Plaza Mayor Madrid" → coords + dirección estructurada + tipo (residential/city/street/etc).
*Aporta*: dos cosas — (1) coordenadas precisas de un lugar nombrado, y (2) confirmación de que ese lugar existe en OSM. Es decir, valida la existencia de hipótesis tipo "hay un X en Y".

**`reverse_geocode(lat, lon, zoom)`**
Convierte coords a dirección. `zoom` controla detalle: 3=país, 10=ciudad, 17=edificio, 18=calle.
*Aporta*: el "qué hay" en un punto geográfico — nombre administrativo, calle, edificio.

**`historical_query(south, west, north, east, preset, year, require_dated, max_features)`**
Busca features de OpenHistoricalMap en un bounding box. `preset`: `buildings`, `churches`, `schools`, `factories`, `railway_stations`, `monuments`, `houses`, `all_named`. Si `year` está dado, filtra features que existían ese año. Cada feature trae `temporal_confidence` (`high` si tiene `start_date`/`end_date` confirmados, `low` si no). OHM cobertura DESIGUAL: ausencia de resultados no prueba ausencia histórica.
*Aporta*: información temporal-espacial sobre estructuras del pasado. Qué iglesias / fábricas / estaciones / monumentos / casas registra OpenHistoricalMap en una zona, en un año específico, con sus coords y fechas de construcción/demolición. Permite saber qué estaba físicamente en un lugar y momento.

**`static_map(lat, lon, zoom, map_type)`**
Pide imagen de mapa de Google Maps en las coords dadas. `map_type`: `roadmap` (calles), `satellite` (foto aérea actual), `terrain` (relieve 2D con curvas de nivel), `hybrid` (sat+calles).
*Aporta*: vista cenital del entorno geográfico de un punto cualquiera del planeta — relieve, ríos, layout urbano, costas, montañas, vegetación. Cada `map_type` revela una dimensión distinta del mismo lugar (la geometría del callejero es distinta de la topografía real del satélite).

**`street_view(lat, lon, heading, pitch, fov, contact_sheet)`**
Imagen(es) actuales de Google Street View en coords arbitrarias. Modo single (1 imagen al heading dado) o `contact_sheet=true` (4 imágenes en N/E/S/W). Devuelve fecha del panorama y distancia entre coords pedidas y panorama real. Error `no_coverage` si no hay panorama disponible.
*Aporta*: la realidad fotográfica observable HOY desde cualquier punto del planeta — fachadas, calles, perspectivas, paisaje. Cobertura global con huecos (rural, países con regulaciones).

**`submit_answer(...)`**
Devolver respuesta final. Campos: `location`, `lat`, `lon`, `year`, `reasoning`, `confidence` (alta/media/baja), `visual_clues`, `external_evidence`, `rejected_alternatives`, `verification_checks`, `uncertainty_reason`.

## Filtros automáticos (no podés desactivarlos)

- En `web_search`, `fetch_url`, `fetch_url_with_images`, `image_search` se bloquean automáticamente algunos dominios para evitar shortcuts: reverse image search engines, agregadores masivos con metadata estructurada (caption + geotag), hosting/sharing platforms con propensión a re-publicar archivos, y la fuente específica de la foto que estás investigando. La lista exacta depende de cada foto; no necesitás conocerla.
- Cuando una imagen tiene hash perceptual coincidente con la foto target, la ocultamos: te informamos su cantidad pero no te mostramos los bytes (la foto objetivo no es evidencia sobre dónde fue tomada).

## Idioma

Las queries pueden estar en cualquier idioma. Tus respuestas y razonamiento, en español.

## Razonamiento visible (formato ReAct)

Antes de cada turn de acciones, escribí en TEXTO breve (1-3 oraciones):
1. Qué observás ahora mismo de la foto target o de las observaciones previas.
2. Qué hipótesis estás considerando (idealmente >1, ranqueadas por plausibilidad).
3. Qué esperás conseguir de la(s) próxima(s) acción(es).

Ese texto va como `content` de tu respuesta, separado de los `tool_calls`. Es
para que un investigador humano pueda seguir tu proceso paso a paso — no es
input para las tools.

Si en algún turn realmente no tenés nada nuevo que razonar, podés saltearlo."""


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
    # Estado terminal explícito (C14). Valores:
    #   "submitted"            - el agente llamó submit_answer válido.
    #   "max_steps_no_submit"  - terminó max_steps sin submit.
    #   "no_submit_early_text" - emitió texto sin tool_calls (2 veces seguidas).
    #   "empty_response"       - msg.content y msg.tool_calls ambos None.
    #   "api_error"            - excepción en client.chat.completions.create.
    #   "invalid_submit"       - submit_answer rechazado por validación 3 veces.
    terminal_state: Optional[str] = None
    submit_retry_count: int = 0  # cuántas veces submit_answer fue rechazado por validación
    text_only_attempts: int = 0  # cuántas veces el modelo emitió content sin tool_calls


def run_react_agent(
    image_path: Path,
    model: str = "gpt-5.4",
    max_steps: int = 50,
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
    # LLM provider determinado por modelo (vía llm_adapter.MODEL_SPECS).
    # OpenAI-compatible → passthrough cliente openai; Anthropic → /anthropic/v1/messages.
    llm_provider = get_provider(model)
    if verbose:
        print(f"[run_react_agent] model={model} provider={llm_provider}")
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

    budget_info = (
        f"\n\nBudget: tenés {max_steps} turns disponibles para investigar. "
        f"Usá los que necesites para razonar bien, pero asegurate de invocar "
        f"`submit_answer` con tu mejor hipótesis ANTES de quedarte sin budget. "
        f"Cuando te queden pocos turns te vamos a recordar."
    )
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt + f"\n\nFoto target: {img_w}x{img_h} pixels (ancho x alto). Crop coordinates deben estar dentro de ese rango." + budget_info + "\n\n[Foto target abajo]"},
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
        remaining = max_steps - step
        if verbose:
            print(f"\n--- Step {step + 1}/{max_steps} ---")
        # Soft budget reminders (no son sesgo de tools, solo budget)
        if remaining == 1 and not result.submit_called:
            messages.append({
                "role": "user",
                "content": (
                    "Este es tu ÚLTIMO turn. Llamá `submit_answer` AHORA con tu mejor hipótesis "
                    "(incluso si la confidence es baja). Si realmente no podés geolocalizar la foto, "
                    "submit con confidence='baja' y explicá el motivo en uncertainty_reason."
                ),
            })
        elif remaining in (5, 10) and not result.submit_called:
            messages.append({
                "role": "user",
                "content": f"[Recordatorio: te quedan {remaining} turns. Considerá ir cerrando con `submit_answer`.]",
            })
        try:
            # max_completion_tokens=8000: Claude con thinking mode puede gastar ~2-3K
            # tokens en thinking antes de emitir tool_use/text. Con 3000 algunos
            # turnos quedaban en empty_response (claude-sonnet-4-6 E009 Basel + Tomsk).
            response = llm_complete(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_completion_tokens=8000,
                timeout=180.0,
            )
        except Exception as e:
            result.error = f"API call failed at step {step + 1}: {e}"
            result.terminal_state = "api_error"
            if verbose:
                print(f"[ERROR] {e}")
            break

        msg = response.choices[0].message
        # Anthropic puede emitir bloques 'thinking' separados del content de texto.
        # Los recogemos como evento aparte en el trace para que el annotator los vea.
        anth_thinking = getattr(msg, "thinking_blocks", None) or []
        for tk in anth_thinking:
            if tk:
                result.trace.append({"step": step + 1, "type": "thinking_block", "content": tk})
                if verbose:
                    print(f"[thinking] {tk[:300]}")
        assistant_turn: dict[str, Any] = {"role": "assistant"}
        if msg.content:
            assistant_turn["content"] = msg.content
            # Guardamos el texto que el modelo emite junto con sus tool_calls
            # (cuando lo hay) para inspección de trayectorias. Algunos modelos
            # (tipo gpt-5.4) rara vez generan texto explícito en pasos intermedios,
            # otros sí — esto nos deja ver eso cuando ocurre.
            result.trace.append({"step": step + 1, "type": "thinking", "content": msg.content})
            if verbose:
                print(f"[assistant] {msg.content[:300]}")
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        if msg.content is None and msg.tool_calls is None:
            # Capturar stop_reason / finish_reason para diagnosticar (max_tokens?
            # refusal? end_turn vacío? cf claude-sonnet-4-6 Basel/Tomsk E009).
            finish = getattr(msg, "finish_reason", None) or getattr(response.choices[0], "finish_reason", None)
            n_thinking = len(getattr(msg, "thinking_blocks", []) or [])
            result.error = f"Empty response. finish_reason={finish!r} thinking_blocks={n_thinking}"
            result.terminal_state = "empty_response"
            result.trace.append({
                "step": step + 1, "type": "empty_response_diagnosis",
                "finish_reason": finish, "thinking_blocks_count": n_thinking,
            })
            break
        messages.append(assistant_turn)

        # Bug #3 (Kimi-style): modelo emite intención como TEXTO en vez de tool_call.
        # En lugar de cortar al primer hit, le pedimos explícitamente que invoque la tool.
        # Si lo hace 2 veces seguidas → terminamos.
        if not msg.tool_calls:
            result.text_only_attempts += 1
            result.trace.append({
                "step": step + 1, "type": "no_tool_call_in_response",
                "content": msg.content, "attempt": result.text_only_attempts,
            })
            if result.text_only_attempts >= 2:
                result.terminal_state = "no_submit_early_text"
                if verbose:
                    print("[break] modelo emitió texto sin tool_call 2 veces seguidas")
                break
            # Primera vez: pedirle que llame la tool explícitamente.
            messages.append({
                "role": "user",
                "content": (
                    "Tu respuesta anterior describió una acción en TEXTO, pero NO invocaste "
                    "ninguna tool (function call). Por favor invocá la tool ahora usando function "
                    "calling. Si querés terminar la investigación, invocá `submit_answer` con tu "
                    "mejor hipótesis."
                ),
            })
            if verbose:
                print("[corrective] modelo no invocó tool, le pido retry")
            continue
        # Si llegamos acá, hubo tool_calls — reset contador.
        result.text_only_attempts = 0

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
                    payload = json.dumps(sr.to_dict(), ensure_ascii=False)[:8000]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    top_results = [
                        {"title": r.title, "url": r.url, "snippet": (r.content or "")[:400]}
                        for r in sr.results[:3]
                    ]
                    result.trace.append({
                        "step": step + 1, "type": "web_search",
                        "query": args.get("query"),
                        "result_count": len(sr.results),
                        "blocked": sr.blocked_count,
                        "top_results": top_results,
                        "payload_to_model": payload[:3000],  # exact tool message content que el modelo ve
                        "payload_full_len": len(payload),
                    })
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
                    payload = json.dumps(fp.to_dict(include_images_b64=False), ensure_ascii=False)[:10000]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    result.trace.append({
                        "step": step + 1, "type": "fetch_url",
                        "url": url, "text_len": len(fp.text), "error": fp.error,
                        "title": fp.title, "text_snippet": (fp.text or "")[:500],
                        "payload_to_model": payload[:3000],
                        "payload_full_len": len(payload),
                    })
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
                    payload = json.dumps(summary, ensure_ascii=False)[:10000]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    visible_imgs = [
                        {"url": im.url, "hamming_distance": im.hamming_distance, "base64_jpeg": im.base64_jpeg}
                        for im in fp.images if not im.is_likely_target
                    ]
                    result.trace.append({
                        "step": step + 1, "type": "fetch_url_with_images",
                        "url": url, "n_images": n_imgs, "target_match": n_target,
                        "title": fp.title, "text_snippet": (fp.text or "")[:500],
                        "visible_images": visible_imgs,
                        "payload_to_model": payload[:3000],
                        "payload_full_len": len(payload),
                    })

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
                    payload = json.dumps(meta, ensure_ascii=False)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    visible_imgs = [
                        {"url": im.url, "hamming_distance": im.hamming_distance, "base64_jpeg": im.base64_jpeg}
                        for im in isr.images if not im.is_likely_target
                    ]
                    result.trace.append({
                        "step": step + 1, "type": "image_search",
                        "query": args.get("query"),
                        "n_images": len(isr.images),
                        "target_match": isr.target_match_count,
                        "visible_images": visible_imgs,
                        "payload_to_model": payload[:3000],
                        "payload_full_len": len(payload),
                    })

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
                        # Top 3 resultados con coords + display_name (para visualizar en el mapa)
                        top_results = [
                            {"lat": r.lat, "lon": r.lon, "display_name": r.display_name,
                             "type": r.type}
                            for r in results_list[:3]
                        ]
                    else:
                        gr = reverse_geocode(float(args["lat"]), float(args["lon"]), zoom=int(args.get("zoom", 18)))
                        out = gr.to_dict() if gr else None
                        if verbose:
                            print(f"     → {gr.display_name[:80] if gr else 'no result'}")
                        top_results = (
                            [{"lat": gr.lat, "lon": gr.lon, "display_name": gr.display_name}]
                            if gr else []
                        )
                    payload = json.dumps(out, ensure_ascii=False)[:4000]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    result.trace.append({
                        "step": step + 1, "type": fname,
                        "args": args,
                        "n_results": len(out) if isinstance(out, list) else (1 if out else 0),
                        "top_results": top_results,
                        "payload_to_model": payload[:3000],
                        "payload_full_len": len(payload),
                    })
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
                    payload = json.dumps(hq.to_dict(), ensure_ascii=False)[:8000]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    result.trace.append({
                        "step": step + 1, "type": "historical_query",
                        "args": args, "n_features": hq.n_features,
                        "payload_to_model": payload[:3000],
                        "payload_full_len": len(payload),
                    })
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
                    payload = json.dumps(summary, ensure_ascii=False)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    # Inyectar imagen en next user message
                    parts = [
                        {"type": "text", "text": f"[Crop de la foto target. region={cr.region}, mostrado a {cr.width}x{cr.height}]"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{cr.base64_jpeg}"}},
                    ]
                    pending_image_injections.append(("crop", parts))
                    result.trace.append({
                        "step": step + 1, "type": fname,
                        "region": cr.region,
                        "payload_to_model": payload,
                        "image_inject_kind": "crop",  # tool tambien inyecta imagen al user message next turn
                    })
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
                        payload = json.dumps(meta, ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                        parts = [
                            {"type": "text", "text": f"[Static map {sm.type} en ({sm.lat}, {sm.lon}) zoom {sm.zoom}]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sm.base64_jpeg}"}},
                        ]
                        pending_image_injections.append(("static_map", parts))
                        result.trace.append({
                            "step": step + 1, "type": "static_map",
                            "args": args, "map_type": sm.type, "lat": sm.lat, "lon": sm.lon,
                            "zoom": sm.zoom, "base64_jpeg": sm.base64_jpeg,
                            "payload_to_model": payload,
                            "image_inject_kind": "static_map",
                        })
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
                        payload = json.dumps(meta, ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                        parts = [{"type": "text", "text": f"[Street View en ({sv.lat}, {sv.lon}). {sv.note or ''}]"}]
                        for im in sv.images:
                            parts.append({"type": "text", "text": f"[heading={im.heading} pitch={im.pitch} fov={im.fov}]"})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im.base64_jpeg}"}})
                        pending_image_injections.append(("street_view", parts))
                        result.trace.append({
                            "step": step + 1, "type": "street_view",
                            "args": args, "n_images": n_imgs,
                            "panorama_id": sv.panorama_id,
                            "pano_date": sv.pano_date,
                            "actual_lat": sv.actual_lat,
                            "actual_lon": sv.actual_lon,
                            "distance_to_pano_m": sv.distance_to_pano_m,
                            "images": [{"heading": im.heading, "pitch": im.pitch, "fov": im.fov, "base64_jpeg": im.base64_jpeg} for im in sv.images],
                            "payload_to_model": payload,
                            "image_inject_kind": "street_view",
                        })
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"street_view error: {e}"})
                    result.trace.append({"step": step + 1, "type": "street_view_error", "error": str(e)})

            elif fname == "submit_answer":
                # C4: validar submit_answer antes de aceptarlo.
                ok, err_msg = _validate_submit(args)
                if not ok:
                    result.submit_retry_count += 1
                    if verbose:
                        print(f"     ⚠ SUBMIT inválido (retry {result.submit_retry_count}): {err_msg}")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": f"submit_answer rechazado: {err_msg}",
                    })
                    result.trace.append({
                        "step": step + 1, "type": "submit_rejected",
                        "answer": args, "error": err_msg,
                        "retry_count": result.submit_retry_count,
                    })
                    if result.submit_retry_count >= 3:
                        result.terminal_state = "invalid_submit"
                        result.error = f"submit_answer rechazado 3 veces. Último error: {err_msg}"
                        if verbose:
                            print(f"     [break] submit rechazado 3 veces, abandono")
                        break
                else:
                    result.final_answer = args
                    result.submit_called = True
                    result.terminal_state = "submitted"
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

    # Si salimos del loop sin terminal_state seteado, fue por max_steps.
    if result.terminal_state is None:
        if result.submit_called:
            result.terminal_state = "submitted"
        else:
            result.terminal_state = "max_steps_no_submit"

    return result
