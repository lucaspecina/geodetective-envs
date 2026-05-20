"""static_map: Google Maps Static API + Places Nearby + Elevation (v2 #41).

Devuelve una imagen del mapa en zona X con tipo Y (roadmap, satellite, terrain, hybrid)
+ contexto enriquecido:
- POIs cercanos relevantes (Places API, filtrados por relevancia geo-histórica)
- Altitud + categorización de terreno (Elevation API)
- Opcional: vista multi (compuesta sat+terrain+roadmap+hybrid en una imagen)

Tipo "terrain" 2D con curvas de nivel = vista relieve simple. Cubre 80-90% del valor
de "ver montañas" sin necesidad de pipeline 3D.

Requiere GOOGLE_MAPS_API_KEY en el environment.
Si no hay key, devuelve un error claro (la tool sigue declarada para que el agente
sepa que existe pero no puede usarse hasta que el user agregue la key).

Si más adelante hace falta vista 3D inmersiva, ver issue #19 (deuda registrada).
"""
from __future__ import annotations
import os
import base64
from io import BytesIO
from typing import Optional
from dataclasses import dataclass, field
import httpx
from PIL import Image

from .google_api import get_places_nearby, get_elevation, PlaceInfo, ElevationResult


GOOGLE_STATIC_BASE = "https://maps.googleapis.com/maps/api/staticmap"

# Tipos válidos según Google
VALID_TYPES = {"roadmap", "satellite", "terrain", "hybrid"}


@dataclass
class StaticMapResult:
    base64_jpeg: str
    lat: float
    lon: float
    zoom: int
    type: str
    size: tuple[int, int]  # ancho, alto
    note: Optional[str] = None
    # v2 (#41): contexto enriquecido
    nearby_pois: list[PlaceInfo] = field(default_factory=list)
    elevation: Optional[ElevationResult] = None
    composite_views: list[str] = field(default_factory=list)  # nombres de tipos en composite (si view=multi)


@dataclass
class StaticMapError:
    error: str
    detail: Optional[str] = None


