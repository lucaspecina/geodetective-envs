"""street_view: Google Street View Static API.

Devuelve una foto de Street View desde coords + heading + pitch + fov.
Útil para verificar visualmente con vista actual de la zona.

Cobertura limitada en zonas rurales / históricas / fuera de occidente. Si no hay
cobertura, Google devuelve una imagen "no Street View available" — chequeamos eso.

Requiere GOOGLE_MAPS_API_KEY.
"""
from __future__ import annotations
import os
import base64
from io import BytesIO
from typing import Optional
from dataclasses import dataclass
import httpx
from PIL import Image


GOOGLE_SV_BASE = "https://maps.googleapis.com/maps/api/streetview"
GOOGLE_SV_META = "https://maps.googleapis.com/maps/api/streetview/metadata"


@dataclass
class StreetViewResult:
    base64_jpeg: str
    lat: float
    lon: float
    heading: float
    pitch: float
    fov: int
    panorama_id: Optional[str] = None  # si conocido vía metadata
    actual_lat: Optional[float] = None  # coords del panorama (puede diferir del request)
    actual_lon: Optional[float] = None
    note: Optional[str] = None


@dataclass
class StreetViewError:
    error: str
    detail: Optional[str] = None


def check_street_view_coverage(lat: float, lon: float, radius: int = 50) -> dict:
    """Verificar si hay Street View en coords.

    Devuelve metadata sin cobrar (Street View Image Metadata es free según pricing).
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return {"status": "NO_API_KEY"}
    params = {
        "location": f"{lat},{lon}",
        "radius": radius,
        "key": api_key,
    }
    try:
        r = httpx.get(GOOGLE_SV_META, params=params, timeout=10.0)
        return r.json()
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def street_view(
    lat: float,
    lon: float,
    heading: float = 0.0,
    pitch: float = 0.0,
    fov: int = 90,
    size: tuple[int, int] = (640, 640),
) -> StreetViewResult | StreetViewError:
    """Pedir una imagen Street View.

    Args:
        lat, lon: coordenadas.
        heading: dirección de la cámara, 0=norte, 90=este, 180=sur, 270=oeste.
        pitch: ángulo vertical, -90=down, 0=horizonte, +90=up.
        fov: field of view, 1-120, default 90.
        size: ancho x alto, max 640x640 sin scale=2.

    Returns:
        StreetViewResult o StreetViewError. Si no hay cobertura en la zona,
        devuelve error específico.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return StreetViewError(error="no_api_key", detail="GOOGLE_MAPS_API_KEY no en environment.")

    # Primero check coverage (free)
    meta = check_street_view_coverage(lat, lon, radius=200)
    if meta.get("status") == "ZERO_RESULTS":
        return StreetViewError(error="no_coverage", detail=f"Street View no tiene cobertura en o cerca de ({lat}, {lon}).")
    if meta.get("status") not in ("OK", "ERROR", "NO_API_KEY"):
        return StreetViewError(error=f"status_{meta.get('status')}", detail=meta.get("error", ""))

    panorama_id = meta.get("pano_id") if meta.get("status") == "OK" else None
    actual_lat = meta.get("location", {}).get("lat") if meta.get("status") == "OK" else None
    actual_lon = meta.get("location", {}).get("lng") if meta.get("status") == "OK" else None

    params = {
        "location": f"{lat},{lon}",
        "size": f"{size[0]}x{size[1]}",
        "heading": heading,
        "pitch": pitch,
        "fov": fov,
        "key": api_key,
    }
    try:
        r = httpx.get(GOOGLE_SV_BASE, params=params, timeout=20.0)
    except Exception as e:
        return StreetViewError(error="fetch_error", detail=str(e))

    if r.status_code != 200:
        return StreetViewError(error=f"http_{r.status_code}", detail=r.text[:300])

    try:
        img = Image.open(BytesIO(r.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return StreetViewError(error="image_decode_error", detail=str(e))

    note = None
    if actual_lat and abs(actual_lat - lat) > 0.005:
        note = f"Panorama ubicado a ~{abs(actual_lat - lat) * 111:.1f} km de las coords pedidas."

    return StreetViewResult(
        base64_jpeg=b64,
        lat=lat, lon=lon,
        heading=heading, pitch=pitch, fov=fov,
        panorama_id=panorama_id,
        actual_lat=actual_lat,
        actual_lon=actual_lon,
        note=note,
    )


# OpenAI tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "street_view",
        "description": (
            "Pedir una foto de Street View desde coords específicas, mirando hacia un heading "
            "(0=norte, 90=este, 180=sur, 270=oeste) con pitch (-90 a +90, 0=horizonte). "
            "La imagen viene en el siguiente turn. Útil para verificar visualmente: '¿este lugar "
            "se parece a la foto target?'. NO tiene cobertura en zonas rurales / históricas / "
            "fuera de occidente — si no hay cobertura, devuelve error 'no_coverage'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "heading": {
                    "type": "number",
                    "description": "Dirección de la cámara, 0-360. 0=norte, 90=este, 180=sur, 270=oeste.",
                    "default": 0,
                },
                "pitch": {
                    "type": "number",
                    "description": "Ángulo vertical, -90 a +90. 0=horizonte, +up, -down.",
                    "default": 0,
                },
                "fov": {
                    "type": "integer",
                    "description": "Field of view, 1-120. Default 90 (vista normal). Menor = más zoom.",
                    "default": 90,
                },
            },
            "required": ["lat", "lon"],
        },
    },
}
