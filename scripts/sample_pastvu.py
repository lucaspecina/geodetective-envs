"""Sample fotos de PastVu de zonas diversas y clasifica por contaminación.

Output: experiments/E001_test3_pastvu/candidates.json
"""
import httpx, json, time, random
from pathlib import Path

API = "https://api.pastvu.com/api2"
OUT = Path("experiments/E001_test3_pastvu/candidates.json")
OUT.parent.mkdir(parents=True, exist_ok=True)


def api_call(method: str, params: dict, retries: int = 3):
    for i in range(retries):
        try:
            r = httpx.get(API, params={"method": method, "params": json.dumps(params)}, timeout=30.0)
            r.raise_for_status()
            return r.json().get("result", {})
        except Exception as e:
            if i == retries - 1:
                print(f"  ⚠️  {method} failed: {e}")
                return {}
            time.sleep(1)


def get_photos_in_bounds(bounds, z=14):
    return api_call("photo.getByBounds", {"z": z, "bounds": [bounds]}).get("photos", [])


def get_photo_meta(cid):
    return api_call("photo.giveForPage", {"cid": cid}).get("photo", {})


# Zonas diversas — mix urbano/rural, ex-URSS / Europa / LatAm / Asia
# Para zonas densas (Rusia centro) bajamos zoom para conseguir bbox más grande
zones = [
    # Rusia / ex-URSS (zonas medianas, no centros saturados)
    ("Yekaterinburg",     12, [[56.83, 60.55], [56.86, 60.65]]),
    ("Volgograd",         12, [[48.69, 44.46], [48.74, 44.55]]),
    ("Sevastopol",        12, [[44.58, 33.50], [44.63, 33.55]]),
    ("Yaroslavl",         13, [[57.62, 39.85], [57.65, 39.90]]),
    ("Vladivostok",       13, [[43.10, 131.86], [43.13, 131.91]]),
    ("Pskov",             13, [[57.80, 28.30], [57.84, 28.36]]),
    ("Tashkent",          13, [[41.30, 69.24], [41.33, 69.30]]),
    ("Yerevan",           13, [[40.17, 44.50], [40.21, 44.54]]),
    ("Tbilisi",           13, [[41.69, 44.79], [41.72, 44.83]]),
    ("Riga old town",     14, [[56.945, 24.101], [56.953, 24.117]]),
    # Latam
    ("Buenos Aires sur",  13, [[-34.65, -58.42], [-34.60, -58.36]]),
    ("Mexico DF Coyoacán",13, [[19.34, -99.18], [19.37, -99.15]]),
    ("La Habana Vedado",  13, [[23.12, -82.41], [23.16, -82.36]]),
    ("Bogotá",            13, [[4.59, -74.10], [4.65, -74.05]]),
    ("Lima centro",       13, [[-12.04, -77.05], [-12.02, -77.02]]),
    ("Montevideo",        13, [[-34.91, -56.21], [-34.88, -56.16]]),
    # Europa (no centros saturados)
    ("Praga",             14, [[50.080, 14.410], [50.090, 14.430]]),
    ("Cracovia",          13, [[50.04, 19.92], [50.08, 19.97]]),
    ("Budapest",          13, [[47.49, 19.04], [47.52, 19.07]]),
    ("Lisboa",            13, [[38.71, -9.15], [38.73, -9.12]]),
    ("Atenas",            13, [[37.97, 23.71], [38.00, 23.74]]),
    ("Estambul Sultanahmet",14,[[41.005, 28.97], [41.015, 28.985]]),
    # Asia
    ("Tokyo Asakusa",     14, [[35.708, 139.794], [35.714, 139.805]]),
    ("Beijing Hutongs",   13, [[39.92, 116.39], [39.95, 116.42]]),
    ("Mumbai Fort",       13, [[18.92, 72.83], [18.94, 72.85]]),
    # Rurales / pueblos
    ("Volga rural",       10, [[55.5, 39.0], [56.5, 41.0]]),
    ("Pampa Argentina",   10, [[-37.0, -65.0], [-36.0, -63.0]]),
    ("Cáucaso rural",     10, [[42.0, 43.5], [43.0, 45.0]]),
    ("Steppe Kazajstán",  10, [[49.0, 70.0], [50.0, 73.0]]),
]

print("=== Sampling photos por zona ===\n")
all_candidates = []
seen_cids = set()
for name, z, bounds in zones:
    photos = get_photos_in_bounds(bounds, z=z)
    print(f"{name} (z={z}): {len(photos)} fotos individuales")
    # Tomar hasta 3 por zona, solo type=1 (foto, no grabado/pintura)
    sample = random.sample(photos, min(6, len(photos))) if photos else []
    added = 0
    for p in sample:
        if added >= 3 or p["cid"] in seen_cids:
            continue
        meta = get_photo_meta(p["cid"])
        if not meta:
            continue
        if meta.get("type") != 1:  # solo fotos
            continue
        regions = meta.get("regions", [])
        country = regions[0]["title_local"] if regions else None
        src = (meta.get("source") or "").lower()
        if "wikimedia" in src or "wikipedia" in src:
            cont = "🔴 wikimedia"
        elif "flickr" in src:
            cont = "🟠 flickr"
        elif "<a href" in src or "http" in src:
            cont = "🟡 external"
        else:
            cont = "🟢 native"
        seen_cids.add(p["cid"])
        added += 1
        all_candidates.append({
            "cid": meta["cid"],
            "provider": "pastvu",  # de qué archivo bajamos la foto (controla blacklist runtime).
            "zone": name,
            "title": meta.get("title", ""),
            "year": meta.get("year"),
            "country": country,
            "source": meta.get("source", ""),  # provenance original (free-text con URLs).
            "contamination": cont,
            "geo": meta.get("geo"),
            "file": meta.get("file"),
            "size": meta.get("size"),
            "type": meta.get("type"),  # 1=foto, 2=pintura/grabado
            "h": meta.get("h"),
            "w": meta.get("w"),
            "waterh": meta.get("waterh", 0),
        })

OUT.write_text(json.dumps(all_candidates, indent=2, ensure_ascii=False))
print(f"\n✓ Total candidatos: {len(all_candidates)}")
print(f"✓ Saved to {OUT}\n")

# Resumen por contaminación
from collections import Counter
cont_counts = Counter(c["contamination"] for c in all_candidates)
print("Distribución por contaminación:")
for cont, n in cont_counts.items():
    print(f"  {cont}: {n}")

print("\n=== Lista completa ===")
for c in all_candidates:
    print(f"  #{c['cid']} [{c['zone']}, {c['year']}] {c['contamination']:25s} → {c['title'][:60]}")
