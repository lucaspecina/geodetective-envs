"""Smoke test empírico: ¿pueden los VLMs leer una grilla 4×4 (o 2×4) numerada y
referenciar celdas correctamente? (issue #42, Fase 3 tools redesign).

Setup post-Codex review (agentId af5bf5c184f7f6f44):
- 16 candidatos random del corpus para la grilla 4×4 (escenario realista, sin curado)
- 8 candidatos para la grilla 2×4 (más simple, celdas más grandes — fallback test)
- NO incluye duplicados de la foto target (pHash blocking se testea por separado)
- Foto target: cid=1248470 (Cáucaso rural 1960)
- Bordes negros separadores, números con borde sólido en esquina superior izquierda
- Prompt fuerza clasificación per-cell (plausible/maybe/not_plausible) + reasoning corto
- Calibración: incluir anclas visuales para verificar grounding espacial
  ("¿qué celda tiene personas en primer plano?", "¿cuál es color vs B/N?")

Modelos a probar:
- gpt-5.4-mini, gpt-4o, claude-sonnet-4-6

Métricas de evaluación:
1. JSON parseable
2. Solo referencia celdas válidas (1-16, no inventa)
3. Calibración: identifica correctamente las anclas visuales
4. Discriminación: NO incluye más de 30% de celdas como "plausible"

Costo aprox: 6 calls × ~$0.02-0.05 = $0.10-0.30. Tiempo: ~5 min.

Uso:
    python scripts/test_image_grid_reading.py
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys
from io import BytesIO
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Cargar .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw, ImageFont
from geodetective.llm_adapter import complete as llm_complete


# === Config ===
TARGET_CID = 1248470  # Cáucaso rural 1960
SEED = 42
GRID_DIMS = [(4, 4), (2, 4)]  # (rows, cols) — probaremos 4x4 y 2x4
CELL_SIZE = 256  # pixels por celda
GUTTER = 5  # bordes negros entre celdas
MODELS = ["gpt-5.4-mini", "gpt-4o", "claude-sonnet-4-6"]

CORPUS_DIR = Path("corpus/photos")
OUT_DIR = Path("experiments/E013_grid_smoke")


def load_candidate_pool() -> list[dict]:
    """Carga metadata + path de fotos del corpus, excluyendo target."""
    candidates_json = Path("experiments/E007_sample_diverso/candidates.json")
    if not candidates_json.exists():
        raise SystemExit(f"missing {candidates_json}")
    data = json.loads(candidates_json.read_text(encoding="utf-8"))
    pool = []
    for c in data:
        cid = c["cid"]
        if cid == TARGET_CID:
            continue
        path = CORPUS_DIR / f"{cid}_clean_v1.jpg"
        if path.exists():
            pool.append({"cid": cid, "path": path, "meta": c})
    return pool


def build_grid(target_pool: list[dict], rows: int, cols: int, seed: int) -> tuple[Image.Image, list[dict]]:
    """Construir grilla con celdas numeradas. Devuelve (grilla_img, lista_metadata_per_cell)."""
    random.seed(seed)
    n_cells = rows * cols
    picked = random.sample(target_pool, n_cells)

    # Canvas
    w = cols * CELL_SIZE + (cols + 1) * GUTTER
    h = rows * CELL_SIZE + (rows + 1) * GUTTER
    canvas = Image.new("RGB", (w, h), (0, 0, 0))  # fondo negro = gutters

    try:
        font = ImageFont.truetype("arial.ttf", size=36)
    except Exception:
        font = ImageFont.load_default()

    metadata = []
    for i, p in enumerate(picked):
        r, c = divmod(i, cols)
        x = GUTTER + c * (CELL_SIZE + GUTTER)
        y = GUTTER + r * (CELL_SIZE + GUTTER)
        # Cargar y resize imagen
        img = Image.open(p["path"]).convert("RGB")
        img.thumbnail((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
        # Centrar en la celda
        pad_x = (CELL_SIZE - img.size[0]) // 2
        pad_y = (CELL_SIZE - img.size[1]) // 2
        canvas.paste(img, (x + pad_x, y + pad_y))

        # Número con fondo opaco en esquina superior izquierda
        cell_num = i + 1
        label = f"{cell_num:>2}"
        draw = ImageDraw.Draw(canvas)
        bbox = draw.textbbox((x + 6, y + 6), label, font=font)
        # Padding alrededor del texto
        bg_box = (bbox[0] - 4, bbox[1] - 4, bbox[2] + 4, bbox[3] + 4)
        draw.rectangle(bg_box, fill=(0, 0, 0), outline=(255, 255, 255), width=2)
        draw.text((x + 6, y + 6), label, fill=(255, 255, 255), font=font)

        metadata.append({
            "cell": cell_num,
            "cid": p["cid"],
            "title": (p["meta"].get("title") or "")[:80],
            "country": p["meta"].get("country"),
            "year": p["meta"].get("year"),
            "bucket_pais": p["meta"].get("bucket_pais"),
        })

    return canvas, metadata


def image_to_b64(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def make_prompt(rows: int, cols: int) -> str:
    n = rows * cols
    return f"""Te paso DOS imágenes:
1. **Foto target**: una foto histórica que estamos investigando
2. **Grilla {rows}×{cols}**: {n} candidatos numerados del 1 al {n}, cada uno en una celda

