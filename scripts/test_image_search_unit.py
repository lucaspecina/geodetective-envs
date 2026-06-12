"""Tests unitarios de image_search (sin red) — fixes junio 2026.

Cubre los bugs encontrados en el harness review (#47):
- _do_pick crasheaba con AttributeError (cached.cells / cached.grid_image no
  existen desde el refactor de paginación #45).
- Picks de celdas >16 (páginas 2+) eran rechazados por validación desactualizada.
- _build_grid pegaba las celdas de páginas 2+ FUERA del canvas (posición por
  número global en vez de posición local).
- _build_grid generaba canvas 4×4 completo para 1 celda (imagen negra gigante).
- _simplify_query para el fallback de DDG con queries largas.

Uso: python scripts/test_image_search_unit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from PIL import Image

from geodetective.tools.image_search import (  # noqa: E402
    _build_grid,
    _CachedSearch,
    _CellInternal,
    _do_pick,
    _searches,
    _simplify_query,
    CELL_SIZE,
    GUTTER,
    ImageSearchError,
    PickResult,
)


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return cond


def _mk_cell(num: int, color: tuple) -> _CellInternal:
    return _CellInternal(
        cell=num, url=f"https://example.org/img{num}.jpg",
        title=f"imagen {num}", image=Image.new("RGB", (300, 200), color),
    )


def _mk_cached(n_cells: int) -> _CachedSearch:
    cells = [_mk_cell(i + 1, ((i * 37) % 256, (i * 91) % 256, (i * 53) % 256)) for i in range(n_cells)]
    cached = _CachedSearch(search_id="test12345678", query="test query", all_cells=cells)
    _searches["test12345678"] = cached
    return cached


def run_tests() -> int:
    failures = 0

    print("\nT1 — _do_pick funciona (regresión del AttributeError)")
    _mk_cached(20)  # 2 páginas: 16 + 4
    res = _do_pick("test12345678", [3, 7])
    failures += not _check("pick devuelve PickResult, no error", isinstance(res, PickResult),
                           getattr(res, "error", ""))
    if isinstance(res, PickResult):
        failures += not _check("devuelve las 2 celdas pedidas en hi-res",
                               len(res.picks) == 2 and all(p.get("image_b64") for p in res.picks))
        failures += not _check("grilla de referencia re-inyectada", bool(res.grid_image_b64))

    print("\nT2 — picks en página 2 (celdas 17+) ahora válidos")
    _mk_cached(20)
    res = _do_pick("test12345678", [18])
    failures += not _check("pick de celda 18 aceptado", isinstance(res, PickResult),
                           getattr(res, "detail", ""))
    res = _do_pick("test12345678", [25])
    failures += not _check("pick de celda inexistente (25 de 20) rechazado",
                           isinstance(res, ImageSearchError))

    print("\nT3 — _build_grid: tamaño según celdas reales")
    g1 = _build_grid([_mk_cell(1, (200, 0, 0))])
    expected_1 = CELL_SIZE + 2 * GUTTER
    failures += not _check("1 celda -> canvas 1x1, no 4x4",
                           g1.size == (expected_1, expected_1), f"{g1.size}")
    g6 = _build_grid([_mk_cell(i + 1, (0, 100, 0)) for i in range(6)])
    failures += not _check("6 celdas -> 4 cols x 2 rows",
                           g6.size == (4 * CELL_SIZE + 5 * GUTTER, 2 * CELL_SIZE + 3 * GUTTER),
                           f"{g6.size}")

    print("\nT4 — _build_grid página 2: celdas DENTRO del canvas (posición local)")
    page2_cells = [_mk_cell(i, (250, 250, 0)) for i in range(17, 21)]  # celdas 17-20
    g = _build_grid(page2_cells)
    # Si las celdas se pegaran por número global (fila 4+), el canvas quedaría negro.
    # Chequeo: hay píxeles no-negros dentro del canvas.
    extrema = g.convert("L").getextrema()
    failures += not _check("página 2 tiene contenido visible (no canvas negro)",
                           extrema[1] > 50, f"extrema={extrema}")

    print("\nT5 — _simplify_query")
    failures += not _check(
        "trunca a 6 palabras y saca comillas",
        _simplify_query('"old photo" apartment building stepped gable balcony crowd baltic city')
        == "old photo apartment building stepped gable",
    )
    failures += not _check("query corta queda igual", _simplify_query("tram Lisboa") == "tram Lisboa")

    # cleanup
    _searches.pop("test12345678", None)
    return failures


if __name__ == "__main__":
    n = run_tests()
    print(f"\n{'=' * 60}")
    print("TODOS LOS TESTS OK" if n == 0 else f"{n} TESTS FALLARON")
    sys.exit(1 if n else 0)
