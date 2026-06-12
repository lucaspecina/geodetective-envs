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
import copy
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

from ..corpus.blacklist import compute_excluded_domains
from ..llm_adapter import complete as llm_complete, get_provider
from ..tools.web_search import web_search, TOOL_SCHEMA as WEB_SEARCH_SCHEMA
from ..tools.fetch_url import fetch_url, TOOL_SCHEMA_TEXT as FETCH_URL_SCHEMA, TOOL_SCHEMA_WITH_IMAGES as FETCH_URL_IMG_SCHEMA
from ..tools.image_search import image_search, TOOL_SCHEMA as IMAGE_SEARCH_SCHEMA
from ..tools.geocode import geocode, reverse_geocode, TOOL_SCHEMA_GEOCODE, TOOL_SCHEMA_REVERSE
from ..tools.historical_query import (
    historical_query, historical_query_at,
    TOOL_SCHEMA as HISTORICAL_QUERY_SCHEMA,
    TOOL_SCHEMA_AT as HISTORICAL_QUERY_AT_SCHEMA,
)
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


# === Belief-mode (E016, #47 — research/synthesis/belief_state_redesign.md) ===
# Tool report_belief + evidence_chain en submit. SOLO activos con belief_mode=True
# para que el brazo OFF de la ablation sea idéntico al scaffold canónico.
# El runtime NO puntúa beliefs (el ground truth no entra al loop): el scoring
# es post-hoc con geodetective.eval.belief_scoring.

BELIEF_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_belief",
        "description": (
            "Reportá tu distribución de creencias ACTUAL sobre dónde y cuándo fue tomada la foto. "
            "NO termina la investigación (eso es submit_answer). Llamala después de cada paso en que "
            "la evidencia nueva cambie (o confirme) tu visión del caso. Tu score se calcula con una "
            "proper scoring rule: la estrategia óptima es reportar tu creencia HONESTA — exagerar "
            "confianza te castiga si errás, y reportar más vago de lo que sabés también pierde."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location_belief": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Nombre del candidato (ej 'Lisboa, Portugal')."},
                            "lat": {"type": "number", "minimum": -90, "maximum": 90},
                            "lon": {"type": "number", "minimum": -180, "maximum": 180},
                            "weight": {"type": "number", "minimum": 0, "maximum": 1, "description": "Probabilidad que le asignás a este candidato. Los weights suman ≤ 1; la masa restante es 'no sé todavía'."},
                            "radius_km": {"type": "number", "description": "Incertidumbre espacial alrededor del centro: ~20 = ciudad, ~200 = región chica, ~800 = región grande, 2000+ = continente aprox."},
                        },
                        "required": ["name", "lat", "lon", "weight", "radius_km"],
                    },
                    "description": "Hasta 5 candidatos de ubicación con peso y radio de incertidumbre. Lista vacía = 'todavía no tengo hipótesis localizable'.",
                },
                "year_belief": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "number", "description": "Año inicial del rango."},
                            "to": {"type": "number", "description": "Año final del rango."},
                            "weight": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["from", "to", "weight"],
                    },
                    "description": "Rangos de año candidatos con peso (suman ≤ 1; masa restante = 'no sé').",
                },
                "rationale": {
                    "type": "string",
                    "description": "1-2 oraciones: qué evidencia sostiene este update respecto del reporte anterior.",
                },
            },
            "required": ["location_belief", "year_belief"],
        },
    },
}

BELIEF_PROMPT_SECTION = """## Reporte de creencias (`report_belief`) — OBLIGATORIO en este modo

Además de investigar, tenés que mantener explícito tu estado de creencias. Después de cada paso en que obtengas evidencia relevante (un resultado de tool que cambie o confirme tu visión del caso), llamá `report_belief` con tu distribución ACTUAL:

- `location_belief`: hasta 5 candidatos `{name, lat, lon, weight, radius_km}`. `weight` = probabilidad que le asignás (los weights suman ≤ 1; la masa restante significa "no sé todavía"). `radius_km` = tu incertidumbre espacial (~20 = ciudad, ~200 = región chica, ~800 = región grande, 2000+ = continente).
- `year_belief`: rangos `{from, to, weight}` con la misma lógica.
- `rationale`: 1-2 oraciones con la evidencia que sostiene el update.

Reglas del juego:
- Tu trayectoria de creencias se puntúa con una **proper scoring rule**: reportar tu creencia honesta es la estrategia que maximiza tu score esperado. Sobreconfianza castiga si errás; vaguedad innecesaria también pierde.
- Reportá temprano y seguido: el primer report (después de inspeccionar la foto) puede ser vago (radios grandes, masa sin asignar) — eso es honesto y está bien.
- Si la evidencia contradice tu hipótesis principal, el update tiene que verse en los weights — no la sostengas por inercia.
- `report_belief` NO reemplaza a `submit_answer`: al final igual cerrás con submit."""


