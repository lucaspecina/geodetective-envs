"""Detector de overlays textuales (anti-shortcut Paso 0.5).

Pasa cada foto a un VLM con tool calling. El VLM detecta regiones con texto y
las clasifica:
  - in_scene: texto que estaba EN la realidad fotografiada (carteles, signage, ads).
  - archive_overlay: texto agregado al papel/scan DESPUÉS (captions, números de
    archivo, leyendas en margen). Estos son shortcuts y hay que blurrearlos.
  - uncertain: caso borde — el script los lista pero no los blurrea por default.

Output:
  - {input}_overlay_detection.json  (estructura: list[{photo: ..., regions: [...]}])
  - {input}_overlay_viz/{cid}.jpg   (foto original + bboxes dibujados por color)

Uso:
  python scripts/detect_text_overlays.py --photos-dir experiments/E010_iteration_pilot/photos \\
      --out-dir experiments/E011_text_overlay_detection \\
      --model gpt-5.4 \\
      --pattern "*_clean_v1.jpg"
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env (formato KEY=VALUE)
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from geodetective.llm_adapter import complete as llm_complete


SYSTEM_PROMPT = """Sos un anotador de visión que detecta y clasifica regiones con texto en una fotografía histórica.

Tu tarea: identificar TODAS las regiones con texto visible y clasificarlas en una de:

1. **in_scene**: texto que estaba presente en la REALIDAD FOTOGRAFIADA en el momento de la captura. Ejemplos:
   - Cartel de tienda, banner, marquesina de cine, letrero de calle
   - Texto en vehículo (matrícula, nombre de empresa)
   - Pósters / publicidad pegada en pared
   - Inscripción tallada en monumento, placa
   - Texto en ropa / uniforme de personas
   Pista: tiene perspectiva acorde a la escena, lighting consistente, en plano del objeto fotografiado.

2. **archive_overlay**: texto AGREGADO al papel/scan DESPUÉS de tomar la foto. Ejemplos:
   - Caption manuscrita o impresa al pie/margen describiendo el lugar/año
   - Número de catálogo de archivo
   - Sello de archivo / firma del fotógrafo
   - Watermark del proveedor (PastVu, archivo digital)
   - Texto en margen blanco/negro fuera del marco visual de la escena
   Pista: fronto-parallel (sin perspectiva), suele estar en bordes, contrast uniforme, font tipo máquina de escribir o letra manuscrita.

3. **uncertain**: no podés determinar con confianza si está en escena o fue agregada después.

