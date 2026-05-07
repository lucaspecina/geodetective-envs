"""Test 3: pasar fotos a gpt-5.4 sin tools (N=3 runs) y comparar con ground truth.

Input: experiments/E001_test3_pastvu/candidates.json
Output: experiments/E001_test3_pastvu/results.json
"""
import os, base64, json, re, time
from pathlib import Path
from PIL import Image
import httpx
from openai import OpenAI
from geopy.distance import geodesic

N_RUNS = int(os.environ.get("N_RUNS", "3"))

# Load .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

EXP = Path("experiments/E001_test3_pastvu")
PHOTOS = EXP / "photos"
PHOTOS.mkdir(parents=True, exist_ok=True)

candidates = json.loads((EXP / "candidates.json").read_text())
print(f"Cargados {len(candidates)} candidatos\n")

client = OpenAI(
    base_url=os.environ["AZURE_FOUNDRY_BASE_URL"],
    api_key=os.environ["AZURE_INFERENCE_CREDENTIAL"],
)

PROMPT = """Ubicá esta fotografía con la mayor precisión posible.

Decime:
1. ¿Dónde fue tomada? (ciudad, país, año aproximado, coordenadas si podés)
2. ¿Qué pistas usaste para llegar a eso?
3. ¿Qué tan confiada estás de tu respuesta? (alta/media/baja)
4. ¿Hay info faltante que necesitarías para estar más segura?

NO intentes buscar la imagen en internet, solo razoná con lo que ves.
Respondé en español y en JSON con keys: location, lat, lon, year, reasoning, confidence, missing_info.
"""


def download_photo(c):
    """Bajar foto de PastVu y cropear watermark."""
    url = f"https://pastvu.com/_p/a/{c['file']}"
    out_raw = PHOTOS / f"{c['cid']}_raw.jpg"
    out_clean = PHOTOS / f"{c['cid']}_nowm.jpg"
    if out_clean.exists():
        return out_clean
    try:
        r = httpx.get(url, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        out_raw.write_bytes(r.content)
        # Cropear watermark proporcional
        img = Image.open(out_raw)
        w, h = img.size
        waterh = c.get("waterh", 42) or 42
        orig_h = c.get("h") or 1801
        crop_px = int(waterh * h / orig_h) if orig_h else 42
        img.crop((0, 0, w, h - crop_px)).save(out_clean, quality=92)
        return out_clean
    except Exception as e:
        print(f"  ⚠️  Error bajando {c['cid']}: {e}")
        return None


def call_model(image_path, model="gpt-5.4"):
    img_b64 = base64.b64encode(image_path.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{img_b64}"
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]
                }],
                max_completion_tokens=2000,
                timeout=60.0,
            )
            return resp.choices[0].message.content
        except Exception as e:
            if attempt == 2:
                return f"ERROR: {e}"
            time.sleep(2 ** attempt)


def parse_response(content):
    if not content or content.startswith("ERROR"):
        return {}
    m = re.search(r'\{[\s\S]*\}', content)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def parse_year(year_field):
    """Devuelve un float (año estimado) desde un int, string single year, o range/fuzzy."""
    if year_field is None:
        return None
    if isinstance(year_field, (int, float)):
        return float(year_field)
    if not isinstance(year_field, str):
        return None
    s = year_field.lower()
    # Buscar todos los años de 4 dígitos
    years = [int(y) for y in re.findall(r'\b(1[89]\d{2}|20\d{2})\b', s)]
    if years:
        return sum(years) / len(years)
    # Décadas tipo "1970s", "70s"
    decades = re.findall(r'(\d{2,4})s\b', s)
    if decades:
        years_d = []
        for d in decades:
            d = int(d)
            if d < 100:
                d += 1900 if d > 30 else 2000
            # Modificadores "fines/late"=+7, "principios/early"=+2, "mediados/mid"=+5
            mid = d + 5
            ctx = s[max(0, s.find(str(d)) - 25):s.find(str(d))]
            if any(k in ctx for k in ["fines", "late", "finales"]):
                mid = d + 7
            elif any(k in ctx for k in ["principios", "early", "comienzos"]):
                mid = d + 2
            years_d.append(mid)
        return sum(years_d) / len(years_d)
    return None


