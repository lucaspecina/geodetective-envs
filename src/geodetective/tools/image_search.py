"""image_search v2 (refs #42): grilla 4×4 + zoom on-demand.

Replica el flujo humano en Google Images:
1. image_search(query)              → devuelve grilla 4×4 con 16 thumbnails numerados
2. image_search(query, pick=[3,7])  → devuelve esas celdas en alta resolución 512×512
3. fetch_url_with_images(url_celda) → modelo abre la página fuente si quiere

Diseño post-review Codex (agentId ae26f57001224b393):
- Celdas 384×384 con gutters 5px (grilla total ~1568px)
- Números top-left con fondo opaco
- Curación: DDG top → blocklist → pHash <8 hard-reject → diversidad pHash → 16
- pHash bands: <8 descartar, 8-12 loggear como suspicious (no mostrar)
- Backend cache 50 candidatos por search_id (UUID)
- Metadata por celda al modelo: solo cell_num + alt_text truncado (no domain, no hamming)
- Hamming distance solo en trace (no expuesto al modelo — decisión visual)
- Logging de no-picks para process eval

Backend: DuckDuckGo Images via `ddgs` (gratis, sin API key).
"""
from __future__ import annotations

import base64
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable, Optional, Union

import httpx
import imagehash
from ddgs import DDGS
from PIL import Image, ImageDraw, ImageFont

from ..corpus.blacklist import is_blocked


# === Constantes de diseño ===
GRID_ROWS = 4
GRID_COLS = 4
N_CELLS = GRID_ROWS * GRID_COLS  # 16
CELL_SIZE = 384
GUTTER = 5
ZOOM_SIZE = 512  # alta resolución para picks
OVERFETCH_N = 50  # cantidad a bajar para curar 16

# pHash bands (Codex review)
HARD_REJECT_THRESHOLD = 8       # hamming < 8 → descartar (anti-shortcut)
SUSPICIOUS_THRESHOLD = 12       # 8 <= hamming < 12 → loggear como suspicious, no mostrar

# Limit Codex review
MAX_PICKS_PER_SEARCH = 3
MAX_PICK_ROUNDS = 2


# === Dataclasses ===

@dataclass
class CellMetadata:
    """Metadata visible para el modelo de cada celda (sin shortcut hints)."""
    cell: int
    width: int   # post-thumbnail
    height: int
    alt_text: str = ""  # truncado, de DDG si está

    def to_dict(self) -> dict:
        out = {"cell": self.cell, "width": self.width, "height": self.height}
        if self.alt_text:
            out["alt_text"] = self.alt_text[:120]
        return out


@dataclass
class _CellInternal:
    """Estado interno completo de una celda (NO se expone al modelo directamente)."""
    cell: int
    url: str
    title: str
    image: Image.Image  # PIL en memoria (alta resolución, para zoom)
    hamming_distance: Optional[int] = None
    is_likely_target: bool = False
    is_suspicious: bool = False  # 8-12 hamming


@dataclass
class _CachedSearch:
    """Estado completo cacheado por search_id (backend only)."""
    search_id: str
    query: str
    grid_image: Image.Image       # imagen compuesta 4×4
    cells: list[_CellInternal]    # 16 celdas internas
    extras: list[_CellInternal]   # 34 candidatos sobrantes (para paginación futura)
    suspicious: list[dict]        # logueados, no mostrados
    target_hash: Optional[imagehash.ImageHash]
    excluded_domains: list[str]
    blocked_count: int = 0
    download_failed_count: int = 0
    target_match_count: int = 0
    total_raw_urls: int = 0
    created_ts: float = field(default_factory=time.time)
    pick_rounds: int = 0          # contador de cuántas rondas de pick lleva
    picked_cells: set[int] = field(default_factory=set)  # celdas ya pickeadas


