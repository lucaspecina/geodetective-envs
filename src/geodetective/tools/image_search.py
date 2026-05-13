"""image_search: buscar imágenes con Tavily, bajarlas, hashing perceptual.

Cada imagen viene con un flag `is_likely_target` si su hash perceptual coincide con la
foto objetivo (hamming distance < threshold). NO bloqueamos — flagueamos.

Esto le dice al agente "esa imagen es la foto target o casi-igual" para que decida
qué hacer (debería pivotar y no usarla como respuesta).

También es útil para nuestro logging: medimos qué tan "encontrable" es cada foto del corpus.
"""
from __future__ import annotations
import os
import base64
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable, Optional
import httpx
from PIL import Image
import imagehash
from tavily import TavilyClient

from ..corpus.blacklist import is_blocked


MATCH_THRESHOLD = 8  # hamming distance < esto = "casi igual a target"


@dataclass
class ImageSearchResult:
    url: str
    base64_jpeg: str  # resized 512x512 max
    hamming_distance: Optional[int]
    is_likely_target: bool

    def metadata_only(self) -> dict:
        return {"url": self.url, "hamming_distance": self.hamming_distance, "is_likely_target": self.is_likely_target}


@dataclass
class ImageSearchResponse:
    query: str
    images: list[ImageSearchResult] = field(default_factory=list)
    blocked_domain_count: int = 0
    download_failed_count: int = 0
    total_raw_urls: int = 0
    target_match_count: int = 0


def image_search(
    query: str,
    max_results: int = 3,
    target_image_path: Optional[str] = None,
    excluded_domains: Optional[Iterable[str]] = None,
) -> ImageSearchResponse:
    """Buscar imágenes en la web con Tavily.

    Args:
        query: texto de búsqueda.
        max_results: cuántas imágenes (después de filtros). Default 3 para limitar tokens.
        target_image_path: ruta a la foto target. Si dada, se calcula hash perceptual y
                           cada imagen viene con flag is_likely_target.
        excluded_domains: lista per-photo de hosts a bloquear además del GLOBAL.

    Returns:
        ImageSearchResponse con imágenes (base64) + metadata.
    """
    if not os.environ.get("TAVILY_API_KEY"):
        raise RuntimeError("TAVILY_API_KEY no está en environment.")
    excluded = list(excluded_domains) if excluded_domains else []

    target_hash: Optional[imagehash.ImageHash] = None
    if target_image_path:
        try:
            target_hash = imagehash.phash(Image.open(target_image_path))
        except Exception:
            target_hash = None

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    raw = client.search(query, max_results=max_results * 3, include_images=True, search_depth="advanced")

    image_urls: list[str] = raw.get("images", []) or []
    response = ImageSearchResponse(query=query, total_raw_urls=len(image_urls))

    headers = {"User-Agent": "geodetective-research/0.1"}

    for img_url in image_urls:
        if len(response.images) >= max_results:
            break
        if is_blocked(img_url, excluded):
            response.blocked_domain_count += 1
            continue
        try:
            ir = httpx.get(img_url, timeout=10.0, follow_redirects=True, headers=headers)
            # Recheck post-redirect: el download pudo terminar en otro host.
            if is_blocked(str(ir.url), excluded):
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
                continue  # probably icon/logo, skip
            if img.mode != "RGB":
                img = img.convert("RGB")
            # Hash perceptual
            this_hash = imagehash.phash(img)
            hamming = None
            is_target = False
            if target_hash is not None:
                hamming = int(this_hash - target_hash)
                is_target = hamming < MATCH_THRESHOLD
                if is_target:
                    response.target_match_count += 1
            # Resize
            img.thumbnail((512, 512))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode()
            response.images.append(
                ImageSearchResult(
                    url=img_url,
                    base64_jpeg=b64,
                    hamming_distance=hamming,
                    is_likely_target=is_target,
                )
            )
        except Exception:
            response.download_failed_count += 1
            continue

    return response


# OpenAI tool schema
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
