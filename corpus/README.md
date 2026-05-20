# corpus/

Carpeta canónica para las fotos del benchmark. **Gitignored** (binarios + copyright).

⚠️ **Importante**: las fotos en `corpus/photos/{cid}_clean_v1.jpg` ya tienen aplicado el **blur de overlays textuales** (captions archivísticas, sellos, watermarks). Esto es **necesario** para que el benchmark mida razonamiento, no shortcut OCR. Sin este blur, ~45% de las fotos serían resolubles leyendo el caption con el modelo + googleando.

## Estructura

```
corpus/
├── photos/                 # todas las fotos del corpus, planas
│   ├── {cid}_raw.jpg       # original tal cual se bajó del provider (sin procesar)
│   └── {cid}_clean_v{N}.jpg  # listas para el agente: clean + blur de overlays
└── README.md               # este archivo
```

`{cid}` es el ID en el provider (ej PastVu cid). Una foto ocupa 2 archivos (raw + clean).

## Pipeline de preparación

```
download_corpus_photos.py
  ↓
{cid}_raw.jpg  (descargado tal cual)
  ↓
clean_image.py
  - strip EXIF, ICC, comments
  - crop watermark del provider (banda inferior PastVu)
  - RGBA → RGB
  ↓
{cid}_clean_v1.jpg  (intermediate, NO usado directamente por el agente)
  ↓
detect_text_overlays.py
  - VLM (claude-sonnet) detecta texto archivístico (caption, sello, watermark)
  - blur gaussiano sobre regiones clasificadas `archive_overlay`
  - pass-through si no detecta nada
  ↓
{cid}_clean_v1.jpg  (final, lo que el agente ve)  ← sobrescribe el intermediate
```

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