@dataclass
class GridResult:
    """Resultado de una nueva búsqueda image_search (grilla + metadata)."""
    search_id: str
    query: str
    grid_image_b64: str           # grilla composite
    cells_metadata: list[CellMetadata]  # metadata visible al modelo
    n_cells: int
    blocked_domain_count: int = 0
    target_match_count: int = 0
    suspicious_count: int = 0
    note: str = ""

    def to_dict_no_b64(self) -> dict:
        return {
            "search_id": self.search_id,
            "query": self.query,
            "n_cells": self.n_cells,
            "cells_metadata": [c.to_dict() for c in self.cells_metadata],
            "blocked_domain_count": self.blocked_domain_count,
            "target_match_count": self.target_match_count,
            "suspicious_count": self.suspicious_count,
            "note": self.note,
        }


@dataclass
class PickResult:
    """Resultado de image_search con pick (alta resolución)."""
    search_id: str
    query: str
    picks: list[dict]             # [{"cell": N, "url": "...", "image_b64": "...", "alt_text": "..."}, ...]
    grid_image_b64: str           # grilla original re-inyectada (referencia)
    not_picked_cells: list[int]   # celdas mostradas pero no pickeadas (logging)
    rounds_used: int
    rounds_remaining: int
    note: str = ""

    def to_dict_no_b64(self) -> dict:
        return {
            "search_id": self.search_id,
            "query": self.query,
            "picks_metadata": [
                {"cell": p["cell"], "url": p["url"], "alt_text": p.get("alt_text", "")}
                for p in self.picks
            ],
            "not_picked_cells": self.not_picked_cells,
            "rounds_used": self.rounds_used,
            "rounds_remaining": self.rounds_remaining,
            "note": self.note,
        }


@dataclass
class ImageSearchError:
    error: str
    detail: str = ""


# === Cache global ===
_searches: dict[str, _CachedSearch] = {}
_CACHE_TTL = 3600.0  # 1 hora


def _gc_old_searches() -> None:
    """Limpieza simple del cache: borrar entries con >1h."""
    now = time.time()
    expired = [sid for sid, s in _searches.items() if (now - s.created_ts) > _CACHE_TTL]
    for sid in expired:
        del _searches[sid]


# === Pipeline de búsqueda ===

def _fetch_image(url: str, headers: dict, excluded: list[str], timeout: float = 10.0) -> Optional[Image.Image]:
    """Bajar una imagen y devolver PIL Image. None si falla."""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
        if is_blocked(str(r.url), excluded):
            return None
        if r.status_code != 200 or len(r.content) > 5_000_000:
            return None
        img = Image.open(BytesIO(r.content))
        if img.size[0] < 100 or img.size[1] < 100:
            return None  # logo/icono
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def _diversity_pick(candidates: list[_CellInternal], n: int) -> list[_CellInternal]:
    """De N candidatos seleccionar n más diversos por pHash.

    Greedy: empezar con el primero, agregar el más distante de los ya elegidos.
    Codex review: NO max diversidad pura, sino top-ranked filtrado + diversidad dentro.
    Como input ya viene rankeado por DDG, simplemente mantenemos orden si len <= n.
    """
    if len(candidates) <= n:
        return candidates
    selected = [candidates[0]]
    remaining = list(candidates[1:])

    def min_dist_to_selected(c: _CellInternal) -> int:
        if not selected:
            return 0
        ch = imagehash.phash(c.image) if c.image else None
        if ch is None:
            return 0
        return min(int(ch - imagehash.phash(s.image)) for s in selected if s.image)

    while len(selected) < n and remaining:
        # Tomar el más distante de los ya seleccionados (max-min strategy)
        remaining.sort(key=min_dist_to_selected, reverse=True)
        selected.append(remaining.pop(0))
    return selected


