"""historical_query: queries Overpass sobre OpenHistoricalMap (OHM, CC0).

OHM tiene dimensión temporal: cada feature puede tener `start_date` y `end_date`.
Permite preguntar "¿qué edificios/calles/lugares existían en zona X en año Y?".

Es la pieza diferencial del proyecto. NO requiere API key.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import httpx


# OHM Overpass endpoint (CC0)
OHM_OVERPASS = "https://overpass-api.openhistoricalmap.org/api/interpreter"

# Categorías comunes preconfiguradas. Algunos presets compinan múltiples tags Overpass.
# Forma single-tag: '"key"="value"' o '"key"'.
# Forma multi-tag: lista de filtros que se OR en el body Overpass.
PRESET_QUERIES = {
    "buildings": ['"building"'],
    "churches": [
        '"amenity"="place_of_worship"',
        '"building"="church"',
        '"building"="cathedral"',
        '"building"="chapel"',
        '"historic"="church"',
        '"religion"',
    ],
    "schools": ['"amenity"="school"', '"building"="school"'],
    "factories": ['"man_made"="works"', '"landuse"="industrial"'],
    "railway_stations": ['"railway"="station"', '"public_transport"="station"'],
    "monuments": ['"historic"="monument"', '"historic"="memorial"', '"tourism"="monument"'],
    "houses": ['"building"="residential"', '"building"="house"', '"building"="apartments"'],
    "all_named": ['"name"'],
}


@dataclass
class HistoricalFeature:
    osm_id: str  # ej "way/12345"
    name: Optional[str]
    type: Optional[str]
    tags: dict
    lat: Optional[float] = None
    lon: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    # "high" si tiene start_date confirmado <= year + (no end o end>=year).
    # "low" si NO tiene fechas (asumimos pero sin confirmar).
    # "n/a" si no se filtró por año.
    temporal_confidence: str = "n/a"

    def to_dict(self) -> dict:
        return {
            "osm_id": self.osm_id,
            "name": self.name,
            "type": self.type,
            "lat": self.lat,
            "lon": self.lon,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "temporal_confidence": self.temporal_confidence,
            "tags": self.tags,
        }


@dataclass
class HistoricalQueryResponse:
    bbox: list[float]
    year: Optional[int]
    preset: Optional[str]
    custom_query: Optional[str]
    n_features: int
    features: list[HistoricalFeature] = field(default_factory=list)
    truncated: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "bbox": self.bbox,
            "year": self.year,
            "preset": self.preset,
            "n_features": self.n_features,
            "features": [f.to_dict() for f in self.features],
            "truncated": self.truncated,
            "error": self.error,
        }


def _parse_year_from_date(date_str: Optional[str]) -> Optional[int]:
    """Extraer año de un date_str de OHM.

    OHM usa formato ISO incompleto: '1900', '1900-05', '1900-05-12', '1900-05-12T00:00:00'.
    También acepta strings tipo 'circa 1900' (rare).
    """
    if not date_str:
        return None
    # Take first 4 digits as year
    import re
    m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", date_str)
    if m:
        return int(m.group(1))
    return None


def _feature_existed_in_year(tags: dict, year: int) -> bool:
    """¿Esta feature existía en `year` según sus tags?

    Reglas:
    - Si tiene start_date: start_date <= year.
    - Si tiene end_date: end_date >= year.
    - Si no tiene ninguno, asumimos que sí (no podemos descartar).
    """
    start = _parse_year_from_date(tags.get("start_date"))
    end = _parse_year_from_date(tags.get("end_date"))
    if start is not None and start > year:
        return False
    if end is not None and end < year:
        return False
    return True


def historical_query(
    south: float,
    west: float,
    north: float,
    east: float,
    preset: Optional[str] = None,
    custom_overpass: Optional[str] = None,
    year: Optional[int] = None,
    require_dated: bool = False,
    max_features: int = 30,
) -> HistoricalQueryResponse:
    """Buscar features OHM en un bounding box, opcionalmente filtrando por año.

    Args:
        south, west, north, east: bounding box (lat sur, lon oeste, lat norte, lon este).
        preset: categoría predefinida. Ver PRESET_QUERIES. Ej: "buildings", "churches".
        custom_overpass: Overpass QL custom (avanzado). Ignora preset si está dado.
        year: año a filtrar. Si dado, devuelve solo features que existían en esa fecha.
        require_dated: si True y year is not None, descarta features sin start_date/end_date.
                       Útil para queries estrictas sobre OHM (cobertura desigual: muchas
                       features no tienen tags temporales).
        max_features: cap de features devueltas.

    Returns:
        HistoricalQueryResponse con features. Cada feature incluye `temporal_confidence`:
        - "high" si tiene start_date <= year y (no end_date o end_date >= year).
        - "low" si NO tiene fechas (asumimos pero no podemos confirmar).
        - "n/a" si no se filtró por año.
    """
    if preset and preset not in PRESET_QUERIES and not custom_overpass:
        return HistoricalQueryResponse(
            bbox=[south, west, north, east], year=year, preset=preset, custom_query=None,
            n_features=0, error=f"preset '{preset}' inválido. Disponibles: {list(PRESET_QUERIES)}"
        )

    if custom_overpass:
        body = custom_overpass
    elif preset:
        # Preset puede ser lista de tags — generar múltiples nwr OR'd
        tags = PRESET_QUERIES[preset]
        if isinstance(tags, str):
            tags = [tags]
        body = "\n".join(f'nwr[{t}]({south},{west},{north},{east});' for t in tags)
    else:
        body = f'nwr["name"]({south},{west},{north},{east});'

    # Filtrado temporal en Python (más robusto que [date:] de Overpass OHM).
    # Pedimos extra para compensar el filtrado.
    fetch_size = max_features * 3 if year else max_features + 5
    query = f"""
    [out:json][timeout:30];
    (
      {body}
    );
    out tags center {fetch_size};
    """.strip()

    try:
        r = httpx.post(OHM_OVERPASS, data={"data": query}, timeout=45.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return HistoricalQueryResponse(
            bbox=[south, west, north, east], year=year, preset=preset, custom_query=custom_overpass,
            n_features=0, error=f"overpass_error: {e}"
        )

    elements = data.get("elements", [])
    features = []
    filtered_by_year = 0
    seen_ids = set()  # dedupe (porque pueden venir en múltiples queries OR'd)
    for el in elements:
        if len(features) >= max_features:
            break
        osm_id = f"{el['type']}/{el['id']}"
        if osm_id in seen_ids:
            continue
        seen_ids.add(osm_id)
        tags = el.get("tags", {})
        start_d = tags.get("start_date")
        end_d = tags.get("end_date")
        has_dates = bool(start_d or end_d)
        # Filtrar por año si fue dado
        if year is not None:
            if require_dated and not has_dates:
                filtered_by_year += 1
                continue
            if not _feature_existed_in_year(tags, year):
                filtered_by_year += 1
                continue
            tc = "high" if has_dates else "low"
        else:
            tc = "n/a"
        name = tags.get("name") or tags.get("name:en") or tags.get("name:ru")
        if "lat" in el and "lon" in el:
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"].get("lat"), el["center"].get("lon")
        else:
            lat, lon = None, None
        features.append(HistoricalFeature(
            osm_id=osm_id,
            name=name,
            type=el["type"],
            tags=tags,
            lat=lat,
            lon=lon,
            start_date=start_d,
            end_date=end_d,
            temporal_confidence=tc,
        ))

    return HistoricalQueryResponse(
        bbox=[south, west, north, east], year=year, preset=preset, custom_query=custom_overpass,
        n_features=len(features), features=features,
        truncated=len(elements) > max_features,
    )


# OpenAI tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "historical_query",
        "description": (
            "Buscar features históricos (edificios, iglesias, calles, etc.) en una zona geográfica, "
            "opcionalmente filtrando por año. Usa OpenHistoricalMap (versión histórica de OSM con "
            "dimensión temporal). Devuelve lista de features con nombre, coords, tags, fechas. "
            "Cada feature trae `temporal_confidence`: 'high' si tiene start_date confirmado, 'low' "
            "si no tiene tags temporales (asume que existía en el año pero sin confirmar). "
            "OHM tiene cobertura DESIGUAL: ausencia de resultados NO prueba ausencia histórica."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "south": {"type": "number", "description": "Latitud sur del bbox."},
                "west": {"type": "number", "description": "Longitud oeste."},
                "north": {"type": "number", "description": "Latitud norte."},
                "east": {"type": "number", "description": "Longitud este."},
                "preset": {
                    "type": "string",
                    "description": "Categoría predefinida. Opciones: buildings, churches, schools, factories, railway_stations, monuments, all_named.",
                    "enum": list(PRESET_QUERIES.keys()),
                },
                "year": {
                    "type": "integer",
                    "description": "Año a filtrar. Si dado, devuelve solo features que existían en esa fecha.",
                },
                "require_dated": {
                    "type": "boolean",
                    "description": "Si true (con year dado), descarta features sin start_date/end_date. Útil para queries estrictas.",
                    "default": False,
                },
                "max_features": {
                    "type": "integer",
                    "description": "Cap de features (1-50). Default 30.",
                    "default": 30,
                },
            },
            "required": ["south", "west", "north", "east"],
        },
    },
}