def _fetch_single_static_map(lat: float, lon: float, zoom: int, map_type: str,
                              size: tuple[int, int], api_key: str) -> Optional[Image.Image]:
    """Helper: pedir UNA imagen del Static Maps. Devuelve PIL Image o None si falla."""
    params = {
        "center": f"{lat},{lon}",
        "zoom": zoom,
        "size": f"{size[0]}x{size[1]}",
        "maptype": map_type,
        "key": api_key,
    }
    try:
        r = httpx.get(GOOGLE_STATIC_BASE, params=params, timeout=20.0)
        if r.status_code != 200:
            return None
        img = Image.open(BytesIO(r.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def _compose_multi_view(images: list[tuple[str, Image.Image]], cell_size: tuple[int, int] = (320, 320)) -> Image.Image:
    """Componer 4 imágenes en grid 2×2 con etiquetas. Codex review."""
    from PIL import ImageDraw, ImageFont
    n = len(images)
    if n == 0:
        return Image.new("RGB", cell_size, (200, 200, 200))
    rows = 2 if n > 2 else 1
    cols = 2 if n > 1 else 1
    canvas = Image.new("RGB", (cell_size[0] * cols, cell_size[1] * rows), (255, 255, 255))
    try:
        font = ImageFont.truetype("arial.ttf", size=20)
    except Exception:
        font = ImageFont.load_default()
    for i, (label, img) in enumerate(images[:4]):
        r, c = divmod(i, cols)
        thumb = img.resize(cell_size, Image.LANCZOS)
        canvas.paste(thumb, (c * cell_size[0], r * cell_size[1]))
        # Label arriba a la izquierda con fondo negro semi-transparente
        d = ImageDraw.Draw(canvas)
        text_x = c * cell_size[0] + 8
        text_y = r * cell_size[1] + 8
        bbox = d.textbbox((text_x, text_y), label, font=font)
        d.rectangle(bbox, fill="black")
        d.text((text_x, text_y), label, fill="white", font=font)
    return canvas


def static_map(
    lat: float,
    lon: float,
    zoom: int = 14,
    map_type: str = "roadmap",
    size: tuple[int, int] = (640, 640),
    view: str = "single",  # "single" o "multi"
    enrich: bool = True,    # incluir POIs nearby + elevation
) -> StaticMapResult | StaticMapError:
    """Pedir un mapa estático de Google Static Maps con contexto enriquecido.

    Args:
        lat, lon: centro del mapa.
        zoom: 0 (mundo entero) a 21 (edificio individual). Default 14 (barrio).
        map_type: "roadmap", "satellite", "terrain", "hybrid". Ignorado si view="multi".
        size: ancho x alto en pixels. Max 640x640 sin scale=2.
        view: "single" (1 imagen del map_type pedido) o "multi" (2×2 compuesta con
              sat+terrain+roadmap+hybrid en UNA imagen).
        enrich: si True, agrega POIs cercanos (Places) + altitud (Elevation) al payload.

    Returns:
        StaticMapResult con base64_jpeg + nearby_pois + elevation, o StaticMapError.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return StaticMapError(
            error="no_api_key",
            detail="GOOGLE_MAPS_API_KEY no está en environment. Agregalo al .env del proyecto.",
        )
    if map_type not in VALID_TYPES:
        return StaticMapError(error="invalid_type", detail=f"map_type debe ser uno de {VALID_TYPES}")
    if view not in ("single", "multi"):
        return StaticMapError(error="invalid_view", detail="view debe ser 'single' o 'multi'")

    # --- Construir imagen ---
    composite_views: list[str] = []

    if view == "multi":
        # Pedir las 4 vistas en paralelo (httpx síncrono pero rápido secuencialmente)
        types_to_fetch = ["satellite", "terrain", "roadmap", "hybrid"]
        images_pil = []
        for t in types_to_fetch:
            img = _fetch_single_static_map(lat, lon, zoom, t, (640, 640), api_key)
            if img is not None:
                images_pil.append((t, img))
        if not images_pil:
            return StaticMapError(error="all_fetches_failed", detail="Ninguna de las 4 vistas se pudo bajar.")
        composite = _compose_multi_view(images_pil, cell_size=(320, 320))
        buf = BytesIO()
        composite.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        composite_views = [t for t, _ in images_pil]
        actual_size = composite.size
        result_type = "multi"
    else:
        img = _fetch_single_static_map(lat, lon, zoom, map_type, size, api_key)
        if img is None:
            return StaticMapError(error="fetch_failed", detail="Static Maps request falló.")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        actual_size = size
        result_type = map_type

    # --- Enrichment opcional (Codex review: non-fatal) ---
    nearby_pois: list[PlaceInfo] = []
    elevation: Optional[ElevationResult] = None
    if enrich:
        try:
            nearby_pois = get_places_nearby(lat, lon, radius_m=200, max_results=5)
        except Exception:
            nearby_pois = []
        try:
            elevation = get_elevation(lat, lon, radius_samples_m=1000, n_samples=9)
        except Exception:
            elevation = None

    # --- Construir note descriptiva ---
    note_parts = []
    if view == "multi":
        note_parts.append(f"Vista multi: 4 mapas compuestos ({', '.join(composite_views)}). Cuadrante superior-izquierdo=satellite, sup-derecho=terrain, inf-izquierdo=roadmap, inf-derecho=hybrid.")
    elif map_type == "terrain":
        note_parts.append("Vista terrain 2D: curvas de nivel muestran relieve.")
    if elevation:
        note_parts.append(f"Altitud central: {elevation.elevation_m:.0f}m. Terreno: {elevation.terrain_category}.")
    if nearby_pois:
        top_names = ", ".join(f"{p.name} ({p.distance_m:.0f}m)" for p in nearby_pois[:3])
        note_parts.append(f"POIs cercanos top-3: {top_names}.")

    return StaticMapResult(
        base64_jpeg=b64,
        lat=lat, lon=lon, zoom=zoom, type=result_type, size=actual_size,
        note=" ".join(note_parts) if note_parts else None,
        nearby_pois=nearby_pois,
        elevation=elevation,
        composite_views=composite_views,
    )


# OpenAI tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "static_map",
        "description": (
            "Obtener una imagen de mapa estática de Google Maps + contexto enriquecido. "
            "La imagen viene en el siguiente turn JUNTO con: POIs cercanos (top-5 lugares "
            "categorizados por relevancia geo-histórica: monumentos > estaciones > iglesias > "
            "puentes > plazas), altitud central + categoría de terreno (flat/rolling/mountainous "
            "computada de muestras en radio 1km). "
            "Tipos: roadmap (calles), satellite (foto satelital), terrain (relieve 2D con curvas "
            "de nivel), hybrid (sat+calles). Usá view='multi' para obtener LAS 4 vistas compuestas "
            "en UNA imagen (cuadrante 2×2: sat, terrain, roadmap, hybrid) — útil para descartar "
            "rápido si un lugar candidato es plausible sin gastar 4 calls. NO es vista 3D inmersiva."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "zoom": {
                    "type": "integer",
                    "description": "Nivel de zoom: 6=región (200km), 10=ciudad (40km), 14=barrio (3km), 18=manzana (200m).",
                    "default": 14,
                },
                "map_type": {
                    "type": "string",
                    "enum": ["roadmap", "satellite", "terrain", "hybrid"],
                    "default": "roadmap",
                    "description": "Tipo de mapa para view='single'. Ignorado si view='multi'.",
                },
                "view": {
                    "type": "string",
                    "enum": ["single", "multi"],
                    "default": "single",
                    "description": "'single' = 1 imagen del map_type pedido. 'multi' = 2×2 compuesta con todas las vistas.",
                },
            },
            "required": ["lat", "lon"],
        },
    },
}