REGLAS:
- Devolvé bboxes en pixels de la imagen original (x, y desde top-left; w, h dimensiones).
- Sé EXHAUSTIVO: cualquier región con caracteres legibles, incluso parcial, va en la lista.
- En caso de duda entre in_scene y archive_overlay, preferí 'uncertain' antes que adivinar.
- Si una región tiene texto pero NO podés transcribir nada, igual reportala con text_snippet="(ilegible)".
- Si la foto NO tiene texto detectable, devolvé regions=[].
"""


DETECT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_text_regions",
        "description": "Reportar todas las regiones con texto detectadas en la foto, con su clasificación.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_size": {
                    "type": "object",
                    "description": "Dimensiones de la foto en pixels (para calibrar bboxes).",
                    "properties": {
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["width", "height"],
                },
                "regions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "bbox": {
                                "type": "object",
                                "description": "Bounding box en pixels (x,y top-left + w,h).",
                                "properties": {
                                    "x": {"type": "integer"},
                                    "y": {"type": "integer"},
                                    "w": {"type": "integer"},
                                    "h": {"type": "integer"},
                                },
                                "required": ["x", "y", "w", "h"],
                            },
                            "text_snippet": {
                                "type": "string",
                                "description": "Lo que dice el texto, transliterado o parcial. '(ilegible)' si no se lee.",
                            },
                            "classification": {
                                "type": "string",
                                "enum": ["in_scene", "archive_overlay", "uncertain"],
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Por qué clasificaste así (perspectiva, posición, font, contexto).",
                            },
                        },
                        "required": ["bbox", "text_snippet", "classification", "confidence", "reasoning"],
                    },
                },
                "overall_note": {
                    "type": "string",
                    "description": "Comentario global sobre la foto si corresponde (ej: 'foto sin texto detectable', 'foto muy ruidosa').",
                },
            },
            "required": ["image_size", "regions"],
        },
    },
}


def detect_overlays(image_path: Path, model: str) -> dict:
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"
    with Image.open(image_path) as im:
        w, h = im.size

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Analizá esta foto ({w}x{h} px). Detectá todas las regiones con texto, clasificá cada una, y llamá `report_text_regions` con el resultado."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    response = llm_complete(
        model=model,
        messages=messages,
        tools=[DETECT_TOOL],
        tool_choice="auto",
        max_completion_tokens=4000,
        timeout=120.0,
    )
    msg = response.choices[0].message
    if not msg.tool_calls:
        return {"error": "no_tool_call", "content": msg.content, "image_size": {"width": w, "height": h}}

    tc = msg.tool_calls[0]
    try:
        result = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        return {"error": f"json_decode: {e}", "raw": tc.function.arguments}

    # Forzar image_size desde lectura local (modelo puede equivocarse)
    result["image_size"] = {"width": w, "height": h}
    return result


COLOR_BY_CLASS = {
    "in_scene": "#22c55e",         # verde — keep
    "archive_overlay": "#dc2626",  # rojo — blur
    "uncertain": "#f59e0b",        # amarillo — revisar
}


def blur_overlays(image_path: Path, regions: list[dict], out_path: Path,
                  blur_uncertain: bool = False, pad: int = 6, radius: int = 20) -> None:
    """Aplica blur gaussiano fuerte sobre regiones archive_overlay (y opcional uncertain).

    pad: pixels extra alrededor del bbox (por si el modelo subestimó el tamaño).
    radius: radio del GaussianBlur (más grande = más fuerte).
    """
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    classes_to_blur = {"archive_overlay"} | ({"uncertain"} if blur_uncertain else set())
    for r in regions:
        if r.get("classification") not in classes_to_blur:
            continue
        b = r.get("bbox") or {}
        x = max(0, b.get("x", 0) - pad)
        y = max(0, b.get("y", 0) - pad)
        w = min(W - x, b.get("w", 0) + 2 * pad)
        h = min(H - y, b.get("h", 0) + 2 * pad)
        if w <= 0 or h <= 0:
            continue
        region = img.crop((x, y, x + w, y + h))
        blurred = region.filter(ImageFilter.GaussianBlur(radius=radius))
        img.paste(blurred, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92)


def draw_viz(image_path: Path, regions: list[dict], out_path: Path) -> None:
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size=max(14, img.size[0] // 60))
    except Exception:
        font = ImageFont.load_default()
    for r in regions:
        b = r.get("bbox") or {}
        x, y, w, h = b.get("x", 0), b.get("y", 0), b.get("w", 0), b.get("h", 0)
        color = COLOR_BY_CLASS.get(r.get("classification"), "#999999")
        for offset in range(3):
            draw.rectangle([x - offset, y - offset, x + w + offset, y + h + offset], outline=color)
        label = f"{r.get('classification','?')[:4]}: {(r.get('text_snippet','') or '')[:30]}"
        # Background para el texto
        text_bbox = draw.textbbox((x, max(0, y - 22)), label, font=font)
        draw.rectangle(text_bbox, fill=color)
        draw.text((x, max(0, y - 22)), label, fill="white", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=88)


def build_html(detections: list[dict], viz_dir: Path, out_html: Path, blur_dir: Path | None = None) -> None:
    """HTML side-by-side: original + viz + tabla de regiones por foto."""
    parts = ["""<!doctype html><html><head><meta charset="utf-8"/>
