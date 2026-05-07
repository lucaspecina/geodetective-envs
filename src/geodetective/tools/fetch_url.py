"""fetch_url: bajar el contenido de una página web y devolver texto (+ imágenes opcional).

Filtros:
- Domain blacklist (mismo que web_search) — no bajar páginas shortcut.
- Tamaño cap (no bajar páginas gigantes).

Si include_images=True, también baja las imágenes embebidas y calcula hash perceptual
para flagear las que coincidan con la foto target.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from PIL import Image
import imagehash

from .web_search import BLOCKED_DOMAINS


MAX_PAGE_SIZE = 2_000_000  # 2 MB
MAX_TEXT_CHARS = 12_000  # truncate para no inflar tokens
MAX_IMAGES_PER_PAGE = 5  # no más de 5 imágenes por página


def _domain_blocked(url: str) -> bool:
    url_lower = url.lower()
    for d in BLOCKED_DOMAINS:
        if d in url_lower:
            return True
    return False


def _extract_text(html: str) -> str:
    """Extraer texto principal de HTML, sin scripts/styles/nav."""
    soup = BeautifulSoup(html, "lxml")
    # Remover ruido
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    # Texto plano
    text = soup.get_text(separator="\n", strip=True)
    # Limpiar líneas vacías
    lines = [line for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def _extract_image_urls(html: str, base_url: str) -> list[str]:
    """Devolver URLs absolutas de imágenes <img> en el HTML."""
    soup = BeautifulSoup(html, "lxml")
    urls = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        # Resolver URL relativa
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            from urllib.parse import urljoin
            src = urljoin(base_url, src)
        elif not src.startswith("http"):
            from urllib.parse import urljoin
            src = urljoin(base_url, src)
        urls.append(src)
    return urls[:50]  # cap inicial


@dataclass
class FetchedImage:
    url: str
    base64_jpeg: str  # imagen redimensionada a max 512x512, JPEG q80
    hamming_distance: Optional[int] = None  # vs target_hash (si se pasó)
    is_likely_target: bool = False  # True si hamming < threshold

    def to_dict_no_b64(self) -> dict:
        return {"url": self.url, "hamming_distance": self.hamming_distance, "is_likely_target": self.is_likely_target}


@dataclass
class FetchedPage:
    url: str
    status_code: int
    title: str
    text: str  # truncado a MAX_TEXT_CHARS
    text_truncated: bool
    images: list[FetchedImage] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self, include_images_b64: bool = False) -> dict:
        out = {
            "url": self.url,
            "status_code": self.status_code,
            "title": self.title,
            "text": self.text,
            "text_truncated": self.text_truncated,
            "error": self.error,
        }
        if self.images:
            if include_images_b64:
                out["images"] = [{"url": im.url, "base64_jpeg": im.base64_jpeg, "hamming_distance": im.hamming_distance, "is_likely_target": im.is_likely_target} for im in self.images]
            else:
                out["images"] = [im.to_dict_no_b64() for im in self.images]
        return out


def _process_image(image_bytes: bytes, target_hash: Optional[imagehash.ImageHash], match_threshold: int = 8) -> Optional[FetchedImage]:
    """Procesar una imagen bajada: hash perceptual + resize a base64."""
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception:
        return None
    if img.size[0] < 100 or img.size[1] < 100:  # muy chiquita = ruido (logos, iconos)
        return None
    # Convert RGBA/P/etc → RGB
    if img.mode != "RGB":
        img = img.convert("RGB")
    # Hash perceptual sobre original
    this_hash = imagehash.phash(img)
    hamming = None
    is_target = False
    if target_hash is not None:
        hamming = int(this_hash - target_hash)
        is_target = hamming < match_threshold
    # Resize para limitar tokens
    img_thumb = img.copy()
    img_thumb.thumbnail((512, 512))
    buf = BytesIO()
    img_thumb.save(buf, format="JPEG", quality=80)
    import base64
    b64 = base64.b64encode(buf.getvalue()).decode()
    return FetchedImage(url="", base64_jpeg=b64, hamming_distance=hamming, is_likely_target=is_target)


def fetch_url(
    url: str,
    include_images: bool = False,
    target_image_path: Optional[str] = None,
    timeout: float = 20.0,
) -> FetchedPage:
    """Bajar una página y devolver su texto principal (+ imágenes opcional).

    Args:
        url: URL a fetchear.
        include_images: si True, también baja las imágenes embebidas.
        target_image_path: ruta a la foto target (para hash perceptual). Si None, no compara.
        timeout: timeout en segundos.

    Returns:
        FetchedPage con texto + imágenes (con flags).
    """
    if _domain_blocked(url):
        return FetchedPage(url=url, status_code=0, title="", text="", text_truncated=False, error="domain_blocked")

    headers = {"User-Agent": "geodetective-research/0.1 (https://github.com/lucaspecina/geodetective-envs)"}

    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
    except Exception as e:
        return FetchedPage(url=url, status_code=0, title="", text="", text_truncated=False, error=f"fetch_error: {e}")

    if r.status_code != 200:
        return FetchedPage(url=url, status_code=r.status_code, title="", text="", text_truncated=False, error=f"http_{r.status_code}")
    if len(r.content) > MAX_PAGE_SIZE:
        return FetchedPage(url=url, status_code=r.status_code, title="", text="", text_truncated=False, error="page_too_large")

    html = r.text
    text = _extract_text(html)
    truncated = len(text) > MAX_TEXT_CHARS
    text = text[:MAX_TEXT_CHARS]

    title = ""
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()[:200]

    images: list[FetchedImage] = []
    if include_images:
        target_hash = None
        if target_image_path:
            try:
                target_hash = imagehash.phash(Image.open(target_image_path))
            except Exception:
                target_hash = None
        urls = _extract_image_urls(html, url)
        # Filter blocked domains
        urls = [u for u in urls if not _domain_blocked(u)]
        for img_url in urls[:MAX_IMAGES_PER_PAGE * 3]:  # buffer por si fallan algunas
            if len(images) >= MAX_IMAGES_PER_PAGE:
                break
            try:
                ir = httpx.get(img_url, timeout=10.0, follow_redirects=True, headers=headers)
                if ir.status_code != 200 or len(ir.content) > 5_000_000:
                    continue
                fi = _process_image(ir.content, target_hash)
                if fi is None:
                    continue
                fi.url = img_url
                images.append(fi)
            except Exception:
                continue

    return FetchedPage(
        url=url,
        status_code=r.status_code,
        title=title,
        text=text,
        text_truncated=truncated,
        images=images,
    )


# OpenAI tool calling schema
TOOL_SCHEMA_TEXT = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": (
            "Entrar a una página web específica y leer su contenido completo. "
            "Útil cuando un resultado de web_search se ve prometedor y querés "
            "el texto entero de la página, no solo el snippet. "
            "Los dominios shortcut (pastvu.com, wikimedia, flickr, etc.) están bloqueados."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa con http:// o https://"},
            },
            "required": ["url"],
        },
    },
}

TOOL_SCHEMA_WITH_IMAGES = {
    "type": "function",
    "function": {
        "name": "fetch_url_with_images",
        "description": (
            "Igual que fetch_url pero TAMBIÉN baja las imágenes embebidas en la página, "
            "que vas a ver en el siguiente turn. Usalo cuando creas que las imágenes en la "
            "página pueden ayudar a comparar visualmente. Es más caro en tokens — usalo solo "
            "cuando vale la pena. Las imágenes que coinciden visualmente con la foto target "
            "están flagueadas explícitamente con is_likely_target=true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa."},
            },
            "required": ["url"],
        },
    },
}
