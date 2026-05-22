"""Procesa la selección manual del user sobre el corpus v2.

Flujo de carpetas (precedencia: a-remove > need_blur > review):
  - corpus/candidates_review/      → corpus final (lo que queda)
  - corpus/candidates_need_blur/   → re-blurear, EXCLUIR del corpus final
  - corpus/a-remove/               → eliminar, EXCLUIR del corpus final

Si un cid está en a-remove O need_blur, se EXCLUYE del corpus aunque siga
también en candidates_review (el user fue inconsistente: a veces movió,
a veces copió).

Acciones:
  1. Calcula sets de cids por carpeta
  2. final = review - (a-remove ∪ need_blur)
  3. Genera candidates_v2_final.json con el subset final
  4. Mueve fotos de corpus/photos/ rechazadas a corpus/photos_rejected_v2/
  5. Mueve fotos need_blur a corpus/photos_need_reblur/
  6. Imprime distribución por bucket × tier
  7. NO toca las carpetas candidates_*/ (las podes borrar a mano)

Uso:
  python scripts/finalize_corpus_from_review.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

REVIEW_DIR = Path("corpus/candidates_review")
NEED_BLUR_DIR = Path("corpus/candidates_need_blur")
REMOVE_DIR = Path("corpus/a-remove")
PHOTOS_DIR = Path("corpus/photos")
REJECTED_DIR = Path("corpus/photos_rejected_v2")
NEED_REBLUR_DIR = Path("corpus/photos_need_reblur")
CANDIDATES_V2 = Path("experiments/E007_sample_diverso/candidates_v2.json")
CANDIDATES_FINAL = Path("experiments/E007_sample_diverso/candidates_v2_final.json")
CANDIDATES_NEED_REBLUR = Path("experiments/E007_sample_diverso/candidates_need_reblur.json")

NAME_RE = re.compile(r"(\d+)\.jpg$")


def cids_in(d: Path) -> set[int]:
    if not d.exists():
        return set()
    out = set()
    for f in d.glob("*.jpg"):
        m = NAME_RE.search(f.name)
        if m:
            out.add(int(m.group(1)))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    review_cids = cids_in(REVIEW_DIR)
    need_blur_cids = cids_in(NEED_BLUR_DIR)
    remove_cids = cids_in(REMOVE_DIR)

    excluded = need_blur_cids | remove_cids
    final_cids = review_cids - excluded

    print(f"=== Conteos por carpeta ===")
    print(f"  review:    {len(review_cids)}")
    print(f"  need_blur: {len(need_blur_cids)}")
    print(f"  a-remove:  {len(remove_cids)}")
    print(f"")
    print(f"=== Overlaps (review ∩ otras) ===")
    print(f"  review ∩ need_blur: {len(review_cids & need_blur_cids)} (excluidas)")
    print(f"  review ∩ a-remove:  {len(review_cids & remove_cids)} (excluidas)")
    print(f"")
    print(f"=== Corpus final ===")
    print(f"  total: {len(final_cids)} fotos")

    candidates = json.loads(CANDIDATES_V2.read_text(encoding="utf-8"))
    by_cid = {c["cid"]: c for c in candidates}

    final = [by_cid[cid] for cid in final_cids if cid in by_cid]
    need_reblur = [by_cid[cid] for cid in need_blur_cids if cid in by_cid]

    missing = [cid for cid in final_cids if cid not in by_cid]
    if missing:
        print(f"WARN: {len(missing)} cids en review no estan en candidates_v2.json")

    if args.dry_run:
        print("\n[DRY-RUN] no se escribieron archivos ni se movieron fotos.")
    else:
        CANDIDATES_FINAL.write_text(
            json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nwrote {CANDIDATES_FINAL} ({len(final)} fotos)")

        if need_reblur:
            CANDIDATES_NEED_REBLUR.write_text(
                json.dumps(need_reblur, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"wrote {CANDIDATES_NEED_REBLUR} ({len(need_reblur)} fotos)")

        # Mover fotos rechazadas y need_reblur de corpus/photos/
        REJECTED_DIR.mkdir(parents=True, exist_ok=True)
        NEED_REBLUR_DIR.mkdir(parents=True, exist_ok=True)

        moved_rejected = 0
        moved_need_blur = 0
        for f in PHOTOS_DIR.glob("*.jpg"):
            m = re.match(r"(\d+)_", f.name)
            if not m:
                continue
            cid = int(m.group(1))
            if cid in remove_cids:
                shutil.move(str(f), str(REJECTED_DIR / f.name))
                moved_rejected += 1
            elif cid in need_blur_cids:
                shutil.move(str(f), str(NEED_REBLUR_DIR / f.name))
                moved_need_blur += 1

        print(f"moved {moved_rejected} fotos -> {REJECTED_DIR}")
        print(f"moved {moved_need_blur} fotos -> {NEED_REBLUR_DIR}")

    # Distribución por bucket × país (sin tier, ya no aplica)
    print("\n=== Distribución corpus final por bucket ===")
    by_bucket = Counter(c["bucket_pais"] for c in final)
    for b, n in sorted(by_bucket.items(), key=lambda x: -x[1]):
        print(f"  {b:<25} {n:>4}")

    print("\n=== Top países en corpus final ===")
    by_country = Counter(c.get("country", "?") for c in final)
    for c, n in by_country.most_common(15):
        print(f"  {c:<20} {n:>4}")

    print("\n=== Distribución corpus final por década ===")
    by_decada = Counter(c["bucket_decada"] for c in final)
    for d, n in sorted(by_decada.items()):
        print(f"  {d:<10} {n:>4}")


if __name__ == "__main__":
    main()
