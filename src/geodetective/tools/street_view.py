"""street_view: Google Street View Static API.

Devuelve foto(s) de Street View desde coords. Modos:
- single heading: una imagen mirando hacia un ángulo específico.
- contact sheet: 4 imágenes (N, E, S, W) automáticas para cobertura completa.
- nearby (v2 #41): explorar 3-4 panoramas reales en radio ~50m usando Street View
  metadata API. Imita "caminar la cuadra".

Cobertura limitada en zonas rurales / históricas / fuera de occidente. Si no hay
cobertura, devolvemos error 'no_coverage' (verificado vía Metadata API que es free).

Requiere GOOGLE_MAPS_API_KEY.
"""
from __future__ import annotations
import os
import base64
from io import BytesIO
from typing import Optional
from dataclasses import dataclass, field
import httpx
from PIL import Image

from .google_api import get_places_nearby, PlaceInfo


GOOGLE_SV_BASE = "https://maps.googleapis.com/maps/api/streetview"
GOOGLE_SV_META = "https://maps.googleapis.com/maps/api/streetview/metadata"


@dataclass
class StreetViewImage:
    base64_jpeg: str
    heading: float
    pitch: float
    fov: int


@dataclass
class NearbyPanorama:
    """Un panorama vecino al centro pedido (v2 #41)."""
    panorama_id: str
    lat: float
    lon: float
    pano_date: Optional[str] = None
    images: list[StreetViewImage] = field(default_factory=list)  # 1-2 imágenes por pano
    distance_from_center_m: float = 0.0


@dataclass
class StreetViewResult:
    images: list[StreetViewImage]  # 1 o 4 imágenes (single vs contact_sheet)
    lat: float
    lon: float
    panorama_id: Optional[str] = None
    pano_date: Optional[str] = None  # fecha de captura del panorama (ej "2021-10")
    actual_lat: Optional[float] = None
    actual_lon: Optional[float] = None
    distance_to_pano_m: Optional[float] = None  # distancia entre coords pedidas y panorama real
    note: Optional[str] = None
    # v2 (#41): nearby exploration + POIs cercanos
    nearby_panoramas: list[NearbyPanorama] = field(default_factory=list)
    nearby_pois: list[PlaceInfo] = field(default_factory=list)


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


