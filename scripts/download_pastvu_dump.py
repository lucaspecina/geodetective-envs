"""Descarga el dump completo de metadata de PastVu (pastvu.jsonl.zst, 282 MB).

Fuente: HuggingFace dataset `nyuuzyou/pastvu`, archivo `pastvu.jsonl.zst`.
Snapshot 2025-07-23.

Output: experiments/E006_pastvu_audit/data/pastvu.jsonl.zst

Uso:
    python scripts/download_pastvu_dump.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from huggingface_hub import hf_hub_download

REPO = "nyuuzyou/pastvu"
FILENAME = "pastvu.jsonl.zst"
OUT_DIR = Path("experiments/E006_pastvu_audit/data")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / FILENAME
    if target.exists():
        print(f"[skip] already exists: {target} ({target.stat().st_size / (1024**2):.1f} MB)")
        return

    print(f"Downloading {REPO}/{FILENAME} -> {target}")
    local_path = hf_hub_download(
        repo_id=REPO,
        filename=FILENAME,
        repo_type="dataset",
        local_dir=str(OUT_DIR),
    )
    src = Path(local_path)
    if src.resolve() != target.resolve():
        src.replace(target)
    print(f"[ok] downloaded {target} ({target.stat().st_size / (1024**2):.1f} MB)")


if __name__ == "__main__":
    main()
