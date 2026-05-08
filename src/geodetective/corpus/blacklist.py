"""Blacklist runtime de dominios para tools del agente (issue #23).

Dos capas:

1. **`BLOCKED_DOMAINS_GLOBAL`**: dominios que SIEMPRE se bloquean para cualquier foto del corpus.
   Reverse image search engines + agregadores masivos con metadata estructurada (caption + geotag)
   + hosting/sharing platforms con propensión a re-publicar fotos de archivo + stock photo agencies.

2. **`PROVIDER_DOMAINS`**: dominios per-photo según el provider de origen. Cuando una foto vino
   de `pastvu`, sumamos `pastvu.com` a su lista de excluidos. Otra foto de `smapshot` excluye
   `smapshot.heig-vd.ch` pero NO `pastvu.com` — ese archivo queda como material de investigación legítima.

3. Adicional **per-photo**: si el campo `source` del candidate trae links explícitos
   (ej: "<a href='https://wikimedia.org/...'>"), agregamos esos hosts al excluido.

Matching: `urlparse` + suffix match en el host. Evita falsos positivos (`notpastvu.com`)
y falsos negativos (variantes con cctld, paths). Para URLs post-redirect, los callers deben
chequear el `response.url` final, no solo el inicial.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse


# === Capa 1: global ===
# Sitios que NUNCA dejan de ser shortcut. No agregar archivos históricos específicos
# a esta lista — esos van per-provider para no tapar investigación legítima.
BLOCKED_DOMAINS_GLOBAL: frozenset[str] = frozenset({
    # Reverse image search engines (puro shortcut). NO agregar `google.com`, `bing.com`,
    # `duckduckgo.com` o `googleusercontent.com` bare: hostname-only match overbloquea
    # contenido legítimo (Google Books/Scholar, Blogger CDN, etc.). Si más adelante
    # querés filtrar el path-aware (`google.com/search?tbm=isch`) hay que extender
    # `is_blocked` con reglas path-prefix. Por ahora: solo subdomains explícitos.
    "lens.google.com",
    "images.google.com",
    "yandex.com",
    "yandex.ru",
    "tineye.com",
    # Agregadores masivos con metadata estructurada (caption + geotag + colección)
    # — la foto target podría aparecer ahí con info de ubicación al lado.
    "wikimedia.org",
    "wikipedia.org",
    "flickr.com",
    "vk.com",
    "ok.ru",
    # Stock photo agencies que indexan fotos históricas con metadata
    "alamy.com",
    "gettyimages.com",
    "shutterstock.com",
    "istockphoto.com",
    "dreamstime.com",
    "depositphotos.com",
    # Hosting / sharing con propensión a re-publicar archivos
    "pinterest.com",
    "pinterest.ca",
    "pinterest.co.uk",
    "reddit.com",
    "redd.it",
    "imgur.com",
    "postimg.cc",
    "ebay.com",
    "ebay.co.uk",
    "t.me",
    "telegram.org",
})


# === Capa 2: per-provider ===
# Cuando una foto del corpus tiene `provider=X`, se agregan estos hosts a su excluido.
PROVIDER_DOMAINS: dict[str, list[str]] = {
    "pastvu": ["pastvu.com"],
    "smapshot": ["smapshot.heig-vd.ch", "smapshot.ch"],
    "etoretro": ["etoretro.ru"],
    "humus": ["humus.livejournal.com"],
    "oldnyc": ["oldnyc.org"],
    "oldsf": ["oldsf.org"],
    "historypin": ["historypin.org"],
    "sepiatown": ["sepiatown.com"],
}


def domains_for_provider(provider: Optional[str]) -> list[str]:
    """Lista de hosts a excluir cuando una foto del corpus tiene `provider`."""
    if not provider:
        return []
    return list(PROVIDER_DOMAINS.get(provider, []))


def extract_domains_from_source(source: Optional[str]) -> list[str]:
    """Extrae hosts de URLs presentes en el campo `source` del candidate.

    El campo `source` de PastVu es free-text/HTML que puede contener `<a href=...>`,
    URLs sueltas con scheme (`https://...`), o URLs schemeless (`//host/...`).
    Capturamos las tres variantes — se vio en sample real que algunas anchors usan
    protocol-relative.
    """
    if not source:
        return []
    # `(?:https?:)?//host/...` cubre con-scheme y schemeless.
    urls = re.findall(r"(?:https?:)?//[^\s<>\"']+", source)
    hosts: set[str] = set()
    for u in urls:
        # urlparse necesita scheme para popular hostname; prependear si falta.
        if u.startswith("//"):
            u = "https:" + u
        try:
            host = urlparse(u).hostname
        except Exception:
            continue
        if host:
            hosts.add(host.lower())
    return sorted(hosts)


def compute_excluded_domains(
    provider: Optional[str] = None,
    source: Optional[str] = None,
    extra: Optional[Iterable[str]] = None,
) -> list[str]:
    """Lista de hosts adicionales a bloquear PER-PHOTO (encima del GLOBAL).

    Combina:
    - dominios del provider (PROVIDER_DOMAINS).
    - dominios extraídos del campo `source` del candidate.
    - extras pasados explícitamente por el caller.
    """
    out: set[str] = set()
    out.update(domains_for_provider(provider))
    out.update(extract_domains_from_source(source))
    if extra:
        out.update(d.lower() for d in extra if d)
    return sorted(out)


def is_blocked(
    url: str,
    excluded_domains: Optional[Iterable[str]] = None,
) -> bool:
    """¿La URL está bloqueada según GLOBAL + excluded_domains?

    Matching: suffix match sobre el host parseado con urlparse. Evita:
    - falsos positivos por substring (`notpastvu.com` no matchea `pastvu.com`).
    - falsos negativos por path/cctld (`pastvu.com/_p/` SÍ matchea `pastvu.com`).

    Para URLs post-redirect el caller debe llamar esta función con la URL final
    (`response.url`), no solo la inicial.
    """
    try:
        host = urlparse(url).hostname
    except Exception:
        return False
    if not host:
        return False
    host = host.lower()
    blocked: set[str] = set(BLOCKED_DOMAINS_GLOBAL)
    if excluded_domains:
        blocked.update(d.lower() for d in excluded_domains if d)
    for d in blocked:
        # Suffix match: `host == d` o `host` termina en `.d`.
        # Esto cubre subdominios (`upload.wikimedia.org` → `wikimedia.org`)
        # sin matchear `notpastvu.com` con `pastvu.com`.
        if host == d or host.endswith("." + d):
            return True
    return False
