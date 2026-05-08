"""Web search tool con filtros anti-shortcut.

Backend: Tavily API. Filtra dominios shortcut según `corpus.blacklist`:
- GLOBAL: reverse search engines, agregadores con metadata estructurada, hosting/sharing.
- PER-PHOTO: el caller pasa `excluded_domains` (provider de la foto + provenance).
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Iterable, Optional
from tavily import TavilyClient

from ..corpus.blacklist import is_blocked, BLOCKED_DOMAINS_GLOBAL

# Re-export por back-compat de import (`from .web_search import BLOCKED_DOMAINS`).
# ATENCIÓN: el comportamiento cambió en #23. Antes contenía las fuentes del corpus
# (pastvu, smapshot, etc.) — ahora SOLO el GLOBAL minimal (reverse search + agregadores
# masivos + hosting). Las fuentes del corpus se aplican per-photo vía
# `corpus.compute_excluded_domains(provider, source)`. Migrá a esa función si esperabas
# que `pastvu.com` esté siempre bloqueado.
BLOCKED_DOMAINS = BLOCKED_DOMAINS_GLOBAL


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


def web_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "advanced",
    excluded_domains: Optional[Iterable[str]] = None,
) -> SearchResponse:
    """Buscar en la web con Tavily, filtrando dominios shortcut.

    Default: search_depth="advanced" → contenido más rico (1000-5000 chars vs 200).

    Args:
        query: texto de búsqueda.
        max_results: cuántos resultados devolver post-filtrado. Internamente pedimos
            *3 a Tavily para tener buffer cuando el filtrado per-photo descarta varios.
        search_depth: "basic" (rápido, snippets cortos) o "advanced" (más rico).
        excluded_domains: lista per-photo de hosts a bloquear además del GLOBAL
            (típicamente `corpus.compute_excluded_domains(provider, source)`).

    Returns:
        SearchResponse con resultados filtrados + meta.
    """
    if not os.environ.get("TAVILY_API_KEY"):
        raise RuntimeError("TAVILY_API_KEY no está en environment.")
    excluded = list(excluded_domains) if excluded_domains else []
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    # Overfetch *3 para que el filtrado per-photo no nos deje con < max_results.
    raw = client.search(query, max_results=max_results * 3, search_depth=search_depth)
    raw_items = raw.get("results", [])
    filtered: list[SearchResult] = []
    blocked = 0
    for r in raw_items:
        if len(filtered) >= max_results:
            break
        url = r.get("url", "")
        if is_blocked(url, excluded):
            blocked += 1
            continue
        filtered.append(SearchResult(
            title=r.get("title", ""),
            url=url,
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
            "evento histórico, idioma de un cartel, vehículo, etc. Algunos dominios "
            "se filtran automáticamente como anti-shortcut según la foto que estás "
            "investigando — no necesitás especificarlos. Usá queries específicas en "
            "el idioma apropiado (español, inglés, ruso, etc.)."
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
