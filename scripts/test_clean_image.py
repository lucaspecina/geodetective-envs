"""Tests sintéticos de geodetective.corpus.clean_image (issue #22).

No depende de fotos PastVu reales — genera imágenes de prueba con propiedades
controladas (EXIF, RGBA, watermark sintético) y verifica que la limpieza:
- recorte la franja correcta cuando hay watermark.
- NO recorte cuando waterh=0 / None / provider unknown.
- componga RGBA sobre fondo blanco (no negro).
- elimine EXIF y metadata embebida.
- maneje served_h != meta_h proporcionalmente.

Uso: python scripts/test_clean_image.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.corpus import clean_image, CLEAN_VERSION


def _make_jpeg_with_watermark(
    path: Path,
    size: tuple[int, int] = (800, 600),
    watermark_h: int = 30,
    with_exif: bool = False,
) -> None:
    """JPEG con franja roja en el bottom (simula watermark) y EXIF opcional."""
    img = Image.new("RGB", size, (200, 200, 200))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.rectangle([0, h - watermark_h, w, h], fill=(255, 0, 0))
    draw.rectangle([10, 10, 60, 60], fill=(0, 0, 255))  # marcador top-left
    save_kwargs = {"format": "JPEG", "quality": 92}
    if with_exif:
        exif = img.getexif()
        exif[0x010E] = "TEST_DESCRIPTION_LEAK"  # ImageDescription
        exif[0x8298] = "TEST_COPYRIGHT_LEAK"  # Copyright
        save_kwargs["exif"] = exif.tobytes()
    img.save(path, **save_kwargs)


def _make_png_rgba(path: Path, size: tuple[int, int] = (400, 300)) -> None:
    """Verde semi-transparente (alpha=128) sin outline, para que el composite sea testeable."""
    img = Image.new("RGBA", size, (0, 200, 0, 128))
    img.save(path, format="PNG")


def _make_png_palette_with_transparency(path: Path) -> None:
    """PNG modo P con palette + transparency entry."""
    img = Image.new("P", (200, 150))
    img.putpalette([0, 200, 0] * 256)
    img.info["transparency"] = 0
    img.save(path, format="PNG", transparency=0)


def _make_jpeg_with_comment_and_icc(path: Path) -> None:
    """JPEG con comment + ICC profile sintético (no válido como ICC pero suficiente para verificar strip)."""
    img = Image.new("RGB", (300, 200), (180, 180, 180))
    fake_icc = b"\x00\x00\x02\x0cMOCK_ICC_PROFILE_PAYLOAD" + b"\x00" * 200
    img.save(
        path,
        format="JPEG",
        quality=92,
        comment=b"MOCK_JPEG_COMMENT_LEAK",
        icc_profile=fake_icc,
    )


def _has_jpeg_comment(path: Path) -> bool:
    """Buscar markers COM (0xFFFE) y APP2/ICC (0xFFE2) en raw bytes."""
    data = path.read_bytes()
    return b"\xff\xfe" in data or b"MOCK_JPEG_COMMENT" in data


def _has_icc(path: Path) -> bool:
    img = Image.open(path)
    return bool(img.info.get("icc_profile"))


def _has_exif(path: Path) -> bool:
    img = Image.open(path)
    return bool(img.info.get("exif")) or bool(img.getexif())


def _pixel(path: Path, xy: tuple[int, int]) -> tuple[int, int, int]:
    img = Image.open(path).convert("RGB")
    return img.getpixel(xy)[:3]


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return cond


def run_tests() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # T1 — JPEG con EXIF, provider=pastvu, waterh real
        print("\nT1 — JPEG + EXIF + watermark, provider=pastvu")
        raw = td / "t1_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(800, 600), watermark_h=30, with_exif=True)
        # h "original" = 600, waterh=30 → crop_px=30
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 30, "h": 600}, out_dir=td)
        failures += not _check("action=cleaned", r.action == "cleaned", r.action)
        failures += not _check("crop_px=30", r.crop_px == 30, str(r.crop_px))
        failures += not _check("had_exif=True", r.had_exif is True)
        failures += not _check("had_alpha=False", r.had_alpha is False)
        failures += not _check("no EXIF en output", not _has_exif(r.path))
        out_h = Image.open(r.path).size[1]
        failures += not _check("altura post-crop=570", out_h == 570, str(out_h))

        # T2 — PNG RGBA, provider=pastvu, waterh + provider_meta downsize.
        # ceil: 30*300/900 = 10.0 exacto → crop_px=10. 30*299/900=9.97 → ceil=10 (clamp).
        print("\nT2 — PNG RGBA, downsize (served_h != meta_h)")
        raw = td / "t2_raw.png"
        _make_png_rgba(raw, size=(400, 300))
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 30, "h": 900}, out_dir=td)
        failures += not _check("action=cleaned", r.action == "cleaned", r.action)
        failures += not _check("crop_px=10 (ceil 30*300/900)", r.crop_px == 10, str(r.crop_px))
        failures += not _check("had_alpha=True", r.had_alpha is True)
        failures += not _check("anota scaling", any("scaling_crop" in n for n in r.notes), str(r.notes))
        # Pixel interior (50,50): alpha=128 sobre verde (0,200,0) compuesto con blanco
        # → R≈127, G≈227, B≈127 aprox. Si el composite fuera contra negro: R≈0, G≈100, B≈0.
        px = _pixel(r.path, (50, 50))
        failures += not _check(
            "RGBA→RGB sobre blanco (no negro)",
            px[0] > 100 and px[2] > 100,
            f"R={px[0]} G={px[1]} B={px[2]}",
        )

        # T3 — waterh=0 (sin watermark conocido) → no crop
        print("\nT3 — waterh=0, provider=pastvu → no crop")
        raw = td / "t3_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 400), watermark_h=0)
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 0, "h": 400}, out_dir=td)
        failures += not _check("action=no_watermark", r.action == "no_watermark", r.action)
        failures += not _check("crop_px=0", r.crop_px == 0)
        failures += not _check("note waterh_zero_or_missing", any("waterh_zero" in n for n in r.notes))

        # T4 — waterh=None
        print("\nT4 — waterh=None, provider=pastvu → no crop")
        raw = td / "t4_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 400), watermark_h=0)
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": None, "h": 400}, out_dir=td)
        failures += not _check("action=no_watermark", r.action == "no_watermark", r.action)
        failures += not _check("crop_px=0", r.crop_px == 0)

        # T5 — provider=unknown → no crop, nota
        print("\nT5 — provider=unknown → no crop, nota")
        raw = td / "t5_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 400), watermark_h=20)
        r = clean_image(raw, provider="unknown", provider_meta={"waterh": 20, "h": 400}, out_dir=td)
        failures += not _check("action=no_watermark", r.action == "no_watermark", r.action)
        failures += not _check("crop_px=0", r.crop_px == 0)
        failures += not _check("note unknown_provider", any("unknown_provider" in n for n in r.notes))

        # T6 — provider=smapshot (stub no implementado)
        print("\nT6 — provider=smapshot (stub) → no crop, nota")
        raw = td / "t6_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 400), watermark_h=20)
        r = clean_image(raw, provider="smapshot", provider_meta={}, out_dir=td)
        failures += not _check("action=no_watermark", r.action == "no_watermark", r.action)
        failures += not _check("note rule_not_implemented", any("rule_not_implemented" in n for n in r.notes))

        # T7 — cache: segunda llamada devuelve skipped_cached
        print("\nT7 — cache: 2da call → skipped_cached")
        raw = td / "t7_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 400), watermark_h=20, with_exif=True)
        r1 = clean_image(raw, provider="pastvu", provider_meta={"waterh": 20, "h": 400}, out_dir=td)
        r2 = clean_image(raw, provider="pastvu", provider_meta={"waterh": 20, "h": 400}, out_dir=td)
        failures += not _check("r1 cleaned", r1.action == "cleaned")
        failures += not _check("r2 skipped_cached", r2.action == "skipped_cached", r2.action)
        failures += not _check("r2 path same as r1", r1.path == r2.path)

        # T8 — force=True invalida cache
        print("\nT8 — force=True regenera")
        r3 = clean_image(raw, provider="pastvu", provider_meta={"waterh": 20, "h": 400}, out_dir=td, force=True)
        failures += not _check("r3 cleaned (no cached)", r3.action == "cleaned", r3.action)

        # T9 — filename con _raw → versionado
        print("\nT9 — filename versionado contiene _clean_v{N}")
        failures += not _check(
            f"path contiene _clean_v{CLEAN_VERSION}",
            f"_clean_v{CLEAN_VERSION}" in r3.path.name,
            r3.path.name,
        )

        # T10 — PNG modo P con transparency → composite sobre blanco
        print("\nT10 — PNG mode P + transparency → RGB sobre blanco")
        raw = td / "t10_raw.png"
        _make_png_palette_with_transparency(raw)
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 0, "h": 150}, out_dir=td)
        failures += not _check("had_alpha=True (P+transparency)", r.had_alpha is True)
        failures += not _check("output abre como JPEG", r.path.exists() and r.path.suffix == ".jpg")
        # No verificamos pixel exacto porque la palette varía, pero confirmamos que abre como RGB
        failures += not _check("output mode=RGB", Image.open(r.path).mode == "RGB")

        # T11 — JPEG con comment + ICC → strip ambos
        print("\nT11 — JPEG con comment + ICC → ambos strippeados")
        raw = td / "t11_raw.jpg"
        _make_jpeg_with_comment_and_icc(raw)
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 0, "h": 200}, out_dir=td)
        failures += not _check("output existe", r.path is not None and r.path.exists())
        failures += not _check("no MOCK_JPEG_COMMENT en output", b"MOCK_JPEG_COMMENT" not in r.path.read_bytes())
        failures += not _check("no ICC profile en output", not _has_icc(r.path))

        # T12 — metadata patológica: waterh > h → discarded, no pass-through
        print("\nT12 — waterh >= h (metadata corrupta) → discarded")
        raw = td / "t12_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 100), watermark_h=10)
        # waterh=200 con orig_h=100 → crop_px=200 >= h=100 → debe descartar
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 200, "h": 100}, out_dir=td)
        failures += not _check("action=discarded", r.action == "discarded", r.action)
        failures += not _check("path=None", r.path is None)
        failures += not _check("note invalid_meta", any("invalid_meta" in n for n in r.notes), str(r.notes))

        # T13 — ceil clamp: caso non-integer crop
        print("\nT13 — ceil clamp en crop proporcional no entero")
        raw = td / "t13_raw.jpg"
        _make_jpeg_with_watermark(raw, size=(500, 299), watermark_h=10)
        # waterh=30, orig_h=900, served_h=299 → 30*299/900 = 9.97 → ceil = 10
        r = clean_image(raw, provider="pastvu", provider_meta={"waterh": 30, "h": 900}, out_dir=td)
        failures += not _check("crop_px=10 (ceil de 9.97)", r.crop_px == 10, str(r.crop_px))

    print(f"\n{'=' * 50}")
    if failures:
        print(f"❌ {failures} fallos")
        return 1
    print("✅ Todos los tests pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
