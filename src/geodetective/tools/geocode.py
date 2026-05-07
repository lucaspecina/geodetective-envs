"""Geocoding y reverse geocoding via Nominatim (OSM, free).

Rate limit oficial Nominatim: 1 req/s. User-Agent obligatorio.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional
import httpx


NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "geodetective-research/0.1 (https://github.com/lucaspecina/geodetective-envs)"

# Tracking simple para respetar rate limit (1 req/s)
_last_request_time = [0.0]


def _wait_rate_limit():
    """Esperar al menos 1.1s desde el último request."""
    now = time.time()
    elapsed = now - _last_request_time[0]
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    _last_request_time[0] = time.time()


@dataclass
class GeocodeResult:
    display_name: str
    lat: float
    lon: float
    type: Optional[str] = None  # ej "city", "village", "street"
    importance: Optional[float] = None
    bbox: Optional[list[float]] = None  # [south, north, west, east]
    address: Optional[dict] = None  # ej {"city": "...", "country": "..."}

    def to_dict(self) -> dict:
        return {
            "display_name": self.display_name,
            "lat": self.lat,
            "lon": self.lon,
            "type": self.type,
            "importance": self.importance,
            "bbox": self.bbox,
            "address": self.address,
        }


def geocode(query: str, max_results: int = 3, language: str = "en") -> list[GeocodeResult]:
    """Buscar coords desde nombre/dirección.

    Args:
        query: texto de búsqueda. Ej: "Plaza Mayor, Madrid" o "Серебристый бульвар, Saint Petersburg".
        max_results: cuántos candidatos devolver.
        language: hint de idioma para nominatim (en, es, ru, etc.). NO restringe.

    Returns:
        Lista de candidatos ordenados por relevancia.
    """
    _wait_rate_limit()
    headers = {"User-Agent": USER_AGENT, "Accept-Language": language}
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": max_results,
        "addressdetails": 1,
    }
    try:
        r = httpx.get(f"{NOMINATIM_BASE}/search", params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    results = []
    for item in data:
        try:
            bbox = None
            if item.get("boundingbox"):
                bbox = [float(x) for x in item["boundingbox"]]
            results.append(GeocodeResult(
                display_name=item.get("display_name", ""),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                type=item.get("type"),
                importance=item.get("importance"),
                bbox=bbox,
                address=item.get("address"),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return results


def reverse_geocode(lat: float, lon: float, language: str = "en", zoom: int = 18) -> Optional[GeocodeResult]:
    """Convertir coords a dirección.

    Args:
        lat, lon: coordenadas decimales.
        language: idioma del display_name.
        zoom: nivel de detalle (3=country, 10=city, 17=building, 18=street).
    """
    _wait_rate_limit()
    headers = {"User-Agent": USER_AGENT, "Accept-Language": language}
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "addressdetails": 1,
        "zoom": zoom,
    }
    try:
        r = httpx.get(f"{NOMINATIM_BASE}/reverse", params=params, headers=headers, timeout=15.0)
        r.raise_for_status()
        item = r.json()
    except Exception:
        return None

    if "error" in item:
        return None
    try:
        return GeocodeResult(
            display_name=item.get("display_name", ""),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            type=item.get("type"),
            address=item.get("address"),
        )
    except (KeyError, ValueError, TypeError):
        return None


# OpenAI tool schemas
TOOL_SCHEMA_GEOCODE = {
    "type": "function",
    "function": {
        "name": "geocode",
        "description": (
            "Convertir un nombre/dirección a coordenadas (lat, lon). Usa Nominatim (OSM). "
            "Útil cuando identificás un nombre de calle, plaza, barrio, ciudad y querés sus coords. "
            "Ejemplo: geocode('Серебристый бульвар, Saint Petersburg') → coords del barrio."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nombre del lugar a geolocalizar."},
                "max_results": {"type": "integer", "description": "Cuántos candidatos (1-5).", "default": 3},
                "language": {"type": "string", "description": "Idioma del display_name (en, es, ru, etc.).", "default": "en"},
            },
            "required": ["query"],
        },
    },
}

TOOL_SCHEMA_REVERSE = {
    "type": "function",
    "function": {
        "name": "reverse_geocode",
        "description": (
            "Convertir coordenadas a dirección/nombre del lugar. Útil cuando tenés "
            "una hipótesis de coords y querés saber si corresponden a algo razonable "
            "(ej: '¿esas coords son una calle, un edificio, un campo?')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "zoom": {
                    "type": "integer",
                    "description": "Nivel de detalle: 3=país, 10=ciudad, 17=edificio, 18=calle. Default 18.",
                    "default": 18,
                },
            },
            "required": ["lat", "lon"],
        },
    },
}
