"""Smoke test del v2 de fetch_url_with_images — verifica que el contexto se extrae bien.

Prueba sobre HTML sintético + (si hay red) sobre una URL real (Wikipedia).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geodetective.tools.fetch_url import _extract_images_with_context


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta property="og:image" content="https://example.com/og-image.jpg"/>
  <meta property="og:image:alt" content="Vista aérea de Praça da Liberdade, Porto"/>
  <script type="application/ld+json">
  {
    "@type": "Article",
    "image": {
      "@type": "ImageObject",
      "url": "https://example.com/article-img.jpg",
      "caption": "Praça da Liberdade en 1947 - tranvía circulando"
    }
  }
  </script>
</head>
<body>
  <article>
    <h1>El tranvía histórico de Porto</h1>
    <figure>
      <img src="/photos/tram1.jpg" alt="Tranvía nº 73"/>
      <figcaption>Eléctrico nº 73 en la Praça da Liberdade, 1947</figcaption>
    </figure>
    <p>Esta vista muestra el tranvía circulando por la avenida central de la ciudad, en uno de los puntos más emblemáticos del centro histórico.</p>

    <figure>
      <img src="https://other.com/img.jpg" alt="Vista de Avenida dos Aliados" title="Avenida dos Aliados 1950"/>
      <figcaption>Avenida dos Aliados décadas después</figcaption>
    </figure>
  </article>

  <a href="/about" title="Conocé más">
    <img src="/icon.png" alt="ícono"/>
  </a>

  <div class="card">
    <img src="/photos/card.jpg" data-caption="Foto del archivo Municipal"/>
    <p>Otro párrafo más cercano a la imagen.</p>
  </div>
</body>
</html>
"""


def test_extract_basic():
    results = _extract_images_with_context(SAMPLE_HTML, "https://example.com/page")
    print(f"Found {len(results)} images:\n")
    for i, (url, ctx) in enumerate(results, 1):
        print(f"  [{i}] {url}")
        d = ctx.to_dict()
        if d:
            for k, v in d.items():
                print(f"      {k}: {v[:120]}")
        else:
            print(f"      (sin contexto)")
        print(f"      best_caption: {ctx.best_caption()[:120]}")
        print()


def test_real_wikipedia():
    """Test sobre una URL real de Wikipedia (si hay red)."""
    from geodetective.tools.fetch_url import fetch_url
    print("\n=== Test real: Wikipedia 'Praça da Liberdade Porto' ===")
    try:
        fp = fetch_url(
            "https://en.wikipedia.org/wiki/Pra%C3%A7a_da_Liberdade_(Porto)",
            include_images=True,
            timeout=15.0,
        )
    except Exception as e:
        print(f"  network error (skipping): {e}")
        return
    print(f"  status={fp.status_code} title={fp.title[:80]}")
    print(f"  text_len={len(fp.text)} truncated={fp.text_truncated}")
    print(f"  images={len(fp.images)}")
    for i, im in enumerate(fp.images[:5], 1):
        print(f"\n  [{i}] {im.url[:100]}")
        if im.context:
            d = im.context.to_dict()
            for k, v in d.items():
                print(f"      {k}: {v[:100]}")
            print(f"      best_caption: {im.context.best_caption()[:120]}")
        else:
            print(f"      (sin contexto)")


if __name__ == "__main__":
    print("=== Test sintético ===\n")
    test_extract_basic()

    print("\n" + "=" * 60)
    test_real_wikipedia()
    print("\nALL TESTS DONE")
