# GeoDetective Envs

**Benchmark para evaluar agentes investigativos sobre fotografías históricas.** El agente recibe una foto antigua y debe descubrir **dónde** y **cuándo** fue tomada, usando herramientas reales (búsqueda web, Google Maps, Street View, OpenHistoricalMap, etc.) en un loop ReAct multi-paso.

Mide qué tan bien razona el modelo investigando — no solo si acierta la respuesta, sino cómo llega a ella.

## Qué se puede hacer hoy

- Correr cualquier modelo (OpenAI, Anthropic, xAI, DeepSeek, Moonshot) sobre el corpus de 185 fotos balanceadas (6 países × 6 décadas, 1890-1949).
- Comparar modelos cross-provider con métricas: distancia geodésica, year accuracy, calibración, uso de herramientas, verificación visual.
- Analizar paso a paso qué hizo el agente: qué tools usó, qué información recibió, cómo razonó.
- Inspeccionar trazas con viewer HTML interactivo (mapa + crops inline + step-by-step).

## Setup

```bash
git clone https://github.com/lucaspecina/geodetective-envs.git
cd geodetective-envs
conda create -n geodetective python=3.11 -y && conda activate geodetective
pip install openai httpx pillow imagehash beautifulsoup4 lxml geopy pydantic ddgs zstandard huggingface_hub pygeohash
```

Crear `.env` en la raíz (gitignored):

```
AZURE_INFERENCE_CREDENTIAL=...
AZURE_FOUNDRY_BASE_URL=https://your-resource.openai.azure.com/openai/v1
AZURE_MODEL=gpt-5.4
GOOGLE_MAPS_API_KEY=...
```

Modelos soportados (via Azure Foundry o compatibles): `gpt-4o`, `gpt-5.4`, `gpt-5.4-mini`, `claude-opus-4-6`, `claude-sonnet-4-6`, `grok-4.3`, `Kimi-K2.6`, otros.

## Quick start

Investigar UNA foto del corpus:

```bash
# Bajar el corpus (~185 fotos, ~275 MB, una sola vez)
python scripts/download_pastvu_dump.py
python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates.json

# Correr el agente sobre 1 foto específica
MODEL=gpt-5.4-mini CIDS=2165013 python scripts/run_e010_iteration.py
# Output: experiments/E010_iteration_pilot/results_gpt-5_4-mini.json

# Generar viewer step-by-step
python scripts/build_iteration_viewer.py experiments/E010_iteration_pilot/results_gpt-5_4-mini.json
# Abrir el HTML resultante en el browser
```

Cross-model sobre múltiples fotos:

```bash
MODELS="gpt-5.4,gpt-4o,claude-sonnet-4-6" python scripts/run_multimodel_pilot.py
```

Métricas post-hoc sobre resultados existentes:

```bash
python scripts/compute_metrics.py experiments/E010_iteration_pilot/results_*.json
# Devuelve: distance buckets, year accuracy, calibración, uso de tools
```

## Dossier — visualizar todo (análisis + expedientes paso a paso)

El **dossier** es un documento HTML navegable con dos vistas: (1) **📊 Análisis** — perfil conductual por modelo (heatmap de vicios investigativos por familia + estilo/recursos); (2) **🗂️ Expedientes** — cada investigación paso a paso, con la foto, los recortes que hizo el agente, los street views / mapas que miró, su razonamiento, sus creencias por paso, y el mapa de la trayectoria.

```bash
# Genera el dossier de un experimento (auto-split por modelo si hay varios)
python scripts/build_dossier.py --dir experiments/E016_belief_pilot --title "Mi experimento"
```

**Cómo abrirlo**: los archivos quedan en el directorio del experimento. Son **HTML autocontenidos** (imágenes embebidas) — **doble click** los abre en tu navegador, sin servidor.

- `dossier.html` — índice liviano: análisis comparativo global + links a los dossiers por modelo.
- `dossier_<modelo>.html` — un dossier completo **con imágenes** por modelo (~130-190 MB c/u).

Por qué se parte por modelo: un solo archivo con todas las corridas + imágenes pesa cientos de MB y cuelga el navegador. Cada dossier por modelo pesa lo mismo que un viewer normal.

**Variantes**:

```bash
python scripts/build_dossier.py --dir <exp> --no-images       # UN dossier liviano (sin imágenes)
python scripts/build_dossier.py --dir <exp> --split-by-model  # forzar split (aunque sea 1 modelo)
```

**Trabajás por SSH** (no podés abrir archivos locales)? Levantá un servidor y tunelizá el puerto:

```bash
python -m http.server 8016 --bind 127.0.0.1 --directory experiments/E016_belief_pilot
# En VS Code: panel "Ports" → reenviar 8016 → abrir http://localhost:8016/dossier.html
```