def _submit_schema_with_evidence_chain() -> dict:
    """SUBMIT_TOOL_SCHEMA + campo evidence_chain auditable (belief mode only)."""
    schema = copy.deepcopy(SUBMIT_TOOL_SCHEMA)
    schema["function"]["parameters"]["properties"]["evidence_chain"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "Afirmación concreta y verificable que respalda tu respuesta."},
                "step": {"type": "integer", "description": "Step en el que una tool devolvió la evidencia que respalda el claim."},
                "tool": {"type": "string", "description": "Nombre de la tool cuyo resultado respalda el claim."},
            },
            "required": ["claim", "step", "tool"],
        },
        "description": (
            "Cadena de evidencia AUDITABLE: cada claim cita el step y la tool cuyo output real lo respalda. "
            "Un auditor va a verificar cada claim contra el log registrado de esa tool — no cites nada que el log no muestre."
        ),
    }
    return schema


def _validate_belief(args: dict) -> tuple[bool, Optional[str]]:
    """Validación estructural de report_belief. Devuelve (ok, error_msg).

    Solo estructura/rangos — NO evalúa calidad (eso es el scoring post-hoc).
    Listas vacías son válidas ("no sé todavía").
    """
    loc = args.get("location_belief")
    yr = args.get("year_belief")
    if not isinstance(loc, list) or not isinstance(yr, list):
        return False, "location_belief y year_belief deben ser listas (pueden ser vacías si todavía no sabés)."
    if len(loc) > 5:
        return False, f"location_belief tiene {len(loc)} candidatos, máximo 5. Consolidá los menos plausibles en uno regional con radius_km grande."
    total_w = 0.0
    for i, c in enumerate(loc):
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
            w = float(c["weight"])
            r = float(c["radius_km"])
        except (KeyError, TypeError, ValueError):
            return False, f"location_belief[{i}] inválido: cada candidato necesita name, lat, lon, weight, radius_km (numéricos)."
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return False, f"location_belief[{i}]: lat/lon fuera de rango ({lat}, {lon})."
        if w < 0:
            return False, f"location_belief[{i}]: weight negativo."
        if r <= 0:
            return False, f"location_belief[{i}]: radius_km debe ser > 0 (expresá tu incertidumbre espacial)."
        total_w += w
    if total_w > 1.001:
        return False, f"los weights de location_belief suman {total_w:.2f} > 1. Renormalizá: la masa no asignada significa 'no sé'."
    total_yw = 0.0
    for i, c in enumerate(yr):
        try:
            yf, yt = float(c["from"]), float(c["to"])
            w = float(c["weight"])
        except (KeyError, TypeError, ValueError):
            return False, f"year_belief[{i}] inválido: necesita from, to, weight numéricos."
        if yt < yf:
            return False, f"year_belief[{i}]: from ({yf:.0f}) > to ({yt:.0f})."
        if w < 0:
            return False, f"year_belief[{i}]: weight negativo."
        total_yw += w
    if total_yw > 1.001:
        return False, f"los weights de year_belief suman {total_yw:.2f} > 1. Renormalizá."
    return True, None


def _count_images_in_messages(messages: list[dict]) -> int:
    """Cuenta cuántas partes type='image_url' hay en messages (Azure 50 hard limit)."""
    count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    count += 1
    return count


def _prune_old_images(messages: list[dict], target_count: int = 40, step: Optional[int] = None) -> int:
    """Elimina imágenes viejas del historial hasta llegar a `target_count`.

    Estrategia:
    - La PRIMERA imagen del historial (foto target, en messages[1].content) NUNCA se elimina.
    - Recorre en orden cronológico (FIFO) y reemplaza partes type='image_url' por
      un marker textual con metadatos para que el modelo sepa qué había.
    - El text descriptor que cada tool injecta ANTES de la imagen queda intacto
      (ej "[Crop region={...}]"), así el modelo retiene contexto semántico.

    Returns: número de imágenes eliminadas.
    """
    current = _count_images_in_messages(messages)
    if current <= target_count:
        return 0

    need_to_remove = current - target_count
    removed = 0
    seen_first_image = False  # foto target inmune

    for msg in messages:
        if removed >= need_to_remove:
            break
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        new_parts: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                new_parts.append(part)
                continue
            if part.get("type") != "image_url":
                new_parts.append(part)
                continue
            # Es una imagen.
            if not seen_first_image:
                # Foto target — preservar y marcar como vista
                seen_first_image = True
                new_parts.append(part)
                continue
            if removed >= need_to_remove:
                new_parts.append(part)
                continue
            # Eliminar y reemplazar con marker text
            marker = (
                f"[imagen eliminada del contexto"
                + (f" en step {step}" if step is not None else "")
                + ". Para re-acceder, invocá la tool original con sus parámetros guardados.]"
            )
            new_parts.append({"type": "text", "text": marker})
            removed += 1
        msg["content"] = new_parts

    return removed


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