# Run test — N runs por foto
results = []
for i, c in enumerate(candidates, 1):
    print(f"[{i}/{len(candidates)}] #{c['cid']} [{c['zone']}, {c['year']}] {c['contamination']}")
    print(f"    Title: {c['title'][:70]}")

    img_path = download_photo(c)
    if not img_path:
        results.append({**c, "error": "download_failed"})
        continue

    runs = []
    for run_idx in range(N_RUNS):
        raw = call_model(img_path)
        parsed = parse_response(raw)
        truth = c.get("geo")
        pred_lat, pred_lon = parsed.get("lat"), parsed.get("lon")
        dist_km = None
        if truth and pred_lat is not None and pred_lon is not None:
            try:
                dist_km = geodesic((truth[0], truth[1]), (float(pred_lat), float(pred_lon))).km
            except Exception:
                pass
        truth_year = c.get("year")
        pred_year = parse_year(parsed.get("year"))
        year_err = abs(truth_year - pred_year) if (truth_year and pred_year) else None
        runs.append({
            "raw_response": raw, "parsed": parsed,
            "distance_km": dist_km, "pred_year": pred_year, "year_error": year_err,
            "confidence": parsed.get("confidence"),
        })
        loc = (parsed.get("location") or "")[:50]
        d_s = f"{dist_km:.1f}km" if dist_km is not None else "N/A"
        ye_s = f"{year_err:.0f}" if year_err is not None else "N/A"
        print(f"    run {run_idx+1}/{N_RUNS}: dist={d_s:>10} yerr={ye_s:>4} conf={parsed.get('confidence', '?'):8s} | {loc}")

    # Stats sobre los N runs
    dists = [r["distance_km"] for r in runs if r["distance_km"] is not None]
    yerrs = [r["year_error"] for r in runs if r["year_error"] is not None]
    confs = [r["confidence"] for r in runs if r["confidence"]]
    stats = {
        "dist_min": min(dists) if dists else None,  # peor caso para nuestro filtro = más informado
        "dist_median": sorted(dists)[len(dists)//2] if dists else None,
        "dist_max": max(dists) if dists else None,
        "year_err_min": min(yerrs) if yerrs else None,
        "year_err_median": sorted(yerrs)[len(yerrs)//2] if yerrs else None,
        "n_with_coords": len(dists),
        "confidences": confs,
    }
    print(f"    📊 dist: min={stats['dist_min']}, median={stats['dist_median']}, max={stats['dist_max']}")
    print()

    results.append({**c, "runs": runs, "stats": stats})

# Save
out = EXP / "results.json"
out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"\n✓ Saved to {out}")

# Tabla resumen — usando dist_min (peor caso = más informado del modelo)
print("\n=== Tabla resumen (dist_min = peor caso para el filtro) ===")
print(f"{'CID':>8} {'Cont':3} {'Zone':22} {'YR':>5} {'min/med/max':>16} {'YE_med':>6}  Title")
print("-" * 130)
for r in results:
    cont_emoji = r["contamination"].split()[0] if r.get("contamination") else "?"
    s = r.get("stats", {})
    dmin = f"{s['dist_min']:.0f}" if s.get('dist_min') is not None else "N/A"
    dmed = f"{s['dist_median']:.0f}" if s.get('dist_median') is not None else "N/A"
    dmax = f"{s['dist_max']:.0f}" if s.get('dist_max') is not None else "N/A"
    dist_str = f"{dmin}/{dmed}/{dmax}"
    yerr = s.get('year_err_median')
    yerr_s = f"{yerr:.0f}" if yerr is not None else "N/A"
    title = r['title'][:50]
    print(f"{r['cid']:>8} {cont_emoji}   {r['zone'][:22]:22} {r['year']:>5} {dist_str:>16} {yerr_s:>6}  {title}")
