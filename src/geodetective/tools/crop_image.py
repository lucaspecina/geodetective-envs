"""crop_image / zoom_in: hacer zoom en una región específica de la foto target.

Útil para detalles chiquitos (carteles, números, marcas) que el modelo no lee
cuando ve la foto entera redimensionada a 512x512.

Tool local, sin red. Solo PIL.
"""
from __future__ import annotations
import base64
from io import BytesIO
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from PIL import Image


@dataclass
class CropResult:
    """Una imagen cropeada lista para mostrar al modelo."""
    base64_jpeg: str
    width: int
    height: int
    region: dict  # {"x", "y", "w", "h"} en pixels de la imagen original
    note: Optional[str] = None


def crop_image(
    image_path: str | Path,
    x: int,
    y: int,
    width: int,
    height: int,
    upscale_to: int = 1024,
) -> CropResult:
    """Recortar una región de la imagen y opcionalmente escalarla a `upscale_to` (lado mayor).

    Args:
        image_path: ruta a la foto target.
        x, y: esquina superior izquierda del crop (pixels en la imagen original).
        width, height: dimensiones del crop.
        upscale_to: tamaño deseado del lado mayor del output. Default 1024 para que detalles
                    chiquitos sean legibles.
    """
    img = Image.open(image_path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    W, H = img.size
    # Clamp coords
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    width = max(1, min(width, W - x))
    height = max(1, min(height, H - y))
    crop = img.crop((x, y, x + width, y + height))
    cw, ch = crop.size
    # Upscale para detalles chiquitos
    if max(cw, ch) < upscale_to:
        ratio = upscale_to / max(cw, ch)
        new_size = (int(cw * ratio), int(ch * ratio))
        crop = crop.resize(new_size, Image.LANCZOS)
    buf = BytesIO()
    crop.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return CropResult(
        base64_jpeg=b64,
        width=crop.size[0],
        height=crop.size[1],
        region={"x": x, "y": y, "w": width, "h": height},
        note=f"Cropped from original {W}x{H}, displayed at {crop.size[0]}x{crop.size[1]}.",
    )


def crop_image_relative(
    image_path: str | Path,
    region: str,
    upscale_to: int = 1024,
) -> CropResult:
    """Versión simplificada: cropear una región nombrada de la imagen.

    region: 'top_left', 'top_right', 'top_center', 'middle', 'bottom_left',
            'bottom_right', 'bottom_center', 'left_half', 'right_half',
            'top_half', 'bottom_half', 'center'.
    """
    img = Image.open(image_path)
    W, H = img.size
    h_third = H // 3
    w_third = W // 3
    h_half = H // 2
    w_half = W // 2

    regions = {
        "top_left":      (0, 0, w_third, h_third),
        "top_right":     (W - w_third, 0, w_third, h_third),
        "top_center":    (w_third, 0, w_third, h_third),
        "bottom_left":   (0, H - h_third, w_third, h_third),
        "bottom_right":  (W - w_third, H - h_third, w_third, h_third),
        "bottom_center": (w_third, H - h_third, w_third, h_third),
        "middle":        (w_third, h_third, w_third, h_third),
        "center":        (w_third, h_third, w_third, h_third),
        "left_half":     (0, 0, w_half, H),
        "right_half":    (w_half, 0, w_half, H),
        "top_half":      (0, 0, W, h_half),
        "bottom_half":   (0, h_half, W, h_half),
    }
    if region not in regions:
        raise ValueError(f"region '{region}' inválida. Opciones: {list(regions)}")
    x, y, w, h = regions[region]
    return crop_image(image_path, x, y, w, h, upscale_to=upscale_to)


# OpenAI tool schemas
TOOL_SCHEMA_CROP = {
    "type": "function",
    "function": {
        "name": "crop_image",
        "description": (
            "Hacer zoom en una región específica de la foto target. Útil cuando hay un detalle "
            "chiquito (cartel, número, escritura) que no se lee bien en la foto completa. "
            "Las coordenadas están en pixels de la imagen original. Si no sabés las coords exactas, "
            "usá crop_image_relative con regiones nombradas (top_left, center, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X de la esquina superior izquierda del crop."},
                "y": {"type": "integer", "description": "Y de la esquina superior izquierda."},
                "width": {"type": "integer", "description": "Ancho del crop en pixels."},
                "height": {"type": "integer", "description": "Alto del crop en pixels."},
            },
            "required": ["x", "y", "width", "height"],
        },
    },
}

TOOL_SCHEMA_CROP_RELATIVE = {
    "type": "function",
    "function": {
        "name": "crop_image_relative",
        "description": (
            "Hacer zoom en una región nombrada de la foto target (más fácil que coords exactas). "
            "Opciones: top_left, top_right, top_center, bottom_left, bottom_right, bottom_center, "
            "middle, center, left_half, right_half, top_half, bottom_half."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "enum": [
                        "top_left", "top_right", "top_center",
                        "bottom_left", "bottom_right", "bottom_center",
                        "middle", "center",
                        "left_half", "right_half", "top_half", "bottom_half",
                    ],
                },
            },
            "required": ["region"],
        },
    },
}