SYSTEM_PROMPT = """Recibís una fotografía histórica. Tu tarea: descubrir DÓNDE fue tomada (coords lat/lon) y CUÁNDO (año aproximado). Cerrá con `submit_answer`.

## Herramientas disponibles

NO te decimos CUÁNDO usar cada una. Vos decidís según el caso. Sí te explicamos exactamente QUÉ hace cada una y QUÉ INFO DEVUELVE, para que sepas elegir bien.

### Texto y páginas web

**`web_search(query, max_results=10)`** — Buscar en la web (Azure Bing Grounding).
Devuelve hasta 10 resultados con: `title`, `url`, `snippet` (1000-2000 chars con info concreta), y **metadata enriquecida**: `site_name` (Wikipedia, archive.org, fotopolska.eu, etc.), `date_published` si aparece, `language`, `source_type` (wikipedia/article/archive/blog/forum/social). La metadata te ayuda a priorizar fuentes confiables sin tener que abrir cada página.

**`fetch_url(url)`** — Bajar texto de una página web específica.
Devuelve `title` + `text` (hasta 12000 chars del contenido principal, sin imágenes). Útil cuando ya sabés que querés el TEXTO completo y las imágenes no van a ayudar.

**`fetch_url_with_images(url)`** — Bajar la página CON sus imágenes embebidas y contexto.
Devuelve `title` + `text` + hasta **10 imágenes** embebidas. **Cada imagen viene con su contexto semántico extraído del HTML**: `figcaption` (caption explícita), `alt` text, `nearby_text` (párrafo cercano en el HTML), `title` attribute, atributos `data-caption`, OpenGraph/Twitter Card metadata, JSON-LD schema.org. Esto te permite **conectar imagen + texto como un humano lee una página de archivo**: ves la foto del archivo Y leés "Eléctrico nº 73 en la Praça da Liberdade, 1947" debajo.
Las imágenes que matchean visualmente con la foto target se ocultan automáticamente (anti-shortcut).

### Imágenes (estilo Google Images con grilla)

**`image_search(query)` — buscar IMÁGENES en internet (no texto).**

**¿Cuándo usarlo? Diferencia con `web_search`:**
- `web_search` devuelve **texto**: snippets, descripciones, info escrita.
- `image_search` devuelve **imágenes**: las VES con tus ojos.

Usá `image_search` cuando:
- Necesitás **identificar visualmente** algo de la foto target (tipo de tranvía/auto/uniforme/arquitectura → buscar imágenes similares para datar y ubicar)
- **No tenés palabras precisas** para buscar pero "lo reconocerías al verlo" (ej: "edificio art deco con fachada redondeada Sudamérica años 30")
- Querés **comparar candidatos visuales** con tu foto target (ej: si crees que es Plaza Bolívar Bogotá vs Plaza Mayor Quito, buscás fotos antiguas de ambas y comparás)
- Vas a **descartar hipótesis** visualmente (mirando 16 candidatos a la vez ves rápido si tu intuición era correcta)

**Flujo de 3 modos** (replica humano scrolleando Google Images):

1. **Nueva búsqueda** — `image_search(query)`: devuelve UNA grilla 4×4 con 16 candidatos numerados + un `search_id` + flag `has_next_page`. **Escaneás visualmente las 16** y descartás las irrelevantes (mismo proceso que un humano en Google Images).
2. **Página adicional** — `image_search(query, page=2, search_id="abc")`: si los primeros 16 no tienen lo que buscás, pedí la siguiente página (cells 17-32, 33-48, etc.).
3. **Zoom en celdas prometedoras** — `image_search(query, pick=[3,7], search_id="abc")`: inspeccionás las celdas que TE LLAMARON LA ATENCIÓN en alta resolución (512×512) + recibís la grilla original re-inyectada para referencia. Después podés llamar `fetch_url_with_images` con la URL de cualquier celda para ver la página fuente completa con contexto.

**Workflow típico**: image_search → escaneás grilla → pick 1-3 interesantes → si la imagen confirma una hipótesis, fetch_url_with_images para ver contexto en la página fuente.

Límites: max 3 picks por call, max 2 rondas de pick por búsqueda.
Las imágenes que matchean visualmente con la foto target se descartan automáticamente (anti-shortcut).

### Recorte de la foto target

**`crop_image(x, y, width, height)` / `crop_image_relative(region)`** — Zoom en una región de la foto target.
La región se muestra ampliada en el siguiente turn. `crop_image_relative` acepta regiones nombradas: `top_left`, `top_right`, `top_center`, `bottom_left`, `bottom_right`, `bottom_center`, `middle`, `center`, `left_half`, `right_half`, `top_half`, `bottom_half`. Útil para leer texto chiquito en carteles, ver detalles arquitectónicos, distinguir vehículos, etc.

### Geocodificación

**`geocode(query, language)`** — Nombre → coords. Nominatim/OSM.
Ej: "Plaza Mayor Madrid" → coords + dirección estructurada + tipo (residential/city/street/etc). Te sirve para (a) obtener coords precisas de un lugar nombrado, (b) confirmar que el lugar EXISTE en OSM.

**`reverse_geocode(lat, lon, zoom)`** — Coords → dirección.
`zoom`: 3=país, 10=ciudad, 17=edificio, 18=calle.

### Mapas con contexto enriquecido

**`static_map(lat, lon, zoom, map_type, view='single')`** — Mapa de Google + contexto.
Devuelve imagen del mapa **junto con**:
- **POIs cercanos** (top-5 categorizados por relevancia geo-histórica: monumentos > estaciones > iglesias > puentes > plazas > parques). Cada uno con nombre + distancia en metros.
- **Altitud** del punto + **categoría de terreno** (`flat`/`rolling`/`mountainous`) computada de muestras en radio 1km.
- Si pedís `view='multi'`: devuelve UNA imagen compuesta 2×2 con sat + terrain + roadmap + hybrid en simultáneo. Útil para descartar rápido un lugar candidato sin gastar 4 calls.

### Street View con exploración

**`street_view(lat, lon, heading=0, contact_sheet=False, nearby=False)`** — Vista actual + nearby.
- Modo default: 1 imagen al heading dado.
- `contact_sheet=True`: 4 imágenes (N/E/S/W) — usá esto para **VERIFICAR una hipótesis sin comprometerte a una sola vista**.
- `nearby=True`: además del centro, devuelve 3-4 panoramas **reales sobre calles vecinas** en radio ~50m (usa Street View metadata para encontrar panoramas reales, no construye direcciones random). Imita "caminar la cuadra".
- Payload incluye POIs cercanos en radio 30m + fecha del panorama + distancia entre las coords pedidas y el panorama real.

### Información histórico-temporal

**`historical_query(south, west, north, east, preset, year)`** — OpenHistoricalMap.
Busca estructuras histórico-espaciales en un bbox: `buildings`, `churches`, `schools`, `factories`, `railway_stations`, `monuments`, `houses`, `all_named`. Si dado `year`, filtra features existentes ese año. **Cobertura desigual** (mucha información en Europa, poca en otras regiones) — ausencia de resultados NO prueba ausencia histórica. Es la única tool que distingue "esto EXISTÍA en YYYY" de "esto existe HOY".

### Submit final

**`submit_answer(location, lat, lon, year, reasoning, confidence, ...)`** — Devolvé respuesta.
Campos: `location` (texto descriptivo), `lat`, `lon`, `year` (puede ser rango "1960-1970"), `reasoning`, `confidence` (alta/media/baja), `visual_clues` (lista de pistas concretas que extrajiste de la foto), `external_evidence` (URLs + qué confirma cada una), `rejected_alternatives` (hipótesis descartadas + por qué), `verification_checks` (chequeos independientes, idealmente VISUALES con street_view/static_map/comparación), `uncertainty_reason` (si confianza ≠ alta, qué falta).

## Filtros automáticos anti-shortcut

NO podés desactivarlos:
- **Blacklist de dominios**: bloqueamos reverse image search, agregadores con metadata estructurada, hosting/sharing, y la fuente específica de la foto target. Específicos por foto.
- **Hash perceptual de la foto target**: imágenes que matchean visualmente con la foto se descartan o se ocultan completamente (no es evidencia válida).

## Flujo recomendado y patrones útiles

- **Antes de comprometerte con UNA hipótesis**, considerá ≥2 alternativas explícitas en el thinking. La primera intuición puede ser la trampa.
- **Verificá VISUALMENTE antes de submit**. Una hipótesis sin street_view o static_map de comparación es débil. `verification_checks` que solo cita texto es menos confiable que comparar visualmente la foto target con un panorama actual.
- **Las imágenes pueden caducar del contexto** después de muchos pasos (límite hard del sistema). Si una imagen es importante, ANOTÁ en tu thinking lo que viste y guardá la URL/coords/region para re-acceder con `fetch_url`/`street_view`/`static_map`/`crop_image` después si lo necesitás.

## ⚠️ Cuándo submitir (CRÍTICO — leé bien)

**NO submitas hasta tener evidencia fuerte.** Específicamente:

**Submit SOLO si**:
1. Podés **CITAR explícitamente ≥2 piezas de evidencia independientes** que respaldan tu hipótesis. Ejemplos válidos:
   - "Wikipedia confirma que el edificio X estaba en Y desde 1920"
   - "El panorama de street_view en (lat, lon) muestra la misma fachada que la foto target — comparé arquitectura, ventanas y proporciones"
   - "historical_query confirmó que la iglesia Z existía en 1947 en ese radio"
   - "El cartel parcial dice 'AVDA 18' + en Buenos Aires hay Av. 18 de Julio = match"
2. Estimás distancia **< 25 km con alta probabilidad** de tu hipótesis al lugar real. Esto significa identificaste **barrio o landmark específico**, NO solo "está en Rusia".

**Si NO podés citar ≥2 evidencias O NO estás seguro de <25 km**: SEGUÍ investigando.
- Hipótesis competidoras pendientes → testealas con `street_view` o `image_search`
- Pistas visuales no investigadas (carteles, vehículos, vegetación) → `crop_image` + `image_search`
- Falta verificación visual de tu top hipótesis → `street_view` de las coords candidatas

**Hard cap — si llegás al step 18-19** (te quedan 1-2 turns):
- Submit con tu mejor hipótesis aunque sea débil
- `confidence='baja'`
- En `uncertainty_reason` explicá HONESTAMENTE qué evidencia te faltó

NO uses tu budget defensivamente — si tenés evidencia fuerte en step 6, submit en step 6. Pero la barra de "evidencia fuerte" es ALTA: 2+ evidencias citables + estimación de cercanía real.

## Idioma

Tus razonamientos y respuestas en **español**. Las queries de búsqueda en el idioma apropiado al contexto (ruso para fotos cirílicas, portugués para Brasil/Portugal, etc.).

## Razonamiento visible (formato ReAct)

Antes de cada turn de acciones, escribí en TEXTO breve (1-3 oraciones):
1. Qué observás de la foto target o de las observaciones previas.
2. Qué hipótesis estás considerando (idealmente >1, ranqueadas por plausibilidad).
3. Qué esperás conseguir de la(s) próxima(s) acción(es).

Ese texto va como `content` de tu respuesta, separado de los `tool_calls`. Es para que un investigador humano pueda seguir tu proceso paso a paso — no es input para las tools.

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
    belief_report_count: int = 0
    belief_reports: list[dict] = field(default_factory=list)  # [{step, belief}] — scoring post-hoc
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
    min_steps: int = 0,
    verbose: bool = True,
    user_prompt: str = "Investigá esta foto y devolvé las coordenadas (lat, lon) y año con submit_answer.",
    provider: Optional[str] = None,
    provenance_source: Optional[str] = None,
    system_prompt: Optional[str] = None,
    belief_mode: bool = False,
    belief_nudge_after: int = 3,
) -> ReActResult:
    """Correr el agente ReAct con todas las tools.

    Anti-shortcut runtime:
    - `provider`: identifica la fuente del corpus (pastvu, smapshot, ...). Sus dominios
      van al excluido per-photo además del GLOBAL.
    - `provenance_source`: campo `source` del candidate (free-text con URLs originales).
      Se extraen hosts y se agregan al excluido.

    `system_prompt`: si None, usa el SYSTEM_PROMPT global del módulo (canónico v3).
    Override útil para iteración de prompts desde notebook/scripts ad-hoc.

    Belief-mode (E016, #47):
    - `belief_mode=True` agrega la tool `report_belief` + sección de prompt + campo
      `evidence_chain` en submit_answer. Con False el scaffold es EXACTAMENTE el
      canónico (brazo OFF de la ablation).
    - `belief_nudge_after`: si pasan N steps con tools sin report_belief, se inyecta
      un recordatorio. Los beliefs NO se puntúan en runtime (ground truth no entra
      al loop); quedan en result.belief_reports para scoring post-hoc.
    """
    sys_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT
    if belief_mode:
        sys_prompt = sys_prompt + "\n\n" + BELIEF_PROMPT_SECTION
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
        {"role": "system", "content": sys_prompt},
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
        HISTORICAL_QUERY_AT_SCHEMA,
        TOOL_SCHEMA_CROP,
        TOOL_SCHEMA_CROP_RELATIVE,
        STATIC_MAP_SCHEMA,
        STREET_VIEW_SCHEMA,
        _submit_schema_with_evidence_chain() if belief_mode else SUBMIT_TOOL_SCHEMA,
    ]
    if belief_mode:
        tools.append(BELIEF_TOOL_SCHEMA)
    result = ReActResult()
    target_path_str = str(image_path)  # para hash perceptual
    steps_since_belief = 0  # steps con tools sin report_belief (para el nudge)

    for step in range(max_steps):
        # Sliding-window cleanup de imágenes acumuladas. Azure tiene un límite hard
        # de 50 imágenes por request (no por tokens). Cuando se acerca, eliminamos
        # las más viejas EXCEPTO la foto target (primera image_url del historial).
        # El text descriptor que cada tool injecta antes de la imagen queda — el
        # modelo sabe que "vio una imagen de tal tipo" sin tener los pixels.
        n_imgs = _count_images_in_messages(messages)
        if n_imgs >= 45:
            removed = _prune_old_images(messages, target_count=40, step=step + 1)
            result.trace.append({
                "step": step + 1, "type": "image_context_cleanup",
                "images_before": n_imgs, "images_removed": removed,
                "images_after": n_imgs - removed,
            })
            if verbose:
                print(f"[cleanup] removed {removed} old images (was {n_imgs}, now {n_imgs - removed})")

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
        elif remaining in (3, 5) and not result.submit_called:
            messages.append({
                "role": "user",
                "content": f"[Recordatorio: te quedan {remaining} turns. Si tu evidencia es fuerte (2+ citables + <25km alta prob), submit YA. Sino, hacé 1-2 verificaciones rápidas más antes del hard cap.]",
            })
        # Nudge belief-mode: pasaron N steps con tools sin report_belief.
        if belief_mode and steps_since_belief >= belief_nudge_after and not result.submit_called:
            messages.append({
                "role": "user",
                "content": (
                    f"[Belief-mode: pasaron {steps_since_belief} steps desde tu último report_belief. "
                    f"Si tu creencia cambió con la evidencia reciente, reportala ahora. Si NO cambió, "
                    f"reportá igual la actual — una creencia que no se mueve también es señal.]"
                ),
            })
            result.trace.append({"step": step + 1, "type": "belief_nudge", "steps_since_belief": steps_since_belief})
            steps_since_belief = 0
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
        # Normalizar content a string (nunca None) — el SDK puede devolver None o
        # "". Azure rechaza con "content: expected a string, got null" si en algún
        # mensaje del historial content es None.
        content_str = msg.content if msg.content is not None else ""
        assistant_turn: dict[str, Any] = {"role": "assistant", "content": content_str}
        if content_str.strip():
            # Guardamos el texto que el modelo emite junto con sus tool_calls
            # (cuando lo hay) para inspección de trayectorias.
            result.trace.append({"step": step + 1, "type": "thinking", "content": content_str})
            if verbose:
                print(f"[assistant] {content_str[:300]}")
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        # Empty response: ni texto ni tool_calls. Cubrir TANTO None como "" — los
        # SDKs (especialmente Anthropic adapter) pueden devolver string vacío en
        # vez de None. Antes solo capturábamos None → con content="" y tool_calls
        # None caíamos en un assistant_turn sin content keys, que rompe Azure.
        if not content_str.strip() and not msg.tool_calls:
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
        belief_reported_this_step = False

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
                        "payload_to_model": payload,  # FULL: exactamente lo que el modelo recibe  # exact tool message content que el modelo ve
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
                        "payload_to_model": payload,  # FULL: exactamente lo que el modelo recibe
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
                        "payload_to_model": payload,  # FULL: exactamente lo que el modelo recibe
                        "payload_full_len": len(payload),
                    })

                    # Build user message with images for next turn.
                    # Hard reject images where hash perceptual matches target (#21 / #24 deuda):
                    # listamos metadata pero NO inyectamos los bytes. La política canon es
                    # "descartar" (PROJECT.md), no "flaggear" como el comportamiento previo.
                    if fp.images:
                        visible = [im for im in fp.images if not im.is_likely_target]
                        hidden = [im for im in fp.images if im.is_likely_target]
                        parts: list[dict] = [{"type": "text", "text": f"[Imágenes encontradas en {url}. Mostradas en orden con su contexto extraído del HTML. {len(hidden)} imágenes ocultadas porque coinciden visualmente con la foto target (hash perceptual match — no son evidencia válida)]"}]
                        for im in visible:
                            # v2 (#40): incluir contexto semántico de la imagen (caption, alt, párrafo cercano)
                            label_parts = [f"img source: {im.url[:100]}", f"hamming={im.hamming_distance}"]
                            if im.context:
                                ctx = im.context
                                if ctx.figcaption:
                                    label_parts.append(f"caption: \"{ctx.figcaption}\"")
                                if ctx.jsonld_caption:
                                    label_parts.append(f"schema_caption: \"{ctx.jsonld_caption}\"")
                                if ctx.og_alt:
                                    label_parts.append(f"og_alt: \"{ctx.og_alt}\"")
                                if ctx.alt:
                                    label_parts.append(f"alt: \"{ctx.alt}\"")
                                if ctx.title:
                                    label_parts.append(f"title: \"{ctx.title}\"")
                                if ctx.aria_label:
                                    label_parts.append(f"aria: \"{ctx.aria_label}\"")
                                if ctx.data_caption:
                                    label_parts.append(f"data_caption: \"{ctx.data_caption}\"")
                                if ctx.link_text:
                                    label_parts.append(f"link_text: \"{ctx.link_text}\"")
                                if ctx.nearby_text:
                                    label_parts.append(f"nearby_text: \"{ctx.nearby_text}\"")
                                if ctx.filename:
                                    label_parts.append(f"filename: \"{ctx.filename}\"")
                            label = "[" + " | ".join(label_parts) + "]"
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
                    # v2 (#42): image_search devuelve GridResult | PickResult | ImageSearchError
                    from ..tools.image_search import GridResult, PickResult, ImageSearchError as ImgSearchErr
                    isr = image_search(
                        query=args.get("query", ""),
                        pick=args.get("pick"),
                        page=args.get("page"),
                        search_id=args.get("search_id"),
                        target_image_path=target_path_str,
                        excluded_domains=excluded_domains,
                    )

                    if isinstance(isr, ImgSearchErr):
                        if verbose:
                            print(f"     → image_search error: {isr.error}")
                        payload = json.dumps({"error": isr.error, "detail": isr.detail}, ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                        result.trace.append({"step": step + 1, "type": "image_search_error", "error": isr.error, "detail": isr.detail})

                    elif isinstance(isr, GridResult):
                        result.target_match_count += isr.target_match_count
                        if verbose:
                            print(f"     → GRID search_id={isr.search_id} page={isr.page}/{isr.n_pages_total} {isr.n_cells} cells target_match={isr.target_match_count} suspicious={isr.suspicious_count}")
                        payload = json.dumps(isr.to_dict_no_b64(), ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                        # Label con info de paginación
                        next_page_hint = ""
                        if isr.has_next_page:
                            next_page_hint = f" Para siguiente página: image_search(query, page={isr.page+1}, search_id='{isr.search_id}')."
                        parts = [
                            {"type": "text", "text": f"[image_search grilla 4×4 PÁGINA {isr.page}/{isr.n_pages_total}. search_id={isr.search_id}. query='{isr.query}'. Celdas {isr.cells_range[0]}-{isr.cells_range[1]} numeradas. Para zoom: image_search(query, pick=[N,M], search_id='{isr.search_id}').{next_page_hint}]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{isr.grid_image_b64}"}},
                        ]
                        pending_image_injections.append(("image_search_grid", parts))
                        result.trace.append({
                            "step": step + 1, "type": "image_search",
                            "query": args.get("query"),
                            "search_id": isr.search_id,
                            "page": isr.page,
                            "n_pages_total": isr.n_pages_total,
                            "has_next_page": isr.has_next_page,
                            "n_cells": isr.n_cells,
                            "cells_range": isr.cells_range,
                            "target_match_count": isr.target_match_count,
                            "suspicious_count": isr.suspicious_count,
                            "cells_metadata": [c.to_dict() for c in isr.cells_metadata],
                            "payload_to_model": payload,
                            "image_inject_kind": "image_search_grid",
                        })

                    elif isinstance(isr, PickResult):
                        if verbose:
                            print(f"     → PICK search_id={isr.search_id} picks={[p['cell'] for p in isr.picks]} rounds={isr.rounds_used}/{isr.rounds_used + isr.rounds_remaining}")
                        payload = json.dumps(isr.to_dict_no_b64(), ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                        # Re-inyectar grilla + celdas pickeadas en alta res
                        parts = [
                            {"type": "text", "text": f"[image_search pick search_id={isr.search_id}. Grilla original re-inyectada + {len(isr.picks)} celdas en alta resolución. Rondas usadas {isr.rounds_used}/{isr.rounds_used + isr.rounds_remaining}.]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{isr.grid_image_b64}"}},
                        ]
                        for pk in isr.picks:
                            label_parts = [f"Celda {pk['cell']} HiRes"]
                            if pk.get("alt_text"):
                                label_parts.append(f"alt: \"{pk['alt_text']}\"")
                            label_parts.append(f"source: {pk['url'][:100]}")
                            parts.append({"type": "text", "text": "[" + " | ".join(label_parts) + "]"})
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{pk['image_b64']}"}})
                        pending_image_injections.append(("image_search_pick", parts))
                        result.trace.append({
                            "step": step + 1, "type": "image_search_pick",
                            "search_id": isr.search_id,
                            "picks": [{"cell": p["cell"], "url": p["url"], "alt_text": p.get("alt_text", "")} for p in isr.picks],
                            "not_picked_cells": isr.not_picked_cells,
                            "rounds_used": isr.rounds_used,
                            "payload_to_model": payload,
                            "image_inject_kind": "image_search_pick",
                        })
                except Exception as e:
                    err = f"image_search error: {type(e).__name__}: {e}"
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
                        "payload_to_model": payload,  # FULL: exactamente lo que el modelo recibe
                        "payload_full_len": len(payload),
                    })
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"{fname} error: {e}"})
                    result.trace.append({"step": step + 1, "type": f"{fname}_error", "error": str(e)})

            elif fname in ("historical_query", "historical_query_at"):
                result.historical_query_count += 1
                try:
                    if fname == "historical_query_at":
                        # Wrapper amigable: lat/lon + radius_km
                        hq = historical_query_at(
                            lat=float(args["lat"]),
                            lon=float(args["lon"]),
                            radius_km=float(args.get("radius_km", 5.0)),
                            preset=args.get("preset", "all_named"),
                            year=args.get("year"),
                            require_dated=bool(args.get("require_dated", False)),
                            max_features=int(args.get("max_features", 30)),
                        )
                    else:
                        hq = historical_query(
                            south=float(args["south"]),
                            west=float(args["west"]),
                            north=float(args["north"]),
                            east=float(args["east"]),
                            preset=args.get("preset"),
                            year=args.get("year"),
                            require_dated=bool(args.get("require_dated", False)),
                            max_features=int(args.get("max_features", 30)),
                        )
                    if verbose:
                        print(f"     → {fname}: {hq.n_features} features (truncated={hq.truncated}, err={hq.error})")
                    payload = json.dumps(hq.to_dict(), ensure_ascii=False)[:8000]
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                    result.trace.append({
                        "step": step + 1, "type": fname,
                        "args": args, "n_features": hq.n_features,
                        "payload_to_model": payload,
                        "payload_full_len": len(payload),
                    })
                except Exception as e:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"{fname} error: {e}"})
                    result.trace.append({"step": step + 1, "type": f"{fname}_error", "error": str(e)})

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
                        "base64_jpeg": cr.base64_jpeg,
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
                        view=args.get("view", "single"),
                    )
                    if isinstance(sm, StaticMapError):
                        if verbose:
                            print(f"     → static_map error: {sm.error}")
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps({"error": sm.error, "detail": sm.detail})})
                        result.trace.append({"step": step + 1, "type": "static_map_error", "error": sm.error})
                    else:
                        if verbose:
                            print(f"     → static_map ok type={sm.type} pois={len(sm.nearby_pois)} elev={sm.elevation.elevation_m if sm.elevation else 'NA'}")
                        # v2 (#41): payload incluye POIs + elevation enriquecidos
                        meta = {
                            "lat": sm.lat, "lon": sm.lon, "zoom": sm.zoom, "type": sm.type,
                            "size": list(sm.size), "note": sm.note,
                            "nearby_pois": [p.to_dict() for p in sm.nearby_pois],
                            "elevation": sm.elevation.to_dict() if sm.elevation else None,
                            "composite_views": sm.composite_views,
                        }
                        payload = json.dumps(meta, ensure_ascii=False)
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
                        # Label visible: incluye POIs + elevation prominentemente
                        label_parts = [f"Static map {sm.type} en ({sm.lat}, {sm.lon}) zoom {sm.zoom}"]
                        if sm.elevation:
                            label_parts.append(f"Altitud {sm.elevation.elevation_m:.0f}m | Terreno: {sm.elevation.terrain_category}")
                        if sm.nearby_pois:
                            poi_strs = [f"{p.name}({p.distance_m:.0f}m)" for p in sm.nearby_pois[:3]]
                            label_parts.append(f"POIs cercanos: {', '.join(poi_strs)}")
                        parts = [
                            {"type": "text", "text": "[" + " | ".join(label_parts) + "]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sm.base64_jpeg}"}},
                        ]
                        pending_image_injections.append(("static_map", parts))
                        result.trace.append({
                            "step": step + 1, "type": "static_map",
                            "args": args, "map_type": sm.type, "lat": sm.lat, "lon": sm.lon,
                            "zoom": sm.zoom, "base64_jpeg": sm.base64_jpeg,
                            "nearby_pois": [p.to_dict() for p in sm.nearby_pois],
                            "elevation": sm.elevation.to_dict() if sm.elevation else None,
                            "composite_views": sm.composite_views,
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

            elif fname == "report_belief":
                # NO se puntúa en runtime (ground truth no entra al loop). Solo
                # validación estructural + registro para scoring post-hoc.
                ok, err_msg = _validate_belief(args)
                if not ok:
                    if verbose:
                        print(f"     ⚠ report_belief rechazado: {err_msg}")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": f"report_belief rechazado: {err_msg} Reintentá con el formato correcto.",
                    })
                    result.trace.append({
                        "step": step + 1, "type": "report_belief_rejected",
                        "belief": args, "error": err_msg,
                    })
                else:
                    result.belief_report_count += 1
                    result.belief_reports.append({"step": step + 1, "belief": args})
                    belief_reported_this_step = True
                    n_loc = len(args.get("location_belief", []))
                    n_yr = len(args.get("year_belief", []))
                    top = ""
                    if n_loc:
                        c0 = max(args["location_belief"], key=lambda c: c.get("weight", 0))
                        top = f" top={c0.get('name', '?')} w={c0.get('weight')}"
                    if verbose:
                        print(f"     → belief #{result.belief_report_count}: {n_loc} loc, {n_yr} year.{top}")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": f"belief_recorded ({n_loc} candidatos de ubicación, {n_yr} rangos de año).",
                    })
                    result.trace.append({"step": step + 1, "type": "report_belief", "belief": args})

            elif fname == "submit_answer":
                # min_steps: bloqueo "hard" — si el modelo intenta terminar antes
                # del piso mínimo, le pedimos que siga investigando. No cuenta como
                # retry de validación porque no es un error del modelo, es política.
                if (step + 1) < min_steps:
                    if verbose:
                        print(f"     ⚠ SUBMIT bloqueado: step {step+1} < min_steps {min_steps}")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": (
                            f"submit_answer bloqueado: estás en el step {step+1} pero el piso mínimo "
                            f"es {min_steps}. Seguí investigando con otras tools antes de submitir tu "
                            f"respuesta final. Aprovechá los steps para verificar hipótesis con tools "
                            f"visuales (street_view, static_map, crop_image) o búsquedas más profundas."
                        ),
                    })
                    result.trace.append({
                        "step": step + 1, "type": "submit_blocked_min_steps",
                        "answer": args, "min_steps": min_steps,
                    })
                    continue
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

        if belief_mode:
            steps_since_belief = 0 if belief_reported_this_step else steps_since_belief + 1

        if result.submit_called:
            break

    # Si salimos del loop sin terminal_state seteado, fue por max_steps.
    if result.terminal_state is None:
        if result.submit_called:
            result.terminal_state = "submitted"
        else:
            result.terminal_state = "max_steps_no_submit"

    return result
