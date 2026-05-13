"""image_search: buscar imágenes, descargarlas, hashing perceptual.

Backend: **DuckDuckGo Images** (via `ddgs` Python package — gratis, sin API key,
usa Bing por debajo). Migrado desde Tavily (cuota agotada).

Cada imagen viene con un flag `is_likely_target` si su hash perceptual coincide con la
foto objetivo (hamming distance < threshold). NO bloqueamos — flagueamos.

Esto le dice al agente "esa imagen es la foto target o casi-igual" para que decida
qué hacer (debería pivotar y no usarla como respuesta).

También es útil para nuestro logging: medimos qué tan "encontrable" es cada foto del corpus.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable, Optional

import httpx
import imagehash
from ddgs import DDGS
from PIL import Image

from ..corpus.blacklist import is_blocked

MATCH_THRESHOLD = 8  # hamming distance < esto = "casi igual a target"


@dataclass
class ImageSearchResult:
    url: str
    base64_jpeg: str  # resized 512x512 max
    hamming_distance: Optional[int]
    is_likely_target: bool
    title: str = ""

    def metadata_only(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "hamming_distance": self.hamming_distance,
            "is_likely_target": self.is_likely_target,
        }


@dataclass
class ImageSearchResponse:
    query: str
    images: list[ImageSearchResult] = field(default_factory=list)
    blocked_domain_count: int = 0
    download_failed_count: int = 0
    total_raw_urls: int = 0
    target_match_count: int = 0


# === Cache liviano (sin TTL, in-memory) ===
_cache: dict[tuple, ImageSearchResponse] = {}


def image_search(
    query: str,
    max_results: int = 3,
    target_image_path: Optional[str] = None,
    excluded_domains: Optional[Iterable[str]] = None,
) -> ImageSearchResponse:
    """Buscar imágenes en la web via DuckDuckGo Images.

    Args:
        query: texto de búsqueda.
        max_results: cuántas imágenes (después de filtros). Default 3.
        target_image_path: ruta a la foto target. Si dada, se calcula hash perceptual
                           y cada imagen viene con flag is_likely_target.
        excluded_domains: lista per-photo de hosts a bloquear además del GLOBAL.

    Returns:
        ImageSearchResponse con imágenes (base64) + metadata.
    """
    excluded = list(excluded_domains) if excluded_domains else []
    cache_key = (query, target_image_path, frozenset(excluded), max_results)
    if cache_key in _cache:
        return _cache[cache_key]

    # Hash de la foto target (si se provee)
    target_hash: Optional[imagehash.ImageHash] = None
    if target_image_path:
        try:
            target_hash = imagehash.phash(Image.open(target_image_path))
        except Exception:
            target_hash = None

    # Overfetch para dejar margen al post-filter
    raw_n = max(max_results * 4, 12)
    try:
        ddgs = DDGS()
        raw_items = list(ddgs.images(query, max_results=raw_n))
    except Exception as e:
        # Rate-limit, network, etc. — devolver respuesta vacía con error count.
        response = ImageSearchResponse(query=query)
        response.download_failed_count = 1  # marcador grosero
        return response

    response = ImageSearchResponse(query=query, total_raw_urls=len(raw_items))
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 geodetective-research/0.1"}

    for item in raw_items:
        if len(response.images) >= max_results:
            break
        image_url = item.get("image", "")
        source_page = item.get("url", "")
        title = item.get("title", "")

        # Blocklist check sobre BOTH image URL AND source page URL
        if is_blocked(image_url, excluded) or is_blocked(source_page, excluded):
            response.blocked_domain_count += 1
            continue

        try:
            ir = httpx.get(image_url, timeout=10.0, follow_redirects=True, headers=headers)
        except Exception:
            response.download_failed_count += 1
            continue

        # Recheck post-redirect: el download pudo terminar en otro host
        final_url = str(ir.url)
        if is_blocked(final_url, excluded):
            response.blocked_domain_count += 1
            continue

        if ir.status_code != 200 or len(ir.content) > 5_000_000:
            response.download_failed_count += 1
            continue

        try:
            img = Image.open(BytesIO(ir.content))
        except Exception:
            response.download_failed_count += 1
            continue

        if img.size[0] < 100 or img.size[1] < 100:
            continue  # icon/logo, skip

        if img.mode != "RGB":
            img = img.convert("RGB")

        # Hash perceptual + comparison con target
        this_hash = imagehash.phash(img)
        hamming = None
        is_target = False
        if target_hash is not None:
            hamming = int(this_hash - target_hash)
            is_target = hamming < MATCH_THRESHOLD
            if is_target:
                response.target_match_count += 1

        # Resize a 512x512 max para no explotar tokens
        img.thumbnail((512, 512))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()

        response.images.append(
            ImageSearchResult(
                url=image_url,
                title=title,
                base64_jpeg=b64,
                hamming_distance=hamming,
                is_likely_target=is_target,
            )
        )

    _cache[cache_key] = response
    return response


# === OpenAI tool schema (sin cambios — back-compat) ===
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "image_search",
        "description": (
            "Buscar imágenes en la web (similar a Google Images). Útil para comparar visualmente la "
            "foto target con imágenes de referencia de un tipo de estructura, paisaje o vestimenta. "
            "Vas a recibir las imágenes en el siguiente turno. Cada imagen viene con un flag "
            "is_likely_target=true si su hash perceptual coincide casi exacto con la foto objetivo "
            "— eso significa que encontraste la foto en sí (o una versión casi igual). Usá ese flag "
            "para SABER que esa imagen no debería contar como evidencia investigativa, y para refinar "
            "tu búsqueda. Es más caro en tokens — usalo cuando realmente te ayuda comparar visualmente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto descriptivo de qué tipo de imágenes querés ver."},
                "max_results": {"type": "integer", "description": "Cuántas imágenes (1-5).", "default": 3},
            },
            "required": ["query"],
        },
    },
}
