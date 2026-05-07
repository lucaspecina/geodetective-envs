"""static_map: Google Maps Static API.

Devuelve una imagen del mapa en zona X con tipo Y (roadmap, satellite, terrain, hybrid).

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
from dataclasses import dataclass
import httpx
from PIL import Image


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


@dataclass
class StaticMapError:
    error: str
    detail: Optional[str] = None


def static_map(
    lat: float,
    lon: float,
    zoom: int = 14,
    map_type: str = "roadmap",
    size: tuple[int, int] = (640, 640),
) -> StaticMapResult | StaticMapError:
    """Pedir un mapa estático de Google Static Maps.

    Args:
        lat, lon: centro del mapa.
        zoom: 0 (mundo entero) a 21 (edificio individual). Default 14 (barrio).
        map_type: "roadmap" (calles), "satellite" (foto satelital), "terrain" (relieve 2D), "hybrid".
        size: ancho x alto en pixels. Max 640x640 sin scale=2.

    Returns:
        StaticMapResult con base64_jpeg, o StaticMapError si falla.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return StaticMapError(
            error="no_api_key",
            detail="GOOGLE_MAPS_API_KEY no está en environment. Agregalo al .env del proyecto.",
        )
    if map_type not in VALID_TYPES:
        return StaticMapError(error="invalid_type", detail=f"map_type debe ser uno de {VALID_TYPES}")

    params = {
        "center": f"{lat},{lon}",
        "zoom": zoom,
        "size": f"{size[0]}x{size[1]}",
        "maptype": map_type,
        "key": api_key,
    }
    try:
        r = httpx.get(GOOGLE_STATIC_BASE, params=params, timeout=20.0)
    except Exception as e:
        return StaticMapError(error="fetch_error", detail=str(e))

    if r.status_code != 200:
        return StaticMapError(error=f"http_{r.status_code}", detail=r.text[:300])

    # Re-encode as JPEG (Google devuelve PNG por default, JPEG es más liviano para tokens)
    try:
        img = Image.open(BytesIO(r.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return StaticMapError(error="image_decode_error", detail=str(e))

    note = None
    if map_type == "terrain":
        note = "Vista terrain 2D: curvas de nivel muestran relieve. Para 3D inmersivo no implementado en v1 (ver issue #19)."

    return StaticMapResult(
        base64_jpeg=b64,
        lat=lat, lon=lon, zoom=zoom, type=map_type, size=size,
        note=note,
    )


# OpenAI tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "static_map",
        "description": (
            "Obtener una imagen de mapa estática de Google Maps. La imagen viene en el siguiente turn. "
            "Tipos: roadmap (calles), satellite (foto satelital), terrain (relieve 2D con curvas de "
            "nivel — útil para identificar montañas/valles/costas), hybrid (sat+calles). "
            "Útil para verificar layout, vegetación, relieve. NO devuelve vista 3D inmersiva — para eso "
            "tendrías que rotar la cámara, lo cual no está implementado en v1."
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
                },
            },
            "required": ["lat", "lon"],
        },
    },
}
