# corpus/

Carpeta canónica para las fotos del benchmark. **Gitignored** (binarios + copyright).

## Estructura

```
corpus/
├── photos/                 # todas las fotos del corpus, planas
│   ├── {cid}_raw.jpg       # original tal cual se bajó del provider
│   └── {cid}_clean_v{N}.jpg  # post clean_image.py (EXIF strippeado + watermark cropeado)
└── README.md               # este archivo
```

`{cid}` es el ID en el provider (ej PastVu cid). Una foto ocupa 2 archivos (raw + clean).

## Cómo poblar la carpeta

### Opción A — sincronizar desde otra máquina

```powershell
# desde la máquina con el corpus completo
rsync -av experiments/E004_attacker_filter/photos/ otra-maquina:.../corpus/photos/
rsync -av experiments/E010_iteration_pilot/photos/ otra-maquina:.../corpus/photos/
```

### Opción B — re-descargar de PastVu

Necesita el dump de metadata PastVu (282MB, no en git):

```bash
python scripts/sample_diverso.py        # samplea N fotos balanceadas país×década
python scripts/run_attacker_filter.py   # filtra las que el atacante GPT-4o resuelve directo
```

Output va a `experiments/E0XX_*/photos/`. Después copiá a `corpus/photos/`:

```powershell
cp experiments/E0XX_*/photos/*.jpg corpus/photos/
```

## Metadata por foto

La metadata (cid, provider, geo, year, country, page_url, etc.) vive en JSONs separados:
- `experiments/E007_sample_diverso/candidates.json` — corpus 180 fotos sampleadas
- `experiments/E004_attacker_filter/results.json` — sobrevivientes del filtro
- `experiments/E010_iteration_pilot/picked_photos.json` — 5 fotos del pilot

El JSON es la fuente canon. `corpus/photos/{cid}_*.jpg` solo guarda los pixels.

## Ver las fotos

Windows Explorer con thumbnails:

```powershell
explorer corpus\photos
```

O un viewer grid HTML (autocontenido, no requiere server):

```powershell
python scripts/build_corpus_viewer.py --photos-dir corpus/photos
start corpus/photos/corpus_viewer.html
```