def _build_grid(cells: list[_CellInternal]) -> Image.Image:
    """Componer grilla 4×4 con números y gutters."""
    w = GRID_COLS * CELL_SIZE + (GRID_COLS + 1) * GUTTER
    h = GRID_ROWS * CELL_SIZE + (GRID_ROWS + 1) * GUTTER
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    try:
        font = ImageFont.truetype("arial.ttf", size=36)
    except Exception:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(canvas)
    for c in cells:
        idx = c.cell - 1
        row, col = divmod(idx, GRID_COLS)
        x = GUTTER + col * (CELL_SIZE + GUTTER)
        y = GUTTER + row * (CELL_SIZE + GUTTER)
        thumb = c.image.copy()
        thumb.thumbnail((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
        pad_x = (CELL_SIZE - thumb.size[0]) // 2
        pad_y = (CELL_SIZE - thumb.size[1]) // 2
        canvas.paste(thumb, (x + pad_x, y + pad_y))
        # Número con fondo opaco arriba-izq
        label = f"{c.cell:>2}"
        bbox = draw.textbbox((x + 8, y + 8), label, font=font)
        bg = (bbox[0] - 4, bbox[1] - 4, bbox[2] + 4, bbox[3] + 4)
        draw.rectangle(bg, fill=(0, 0, 0), outline=(255, 255, 255), width=2)
        draw.text((x + 8, y + 8), label, fill=(255, 255, 255), font=font)
    return canvas


def _image_to_b64(img: Image.Image, quality: int = 85) -> str:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def _search_new(
    query: str,
    target_image_path: Optional[str],
    excluded_domains: list[str],
) -> Union[_CachedSearch, ImageSearchError]:
    """Pipeline completo: DDG → download → curate → grid."""
    target_hash: Optional[imagehash.ImageHash] = None
    if target_image_path:
        try:
            target_hash = imagehash.phash(Image.open(target_image_path))
        except Exception:
            target_hash = None

    try:
        ddgs = DDGS()
        raw_items = list(ddgs.images(query, max_results=OVERFETCH_N))
    except Exception as e:
        return ImageSearchError(error="ddg_fetch_failed", detail=str(e))

    if not raw_items:
        return ImageSearchError(error="no_results", detail=f"DDG devolvió 0 para '{query}'")

    blocked = 0
    download_failed = 0
    target_match = 0
    suspicious: list[dict] = []
    accepted: list[_CellInternal] = []

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 geodetective-research/0.1"}

    # Download paralelo de 50 candidatos para acelerar (Codex review)
    def download_with_meta(item: dict) -> Optional[tuple[dict, Image.Image]]:
        image_url = item.get("image", "")
        source_page = item.get("url", "")
        if is_blocked(image_url, excluded_domains) or is_blocked(source_page, excluded_domains):
            return None
        img = _fetch_image(image_url, headers, excluded_domains)
        if img is None:
            return None
        return (item, img)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(download_with_meta, item): item for item in raw_items}
        for fut in as_completed(futures):
            res = fut.result()
            if res is None:
                # Distinguir blocked vs download_failed: revisa item original
                item = futures[fut]
                if is_blocked(item.get("image", ""), excluded_domains) or is_blocked(item.get("url", ""), excluded_domains):
                    blocked += 1
                else:
                    download_failed += 1
                continue
            item, img = res

            # pHash check
            this_hash = imagehash.phash(img)
            hamming = None
            is_likely_target = False
            is_suspicious = False
            if target_hash is not None:
                hamming = int(this_hash - target_hash)
                if hamming < HARD_REJECT_THRESHOLD:
                    is_likely_target = True
                    target_match += 1
                    suspicious.append({
                        "url": item.get("image", ""),
                        "hamming_distance": hamming,
                        "category": "hard_reject",
                    })
                    continue  # descartar
                elif hamming < SUSPICIOUS_THRESHOLD:
                    is_suspicious = True
                    suspicious.append({
                        "url": item.get("image", ""),
                        "hamming_distance": hamming,
                        "category": "suspicious_8_12",
                    })
                    continue  # no mostrar pero loguear

            accepted.append(_CellInternal(
                cell=0,  # asignaremos después de la curación
                url=item.get("image", ""),
                title=(item.get("title", "") or "")[:120],
                image=img,
                hamming_distance=hamming,
                is_likely_target=is_likely_target,
                is_suspicious=is_suspicious,
            ))

    if not accepted:
        return ImageSearchError(error="all_filtered", detail="Todas las imágenes fueron descartadas por filtros.")

    # Curación: tomar top N_CELLS de los aceptados (con cierta diversidad)
    selected = _diversity_pick(accepted, N_CELLS)
    extras = [c for c in accepted if c not in selected]

    # Asignar números de celda (1-indexed)
    for i, cell in enumerate(selected):
        cell.cell = i + 1

    grid_img = _build_grid(selected)

    search_id = uuid.uuid4().hex[:12]
    _gc_old_searches()
    cached = _CachedSearch(
        search_id=search_id,
        query=query,
        grid_image=grid_img,
        cells=selected,
        extras=extras,
        suspicious=suspicious,
        target_hash=target_hash,
        excluded_domains=excluded_domains,
        blocked_count=blocked,
        download_failed_count=download_failed,
        target_match_count=target_match,
        total_raw_urls=len(raw_items),
    )
    _searches[search_id] = cached
    return cached


def _do_pick(search_id: str, picks: list[int]) -> Union[PickResult, ImageSearchError]:
    """Recuperar grilla cacheada y devolver celdas pickeadas en alta resolución."""
    cached = _searches.get(search_id)
    if cached is None:
        return ImageSearchError(error="invalid_search_id", detail=f"search_id '{search_id}' no encontrado o expirado.")

    # Validar picks
    valid_picks: list[int] = []
    invalid_picks: list[int] = []
    for p in picks:
        if not isinstance(p, int) or p < 1 or p > N_CELLS:
            invalid_picks.append(p)
            continue
        valid_picks.append(p)

    if invalid_picks:
        return ImageSearchError(
            error="invalid_picks",
            detail=f"Picks fuera de rango 1-{N_CELLS}: {invalid_picks}",
        )

    # Codex: max 3 picks por call
    if len(valid_picks) > MAX_PICKS_PER_SEARCH:
        return ImageSearchError(
            error="too_many_picks",
            detail=f"Max {MAX_PICKS_PER_SEARCH} picks por llamada. Recibí {len(valid_picks)}.",
        )

    # Codex: max 2 rounds
    if cached.pick_rounds >= MAX_PICK_ROUNDS:
        return ImageSearchError(
            error="max_pick_rounds_reached",
            detail=f"Max {MAX_PICK_ROUNDS} rondas de pick por search. Hacé nueva image_search con query diferente.",
        )

    cached.pick_rounds += 1
    # Componer respuesta
    cells_by_num = {c.cell: c for c in cached.cells}
    pick_items = []
    for p in valid_picks:
        cell = cells_by_num.get(p)
        if cell is None:
            continue
        # Hi-res: resize a ZOOM_SIZE máx (preservar aspect)
        hi = cell.image.copy()
        hi.thumbnail((ZOOM_SIZE, ZOOM_SIZE), Image.LANCZOS)
        pick_items.append({
            "cell": p,
            "url": cell.url,
            "image_b64": _image_to_b64(hi),
            "alt_text": cell.title,
            "hamming_distance": cell.hamming_distance,  # solo en interno, no expuesto al modelo
        })
        cached.picked_cells.add(p)

    not_picked = [c.cell for c in cached.cells if c.cell not in cached.picked_cells]

    return PickResult(
        search_id=search_id,
        query=cached.query,
        picks=pick_items,
        grid_image_b64=_image_to_b64(cached.grid_image),
        not_picked_cells=not_picked,
        rounds_used=cached.pick_rounds,
        rounds_remaining=MAX_PICK_ROUNDS - cached.pick_rounds,
    )


# === API pública ===

def image_search(
    query: str,
    pick: Optional[list[int]] = None,
    search_id: Optional[str] = None,
    target_image_path: Optional[str] = None,
    excluded_domains: Optional[Iterable[str]] = None,
    # Back-compat: max_results se ignora en v2 (siempre 16)
    max_results: Optional[int] = None,
) -> Union[GridResult, PickResult, ImageSearchError]:
    """v2 (#42): grilla 4×4 + zoom on-demand.

    Modos:
    1. Nueva búsqueda: image_search(query) → GridResult (16 candidatos en grilla)
    2. Zoom: image_search(query, pick=[N,M], search_id="abc") → PickResult con celdas en hi-res

    Args:
        query: texto de búsqueda.
        pick: lista de números de celda a expandir en alta res. Si no None, search_id requerido.
        search_id: id devuelto por una image_search previa. Necesario con pick.
        target_image_path: ruta a la foto target para pHash hard-reject (anti-shortcut).
        excluded_domains: hosts a bloquear adicional al GLOBAL.
        max_results: IGNORADO en v2. Siempre 16 en la grilla.

    Returns:
        GridResult | PickResult | ImageSearchError
    """
    excluded = list(excluded_domains) if excluded_domains else []

    # Modo 2: pick on existing search
    if pick is not None:
        if not search_id:
            return ImageSearchError(error="missing_search_id", detail="Pick requiere search_id de búsqueda previa.")
        return _do_pick(search_id, pick)

    # Modo 1: nueva búsqueda
    result = _search_new(query=query, target_image_path=target_image_path, excluded_domains=excluded)
    if isinstance(result, ImageSearchError):
        return result

    return GridResult(
        search_id=result.search_id,
        query=result.query,
        grid_image_b64=_image_to_b64(result.grid_image),
        cells_metadata=[
            CellMetadata(cell=c.cell, width=c.image.size[0], height=c.image.size[1], alt_text=c.title)
            for c in result.cells
        ],
        n_cells=len(result.cells),
        blocked_domain_count=result.blocked_count,
        target_match_count=result.target_match_count,
        suspicious_count=len(result.suspicious),
        note=(
            f"Grilla {GRID_ROWS}×{GRID_COLS} con {len(result.cells)} candidatos numerados. "
            f"Para profundizar en celdas específicas, llamá image_search(query, pick=[N,M], search_id='{result.search_id}'). "
            f"Hasta {MAX_PICKS_PER_SEARCH} celdas por pick, {MAX_PICK_ROUNDS} rondas total."
        ),
    )


# OpenAI tool schema
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "image_search",
        "description": (
            "Buscar imágenes con flujo de DOS pasos (replica Google Images): "
            "(1) Sin pick: devuelve UNA grilla 4×4 con 16 candidatos numerados — escaneá visualmente. "
            "(2) Con pick=[N,M] + search_id de la grilla previa: devuelve esas celdas en alta resolución "
            "para inspección detallada. Después podés invocar fetch_url_with_images con la URL de cualquier celda. "
            "Imágenes que matchean visualmente con la foto target se descartan automáticamente (anti-shortcut). "
            f"Max {MAX_PICKS_PER_SEARCH} picks por call, {MAX_PICK_ROUNDS} rondas total por búsqueda."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de búsqueda. En cualquier idioma (relevante al contexto).",
                },
                "pick": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": N_CELLS},
                    "description": f"Lista de números de celda (1-{N_CELLS}) a expandir en alta resolución. "
                                   "Solo si ya hiciste image_search previa para obtener la grilla. Requiere search_id.",
                },
                "search_id": {
                    "type": "string",
                    "description": "ID de la búsqueda previa (devuelto en GridResult). Requerido con pick.",
                },
            },
            "required": ["query"],
        },
    },
}
