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
    # v2 (#40): metadata enriquecida
    site_name: str = ""  # "Wikipedia", "fotopolska.eu", "archive.org"
    date_published: str = ""  # YYYY-MM-DD si lo encuentra, sino ""
    language: str = ""  # ISO 2-letter, ej "en", "ru", "pt"
    source_type: str = ""  # "article", "wikipedia", "archive", "blog", "social", "forum", "other"

    def to_dict(self) -> dict:
        out = {"title": self.title, "url": self.url, "content": self.content}
        if self.score is not None:
            out["score"] = self.score
        # Solo incluir metadata si no está vacía
        for k in ("site_name", "date_published", "language", "source_type"):
            v = getattr(self, k, "")
            if v:
                out[k] = v
        return out


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
    """Parsear sources del response. v2 Estrategia:
    1. Parsear como JSON estructurado (formato v2).
    2. Fallback al regex markdown viejo (back-compat).
    3. Fallback URLs sueltas desde `web_search_call.action.sources`.
    """
    import json as _json
    output = getattr(resp, "output", None) or []

    sources: list[dict] = []
    seen_urls: set[str] = set()

    # Path 1: parse JSON del message text (v2)
    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        for c in getattr(item, "content", None) or []:
            if getattr(c, "type", None) != "output_text":
                continue
            text = getattr(c, "text", "") or ""
            # Tolerar code fences ```json ... ``` por si el helper los pone igual
            text_clean = text.strip()
            if text_clean.startswith("```"):
                # Remover primera y última línea (code fence)
                lines = text_clean.split("\n")
                text_clean = "\n".join(lines[1:-1]) if len(lines) > 2 else text_clean
            try:
                data = _json.loads(text_clean)
                results = data.get("results", []) if isinstance(data, dict) else []
                for r in results:
                    if not isinstance(r, dict):
                        continue
                    url = (r.get("url", "") or "").strip().rstrip(".,;:)")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    sources.append({
                        "url": url,
                        "title": (r.get("title", "") or "").strip(),
                        "snippet": (r.get("snippet", "") or "").strip(),
                        "site_name": (r.get("site_name", "") or "").strip(),
                        "date_published": (r.get("date_published", "") or "").strip(),
                        "language": (r.get("language", "") or "").strip(),
                        "source_type": (r.get("source_type", "") or "").strip(),
                    })
            except (_json.JSONDecodeError, AttributeError, KeyError, TypeError):
                # Fallback al regex viejo (back-compat con cache + casos donde el helper devuelve markdown)
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

    for url in fallback_urls:
        sources.append({"url": url, "title": "", "snippet": ""})

    return sources


def _call_websearch(query: str, n: int) -> list[dict]:
    """Llamada cruda a Azure Responses API + web_search tool. Devuelve lista de dicts
    con keys url/title/snippet + metadata enriquecida (v2 #40).

    v2: pedimos JSON estructurado al helper, fallback a regex si JSON falla.
    """
    client = _get_client()
    model = os.environ.get("AZURE_WEBSEARCH_MODEL", "gpt-4.1-mini")
    prompt = (
        f"Hacé una búsqueda web sobre: {query}\n\n"
        f"Después de buscar, devolvé las top {n} fuentes en JSON ESTRICTO con este shape (sin "
        f"texto antes ni después del JSON, ni markdown code fences):\n\n"
        f'{{"results": [\n'
        f'  {{"title": "título descriptivo", "url": "https://...", '
        f'"snippet": "1500-2000 chars con la información concreta del contenido. '
        f'Sé extenso — incluí fechas, nombres, ubicaciones, detalles relevantes.", '
        f'"site_name": "Wikipedia|nombre del sitio", '
        f'"date_published": "YYYY-MM-DD o vacío si no aparece", '
        f'"language": "ISO 2-letter (en|es|ru|pt|...)", '
        f'"source_type": "wikipedia|article|archive|blog|forum|social|other"}},\n'
        f"  ...\n"
        f"]}}\n\n"
        f"NO uses markdown, NO uses ```json```, devolvé SOLO el objeto JSON."
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
            # v2: metadata enriquecida (vacía si el helper no la devolvió)
            site_name=s.get("site_name", ""),
            date_published=s.get("date_published", ""),
            language=s.get("language", ""),
            source_type=s.get("source_type", ""),
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
    max_results: int = 10,  # v2: era 5
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
            "evento histórico, idioma de un cartel, vehículo, etc. Devuelve resultados con "
            "URL, título, snippet largo (1500-2000 chars con info concreta), y metadata: "
            "site_name (Wikipedia, fotopolska.eu, etc.), date_published si aparece, "
            "language, y source_type (wikipedia/article/archive/blog/forum/social). "
            "Algunos dominios se filtran automáticamente como anti-shortcut según la foto "
            "que estás investigando — no necesitás especificarlos. Usá queries específicas "
            "en el idioma apropiado."
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
                    "description": "Máximo número de resultados (1-15, default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
}
