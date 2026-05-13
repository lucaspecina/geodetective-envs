"""Web search tool con filtros anti-shortcut.

Backend: **Azure OpenAI Responses API + `web_search` tool nativo** (Grounding with Bing).
Migrado desde Tavily (cuota agotada). Ver review en CHANGELOG + Codex review notes.

Estrategia:
- Helper model `gpt-4.1-mini` (cheap), `search_context_size: "low"`.
- Prompt pide al modelo formato markdown estructurado tras buscar:
  `N. [TITLE]\nURL: ...\nExtracto: ...`.
- Parseamos con regex; fallback a URLs sueltas de `web_search_call.action.sources`.
- Overfetch ~6 fuentes para cubrir el post-filter del blocklist.
- Blocklist = **post-filter HARD** (Azure no soporta denylist nativo, solo allowlist).
- Cache en memoria por `(query, excluded_domains, max_results)` con TTL.

Pricing aproximado: ~$0.03/call (Bing $14/1K + ~$0.016 tokens del modelo).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from openai import OpenAI

from ..corpus.blacklist import BLOCKED_DOMAINS_GLOBAL, is_blocked


_SOURCE_BLOCK_RE = re.compile(
    r"\d+\.\s*\[?(?P<title>[^\]\n]+?)\]?\s*\n+"
    r"\s*(?:URL|Url|url|Link|Enlace)\s*:\s*(?P<url>https?://\S+)\s*\n+"
    r"\s*(?:Extracto|Snippet|Excerpt|Resumen|Descripción|Description)\s*:\s*(?P<snippet>.+?)"
    r"(?=\n\s*\d+\.|\Z)",
    re.DOTALL,
)

# Re-export por back-compat
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
    blocked_count: int
    total_raw: int

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "blocked_count": self.blocked_count,
            "total_raw": self.total_raw,
        }


# === Cache ===
_cache: dict[tuple, tuple[float, SearchResponse]] = {}
_CACHE_TTL = 3600.0  # 1 hora


def _cache_get(key: tuple) -> Optional[SearchResponse]:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.time() - ts > _CACHE_TTL:
        return None
    return value


def _cache_set(key: tuple, value: SearchResponse) -> None:
    _cache[key] = (time.time(), value)


# === Backend ===
def _get_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
        api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
        timeout=90.0,
        max_retries=2,
    )


def _extract_sources(resp) -> list[dict]:
    """Parsear sources del response. Estrategia:
    1. Parsear el message text en formato `N. [TITLE]\\n URL: ...\\n Extracto: ...`.
    2. Fallback URLs sueltas (sin title/snippet) desde `web_search_call.action.sources`.
    """
    output = getattr(resp, "output", None) or []

    # Path 1: parse markdown del message text
    sources: list[dict] = []
    seen_urls: set[str] = set()
    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        for c in getattr(item, "content", None) or []:
            if getattr(c, "type", None) != "output_text":
                continue
            text = getattr(c, "text", "") or ""
            for m in _SOURCE_BLOCK_RE.finditer(text):
                url = m.group("url").strip().rstrip(".,;:)")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append({
                    "url": url,
                    "title": m.group("title").strip(),
                    "snippet": m.group("snippet").strip(),
                })

    # Path 2 (fallback): URLs de web_search_call.action.sources (solo URL, sin title)
    fallback_urls = []
    for item in output:
        if getattr(item, "type", None) != "web_search_call":
            continue
        action = getattr(item, "action", None)
        if action is None:
            continue
        action_sources = (
            action.get("sources", []) if isinstance(action, dict)
            else (getattr(action, "sources", None) or [])
        )
        for s in action_sources:
            url = (s.get("url", "") if isinstance(s, dict)
                   else getattr(s, "url", "") or "")
            url = url.strip().rstrip(".,;:)")
            if url and url not in seen_urls:
                fallback_urls.append(url)
                seen_urls.add(url)

    # Mergeamos: primero las que tienen title/snippet, después fallback URLs.
    for url in fallback_urls:
        sources.append({"url": url, "title": "", "snippet": ""})

    return sources


def _call_websearch(query: str, n: int) -> list[dict]:
    """Llamada cruda a Azure Responses API + web_search tool. Devuelve lista de dicts
    con keys url/title/snippet."""
    client = _get_client()
    model = os.environ.get("AZURE_WEBSEARCH_MODEL", "gpt-4.1-mini")
    prompt = (
        f"Hacé una búsqueda web sobre: {query}\n\n"
        f"Después de buscar, listá las top {n} fuentes encontradas EN ESTE FORMATO EXACTO "
        f"(usá los labels en español tal cual, sin nada antes ni después de la lista):\n\n"
        f"1. [TÍTULO DESCRIPTIVO DE LA PÁGINA]\n"
        f"   URL: [url completa]\n"
        f"   Extracto: [1-3 oraciones con info concreta del contenido]\n\n"
        f"2. [TÍTULO]\n"
        f"   URL: [url]\n"
        f"   Extracto: [info]\n\n"
        f"...etc. Cada fuente NUMERADA. NO comentes ni resumas — solo listá las fuentes."
    )
    resp = client.responses.create(
        model=model,
        tools=[{"type": "web_search", "search_context_size": "low"}],
        tool_choice="auto",
        input=prompt,
        include=["web_search_call.action.sources"],
    )
    return _extract_sources(resp)


def _filter_sources(
    sources: list[dict], excluded: list[str], max_results: int
) -> tuple[list[SearchResult], int]:
    filtered: list[SearchResult] = []
    blocked = 0
    for s in sources:
        url = s.get("url", "")
        if is_blocked(url, excluded):
            blocked += 1
            continue
        filtered.append(SearchResult(
            title=s.get("title", ""),
            url=url,
            content=s.get("snippet", ""),
        ))
        if len(filtered) >= max_results:
            break
    return filtered, blocked


def _dedupe_by_url(sources: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for s in sources:
        url = s.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(s)
    return out


# === Public API ===
def web_search(
    query: str,
    max_results: int = 5,
    excluded_domains: Optional[Iterable[str]] = None,
    # Param `search_depth` retenido por back-compat de signature; ignorado.
    search_depth: str = "advanced",
) -> SearchResponse:
    """Búsqueda web vía Azure Responses API + web_search tool nativo.

    Args:
        query: texto de búsqueda.
        max_results: cuántos resultados devolver post-filtrado.
        excluded_domains: hosts a bloquear adicional al `BLOCKED_DOMAINS_GLOBAL`.
        search_depth: ignorado (back-compat con la signature de Tavily).

    Returns:
        SearchResponse con resultados filtrados.

    Raises:
        RuntimeError: si la API call falla.
    """
    del search_depth  # silenciar lint
    excluded = list(excluded_domains) if excluded_domains else []
    cache_key = (query, frozenset(excluded), max_results)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    raw_n = max(max_results * 4, 8)  # overfetch

    try:
        sources = _call_websearch(query, raw_n)
    except Exception as e:
        raise RuntimeError(f"Azure web_search call failed: {e}") from e

    filtered, blocked = _filter_sources(sources, excluded, max_results)

    # Retry con -site: si quedan pocos sobrevivientes
    threshold = max(2, max_results // 2)
    if len(filtered) < threshold and excluded:
        site_excludes = " ".join(f"-site:{d}" for d in list(excluded)[:5])
        try:
            sources2 = _call_websearch(f"{query} {site_excludes}", raw_n)
        except Exception:
            sources2 = []
        merged = _dedupe_by_url(sources + sources2)
        filtered, blocked = _filter_sources(merged, excluded, max_results)
        sources = merged

    result = SearchResponse(
        query=query,
        results=filtered,
        blocked_count=blocked,
        total_raw=len(sources),
    )
    _cache_set(cache_key, result)
    return result


# === Schema OpenAI tool calling (sin cambios — back-compat) ===
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Buscar en la web información de contexto sobre un lugar, edificio, "
            "evento histórico, idioma de un cartel, vehículo, etc. Algunos dominios "
            "se filtran automáticamente como anti-shortcut según la foto que estás "
            "investigando — no necesitás especificarlos. Usá queries específicas en "
            "el idioma apropiado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de búsqueda. Sé específico y descriptivo (en cualquier idioma)."
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
