"""fetch_url: bajar el contenido de una página web y devolver texto (+ imágenes opcional).

Filtros:
- Blacklist (GLOBAL + per-photo) — re-chequea URL post-redirect.
- Tamaño cap (no bajar páginas gigantes).

Si include_images=True, también baja las imágenes embebidas y calcula hash perceptual
para flagear las que coincidan con la foto target.

**v2 (issue #40)**: cada imagen se devuelve con contexto semántico extraído del HTML:
- alt, title, aria-label del <img>
- figcaption si está en <figure>
- párrafo narrativo cercano (ancestor semántico)
- atributos data-* (data-caption, data-alt-text)
- filename de la URL
- OpenGraph/Twitter Card metadata
- JSON-LD schema.org ImageObject (si lo encuentra)

El modelo recibe la imagen JUNTO con su contexto, no huérfana.
"""
from __future__ import annotations
import base64
import json
import re
import warnings
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpx
import imagehash
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from PIL import Image

from ..corpus.blacklist import is_blocked

# Filtrar warning de bs4 cuando parseamos XML como HTML (es esperado en algunos sitemaps).
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


MAX_PAGE_SIZE = 2_000_000  # 2 MB
MAX_TEXT_CHARS = 12_000  # truncate para no inflar tokens
MAX_IMAGES_PER_PAGE = 10  # v2: bumpeado de 5 a 10
MAX_CONTEXT_CHARS = 300  # chars max de texto narrativo cercano por imagen
MAX_CAPTION_CHARS = 200  # cap por field individual (alt, figcaption, etc.)


# === Dataclasses ===

@dataclass
class ImageContext:
    """Contexto semántico de una imagen extraído del HTML (v2 issue #40)."""
    alt: str = ""
    title: str = ""
    aria_label: str = ""
    figcaption: str = ""
    nearby_text: str = ""  # párrafo en ancestor semántico
    data_caption: str = ""  # atributos data-caption, data-alt-text
    link_text: str = ""  # texto del <a> padre si está en uno
    filename: str = ""  # nombre del archivo de la URL
    og_alt: str = ""  # OpenGraph og:image:alt (si esta imagen es la OG)
    jsonld_caption: str = ""  # de JSON-LD schema.org ImageObject

    def to_dict(self) -> dict:
        """Solo devuelve fields no vacíos."""
        return {k: v for k, v in self.__dict__.items() if v}

    def best_caption(self) -> str:
        """Caption más informativo disponible, priorizando los más estructurados."""
        for field_name in ("figcaption", "jsonld_caption", "og_alt", "alt",
                           "data_caption", "title", "aria_label", "link_text", "nearby_text"):
            v = getattr(self, field_name, "").strip()
            if v:
                return v
        return ""


@dataclass
class FetchedImage:
    url: str
    base64_jpeg: str  # imagen redimensionada a max 512x512, JPEG q80
    hamming_distance: Optional[int] = None  # vs target_hash (si se pasó)
    is_likely_target: bool = False  # True si hamming < threshold
    context: Optional[ImageContext] = None  # v2: contexto semántico del HTML

    def to_dict_no_b64(self) -> dict:
        out = {
            "url": self.url,
            "hamming_distance": self.hamming_distance,
            "is_likely_target": self.is_likely_target,
        }
        if self.context:
            out["context"] = self.context.to_dict()
        return out


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
                out["images"] = [
                    {
                        "url": im.url,
                        "base64_jpeg": im.base64_jpeg,
                        "hamming_distance": im.hamming_distance,
                        "is_likely_target": im.is_likely_target,
                        **({"context": im.context.to_dict()} if im.context else {}),
                    }
                    for im in self.images
                ]
            else:
                out["images"] = [im.to_dict_no_b64() for im in self.images]
        return out


# === Extracción de texto ===

