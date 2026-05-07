"""Web search tool con filtros anti-shortcut.

Backend: Tavily API. Filtra dominios que constituirían shortcut directo
(fuentes del corpus, reverse image search, agregadores de fotos).
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional
from tavily import TavilyClient


# Dominios que descartamos en results (shortcut directo a la foto/respuesta)
BLOCKED_DOMAINS = {
    # Fuentes del corpus
    "pastvu.com",
    "smapshot.heig-vd.ch",
    "smapshot.ch",
    "etoretro.ru",
    "humus.livejournal.com",
    "oldnyc.org",
    "oldsf.org",
    "historypin.org",
    # Agregadores con thumbnails georreferenciados
    "commons.wikimedia.org",
    "upload.wikimedia.org",
    "flickr.com",
    "vk.com",  # comparte fotos con coords
    # Reverse image search
    "lens.google.com",
    "images.google.com",
    "yandex.com",
    "yandex.ru",
    "tineye.com",
    # Hosting platforms con metadata exif
    "imgur.com",
    "postimg.cc",
}


def _domain_blocked(url: str) -> bool:
    url_lower = url.lower()
    for d in BLOCKED_DOMAINS:
        if d in url_lower:
            return True
    return False


@dataclass
class SearchResult:
    title: str
    url: str
    content: str  # snippet o resumen
    score: Optional[float] = None

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "content": self.content, "score": self.score}


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    blocked_count: int  # cuántos resultados se filtraron por dominio
    total_raw: int

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "blocked_count": self.blocked_count,
            "total_raw": self.total_raw,
        }


def web_search(query: str, max_results: int = 5, search_depth: str = "basic") -> SearchResponse:
    """Buscar en la web con Tavily, filtrando dominios shortcut.

    Args:
        query: texto de búsqueda.
        max_results: cuántos resultados pedirle a Tavily ANTES del filtrado.
                     Si se filtra mucho, devolverá menos.
        search_depth: "basic" o "advanced" (más caro pero más rico).

    Returns:
        SearchResponse con resultados filtrados + meta.
    """
    if not os.environ.get("TAVILY_API_KEY"):
        raise RuntimeError("TAVILY_API_KEY no está en environment.")
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    raw = client.search(query, max_results=max_results, search_depth=search_depth)
    raw_items = raw.get("results", [])
    filtered = []
    blocked = 0
    for r in raw_items:
        if _domain_blocked(r.get("url", "")):
            blocked += 1
            continue
        filtered.append(SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            content=r.get("content", ""),
            score=r.get("score"),
        ))
    return SearchResponse(
        query=query,
        results=filtered,
        blocked_count=blocked,
        total_raw=len(raw_items),
    )


# Schema OpenAI tool calling format
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Buscar en la web información de contexto sobre un lugar, edificio, "
            "evento histórico, idioma de un cartel, vehículo, etc. NO sirve para "
            "buscar la foto en sí (los dominios de archivos públicos están bloqueados). "
            "Usá queries específicas en el idioma apropiado (español, inglés, ruso, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de búsqueda. Ej: 'edificios soviéticos paneles prefabricados Серебристый бульвар San Petersburgo'"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Máximo número de resultados (1-10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}
