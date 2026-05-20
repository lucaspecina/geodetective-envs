"""google_api: cliente unificado para Google Maps Platform APIs con cache compartido.

Cubre los endpoints que usamos en geodetective:
- Static Maps (snapshot)
- Street View Static + Metadata (free)
- Places API New: Nearby Search (categorizada para benchmark geo)
- Elevation API: punto único o muestreo en path

Características:
- Cache compartido por endpoint con TTL configurable
- Cuantización de coords a ~10m precision para mejorar hit rate (4 decimals)
- Error handling parcial NO-FATAL: si una API falla, devolvemos {} y el caller decide
- Cliente httpx único reutilizable

Refs:
- Issue #41 (Fase 2 tools redesign)
- research/synthesis/tools_redesign.md
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


# === Endpoints ===
GOOGLE_MAPS_BASE = "https://maps.googleapis.com/maps/api"
PLACES_NEW_BASE = "https://places.googleapis.com/v1"
ELEVATION_BASE = f"{GOOGLE_MAPS_BASE}/elevation/json"
STATIC_MAPS_BASE = f"{GOOGLE_MAPS_BASE}/staticmap"
STREET_VIEW_BASE = f"{GOOGLE_MAPS_BASE}/streetview"
STREET_VIEW_META = f"{GOOGLE_MAPS_BASE}/streetview/metadata"


# === Cache ===
# Estructura: {endpoint: {key: (timestamp, value)}}
_cache: dict[str, dict[tuple, tuple[float, Any]]] = {}

# TTL por endpoint (segundos). None = indefinido (terrain no cambia)
_TTL: dict[str, Optional[float]] = {
    "places_nearby": 3600.0,         # 1 hora
    "elevation_point": None,          # indefinido — la altitud no cambia
    "streetview_metadata": 3600.0,    # 1 hora (coverage puede cambiar)
}


def _cache_get(endpoint: str, key: tuple) -> Optional[Any]:
    bucket = _cache.get(endpoint)
    if bucket is None:
        return None
    entry = bucket.get(key)
    if entry is None:
        return None
    ts, value = entry
    ttl = _TTL.get(endpoint)
    if ttl is not None and (time.time() - ts) > ttl:
        return None
    return value


def _cache_set(endpoint: str, key: tuple, value: Any) -> None:
    _cache.setdefault(endpoint, {})[key] = (time.time(), value)


def _quantize_coord(lat: float, lon: float, precision: int = 4) -> tuple[float, float]:
    """Cuantizar coords para mejorar cache hit rate. 4 decimals ≈ 11m precision."""
    return (round(lat, precision), round(lon, precision))


def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY no está en environment.")
    return key


# === Places API (New) — Nearby Search ===

# Categorías ranqueadas por relevancia para geo-investigación histórica.
# Codex review: monumentos > estaciones > iglesias > puentes > plazas > parques > cafés.
PLACES_RELEVANCE_ORDER = [
    "tourist_attraction",       # monumentos, landmarks
    "museum",
    "historical_landmark",
    "train_station", "subway_station", "transit_station",
    "church", "mosque", "synagogue", "hindu_temple", "place_of_worship",
    "bridge",
    "square", "town_square",
    "park",
    "city_hall", "government_office",
    "stadium",
    "library",
    "art_gallery",
    "school", "university",
    "store", "shopping_mall",
    "restaurant", "cafe", "bar",
]


@dataclass
class PlaceInfo:
    name: str
    primary_type: str
    distance_m: float
    relevance_score: int  # menor = más relevante (índice en PLACES_RELEVANCE_ORDER)
    location: dict = field(default_factory=dict)  # {"lat": ..., "lng": ...}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.primary_type,
            "distance_m": round(self.distance_m, 1),
        }


def _relevance_score(place_type: str) -> int:
    """Score más bajo = más relevante. Devuelve len si no está en la lista (cae al final)."""
    try:
        return PLACES_RELEVANCE_ORDER.index(place_type)
    except ValueError:
        return len(PLACES_RELEVANCE_ORDER)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    R = 6371000
    lat1r, lat2r = radians(lat1), radians(lat2)
    dlat = lat2r - lat1r
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def get_places_nearby(
    lat: float, lon: float,
    radius_m: int = 200,
    max_results: int = 5,
    timeout: float = 15.0,
) -> list[PlaceInfo]:
    """Places API New: Nearby Search categorizada por relevancia geo-histórica.

    Returns: lista ranqueada por relevancia + distancia. Vacía si falla (no fatal).
    """
    q_lat, q_lon = _quantize_coord(lat, lon)
    cache_key = ("nearby", q_lat, q_lon, radius_m, max_results)
    cached = _cache_get("places_nearby", cache_key)
    if cached is not None:
        return cached

    try:
        api_key = _get_api_key()
    except RuntimeError:
        return []

    url = f"{PLACES_NEW_BASE}/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.primaryType,places.location,places.types",
    }
    body = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": float(radius_m),
            }
        },
        "maxResultCount": min(20, max_results * 4),  # overfetch para filtrar
    }

    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []

    places_raw = data.get("places", []) or []
    parsed: list[PlaceInfo] = []
    for p in places_raw:
        name = (p.get("displayName") or {}).get("text", "") or ""
        ptype = p.get("primaryType", "") or ""
        loc = p.get("location") or {}
        plat = loc.get("latitude")
        plon = loc.get("longitude")
        if plat is None or plon is None or not name:
            continue
        dist = _haversine_m(lat, lon, plat, plon)
        # Si primaryType no está, intentar usar el primer tipo de la lista
        if not ptype:
            types = p.get("types") or []
            ptype = types[0] if types else ""
        score = _relevance_score(ptype)
        parsed.append(PlaceInfo(
            name=name,
            primary_type=ptype or "unknown",
            distance_m=dist,
            relevance_score=score,
            location={"lat": plat, "lng": plon},
        ))

    # Ordenar: relevance ascendente (menor = mejor), luego distancia
    parsed.sort(key=lambda p: (p.relevance_score, p.distance_m))
    out = parsed[:max_results]
    _cache_set("places_nearby", cache_key, out)
    return out


# === Elevation API ===

@dataclass
class ElevationResult:
    elevation_m: float
    terrain_category: str  # "flat" / "rolling" / "mountainous"
    samples_summary: dict = field(default_factory=dict)  # {min, max, mean, std} de samples en radio

    def to_dict(self) -> dict:
        out = {
            "elevation_m": round(self.elevation_m, 1),
            "terrain_category": self.terrain_category,
        }
        if self.samples_summary:
            out["samples_summary"] = self.samples_summary
        return out


def _categorize_terrain(std_m: float) -> str:
    """Categorizar terreno por desviación estándar de elevación en el radio."""
    if std_m < 15:
        return "flat"
    elif std_m < 80:
        return "rolling"
    else:
        return "mountainous"


def get_elevation(
    lat: float, lon: float,
    radius_samples_m: int = 1000,  # radio para muestrear terrain category
    n_samples: int = 9,             # 3x3 grid
    timeout: float = 15.0,
) -> Optional[ElevationResult]:
    """Elevation API: altitud del punto + categorización de terreno en radio.

    Returns: ElevationResult o None si falla.
    """
    q_lat, q_lon = _quantize_coord(lat, lon)
    cache_key = ("elev", q_lat, q_lon, radius_samples_m, n_samples)
    cached = _cache_get("elevation_point", cache_key)
    if cached is not None:
        return cached

    try:
        api_key = _get_api_key()
    except RuntimeError:
        return None

    # Construir 3x3 grid alrededor del punto para samples
    # 1 grado lat ≈ 111km, así que radius/111000 es el delta
    delta_lat = radius_samples_m / 111000.0
    # ajuste lon por cos(lat) — pero a estas latitudes simplificado
    from math import cos, radians
    delta_lon = radius_samples_m / (111000.0 * max(0.1, cos(radians(lat))))

    locations = [(lat, lon)]  # punto central primero
    # 3x3 grid
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            locations.append((lat + dy * delta_lat, lon + dx * delta_lon))

    locs_str = "|".join(f"{la},{lo}" for la, lo in locations[:n_samples + 1])
    params = {"locations": locs_str, "key": api_key}

    try:
        r = httpx.get(ELEVATION_BASE, params=params, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    results = data.get("results", []) or []
    if not results:
        return None

    # Primer resultado = punto central
    center_elev = float(results[0].get("elevation", 0))
    elevations = [float(r.get("elevation", 0)) for r in results]

    if len(elevations) > 1:
        # Estadísticas del grid
        mean = sum(elevations) / len(elevations)
        variance = sum((e - mean) ** 2 for e in elevations) / len(elevations)
        std = variance ** 0.5
        summary = {
            "min_m": round(min(elevations), 1),
            "max_m": round(max(elevations), 1),
            "mean_m": round(mean, 1),
            "std_m": round(std, 1),
        }
        category = _categorize_terrain(std)
    else:
        summary = {}
        category = "unknown"

    out = ElevationResult(
        elevation_m=center_elev,
        terrain_category=category,
        samples_summary=summary,
    )
    _cache_set("elevation_point", cache_key, out)
    return out


# === Street View metadata (free) ===

def get_streetview_metadata(
    lat: float, lon: float,
    radius_m: int = 50,
    timeout: float = 10.0,
) -> dict:
    """Street View Image Metadata API. Free. Devuelve dict (vacío si error)."""
    q_lat, q_lon = _quantize_coord(lat, lon, precision=5)  # más precisión para SV
    cache_key = ("sv_meta", q_lat, q_lon, radius_m)
    cached = _cache_get("streetview_metadata", cache_key)
    if cached is not None:
        return cached

    try:
        api_key = _get_api_key()
    except RuntimeError:
        return {}

    params = {
        "location": f"{lat},{lon}",
        "radius": radius_m,
        "key": api_key,
    }
    try:
        r = httpx.get(STREET_VIEW_META, params=params, timeout=timeout)
        if r.status_code != 200:
            return {}
        data = r.json()
    except Exception:
        return {}

    _cache_set("streetview_metadata", cache_key, data)
    return data