def _extract_text(html: str) -> str:
    """Extraer texto principal de HTML, sin scripts/styles/nav."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


# === Extracción de imágenes con contexto semántico (v2) ===

def _resolve_url(src: str, base_url: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return urljoin(base_url, src)
    if not src.startswith("http"):
        return urljoin(base_url, src)
    return src


def _extract_filename(url: str) -> str:
    """Sacar filename de URL (ej '1947_lisbon_libertad.jpg' → cuenta como hint)."""
    try:
        path = urlparse(url).path
        name = Path(path).stem  # sin extensión
        # Limpiar: quitar IDs largos hex, normalizar separadores
        if re.fullmatch(r"[0-9a-f]{16,}", name, re.IGNORECASE):
            return ""  # nombre solo de hash, irrelevante
        return name.replace("_", " ").replace("-", " ")[:MAX_CAPTION_CHARS]
    except Exception:
        return ""


def _find_nearby_text(img_tag) -> str:
    """Encontrar texto narrativo cercano en ancestor semántico (Codex review).

    Estrategia: buscar primer ancestor en <figure>, <article>, <main>, <section>,
    o cualquier div tipo "card". Dentro, tomar el <p> más cercano (anterior O posterior)
    con >50 chars de texto significativo.
    """
    # Ancestor semántico
    semantic_ancestor = None
    for parent in img_tag.parents:
        if parent.name in ("figure", "article", "main", "section"):
            semantic_ancestor = parent
            break
        # También considerar divs con clase tipo "card" / "media" / "item"
        if parent.name == "div" and parent.get("class"):
            classes = " ".join(parent.get("class", [])).lower()
            if any(c in classes for c in ("card", "media", "item", "post", "entry", "figure")):
                semantic_ancestor = parent
                break
    if semantic_ancestor is None:
        # Fallback: parent directo
        semantic_ancestor = img_tag.parent

    if semantic_ancestor is None:
        return ""

    # Buscar el <p> más cercano (antes o después del img dentro del ancestor)
    candidates = semantic_ancestor.find_all("p")
    best = ""
    for p in candidates:
        text = p.get_text(strip=True)
        if len(text) >= 50:
            best = text
            break
    if not best:
        # Si no hay <p>, tomar todo el texto del ancestor (sin scripts/etc) limitado
        for tag in semantic_ancestor(["script", "style", "noscript"]):
            tag.decompose()
        best = semantic_ancestor.get_text(separator=" ", strip=True)
    return best[:MAX_CONTEXT_CHARS]


def _find_link_text(img_tag) -> str:
    """Si el img está dentro de <a>, devolver el text/title del link."""
    for parent in img_tag.parents:
        if parent.name == "a":
            text = parent.get("title", "") or parent.get_text(strip=True)
            return text[:MAX_CAPTION_CHARS] if text else ""
        # Solo buscar hasta nivel razonable
        if parent.name in ("body", "html") or parent.name is None:
            break
    return ""


def _find_figcaption(img_tag) -> str:
    """Si img está dentro de <figure>, devolver el <figcaption>."""
    for parent in img_tag.parents:
        if parent.name == "figure":
            fc = parent.find("figcaption")
            if fc:
                return fc.get_text(strip=True)[:MAX_CAPTION_CHARS]
            break
    return ""


def _extract_data_caption(img_tag) -> str:
    """Extraer atributos data-caption, data-alt-text, data-description."""
    for attr in ("data-caption", "data-alt-text", "data-description", "data-title"):
        v = img_tag.get(attr, "")
        if v and isinstance(v, str):
            return v.strip()[:MAX_CAPTION_CHARS]
    return ""


def _extract_og_image(soup) -> tuple[str, str]:
    """OpenGraph og:image + og:image:alt. Devuelve (url, alt)."""
    og_url = ""
    og_alt = ""
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if prop == "og:image" and not og_url:
            og_url = meta.get("content", "") or ""
        elif prop in ("og:image:alt", "twitter:image:alt") and not og_alt:
            og_alt = meta.get("content", "") or ""
        elif prop == "twitter:image" and not og_url:
            og_url = meta.get("content", "") or ""
    return og_url, og_alt[:MAX_CAPTION_CHARS]


def _extract_jsonld_images(soup) -> dict[str, str]:
    """Parsear JSON-LD schema.org. Devuelve dict url → caption."""
    out: dict[str, str] = {}
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            content = script.string or script.get_text()
            if not content:
                continue
            data = json.loads(content)
        except (json.JSONDecodeError, AttributeError):
            continue
        # Puede ser un dict o list de dicts
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            # Buscar ImageObject directo o anidado
            _walk_jsonld_for_images(item, out)
    return out


def _walk_jsonld_for_images(node, out: dict[str, str]) -> None:
    """Recorrer JSON-LD recursivamente buscando ImageObject."""
    if isinstance(node, dict):
        t = node.get("@type", "")
        if t == "ImageObject" or (isinstance(t, list) and "ImageObject" in t):
            url = node.get("url") or node.get("contentUrl") or ""
            caption = node.get("caption") or node.get("description") or node.get("name") or ""
            if url and caption:
                out[url] = str(caption)[:MAX_CAPTION_CHARS]
        for v in node.values():
            _walk_jsonld_for_images(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_jsonld_for_images(item, out)


def _extract_images_with_context(html: str, base_url: str) -> list[tuple[str, ImageContext]]:
    """Devolver lista de (url_absoluta, ImageContext) para imágenes con contexto.

    Esta es la función central del v2: en vez de devolver solo URLs, devuelve
    URLs + todo el contexto semántico extraíble del HTML.
    """
    soup = BeautifulSoup(html, "lxml")

    # Pre-compute: OG image + JSON-LD captions
    og_url, og_alt = _extract_og_image(soup)
    og_url_abs = _resolve_url(og_url, base_url) if og_url else ""
    jsonld_captions = _extract_jsonld_images(soup)
    jsonld_captions_abs = {_resolve_url(u, base_url): cap for u, cap in jsonld_captions.items()}

    seen_urls: set[str] = set()
    out: list[tuple[str, ImageContext]] = []

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            # Probar srcset (formato: "url 1x, url2 2x")
            srcset = img.get("srcset", "")
            if srcset:
                src = srcset.split(",")[0].split()[0]
        if not src:
            continue
        url_abs = _resolve_url(src, base_url)
        if url_abs in seen_urls:
            continue
        seen_urls.add(url_abs)

        ctx = ImageContext(
            alt=(img.get("alt", "") or "")[:MAX_CAPTION_CHARS],
            title=(img.get("title", "") or "")[:MAX_CAPTION_CHARS],
            aria_label=(img.get("aria-label", "") or "")[:MAX_CAPTION_CHARS],
            figcaption=_find_figcaption(img),
            nearby_text=_find_nearby_text(img),
            data_caption=_extract_data_caption(img),
            link_text=_find_link_text(img),
            filename=_extract_filename(url_abs),
            og_alt=og_alt if url_abs == og_url_abs else "",
            jsonld_caption=jsonld_captions_abs.get(url_abs, ""),
        )
        out.append((url_abs, ctx))

    # También agregar la OG image si no estaba ya en los <img>
    if og_url_abs and og_url_abs not in seen_urls:
        ctx = ImageContext(og_alt=og_alt, filename=_extract_filename(og_url_abs))
        out.append((og_url_abs, ctx))
        seen_urls.add(og_url_abs)

    # Agregar imágenes que solo aparecen en JSON-LD (no como <img> ni como OG)
    for jsonld_url, jsonld_cap in jsonld_captions_abs.items():
        if jsonld_url in seen_urls:
            continue
        ctx = ImageContext(jsonld_caption=jsonld_cap, filename=_extract_filename(jsonld_url))
        out.append((jsonld_url, ctx))
        seen_urls.add(jsonld_url)

    return out[:50]  # cap inicial generoso


# === Procesamiento de imágenes (mismo que v1) ===

def _process_image(image_bytes: bytes, target_hash: Optional[imagehash.ImageHash],
                   match_threshold: int = 8) -> Optional[FetchedImage]:
    """Procesar imagen bajada: hash perceptual + resize a base64."""
    try:
        img = Image.open(BytesIO(image_bytes))
    except Exception:
        return None
    if img.size[0] < 100 or img.size[1] < 100:  # muy chiquita = ruido
        return None
    if img.mode != "RGB":
        img = img.convert("RGB")
    this_hash = imagehash.phash(img)
    hamming = None
    is_target = False
    if target_hash is not None:
        hamming = int(this_hash - target_hash)
        is_target = hamming < match_threshold
    img_thumb = img.copy()
    img_thumb.thumbnail((512, 512))
    buf = BytesIO()
    img_thumb.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return FetchedImage(url="", base64_jpeg=b64, hamming_distance=hamming, is_likely_target=is_target)


# === fetch_url principal ===

def fetch_url(
    url: str,
    include_images: bool = False,
    target_image_path: Optional[str] = None,
    timeout: float = 20.0,
    excluded_domains: Optional[Iterable[str]] = None,
) -> FetchedPage:
    """Bajar una página y devolver su texto principal (+ imágenes opcional).

    Args:
        url: URL a fetchear.
        include_images: si True, también baja imágenes embebidas CON contexto semántico (v2).
        target_image_path: ruta a la foto target (para hash perceptual). Si None, no compara.
        timeout: timeout en segundos.
        excluded_domains: lista per-photo de hosts a bloquear además del GLOBAL.

    Returns:
        FetchedPage con texto + imágenes (con flags + contexto v2).
    """
    excluded = list(excluded_domains) if excluded_domains else []
    if is_blocked(url, excluded):
        return FetchedPage(url=url, status_code=0, title="", text="", text_truncated=False, error="domain_blocked")

    headers = {"User-Agent": "geodetective-research/0.1 (https://github.com/lucaspecina/geodetective-envs)"}

    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
    except Exception as e:
        return FetchedPage(url=url, status_code=0, title="", text="", text_truncated=False, error=f"fetch_error: {e}")

    final_url = str(r.url)
    if is_blocked(final_url, excluded):
        return FetchedPage(url=url, status_code=r.status_code, title="", text="", text_truncated=False, error="domain_blocked_after_redirect")
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
        # v2: usar la nueva función que extrae imágenes CON contexto
        url_ctx_pairs = _extract_images_with_context(html, final_url)
        # Filtrar dominios bloqueados (URL inicial)
        url_ctx_pairs = [(u, c) for u, c in url_ctx_pairs if not is_blocked(u, excluded)]

        for img_url, ctx in url_ctx_pairs[:MAX_IMAGES_PER_PAGE * 3]:  # buffer
            if len(images) >= MAX_IMAGES_PER_PAGE:
                break
            try:
                ir = httpx.get(img_url, timeout=10.0, follow_redirects=True, headers=headers)
                if is_blocked(str(ir.url), excluded):
                    continue
                if ir.status_code != 200 or len(ir.content) > 5_000_000:
                    continue
                fi = _process_image(ir.content, target_hash)
                if fi is None:
                    continue
                fi.url = img_url
                fi.context = ctx
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


# === Tool schemas (sin cambios visibles para el modelo) ===

TOOL_SCHEMA_TEXT = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": (
            "Entrar a una página web específica y leer su contenido completo. "
            "Útil cuando un resultado de web_search se ve prometedor y querés "
            "el texto entero de la página, no solo el snippet. Algunos dominios se filtran "
            "automáticamente como anti-shortcut según la foto que estás investigando."
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
            "Igual que fetch_url pero TAMBIÉN baja las imágenes embebidas en la página "
            "(hasta 10), que vas a ver en el siguiente turn JUNTO con su contexto semántico "
            "extraído del HTML: caption del <figcaption>, alt text, párrafo cercano de la "
            "página, y referencias schema.org/OpenGraph si las hay. Esto te permite conectar "
            "texto e imagen como un humano lee una página. Usalo cuando creas que las imágenes "
            "en la página pueden ayudar a comparar visualmente o si la página parece tener "
            "fotos de archivo relevantes. Las imágenes que coinciden visualmente con la foto "
            "target están flagueadas con is_likely_target=true."
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
