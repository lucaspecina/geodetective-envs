"""Aplica blur a corpus/photos/{cid}_clean_v1.jpg usando regions ya detectadas
en un detections.json (commited en git).

Esto permite reproducir el corpus blureado en una máquina nueva SIN re-correr el
VLM detector (que cuesta plata y tiempo). El detections.json es la fuente canon.

Flujo:
  1. Lee experiments/E011_text_overlay_detection/sample270_v2/detections.json
  2. Para cada foto con archive_overlay, aplica GaussianBlur sobre las bboxes
  3. Sobreescribe corpus/photos/{cid}_clean_v1.jpg con la versión blureada
  4. Las fotos sin overlay quedan tal cual (pass-through).

Pre-requisito: corpus/photos/{cid}_clean_v1.jpg ya existe (post download + clean).

Uso:
  python scripts/apply_blur_from_detections.py
  python scripts/apply_blur_from_detections.py --detections OTRO.json --photos-dir corpus/photos
  python scripts/apply_blur_from_detections.py --candidates-filter experiments/E007_sample_diverso/candidates_v2_final.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# Reusamos la función de detect_text_overlays.py
from detect_text_overlays import blur_overlays


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--detections",
        default="experiments/E011_text_overlay_detection/sample270_v2/detections.json",
    )
    ap.add_argument("--photos-dir", default="corpus/photos")
    ap.add_argument(
        "--candidates-filter",
        default=None,
        help="Opcional: solo procesar cids presentes en este JSON (ej candidates_v2_final.json)",
    )
    ap.add_argument("--blur-radius", type=int, default=20)
    ap.add_argument("--pad", type=int, default=6)
    args = ap.parse_args()

    det_path = Path(args.detections)
    photos_dir = Path(args.photos_dir)

    if not det_path.exists():
        raise SystemExit(f"missing detections: {det_path}")
    if not photos_dir.exists():
        raise SystemExit(f"missing photos dir: {photos_dir}")

    detections = json.loads(det_path.read_text(encoding="utf-8"))

    filter_cids = None
    if args.candidates_filter:
        cf = Path(args.candidates_filter)
        cands = json.loads(cf.read_text(encoding="utf-8"))
        # Normalizar a int para comparación robusta (detections.json puede traer str)
        filter_cids = {int(c["cid"]) for c in cands}
        print(f"filter: {len(filter_cids)} cids from {cf.name}")

    blurred = 0
    skipped_no_overlay = 0
    skipped_missing = 0
    skipped_filter = 0

    for det in detections:
        cid = int(det["cid"])  # normalizar
        if filter_cids is not None and cid not in filter_cids:
            skipped_filter += 1
            continue

        regions = det.get("regions", [])
        has_overlay = any(r.get("classification") == "archive_overlay" for r in regions)
        if not has_overlay:
            skipped_no_overlay += 1
            continue

        photo = photos_dir / f"{cid}_clean_v1.jpg"
        if not photo.exists():
            skipped_missing += 1
            print(f"  WARN: missing {photo}")
            continue

        blur_overlays(
            photo,
            regions,
            photo,  # in-place
            blur_uncertain=False,
            pad=args.pad,
            radius=args.blur_radius,
        )
        blurred += 1
        if blurred % 20 == 0:
            print(f"  blurred {blurred}...")

    print(f"\n=== Resumen ===")
    print(f"  blurred:                {blurred}")
    print(f"  skipped (no overlay):   {skipped_no_overlay}")
    print(f"  skipped (filter):       {skipped_filter}")
    print(f"  skipped (missing file): {skipped_missing}")
    print(f"  total dets:             {len(detections)}")


if __name__ == "__main__":
    main()