def _fetch_sv_image(lat: float, lon: float, heading: float, pitch: float, fov: int, size: tuple[int, int], api_key: str) -> Optional[StreetViewImage]:
    """Helper: bajar 1 imagen Street View."""
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
        if r.status_code != 200:
            return None
        img = Image.open(BytesIO(r.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return StreetViewImage(
            base64_jpeg=base64.b64encode(buf.getvalue()).decode(),
            heading=heading, pitch=pitch, fov=fov,
        )
    except Exception:
        return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, sin, cos, asin, sqrt
    R = 6371000
    lat1r, lat2r = radians(lat1), radians(lat2)
    dlat = lat2r - lat1r
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _find_nearby_panoramas(lat: float, lon: float, radius_m: int = 50,
                           max_panos: int = 4) -> list[dict]:
    """Encontrar panorámicas únicas en radio del centro usando Metadata API (free).

    Estrategia: probar varios puntos en grid alrededor del centro, recolectar
    pano_ids únicos (Codex review: panoramas REALES sobre calles, no construir
    headings cardinales desde coords arbitrarias).

    Returns: lista de dicts con pano_id/lat/lon/date, ordenada por distancia del centro.
    """
    from math import cos, radians
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return []

    # Probar 8 puntos en círculo + centro (≈ 1 deg ≈ 111km, radius/111000 = grados)
    delta_lat = radius_m / 111000.0
    delta_lon = radius_m / (111000.0 * max(0.1, cos(radians(lat))))

    probe_points = [(lat, lon)]  # centro
    for angle_deg in (0, 45, 90, 135, 180, 225, 270, 315):
        from math import sin, radians as rad
        a = rad(angle_deg)
        plat = lat + sin(a) * delta_lat
        plon = lon + cos(a) * delta_lon
        probe_points.append((plat, plon))

    seen_panos: dict[str, dict] = {}
    for plat, plon in probe_points:
        meta = check_street_view_coverage(plat, plon, radius=radius_m)
        if meta.get("status") != "OK":
            continue
        pano_id = meta.get("pano_id", "")
        if not pano_id or pano_id in seen_panos:
            continue
        loc = meta.get("location", {})
        actual_lat = loc.get("lat", plat)
        actual_lon = loc.get("lng", plon)
        seen_panos[pano_id] = {
            "panorama_id": pano_id,
            "lat": actual_lat,
            "lon": actual_lon,
            "date": meta.get("date"),
            "distance_from_center_m": _haversine_m(lat, lon, actual_lat, actual_lon),
        }
        if len(seen_panos) >= max_panos:
            break

    out = list(seen_panos.values())
    out.sort(key=lambda p: p["distance_from_center_m"])
    return out


def street_view(
    lat: float,
    lon: float,
    heading: float = 0.0,
    pitch: float = 0.0,
    fov: int = 90,
    contact_sheet: bool = False,
    nearby: bool = False,
    size: tuple[int, int] = (640, 640),
    enrich_pois: bool = True,
) -> StreetViewResult | StreetViewError:
    """Pedir Street View desde coords. Single heading, contact sheet, o nearby exploration.

    Args:
        lat, lon: coordenadas.
        heading: dirección de la cámara (solo si contact_sheet=False y nearby=False). 0=norte, 90=este.
        pitch: ángulo vertical, -90 a +90. Default 0=horizonte.
        fov: field of view, 1-120. Default 90.
        contact_sheet: si True, devuelve 4 imágenes (heading 0/90/180/270 = N/E/S/W).
        nearby: v2 (#41). Si True, además del centro busca 3-4 panoramas REALES en radio ~50m
                (sobre calles, usando Street View metadata) y devuelve 1-2 imágenes por cada uno.
                Imita "caminar la cuadra".
        size: ancho x alto.
        enrich_pois: v2. Si True, agrega POIs cercanos (Places API radius 30m).

    Returns:
        StreetViewResult con `images` (centro) + opcional `nearby_panoramas` y `nearby_pois`.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return StreetViewError(error="no_api_key", detail="GOOGLE_MAPS_API_KEY no en environment.")

    # Coverage check (free)
    meta = check_street_view_coverage(lat, lon, radius=200)
    if meta.get("status") == "ZERO_RESULTS":
        return StreetViewError(error="no_coverage", detail=f"Street View no tiene cobertura cerca de ({lat}, {lon}).")
    if meta.get("status") not in ("OK", "ERROR", "NO_API_KEY"):
        return StreetViewError(error=f"status_{meta.get('status')}", detail=meta.get("error", ""))

    panorama_id = meta.get("pano_id") if meta.get("status") == "OK" else None
    pano_date = meta.get("date") if meta.get("status") == "OK" else None
    actual_lat = meta.get("location", {}).get("lat") if meta.get("status") == "OK" else None
    actual_lon = meta.get("location", {}).get("lng") if meta.get("status") == "OK" else None

    distance_m = None
    if actual_lat is not None and actual_lon is not None:
        distance_m = _haversine_m(lat, lon, actual_lat, actual_lon)

    if contact_sheet:
        headings = [0.0, 90.0, 180.0, 270.0]
    else:
        headings = [heading]

    images = []
    for h in headings:
        img = _fetch_sv_image(lat, lon, h, pitch, fov, size, api_key)
        if img is not None:
            images.append(img)

    if not images:
        return StreetViewError(error="image_fetch_failed", detail="Coverage existe pero todas las imágenes fallaron.")

    note_parts = []
    if distance_m is not None and distance_m > 100:
        note_parts.append(f"Panorama está a {distance_m:.0f} m de las coords pedidas.")
    if pano_date:
        note_parts.append(f"Panorama capturado en {pano_date}.")
    if contact_sheet:
        note_parts.append("Contact sheet: 4 imágenes (N/E/S/W).")

    # === v2 (#41): nearby exploration ===
    nearby_panoramas: list[NearbyPanorama] = []
    if nearby:
        candidates = _find_nearby_panoramas(lat, lon, radius_m=50, max_panos=4)
        # Excluir el panorama central (mismo pano_id) si está en la lista
        candidates = [c for c in candidates if c["panorama_id"] != panorama_id]
        for cand in candidates[:3]:  # max 3 panoramas extra
            plat = cand["lat"]
            plon = cand["lon"]
            # Pedir 2 imágenes por panorama vecino: heading 0 y heading 180 (vista opuesta)
            pano_images = []
            for h in (0.0, 180.0):
                img = _fetch_sv_image(plat, plon, h, pitch, fov, size, api_key)
                if img is not None:
                    pano_images.append(img)
            if pano_images:
                nearby_panoramas.append(NearbyPanorama(
                    panorama_id=cand["panorama_id"],
                    lat=plat, lon=plon,
                    pano_date=cand.get("date"),
                    images=pano_images,
                    distance_from_center_m=cand["distance_from_center_m"],
                ))
        if nearby_panoramas:
            note_parts.append(f"Nearby: {len(nearby_panoramas)} panoramas extra en radio 50m.")

    # === v2 (#41): POIs cercanos enriquecidos ===
    nearby_pois: list[PlaceInfo] = []
    if enrich_pois:
        try:
            nearby_pois = get_places_nearby(lat, lon, radius_m=30, max_results=3)
        except Exception:
            nearby_pois = []
        if nearby_pois:
            top_names = ", ".join(f"{p.name}({p.distance_m:.0f}m)" for p in nearby_pois[:3])
            note_parts.append(f"POIs cercanos (radio 30m): {top_names}.")

    return StreetViewResult(
        images=images,
        lat=lat, lon=lon,
        panorama_id=panorama_id, pano_date=pano_date,
        actual_lat=actual_lat, actual_lon=actual_lon,
        distance_to_pano_m=distance_m,
        note=" ".join(note_parts) if note_parts else None,
        nearby_panoramas=nearby_panoramas,
        nearby_pois=nearby_pois,
    )


# OpenAI tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "street_view",
        "description": (
            "Pedir Street View desde coords. 2 modos: single heading (1 imagen), o contact_sheet=True "
            "(4 imágenes auto: N/E/S/W = headings 0/90/180/270). La imagen incluye fecha del panorama "
            "y distancia entre las coords pedidas y el panorama real. Sin cobertura → error 'no_coverage'. "
            "**Recomendación**: cuando estás VERIFICANDO una hipótesis (creés haber encontrado el lugar), "
            "usá `contact_sheet=True` — ver el lugar desde 4 ángulos te ayuda a no comprometerte a una "
            "sola vista que puede no representar el lugar completo. Para exploración inicial rápida o "
            "para mirar un detalle específico en cierta dirección, usá single heading."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "heading": {
                    "type": "number",
                    "description": "Dirección de la cámara 0-360 (solo si contact_sheet=false). 0=norte, 90=este.",
                    "default": 0,
                },
                "pitch": {
                    "type": "number",
                    "description": "Ángulo vertical, -90 a +90. 0=horizonte.",
                    "default": 0,
                },
                "fov": {
                    "type": "integer",
                    "description": "Field of view 1-120. Default 90. Menor = más zoom.",
                    "default": 90,
                },
                "contact_sheet": {
                    "type": "boolean",
                    "description": "Si true, devuelve 4 imágenes en N/E/S/W (cobertura completa). Más caro pero útil cuando no sabés qué ángulo mirar.",
                    "default": False,
                },
                "nearby": {
                    "type": "boolean",
                    "description": "Si true, además del punto pedido devuelve hasta 3 panoramas REALES sobre calles vecinas en radio ~50m (2 vistas opuestas c/u). Imita 'caminar la cuadra' — útil para verificar una hipótesis sin comprometerte a un solo punto de vista.",
                    "default": False,
                },
            },
            "required": ["lat", "lon"],
        },
    },
}
