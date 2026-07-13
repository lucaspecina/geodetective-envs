"""Genera versiones 'slim' de los results de E016 para commitear (refs #47).

Los results crudos guardan imágenes base64 embebidas en el trace (street_view,
static_map, crops, grillas de image_search) → 35-110 MB por archivo, dos superan
el límite de 100 MB de GitHub. El viewer regenera las imágenes on-demand desde el
corpus, y el análisis no necesita los bytes. Esta versión slim elimina los campos
base64 del trace y de belief_reports, dejando todo lo demás intacto.

Output: results_*.slim.json (los que se commitean). Los crudos quedan gitignored.

Uso: python scripts/slim_results.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EXP_DIR = Path("experiments/E016_belief_pilot")
# Campos que cargan bytes de imagen (base64) — se eliminan del trace.
B64_KEYS = {"base64_jpeg", "grid_image_b64", "image_b64"}


def strip_b64(obj):
    """Recursivamente: elimina claves base64 y marca que había imagen."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in B64_KEYS and isinstance(v, str):
                out[k + "_stripped"] = len(v)  # dejamos rastro del tamaño, no los bytes
            elif k == "visible_images" and isinstance(v, list):
                # cada imagen visible: conservar url + hamming, tirar base64
                out[k] = [{kk: vv for kk, vv in im.items() if kk != "base64_jpeg"}
                          for im in v if isinstance(im, dict)]
            elif k == "images" and isinstance(v, list):
                out[k] = [{kk: vv for kk, vv in im.items() if kk not in B64_KEYS}
                          for im in v if isinstance(im, dict)]
            else:
                out[k] = strip_b64(v)
        return out
    if isinstance(obj, list):
        return [strip_b64(x) for x in obj]
    return obj


def main() -> None:
    total_before = total_after = 0
    for p in sorted(EXP_DIR.glob("results_*.json")):
        if p.name.endswith(".slim.json"):
            continue
        records = json.loads(p.read_text(encoding="utf-8"))
        slim = strip_b64(records)
        out = p.with_suffix(".slim.json")
        out.write_text(json.dumps(slim, indent=2, ensure_ascii=False), encoding="utf-8")
        b, a = p.stat().st_size, out.stat().st_size
        total_before += b
        total_after += a
        print(f"{p.name}: {b/1e6:.1f} MB -> {out.name}: {a/1e6:.1f} MB")
    print(f"\nTOTAL: {total_before/1e6:.0f} MB -> {total_after/1e6:.1f} MB "
          f"({100*(1-total_after/total_before):.0f}% reducción)")


if __name__ == "__main__":
    main()
