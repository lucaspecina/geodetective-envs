"""Genera corpus/candidates_review/ con copias de las fotos blureadas y nombre
informativo, para que el user descarte manualmente desde Explorer.

Naming: {tier}_{bucket}_{year}_{country}_{cid}.jpg

tier viene de results.json del atacante:
  - easy:   atacante acertó (<10km AND conf>=media) en ≥1 run → probable shortcut
  - medium: atacante en zona (<200km) o conf alta sin acertar → señales débiles
  - hard:   atacante perdido (>=200km O conf baja en todos) → ideal para benchmark
  - skip:   atacante falló todas las corridas (errores) → revisar manual

Uso:
  python scripts/build_review_folder.py [--results PATH] [--candidates PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def sanitize(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", str(s))
    return s.strip("_")[:30] or "x"


def classify(stats: dict, runs: list[dict]) -> str:
    """Clasifica una foto en easy/medium/hard según el atacante.

    Heurística:
      - easy:   ≥1 run con dist<10km AND conf>=media → shortcut probable
      - medium: dist_min<200km O alguna conf=alta (señal débil pero presente)
      - hard:   el resto (atacante perdido / no pudo dar coords)
    """
    if not runs:
        return "hard"
    dists = [r.get("distance_km") for r in runs if r.get("distance_km") is not None]
    confs = [(r.get("confidence") or "").lower() for r in runs]

    # easy: ≥1 run con dist<10 AND conf>=media
    for r in runs:
        d = r.get("distance_km")
        conf = (r.get("confidence") or "").lower()
        if d is not None and d < 10 and conf in {"media", "alta"}:
            return "easy"

    # medium: mejor distancia <200km O alguna conf=alta
    if dists and min(dists) < 200:
        return "medium"
    if "alta" in confs:
        return "medium"

    # hard: atacante perdido o sin coords parseables
    return "hard"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="experiments/E015_attacker_v2/results.json")
    ap.add_argument("--candidates", default="experiments/E007_sample_diverso/candidates_v2.json")
    ap.add_argument("--photos", default="corpus/photos")
    ap.add_argument("--out", default="corpus/candidates_review")
    ap.add_argument("--clean-version", default="1")
    args = ap.parse_args()

    results_path = Path(args.results)
    candidates_path = Path(args.candidates)
    photos_dir = Path(args.photos)
    out_dir = Path(args.out)

    if not candidates_path.exists():
        raise SystemExit(f"missing candidates: {candidates_path}")

    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    by_cid = {c["cid"]: c for c in candidates}

    # Atacante: si no existe el JSON aún, todos van como "unknown"
    tier_by_cid: dict[int, str] = {}
    if results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        for r in results:
            cid = r["cid"]
            tier_by_cid[cid] = classify(r.get("stats", {}), r.get("runs", []))
        print(f"loaded attacker results: {len(results)} fotos")
    else:
        print(f"WARNING: no attacker results at {results_path}, all tiered as 'pending'")

    out_dir.mkdir(parents=True, exist_ok=True)

    tier_counts: dict[str, int] = {}
    copied = 0
    missing_photo = 0
    for cid, c in by_cid.items():
        src = photos_dir / f"{cid}_clean_v{args.clean_version}.jpg"
        if not src.exists():
            missing_photo += 1
            continue

        tier = tier_by_cid.get(cid, "pending")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        bucket = sanitize(c.get("bucket_pais", "x"))
        year = c.get("year") or "x"
        country = sanitize(c.get("country", "x"))
        dst_name = f"{tier}_{bucket}_{year}_{country}_{cid}.jpg"
        dst = out_dir / dst_name

        shutil.copy2(src, dst)
        copied += 1

    print(f"\ncopied: {copied} fotos -> {out_dir}")
    print(f"missing en photos/: {missing_photo}")
    print(f"\ndistribución por tier:")
    for tier, n in sorted(tier_counts.items()):
        print(f"  {tier:10s}: {n}")

    print(f"\nProx paso: abrir Explorer en {out_dir} y BORRAR las fotos que no quieras.")  # noqa
    print("Después correr: python scripts/finalize_corpus_from_review.py")


if __name__ == "__main__":
    main()
