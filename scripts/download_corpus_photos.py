"""Descarga fotos del corpus desde PastVu y las cleanea.

Lee un candidates.json (output de sample_diverso.py), para cada foto:
  1. baja {cid}_raw.jpg con httpx
  2. corre clean_image.py → {cid}_clean_v{N}.jpg (strip EXIF + crop watermark)

Output: corpus/photos/{cid}_{raw|clean_vN}.jpg

Idempotent: si {cid}_clean_vN.jpg ya existe, skipea.
Paralelo (default 8 workers).

Uso:
    python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates.json
    python scripts/download_corpus_photos.py path/to/candidates.json --workers 16 --out corpus/photos
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geodetective.corpus.clean_image import clean_image, CLEAN_VERSION


PASTVU_PREFIX = "https://pastvu.com/_p/a/"


def resolve_url(file_url: str | None) -> str | None:
    """candidates.json puede traer URL absoluta o solo el path relativo (rec['file'])."""
    if not file_url:
        return None
    if file_url.startswith("http://") or file_url.startswith("https://"):
        return file_url
    return PASTVU_PREFIX + file_url.lstrip("/")


def download_one(c: dict, out_dir: Path) -> dict:
    cid = c["cid"]
    raw = out_dir / f"{cid}_raw.jpg"
    clean = out_dir / f"{cid}_clean_v{CLEAN_VERSION}.jpg"

    if clean.exists():
        return {"cid": cid, "status": "cached", "clean": str(clean)}

    url = resolve_url(c.get("file_url") or c.get("file"))
    if not url:
        return {"cid": cid, "status": "no_url"}

    try:
        if not raw.exists():
            r = httpx.get(url, timeout=30.0, follow_redirects=True)
            r.raise_for_status()
            raw.write_bytes(r.content)
        cr = clean_image(
            raw_path=raw,
            provider=c.get("provider", "pastvu"),
            provider_meta={"waterh": c.get("waterh"), "h": c.get("h")},
            out_dir=out_dir,
        )
        if cr.path is None:
            return {"cid": cid, "status": "clean_discarded", "notes": cr.notes}
        return {"cid": cid, "status": "ok", "clean": str(cr.path), "crop_px": cr.crop_px}
    except httpx.HTTPStatusError as e:
        return {"cid": cid, "status": "http_error", "code": e.response.status_code, "url": url}
    except Exception as e:
        return {"cid": cid, "status": "error", "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path, help="path al candidates.json")
    parser.add_argument("--out", type=Path, default=Path("corpus/photos"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="0 = todas")
    args = parser.parse_args()

    if not args.candidates.exists():
        raise SystemExit(f"missing: {args.candidates}")

    raw = json.loads(args.candidates.read_text(encoding="utf-8"))
    records = raw if isinstance(raw, list) else raw.get("records") or raw.get("candidates") or []
    if args.limit > 0:
        records = records[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"downloading {len(records)} photos -> {args.out} (workers={args.workers})")

    t0 = time.time()
    counts = {"ok": 0, "cached": 0, "no_url": 0, "clean_discarded": 0, "http_error": 0, "error": 0}
    log = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, c, args.out): c for c in records}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            log.append(r)
            if r["status"] in ("ok", "cached"):
                tag = "+" if r["status"] == "ok" else "."
            else:
                tag = "x"
                print(f"  [{i}/{len(records)}] cid={r['cid']:>10} {tag} {r['status']} {r.get('error','') or r.get('url','')}")
            if i % 25 == 0 or i == len(records):
                elapsed = time.time() - t0
                print(f"  [{i}/{len(records)}] {elapsed:.0f}s · " + " ".join(f"{k}={v}" for k, v in counts.items() if v))

    log_path = args.out.parent / "download_log.json"
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone in {time.time()-t0:.0f}s")
    print(f"  {counts}")
    print(f"  log: {log_path}")


if __name__ == "__main__":
    main()