<title>Text overlay detection</title>
<style>
  body{font-family:-apple-system,Segoe UI,sans-serif;margin:0;background:#f5f5f7}
  section{max-width:1800px;margin:24px auto;background:#fff;border-radius:8px;padding:24px;box-shadow:0 2px 6px rgba(0,0,0,0.06)}
  h2{margin:0 0 12px;color:#1f2937}
  .pair{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:16px}
  .pair img{width:100%;border:1px solid #ddd;border-radius:4px}
  .pair .lbl{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{padding:6px 8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
  th{background:#f9fafb;color:#374151;font-weight:600}
  .pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:white}
  .pill.in_scene{background:#22c55e}.pill.archive_overlay{background:#dc2626}.pill.uncertain{background:#f59e0b}
  .summary{background:#eef2ff;padding:10px 14px;border-radius:6px;margin-bottom:14px;font-size:13px;color:#3730a3}
</style></head><body>"""]

    # Resumen global
    n_overlay = sum(1 for d in detections for r in d.get("regions", []) if r.get("classification") == "archive_overlay")
    n_scene = sum(1 for d in detections for r in d.get("regions", []) if r.get("classification") == "in_scene")
    n_unc = sum(1 for d in detections for r in d.get("regions", []) if r.get("classification") == "uncertain")
    parts.append(f"<section><h2>Resumen</h2><div class='summary'>{len(detections)} fotos analizadas · "
                 f"<b>{n_overlay}</b> archive_overlay · {n_scene} in_scene · {n_unc} uncertain</div></section>")

    def to_data_url(path: Path) -> str | None:
        if not path.exists():
            return None
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:image/jpeg;base64,{b64}"

    for d in detections:
        cid = d.get("cid", "?")
        original = Path(d.get("photo", ""))
        orig_url = to_data_url(original) if original.name else None
        viz_url = to_data_url(viz_dir / f"{cid}.jpg")
        blur_url = to_data_url(blur_dir / f"{cid}.jpg") if blur_dir else None

        rows = []
        for r in d.get("regions", []):
            cls = r.get("classification", "?")
            rows.append(
                f"<tr><td><span class='pill {cls}'>{cls}</span></td>"
                f"<td>{(r.get('text_snippet','') or '')[:80]}</td>"
                f"<td>{r.get('confidence','?')}</td>"
                f"<td>{r.get('bbox',{})}</td>"
                f"<td>{(r.get('reasoning','') or '')[:200]}</td></tr>"
            )
        if not rows:
            rows.append("<tr><td colspan='5'><i>(sin regiones detectadas)</i></td></tr>")

        viz_html = f"<div><div class='lbl'>Detección (bboxes)</div><img src='{viz_url}'/></div>" if viz_url else "<div><i>viz no generado</i></div>"
        orig_html = f"<div><div class='lbl'>Original</div><img src='{orig_url}'/></div>" if orig_url else "<div><i>original no disponible</i></div>"
        blur_html = f"<div><div class='lbl'>Post-blur (lo que verá el modelo)</div><img src='{blur_url}'/></div>" if blur_url else "<div><i>blur no generado</i></div>"
        parts.append(f"""<section>
  <h2>cid={cid}</h2>
  <div class='pair'>
    {orig_html}
    {viz_html}
    {blur_html}
  </div>
  <table><thead><tr><th>Clase</th><th>Texto</th><th>Conf</th><th>BBox</th><th>Razonamiento</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
</section>""")

    parts.append("</body></html>")
    out_html.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--photos-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--pattern", default="*_clean_v1.jpg")
    parser.add_argument("--limit", type=int, default=0, help="0 = todas")
    parser.add_argument("--sample", type=int, default=0, help="N random fotos del pattern. 0=todas")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--blur-uncertain", action="store_true", help="blurrear también 'uncertain'")
    parser.add_argument("--blur-radius", type=int, default=20)
    parser.add_argument("--only-with-overlay", action="store_true",
                        help="solo guardar viz/blurred + viewer entry para fotos con >=1 archive_overlay")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    photos = sorted(args.photos_dir.glob(args.pattern))
    if args.sample > 0:
        import random as _random
        _random.seed(args.seed)
        photos = _random.sample(photos, min(args.sample, len(photos)))
    if args.limit > 0:
        photos = photos[: args.limit]
    if not photos:
        raise SystemExit(f"no matching photos in {args.photos_dir} pattern={args.pattern}")

    print(f"Detecting overlays on {len(photos)} photos with {args.model}")
    detections = []
    viz_dir = args.out_dir / "viz"
    blur_dir = args.out_dir / "blurred"
    t0 = time.time()
    for i, p in enumerate(photos, 1):
        cid = p.stem.split("_")[0]
        print(f"  [{i}/{len(photos)}] cid={cid}", end=" ", flush=True)
        try:
            result = detect_overlays(p, args.model)
            n = len(result.get("regions", []))
            classes = [r.get("classification") for r in result.get("regions", [])]
            print(f"-> {n} regions: in_scene={classes.count('in_scene')} overlay={classes.count('archive_overlay')} uncertain={classes.count('uncertain')}")
            result["cid"] = cid
            result["photo"] = str(p.resolve())
            detections.append(result)
            has_overlay = any(r.get("classification") == "archive_overlay" for r in result.get("regions", []))
            if has_overlay or not args.only_with_overlay:
                draw_viz(p, result.get("regions", []), viz_dir / f"{cid}.jpg")
                blur_overlays(p, result.get("regions", []), blur_dir / f"{cid}.jpg",
                              blur_uncertain=args.blur_uncertain, radius=args.blur_radius)
        except Exception as e:
            print(f"ERROR: {e}")
            detections.append({"cid": cid, "photo": str(p.resolve()), "error": str(e)})

    out_json = args.out_dir / "detections.json"
    out_json.write_text(json.dumps(detections, indent=2, ensure_ascii=False), encoding="utf-8")
    out_html = args.out_dir / "viewer.html"
    if args.only_with_overlay:
        viewer_dets = [d for d in detections if any(r.get("classification") == "archive_overlay" for r in d.get("regions", []))]
        print(f"  filtered for viewer: {len(viewer_dets)}/{len(detections)} with archive_overlay")
    else:
        viewer_dets = detections
    build_html(viewer_dets, viz_dir, out_html, blur_dir=blur_dir)
    print(f"\nDone in {time.time()-t0:.0f}s")
    print(f"  json: {out_json}")
    print(f"  html: {out_html}")


if __name__ == "__main__":
    main()
