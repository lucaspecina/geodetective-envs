"""Tests sintéticos de geodetective.corpus.blacklist (issue #23).

Cubre:
- Suffix match correcto (host == d o host endswith ".d") sin falsos positivos
  (`notpastvu.com` NO matchea `pastvu.com`).
- Subdomain match (`upload.wikimedia.org` matchea `wikimedia.org`).
- GLOBAL bloquea siempre (lens.google.com, wikimedia, etc.).
- Per-provider bloquea SOLO si la foto tiene ese provider.
- Wikimedia/Wikipedia/Flickr quedan en GLOBAL.
- Provenance extraída de `source` field se suma al excluido.
- compute_excluded_domains combina las tres capas.

Uso: python scripts/test_blacklist.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.corpus.blacklist import (
    BLOCKED_DOMAINS_GLOBAL,
    compute_excluded_domains,
    domains_for_provider,
    extract_domains_from_source,
    is_blocked,
)


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return cond


def run_tests() -> int:
    failures = 0

    # === Suffix matching ===
    print("\nT1 — suffix match correcto, sin falsos positivos")
    failures += not _check(
        "pastvu.com matchea solo si está en la blacklist",
        is_blocked("https://pastvu.com/p/12345", excluded_domains=["pastvu.com"]),
    )
    failures += not _check(
        "subdomain matchea (cdn.pastvu.com)",
        is_blocked("https://cdn.pastvu.com/img.jpg", excluded_domains=["pastvu.com"]),
    )
    failures += not _check(
        "notpastvu.com NO matchea pastvu.com (anti substring false positive)",
        not is_blocked("https://notpastvu.com/x", excluded_domains=["pastvu.com"]),
    )
    failures += not _check(
        "pastvulike.org NO matchea pastvu.com",
        not is_blocked("https://pastvulike.org/x", excluded_domains=["pastvu.com"]),
    )

    # === GLOBAL siempre bloquea ===
    print("\nT2 — GLOBAL bloquea siempre, sin excluded_domains")
    for url in [
        "https://commons.wikimedia.org/wiki/File:Foo.jpg",
        "https://en.wikipedia.org/wiki/Foo",
        "https://www.flickr.com/photos/123",
        "https://lens.google.com/uploadbyurl?url=...",
        "https://yandex.ru/images",
        "https://www.tineye.com/search/...",
        "https://pinterest.com/pin/123",
        "https://i.imgur.com/x.jpg",
        "https://www.gettyimages.com/detail/x",
    ]:
        failures += not _check(f"  GLOBAL bloquea: {url[:50]}", is_blocked(url))

    # Nota: `google.com` bare NO está en GLOBAL (overblocking). Solo lens/images.google.com.
    failures += not _check(
        "lens.google.com bloqueado",
        is_blocked("https://lens.google.com/uploadbyurl?url=foo"),
    )

    # === GLOBAL no toca dominios neutros ===
    print("\nT3 — GLOBAL deja pasar sitios legítimos de investigación")
    for url in [
        "https://blog.example.com/some-post",
        "https://news.bbc.co.uk/article",
        "https://www.archive.org/details/foo",
        "https://academic.oup.com/article/123",
    ]:
        failures += not _check(f"  GLOBAL no bloquea: {url[:50]}", not is_blocked(url))

    # === Provider mapping ===
    print("\nT4 — domains_for_provider devuelve la lista correcta")
    failures += not _check("pastvu → ['pastvu.com']", domains_for_provider("pastvu") == ["pastvu.com"])
    failures += not _check(
        "smapshot → ['smapshot.heig-vd.ch', 'smapshot.ch']",
        domains_for_provider("smapshot") == ["smapshot.heig-vd.ch", "smapshot.ch"],
    )
    failures += not _check("None → []", domains_for_provider(None) == [])
    failures += not _check("provider unknown → []", domains_for_provider("xyz") == [])

    # === Per-photo: pastvu solo se bloquea cuando provider=pastvu ===
    print("\nT5 — per-photo: pastvu solo bloquea cuando es el provider")
    excluded_pastvu = compute_excluded_domains(provider="pastvu")
    failures += not _check(
        "foto pastvu: pastvu.com bloqueado",
        is_blocked("https://pastvu.com/p/123", excluded_domains=excluded_pastvu),
    )
    failures += not _check(
        "foto pastvu: smapshot.ch NO bloqueado (queda accesible)",
        not is_blocked("https://smapshot.ch/foo", excluded_domains=excluded_pastvu),
    )

    excluded_smapshot = compute_excluded_domains(provider="smapshot")
    failures += not _check(
        "foto smapshot: smapshot.ch bloqueado",
        is_blocked("https://smapshot.ch/foo", excluded_domains=excluded_smapshot),
    )
    failures += not _check(
        "foto smapshot: pastvu.com NO bloqueado",
        not is_blocked("https://pastvu.com/p/123", excluded_domains=excluded_smapshot),
    )

    # === extract_domains_from_source ===
    print("\nT6 — extract_domains_from_source pesca URLs en HTML/free-text")
    src = '<a href="https://commons.wikimedia.org/wiki/File:Foo.jpg">via Wikimedia</a> + http://humus.livejournal.com/123.html'
    domains = extract_domains_from_source(src)
    failures += not _check(
        "extrae commons.wikimedia.org",
        "commons.wikimedia.org" in domains,
        str(domains),
    )
    failures += not _check(
        "extrae humus.livejournal.com",
        "humus.livejournal.com" in domains,
        str(domains),
    )
    failures += not _check("source vacío → []", extract_domains_from_source("") == [])
    failures += not _check("source None → []", extract_domains_from_source(None) == [])

    # === compute_excluded_domains combina las 3 fuentes ===
    print("\nT7 — compute_excluded_domains combina provider + source + extras")
    excl = compute_excluded_domains(
        provider="pastvu",
        source='<a href="https://humus.livejournal.com/x">link</a>',
        extra=["custom.example.com"],
    )
    failures += not _check("contiene pastvu.com (provider)", "pastvu.com" in excl)
    failures += not _check("contiene humus.livejournal.com (source)", "humus.livejournal.com" in excl)
    failures += not _check("contiene custom.example.com (extra)", "custom.example.com" in excl)
    failures += not _check("ordenado y único", excl == sorted(set(excl)))

    # === Caso E2E ===
    print("\nT8 — flujo end-to-end de una foto pastvu con provenance wikimedia")
    excluded = compute_excluded_domains(
        provider="pastvu",
        source='<a href="https://commons.wikimedia.org/wiki/File:Foo.jpg">orig</a>',
    )
    failures += not _check(
        "pastvu.com bloqueado (per-provider)",
        is_blocked("https://pastvu.com/p/123", excluded_domains=excluded),
    )
    failures += not _check(
        "commons.wikimedia.org bloqueado (GLOBAL + source)",
        is_blocked("https://commons.wikimedia.org/wiki/Special:File", excluded_domains=excluded),
    )
    failures += not _check(
        "smapshot NO bloqueado (otro archivo histórico, queda accesible)",
        not is_blocked("https://smapshot.ch/x", excluded_domains=excluded),
    )

    # === GLOBAL no debe contener provider sources ===
    print("\nT9 — GLOBAL no contiene archivos históricos provider (movidos a per-photo)")
    for d in ["pastvu.com", "smapshot.ch", "smapshot.heig-vd.ch", "etoretro.ru",
              "humus.livejournal.com", "oldnyc.org", "oldsf.org", "historypin.org", "sepiatown.com"]:
        failures += not _check(
            f"  '{d}' fuera del GLOBAL (queda como per-photo)",
            d not in BLOCKED_DOMAINS_GLOBAL,
        )

    # === GLOBAL sí debe contener wikimedia/wikipedia/flickr ===
    print("\nT10 — GLOBAL contiene agregadores con metadata estructurada")
    for d in ["wikimedia.org", "wikipedia.org", "flickr.com", "vk.com", "ok.ru"]:
        failures += not _check(f"  '{d}' está en GLOBAL", d in BLOCKED_DOMAINS_GLOBAL)

    # === Edge cases ===
    print("\nT11 — edge cases")
    failures += not _check("URL inválida → no bloqueado, no crashea", not is_blocked("not-a-url"))
    failures += not _check("string vacío → no bloqueado", not is_blocked(""))
    failures += not _check(
        "compute_excluded_domains sin args → []",
        compute_excluded_domains() == [],
    )

    # === Anti-overblocking: google.com bare NO bloquea contenido legítimo ===
    print("\nT12 — anti-overblocking: google.com / bing.com / googleusercontent NO bloquean")
    failures += not _check(
        "books.google.com NO bloqueado (Google Books legítimo)",
        not is_blocked("https://books.google.com/books?id=abc"),
    )
    failures += not _check(
        "scholar.google.com NO bloqueado",
        not is_blocked("https://scholar.google.com/scholar?q=foo"),
    )
    failures += not _check(
        "blogspot.googleusercontent.com NO bloqueado (CDN de Blogger)",
        not is_blocked("https://blogger.googleusercontent.com/img/x.jpg"),
    )
    failures += not _check(
        "www.bing.com NO bloqueado (búsqueda general)",
        not is_blocked("https://www.bing.com/search?q=foo"),
    )

    # === Schemeless URLs en source ===
    print("\nT13 — extract_domains_from_source captura schemeless `//host/...`")
    src_schemeless = '<a href="//commons.wikimedia.org/wiki/File:X.jpg">link</a>'
    domains = extract_domains_from_source(src_schemeless)
    failures += not _check(
        "schemeless: commons.wikimedia.org capturado",
        "commons.wikimedia.org" in domains,
        str(domains),
    )
    src_mix = "ver https://flickr.com/x y //humus.livejournal.com/y"
    domains = extract_domains_from_source(src_mix)
    failures += not _check(
        "mezcla scheme + schemeless: ambos capturados",
        "flickr.com" in domains and "humus.livejournal.com" in domains,
        str(domains),
    )

    # === Reverse search engines (los que SÍ deben quedar) ===
    print("\nT14 — reverse search engines explícitos siguen bloqueados")
    for url in [
        "https://lens.google.com/search?p=foo",
        "https://images.google.com/imghp",
        "https://www.tineye.com/search/abc",
        "https://yandex.ru/images/search?text=foo",
    ]:
        failures += not _check(f"  bloqueado: {url[:50]}", is_blocked(url))

    print(f"\n{'=' * 50}")
    if failures:
        print(f"❌ {failures} fallos")
        return 1
    print("✅ Todos los tests pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
