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

from ..tools.web_search import web_search, TOOL_SCHEMA as WEB_SEARCH_SCHEMA
from ..tools.fetch_url import fetch_url, TOOL_SCHEMA_TEXT as FETCH_URL_SCHEMA, TOOL_SCHEMA_WITH_IMAGES as FETCH_URL_IMG_SCHEMA
from ..tools.image_search import image_search, TOOL_SCHEMA as IMAGE_SEARCH_SCHEMA
from ..tools.geocode import geocode, reverse_geocode, TOOL_SCHEMA_GEOCODE, TOOL_SCHEMA_REVERSE
from ..tools.historical_query import historical_query, TOOL_SCHEMA as HISTORICAL_QUERY_SCHEMA
from ..tools.crop_image import crop_image, crop_image_relative, TOOL_SCHEMA_CROP, TOOL_SCHEMA_CROP_RELATIVE, CropResult
from ..tools.static_map import static_map, StaticMapResult, StaticMapError, TOOL_SCHEMA as STATIC_MAP_SCHEMA
from ..tools.street_view import street_view, StreetViewResult, StreetViewError, TOOL_SCHEMA as STREET_VIEW_SCHEMA


SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": (
            "Submit tu respuesta final. Llamá esta función cuando tengas suficiente "
            "información para dar coordenadas. Si no podés precisar, devolvé la mejor "
            "estimación con confidence='baja'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "Descripción humana del lugar."},
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "year": {"type": "string", "description": "Año o rango (ej '1965', '1960-1970')."},
                "reasoning": {"type": "string", "description": "Resumen breve del razonamiento."},
                "confidence": {"type": "string", "enum": ["alta", "media", "baja"]},
            },
            "required": ["location", "lat", "lon", "reasoning", "confidence"],
        },
    },
}


