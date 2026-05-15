"""Corpus viewer — grid HTML autocontenido con todas las fotos de un experiment dir.

Sirve para inspeccionar visualmente el corpus localmente (sin GitHub, sin server).
Muestra cada foto con: cid, zona, año, país, geo (lat,lon), bucket década, link a PastVu.

Uso:
    # Todo lo que haya en photos/
    python scripts/build_corpus_viewer.py experiments/E010_iteration_pilot

    # Con candidates.json explícito (otro nombre)
    python scripts/build_corpus_viewer.py experiments/E004_attacker_filter --candidates results.json

    # Carpeta photos directa (sin candidates)
    python scripts/build_corpus_viewer.py --photos-dir experiments/E010_iteration_pilot/photos
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def to_thumb_b64(path: Path, max_side: int = 360) -> str | None:
    """Embebe foto como base64. Redimensiona para no inflar el HTML."""
    try:
        from PIL import Image
        from io import BytesIO
        img = Image.open(path).convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def find_candidates(exp_dir: Path) -> Path | None:
    """Busca el JSON con metadata del corpus en convenciones comunes."""
    for name in ("picked_photos.json", "candidates.json", "results.json"):
        p = exp_dir / name
        if p.exists():
            return p
    return None


def load_metadata(cand_path: Path | None) -> dict[str, dict]:
    """cid -> metadata dict. Tolera shapes: list[dict] o {records: [...]}."""
    if not cand_path or not cand_path.exists():
        return {}
    try:
        raw = json.loads(cand_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] no pude leer {cand_path}: {e}")
        return {}
    records = raw if isinstance(raw, list) else raw.get("records") or raw.get("candidates") or []
    out: dict[str, dict] = {}
    for r in records:
        cid = r.get("cid")
        if cid is not None:
            out[str(cid)] = r
    return out


def render_card(cid: str, photo_path: Path, meta: dict) -> str:
    b64 = to_thumb_b64(photo_path)
    img_html = f'<img src="data:image/jpeg;base64,{b64}"/>' if b64 else '<div class="noimg">(no preview)</div>'

    zone = meta.get("zone") or meta.get("title", "")
    year = meta.get("year")
    year2 = meta.get("year2")
    year_str = f"{year}–{year2}" if year2 and year2 != year else (str(year) if year else "?")
    country = meta.get("country") or meta.get("bucket_pais", "?")
    decada = meta.get("bucket_decada", "?")
    geo = meta.get("geo")
    geo_str = f"{geo[0]:.3f}, {geo[1]:.3f}" if isinstance(geo, list) and len(geo) >= 2 else "?"
    provider = meta.get("provider", "?")
    page_url = meta.get("page_url", "")
    page_link = f'<a href="{esc(page_url)}" target="_blank">source</a>' if page_url else ""

    return f"""<div class="card">
  {img_html}
  <div class="meta">
    <div class="cid">cid={esc(cid)}</div>
    <div class="title">{esc((zone or '')[:80])}</div>
    <div class="row"><b>year:</b> {esc(year_str)} | <b>decada:</b> {esc(decada)}</div>
    <div class="row"><b>country:</b> {esc(country)}</div>
    <div class="row"><b>geo:</b> {esc(geo_str)}</div>
    <div class="row"><b>provider:</b> {esc(provider)} {page_link}</div>
  </div>
</div>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("exp_dir", type=Path, nargs="?", default=None,
                        help="experiment dir (busca photos/ + candidates.json adentro)")
    parser.add_argument("--photos-dir", type=Path, default=None,
                        help="carpeta con fotos. Si se da, anula exp_dir/photos")
    parser.add_argument("--candidates", type=Path, default=None,
                        help="JSON con metadata por cid. Default: busca en exp_dir")
    parser.add_argument("--pattern", default="*_clean_v*.jpg")
    parser.add_argument("--output", type=Path, default=None,
                        help="HTML output. Default: <exp_dir>/corpus_viewer.html")
    parser.add_argument("--max-side", type=int, default=360, help="thumbnail max side")
    args = parser.parse_args()

    if args.photos_dir:
        photos_dir = args.photos_dir
        exp_dir = photos_dir.parent
    elif args.exp_dir:
        exp_dir = args.exp_dir
        photos_dir = exp_dir / "photos"
    else:
        raise SystemExit("dame exp_dir o --photos-dir")

    if not photos_dir.exists():
        raise SystemExit(f"no existe: {photos_dir}")

    cand_path = args.candidates or find_candidates(exp_dir)
    if cand_path:
        print(f"metadata: {cand_path}")
    else:
        print("[warn] no metadata json found — solo cid + foto")
    metadata = load_metadata(cand_path)

    photos = sorted(photos_dir.glob(args.pattern))
    if not photos:
        # Fallback a raw si no hay clean
        photos = sorted(photos_dir.glob("*.jpg"))
    if not photos:
        raise SystemExit(f"no fotos en {photos_dir} con pattern {args.pattern}")

    print(f"rendering {len(photos)} fotos desde {photos_dir}")
    cards = []
    for p in photos:
        cid = p.stem.split("_")[0]
        cards.append(render_card(cid, p, metadata.get(cid, {})))

    html_str = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"/>
<title>Corpus viewer — {esc(exp_dir.name)}</title>
<style>
  body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f5f5f7;margin:0;padding:24px}}
  h1{{margin:0 0 8px;color:#1f2937;font-size:18px}}
  .summary{{color:#6b7280;font-size:13px;margin-bottom:20px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px}}
  .card{{background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 5px rgba(0,0,0,0.08)}}
  .card img,.card .noimg{{width:100%;height:240px;object-fit:cover;background:#e5e7eb;display:flex;align-items:center;justify-content:center;color:#9ca3af}}
  .meta{{padding:10px 12px;font-size:12.5px;color:#374151}}
  .meta .cid{{color:#6b7280;font-size:11px;margin-bottom:2px}}
  .meta .title{{font-weight:600;font-size:13.5px;margin-bottom:6px;color:#111827;line-height:1.3}}
  .meta .row{{color:#4b5563;line-height:1.5}}
  .meta a{{color:#2563eb;text-decoration:none}}
  .meta a:hover{{text-decoration:underline}}
</style></head><body>
<h1>Corpus viewer — {esc(exp_dir.name)}</h1>
<div class="summary">{len(photos)} fotos · photos_dir = <code>{esc(photos_dir)}</code> · candidates = <code>{esc(cand_path) if cand_path else '(none)'}</code></div>
<div class="grid">
{''.join(cards)}
</div>
</body></html>"""

    out = args.output or (exp_dir / "corpus_viewer.html")
    out.write_text(html_str, encoding="utf-8")
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"wrote {out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