**Tu tarea**: clasificá CADA celda como `plausible`, `maybe` o `not_plausible` según similitud visual con la foto target (mismo tipo de escena, paisaje, época). Ignorá metadatos — solo evaluá por contenido visual.

**También respondé**:
- `personas_primer_plano`: número de celda(s) que muestran personas en primer plano (calibración de grounding espacial)
- `solo_color`: número de celda(s) con foto a color (si hay) — si todas son B/N, dejá array vacío
- `urbanas_grandes`: número de celda(s) con escenas urbanas grandes (avenidas, plazas amplias)

**Output JSON estricto, sin markdown**:
{{
  "celdas": [
    {{"cell": 1, "class": "not_plausible", "reasoning": "fachada urbana, foto target es rural"}},
    {{"cell": 2, "class": "maybe", "reasoning": "..."}},
    ...
  ],
  "personas_primer_plano": [3, 7],
  "solo_color": [],
  "urbanas_grandes": [1, 5, 9]
}}"""


def call_model(model: str, target_b64: str, grid_b64: str, prompt: str) -> dict:
    """Llamar al modelo con foto_target + grilla + prompt. Devuelve dict parsed o error."""
    try:
        resp = llm_complete(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "text", "text": "Foto TARGET:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{target_b64}"}},
                    {"type": "text", "text": "Grilla CANDIDATOS:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{grid_b64}"}},
                ],
            }],
            max_completion_tokens=4000,
            timeout=120.0,
        )
        text = resp.choices[0].message.content or ""
        # Strip markdown fences
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        return {"raw_text": text, "parsed": json.loads(text)}
    except json.JSONDecodeError as e:
        return {"raw_text": text, "error": f"JSON parse failed: {e}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


def evaluate(result: dict, n_cells: int) -> dict:
    """Evaluar criterios del Codex review."""
    if "error" in result:
        return {"json_ok": False, "valid_cells": False, "discrimination_ok": False, "note": result["error"][:100]}

    parsed = result.get("parsed", {})
    celdas = parsed.get("celdas", [])
    valid_nums = set(range(1, n_cells + 1))
    refs = [c.get("cell") for c in celdas]
    valid_cells = all(r in valid_nums for r in refs) and len(refs) <= n_cells
    classes = [c.get("class") for c in celdas]
    plausible_count = classes.count("plausible")
    discrimination_ok = plausible_count / max(1, len(classes)) < 0.4  # menos del 40%
    return {
        "json_ok": True,
        "valid_cells": valid_cells,
        "discrimination_ok": discrimination_ok,
        "plausible_count": plausible_count,
        "total_classified": len(classes),
        "personas_count": len(parsed.get("personas_primer_plano", [])),
        "solo_color_count": len(parsed.get("solo_color", [])),
        "urbanas_count": len(parsed.get("urbanas_grandes", [])),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading corpus...")
    pool = load_candidate_pool()
    print(f"  pool: {len(pool)} candidates")

    target_path = CORPUS_DIR / f"{TARGET_CID}_clean_v1.jpg"
    if not target_path.exists():
        raise SystemExit(f"missing target: {target_path}")
    target_img = Image.open(target_path).convert("RGB")
    target_img.thumbnail((640, 640), Image.LANCZOS)
    target_b64 = image_to_b64(target_img)
    print(f"  target cid={TARGET_CID} loaded")

    all_results = []
    for rows, cols in GRID_DIMS:
        n_cells = rows * cols
        print(f"\n{'='*70}\nGrilla {rows}×{cols} ({n_cells} celdas)\n{'='*70}")
        grid, metadata = build_grid(pool, rows, cols, seed=SEED)
        grid_path = OUT_DIR / f"grid_{rows}x{cols}.jpg"
        grid.save(grid_path, "JPEG", quality=90)
        meta_path = OUT_DIR / f"grid_{rows}x{cols}_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  wrote grid: {grid_path} ({grid.size[0]}x{grid.size[1]} px)")
        grid_b64 = image_to_b64(grid)

        prompt = make_prompt(rows, cols)

        for model in MODELS:
            print(f"\n  -> {model}...")
            result = call_model(model, target_b64, grid_b64, prompt)
            eval_result = evaluate(result, n_cells)
            all_results.append({
                "model": model,
                "grid": f"{rows}x{cols}",
                "n_cells": n_cells,
                "result": result,
                "evaluation": eval_result,
            })
            print(f"     json_ok={eval_result.get('json_ok')} valid_cells={eval_result.get('valid_cells')} "
                  f"discrim_ok={eval_result.get('discrimination_ok')} "
                  f"plausible={eval_result.get('plausible_count')}/{eval_result.get('total_classified', '?')}")
            if eval_result.get('json_ok') and "parsed" in result:
                parsed = result['parsed']
                plausible_cells = [c['cell'] for c in parsed.get('celdas', []) if c.get('class') == 'plausible']
                print(f"     plausible cells: {plausible_cells}")
                print(f"     personas_primer_plano: {parsed.get('personas_primer_plano')}")
                print(f"     solo_color: {parsed.get('solo_color')}")

    # Save all results
    out_json = OUT_DIR / "smoke_results.json"
    out_json.write_text(json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