SYSTEM_PROMPT = """Sos un detective geográfico investigativo. Recibís una fotografía histórica y tu tarea es descubrir DÓNDE fue tomada (coords lat/lon) y CUÁNDO (año aproximado).

## Tus herramientas

### Investigación textual
1. `web_search(query)` — buscar en la web. Recibís URLs + snippets.
2. `fetch_url(url)` — entrar a una página específica y leer su texto completo.

### Investigación visual
3. `fetch_url_with_images(url)` — entrar a una página y ver sus imágenes embebidas.
4. `image_search(query)` — buscar imágenes en la web (similar a Google Images).
5. `crop_image(x, y, w, h)` o `crop_image_relative(region)` — hacer ZOOM en una región específica de la foto target. Útil para detalles chiquitos (carteles, números, marcas) que no se leen al ver la foto entera.

### Geo
6. `geocode(query)` — convertir nombre/dirección a coords. Ej: "Plaza Mayor Madrid" → (40.41, -3.71).
7. `reverse_geocode(lat, lon)` — convertir coords a nombre/dirección.
8. `historical_query(bbox, year, preset)` — buscar features históricos (edificios, iglesias, calles) en una zona, OPCIONALMENTE filtrados por año. Pieza ÚNICA del proyecto. Ej: "qué iglesias había en Buenos Aires en 1900".
9. `static_map(lat, lon, zoom, map_type)` — pedir imagen de mapa (roadmap/satellite/terrain/hybrid). type=terrain muestra relieve 2D con curvas de nivel — útil para identificar montañas/valles.
10. `street_view(lat, lon, heading, pitch)` — pedir foto de Street View desde un punto y ángulo. Útil para verificar visualmente si un lugar moderno coincide con la foto histórica.

### Final
11. `submit_answer(...)` — devolver respuesta.

## Estrategia recomendada

1. **Examiná la foto** cuidadosamente. Identificá pistas: arquitectura, vegetación, vehículos, vestimenta, idiomas, modelos, iluminación. Si hay un detalle chiquito (cartel, número), hacé `crop_image` para verlo mejor.
2. **Hipótesis**: 2-3 candidatos sobre dónde puede ser.
3. **Buscá texto** con `web_search` para validar/discriminar hipótesis. Ej: identificar arquitectura, idioma de carteles, época.
4. **Profundizá** con `fetch_url` en URLs prometedores.
5. **Compará visualmente**: `image_search` para imágenes generales del estilo, `street_view` para vistas modernas de un lugar específico, `static_map(terrain)` para verificar relieve.
6. **Verificá ubicación específica** con `geocode` (nombre→coords) o `reverse_geocode` (coords→nombre).
7. **Si es foto antigua**: `historical_query` para saber qué edificios existían en zona X en año Y.
8. **Refiná** hipótesis con cada paso. Pivotá si evidencia contradice.
9. **Submit** cuando tengas confianza razonable.

## Filtros anti-shortcut

- Los dominios de archivos públicos (pastvu.com, wikimedia, flickr, vk, yandex, lens, tineye) están BLOQUEADOS automáticamente.
- Las imágenes que devuelven `image_search` o `fetch_url_with_images` vienen con flag `is_likely_target`. Si =true, esa imagen es la foto objetivo o casi-igual — NO cuenta como evidencia válida. Pivotá.

## Reglas

- Sé EFICIENTE: cada tool call cuesta. Mejor 5 calls específicas que 15 vagas.
- `image_search`, `fetch_url_with_images`, `static_map`, `street_view` son más caros en tokens — usalos cuando vale la pena.
- `historical_query` es free (no Tavily) y útil para fotos antiguas.
- Si después de varias búsquedas no podés precisar, devolvé tu mejor estimación con confidence='baja'.
- Pensás y respondés en español. Las queries pueden estar en cualquier idioma."""


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
) -> ReActResult:
    """Correr el agente ReAct con todas las tools."""
    client = OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
    )
    image_path = Path(image_path)

    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt + "\n\n[Foto target abajo]"},
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
                    sr = web_search(query=args.get("query", ""), max_results=int(args.get("max_results", 5)))
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
                    fp = fetch_url(url, include_images=False)
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
                    fp = fetch_url(url, include_images=True, target_image_path=target_path_str)
                    n_imgs = len(fp.images)
                    n_target = sum(1 for i in fp.images if i.is_likely_target)
                    result.target_match_count += n_target
                    if verbose:
                        print(f"     → status={fp.status_code} text={len(fp.text)}c imgs={n_imgs} target_match={n_target}")
                    # Tool result: solo metadata + texto, NO base64.
                    summary = fp.to_dict(include_images_b64=False)
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(summary, ensure_ascii=False)[:10000]})
                    result.trace.append({"step": step + 1, "type": "fetch_url_with_images", "url": url, "n_images": n_imgs, "target_match": n_target})

                    # Build user message with images for next turn
                    if fp.images:
                        parts: list[dict] = [{"type": "text", "text": f"[Imágenes encontradas en {url}. Mostradas en orden. is_likely_target indica si una imagen coincide visualmente con la foto target]"}]
                        for im in fp.images:
                            label = f"[img: hamming={im.hamming_distance}, is_likely_target={im.is_likely_target}]"
                            parts.append({"type": "text", "text": label})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im.base64_jpeg}"}})
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
                    )
                    result.target_match_count += isr.target_match_count
                    if verbose:
                        print(f"     → {len(isr.images)} imgs target_match={isr.target_match_count} blocked_dom={isr.blocked_domain_count} dl_failed={isr.download_failed_count}")
                    # Tool result: metadata only.
                    meta = {
                        "query": isr.query,
                        "n_images": len(isr.images),
                        "target_match_count": isr.target_match_count,
                        "blocked_domain_count": isr.blocked_domain_count,
                        "images_metadata": [im.metadata_only() for im in isr.images],
                    }
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": json.dumps(meta, ensure_ascii=False)})
                    result.trace.append({"step": step + 1, "type": "image_search", "query": args.get("query"), "n_images": len(isr.images), "target_match": isr.target_match_count})

                    # Inject images as user message in next turn
                    if isr.images:
                        parts = [{"type": "text", "text": f"[Imágenes encontradas para image_search '{isr.query}'. is_likely_target=true significa coincide casi-exacto con la foto target — pivotá si aparece]"}]
                        for im in isr.images:
                            label = f"[img: hamming={im.hamming_distance}, is_likely_target={im.is_likely_target}, source={im.url[:80]}]"
                            parts.append({"type": "text", "text": label})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{im.base64_jpeg}"}})
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
                    )
                    if isinstance(sv, StreetViewError):
                        if verbose:
                            print(f"     → street_view error: {sv.error}")
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": sv.error, "detail": sv.detail})})
                        result.trace.append({"step": step + 1, "type": "street_view_error", "error": sv.error})
                    else:
                        if verbose:
                            print(f"     → street_view ok pano={sv.panorama_id}")
                        meta = {"lat": sv.lat, "lon": sv.lon, "heading": sv.heading, "pitch": sv.pitch, "panorama_id": sv.panorama_id, "actual_lat": sv.actual_lat, "actual_lon": sv.actual_lon, "note": sv.note}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(meta, ensure_ascii=False)})
                        parts = [
                            {"type": "text", "text": f"[Street View en ({sv.lat}, {sv.lon}) heading={sv.heading} pitch={sv.pitch}]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sv.base64_jpeg}"}},
                        ]
                        pending_image_injections.append(("street_view", parts))
                        result.trace.append({"step": step + 1, "type": "street_view", "args": args})
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
