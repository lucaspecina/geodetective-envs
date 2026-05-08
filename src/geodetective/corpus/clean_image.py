"""Limpieza pre-filtro de imágenes del corpus (Paso 0 del pipeline #21).

Antes de cualquier filtro adversarial, una foto cruda tiene que:
- normalizarse de modo (RGBA → RGB sobre fondo blanco, no negro).
- recortar la marca de agua que imprime el provider (si la imprime).
- re-encodearse strippeando EXIF / XMP / JPEG comments / ICC.

`provider` = de qué API/archivo bajamos la imagen (pastvu, smapshot, ...).
NO confundir con `provenance` (origen original: wikimedia/flickr/native/external),
que es otro concepto y no controla el crop.
"""
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

# Bumpear cuando cambia la lógica → invalida fotos `_clean_vN.jpg` viejas.
CLEAN_VERSION = 1


@dataclass
class CleanResult:
    path: Optional[Path]
    action: str  # "cleaned" | "no_watermark" | "discarded" | "skipped_cached"
    crop_px: int = 0
    crop_pct: float = 0.0
    had_alpha: bool = False
    had_exif: bool = False
    notes: list[str] = field(default_factory=list)


def clean_image(
    raw_path: Path,
    provider: str,
    provider_meta: Optional[dict] = None,
    out_dir: Optional[Path] = None,
    force: bool = False,
) -> CleanResult:
    """Limpia una imagen cruda y devuelve auditoría.

    raw_path: archivo descargado tal cual del provider.
    provider: "pastvu" | "smapshot" | "loc" | ... | "unknown".
    provider_meta: dict con datos del provider. Para pastvu: {"waterh": int, "h": int}.
    out_dir: dónde escribir el archivo limpio (default: junto al raw).
    force: si True, regenera aunque exista cache.
    """
    raw_path = Path(raw_path)
    if not raw_path.exists():
        return CleanResult(path=None, action="discarded", notes=[f"raw_not_found:{raw_path}"])

    out_dir = Path(out_dir) if out_dir else raw_path.parent
    out_path = out_dir / f"{raw_path.stem.removesuffix('_raw')}_clean_v{CLEAN_VERSION}.jpg"

    if out_path.exists() and not force:
        return CleanResult(path=out_path, action="skipped_cached")

    try:
        img = Image.open(raw_path)
        img.load()
    except Exception as exc:
        return CleanResult(path=None, action="discarded", notes=[f"open_failed:{exc!r}"])

    had_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    had_exif = bool(img.info.get("exif")) or bool(img.getexif())

    img_rgb = _normalize_mode(img)
    img_cropped, crop_px, notes = _apply_provider_rule(img_rgb, provider, provider_meta or {})

    if img_cropped is None:
        # Metadata patológica (ej: waterh >= h). Mejor descartar que dejar watermark entero.
        return CleanResult(
            path=None,
            action="discarded",
            crop_px=crop_px,
            had_alpha=had_alpha,
            had_exif=had_exif,
            notes=notes,
        )

    h_before = img_rgb.size[1]
    crop_pct = (crop_px / h_before) if h_before else 0.0

    out_dir.mkdir(parents=True, exist_ok=True)
    _reencode_strip_metadata(img_cropped, out_path)

    action = "cleaned" if crop_px > 0 else "no_watermark"
    return CleanResult(
        path=out_path,
        action=action,
        crop_px=crop_px,
        crop_pct=crop_pct,
        had_alpha=had_alpha,
        had_exif=had_exif,
        notes=notes,
    )


def _normalize_mode(img: Image.Image) -> Image.Image:
    """Cualquier modo con alpha → RGB sobre fondo blanco (no negro). Resto → convert directo."""
    if img.mode == "RGB":
        return img
    has_alpha = (
        img.mode in ("RGBA", "LA", "PA", "La", "RGBa")
        or "transparency" in img.info
    )
    if has_alpha:
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    # L, CMYK, YCbCr, I, F
    return img.convert("RGB")


def _apply_provider_rule(
    img: Image.Image,
    provider: str,
    meta: dict,
) -> tuple[Image.Image, int, list[str]]:
    """Aplica la regla de crop de watermark del provider. Devuelve (img_cropped, crop_px, notes)."""
    notes: list[str] = []
    w, h = img.size

    if provider == "pastvu":
        waterh = meta.get("waterh")
        orig_h = meta.get("h")
        if waterh is None or waterh <= 0:
            notes.append("pastvu:waterh_zero_or_missing")
            return img, 0, notes
        if orig_h is None or orig_h <= 0:
            notes.append("pastvu:orig_h_missing,using_served_h")
            orig_h = h
        if orig_h != h:
            notes.append(f"pastvu:served_h={h}!=meta_h={orig_h},scaling_crop")
        # ceil + clamp >=1: evita dejar 1px de watermark por floor en downscale no entero.
        crop_px = max(1, math.ceil(waterh * h / orig_h))
        if crop_px >= h:
            notes.append(f"pastvu:crop_px={crop_px}>=h={h},invalid_meta")
            return None, crop_px, notes
        return img.crop((0, 0, w, h - crop_px)), crop_px, notes

    if provider in ("smapshot", "loc", "oldnyc"):
        notes.append(f"{provider}:rule_not_implemented")
        return img, 0, notes

    notes.append(f"unknown_provider:{provider}")
    return img, 0, notes


def _reencode_strip_metadata(img: Image.Image, out_path: Path) -> None:
    """Re-encode JPEG sin EXIF / ICC / comments / XMP. Escritura atómica (temp + replace)
    para evitar archivos truncados si el proceso crashea entre save y completar."""
    # Re-crear imagen desde píxeles para descartar TODO `img.info` (comment, xmp, dpi, etc.).
    # Pillow puede arrastrar `comment` en JPEG save si está en info.
    clean = Image.new(img.mode, img.size)
    clean.putdata(list(img.getdata()))
    buf = BytesIO()
    clean.save(
        buf,
        format="JPEG",
        quality=92,
        optimize=True,
        exif=b"",
        icc_profile=None,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=out_path.name + ".", suffix=".tmp", dir=str(out_path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(buf.getvalue())
        os.replace(tmp, out_path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