### Perfil conductual solo (sin HTML)

```bash
python scripts/behavior_profile.py --dir experiments/E016_belief_pilot
# Tabla por (modelo, arm): ~35 señales de estilo de investigación, todas mecánicas
```

### Otros viewers (una sola foto / trayectoria)

- `build_belief_viewer.py <results.json>` — trayectorias belief con timeline + mapa por step.
- `build_iteration_viewer.py <results.json>` — viewer step-by-step de una traza.

## Herramientas del agente

El agente tiene acceso a 12 herramientas, cada una con un rol diferente:

| Tool | Qué hace |
|---|---|
| `web_search` | Búsqueda web (Azure + Bing) con metadata enriquecida: title, snippet largo, site_name, fecha, idioma, tipo (wikipedia/article/archive/etc.) |
| `fetch_url` | Texto completo de una página web (12K chars max) |
| `fetch_url_with_images` | Texto + imágenes embebidas con sus **captions/alt/figcaption/contexto narrativo** del HTML |
| `image_search` | Búsqueda de imágenes en flujo 3-pasos: grilla 4×4 numerada → pick celdas en alta res → ver página fuente. Soporta paginación. |
| `geocode` / `reverse_geocode` | Nombre ↔ coordenadas (Nominatim/OSM) |
| `historical_query` / `historical_query_at` | OpenHistoricalMap: qué edificios/iglesias/estaciones existían en zona X en año Y |
| `crop_image` / `crop_image_relative` | Zoom en regiones de la foto target |
| `static_map` | Mapas Google con POIs cercanos categorizados + altitud + categoría de terreno. Soporta vista compuesta 4-en-1 (sat+terrain+roadmap+hybrid). |
| `street_view` | Vistas actuales de Street View con opción de exploración de panoramas vecinos |
| `submit_answer` | Respuesta final estructurada (location, lat, lon, year, confidence, reasoning, verification_checks) |

## Estructura del proyecto

```
src/geodetective/
├── tools/              # 12 herramientas del agente
├── agents/react.py     # Loop ReAct multi-paso con OpenAI tool calling
├── llm_adapter.py      # Rutea OpenAI-compatible vs Anthropic via Foundry
├── corpus/             # Pipeline de preparación del corpus (clean, blacklist)
├── judge/              # Annotator de procesos (CORRAL-adapted)
└── eval/metrics.py     # Métricas post-hoc (distance buckets, year, calibration)

scripts/                # CLI: pipeline, ejecución, análisis, reports
experiments/            # Resultados de experimentos (JSONs canónicos commiteados)
corpus/photos/          # 185 fotos canónicas (gitignored, regenerable)
research/               # Notas de experimentos, síntesis, decisiones de diseño
```

## Cómo armar un corpus desde cero

Si querés samplear un corpus nuevo (más fotos, otro balance):

```bash
# 1. Bajar el dump completo de PastVu (~282 MB, una vez)
python scripts/download_pastvu_dump.py

# 2. Samplear N fotos balanceadas (default 180: 6 buckets país × 6 décadas × K=5)
K_PER_CELL=10 python scripts/sample_diverso.py
# Output: experiments/E007_sample_diverso/candidates.json

# 3. Descargar las fotos sampleadas y limpiarlas (strip EXIF, crop watermark)
python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates.json
# Output: corpus/photos/{cid}_raw.jpg + {cid}_clean_v1.jpg

# 4. (Opcional) Filtrar con atacante GPT-4o sin tools — descarta las "demasiado fáciles"
python scripts/run_attacker_filter.py
```

## Anti-shortcut

El benchmark mide investigación REAL, no memorización ni búsqueda inversa. Por eso:

- **Hash perceptual hard-reject**: imágenes que matchean visualmente con la foto target se descartan automáticamente.
- **Blacklist por foto**: bloquea reverse image search, agregadores, hosting platforms, y la fuente original del archivo.
- **Detección y blur de texto archivístico**: captions/sellos del archivo que revelan ubicación se borronean (para que el modelo no haga OCR shortcut).
- **Foto cleaning**: strip EXIF + crop de watermarks del proveedor.

## Documentación adicional

| | |
|---|---|
| **Estado actual del sistema** | [CURRENT_STATE.md](CURRENT_STATE.md) |
| **Historial de cambios** | [CHANGELOG.md](CHANGELOG.md) |
| **Notas de experimentos** | [research/notes/](research/notes/) |
| **Decisiones de diseño consolidadas** | [research/synthesis/](research/synthesis/) |
| **Roadmap** | [Project v2](https://github.com/users/lucaspecina/projects/6) |

## Licencia

Por definir.
