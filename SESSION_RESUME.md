# Cómo retomar desde otra máquina / sesión nueva

> **Última sesión**: 2026-05-22 — corpus v2 cerrado (151 fotos finales post-selección manual). Related work checked: SpotAgent (feb 2026) y GeoVista (nov 2025) son competidores cercanos. **Próximo paso claro**: implementar CORRAL annotator (diferenciador metodológico crítico) + cross-model run sobre el corpus consolidado.
>
> Si retomás en otra máquina, leé este doc PRIMERO. Después tenés `CURRENT_STATE.md` para el panorama completo.

---

## Estado al cierre (2026-05-22)

### Corpus consolidado — listo

| Item | Detalle |
|---|---|
| **Corpus final canónico** | 151 fotos blureadas, balanceadas país × década |
| **Metadata canónica** | `experiments/E007_sample_diverso/candidates_v2_final.json` (en git) |
| **Need re-blur** | 26 fotos pendientes de re-blureado, `candidates_need_reblur.json` (en git) |
| **Rechazadas** | 93 fotos descartadas en selección manual, `candidates_rejected_v2.json` (en git) |
| **Blacklist consolidada** | 390 cids ya procesados, `blacklist_cids.json` (en git) — para futuros sampleos suplementarios |
| **Detections (anti-shortcut)** | `experiments/E011_text_overlay_detection/sample270_v2/detections.json` (en git, 580KB) — fuente canon de bboxes para re-aplicar blur |

### Distribución del corpus final (151)

```
Asia-non-URSS        24   |  China        16
LatinoAmerica        22   |  Russia       15
Africa-ME            17   |  USA          14
Oceania              15   |  UK            9
Norteamerica         15   |  Israel        7
Ex-URSS              11   |  Australia     7
Europa-Britanica      9   |  NZ            6
Europa-Nordica        8   |  Denmark       6
Russia-Asia           8   |  Turkey        6
Russia-EU             7   |  Egypt         5
Europa-Occidental     6   |  ...
Europa-Mediterranea   5   |
Europa-CentroEste     4   |
```

Décadas: 1890s=26, 1900s=26, 1910s=22, 1920s=23, 1930s=25, 1940s=29. Muy uniforme.

### Hallazgo clave: competitive landscape (mayo 2026)

**No estamos reinventando**, pero hay competidores cercanos publicados últimos 6 meses:

- **SpotAgent** (feb 2026, Fudan/Tencent) — agentic + 3 tools + GRPO + reward geodésico piecewise. **Contemporáneo, no histórico, sin process eval**.
- **GeoVista + GeoBench** (nov 2025, Fudan/Tencent/Tsinghua) — agentic + 2 tools + GRPO. **Contemporáneo, sin process eval**.
- **WanderBench / GeoAoT** (2026, SJTU) — geo embodied (StreetView navigable). **No histórico**.

**Nuestro moat queda en**: histórico + 12 tools (vs 2-3 competidores) + process eval CORRAL + pipeline anti-shortcut serio + environment reusable para RL training.

**Sin CORRAL implementado, somos "SpotAgent con fotos viejas y más tools"**. CORRAL es CRÍTICO para diferenciación metodológica.

Detalle completo en `research/synthesis/related_work.md` (actualizar al volver).

---

## Cómo retomar técnicamente en otra máquina

### Paso 1 — clone + setup

```bash
git clone https://github.com/lucaspecina/geodetective-envs.git
cd geodetective-envs
conda create -n geodetective python=3.11 -y && conda activate geodetective
pip install openai httpx pillow imagehash beautifulsoup4 lxml geopy pydantic ddgs zstandard huggingface_hub pygeohash
```

Crear `.env` (no va a git):

```
AZURE_INFERENCE_CREDENTIAL=...
AZURE_FOUNDRY_BASE_URL=https://amalia-resource.openai.azure.com/openai/v1
AZURE_MODEL=gpt-5.4
GOOGLE_MAPS_API_KEY=...
```

### Paso 2 — regenerar el corpus canónico (151 fotos)

Las fotos NO van a git (binarios + copyright). Pero los JSONs sí, así que se regeneran:

```bash
# Baja las 151 fotos y aplica clean_image (strip EXIF + crop watermark)
# Output: corpus/photos/{cid}_{raw,clean_v1}.jpg sin blur
python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates_v2_final.json

# Aplica blur sobre archive_overlays usando detections.json (ya en git)
# Sobreescribe corpus/photos/{cid}_clean_v1.jpg in-place
python scripts/apply_blur_from_detections.py --candidates-filter experiments/E007_sample_diverso/candidates_v2_final.json
```

Después de esos 2 comandos, `corpus/photos/` queda idéntico bit-a-bit (módulo re-encode JPEG) al estado de la máquina origen.

Verificar:
```bash
ls corpus/photos/*_clean_v1.jpg | wc -l   # debería dar 151
```

### Paso 3 — opcionalmente bajar el dump PastVu (solo si vas a re-samplear)

Solo necesario si querés hacer un sampleo suplementario (no para usar el corpus existente):

```bash
python scripts/download_pastvu_dump.py   # 282 MB, una vez
```

---

## Próximos pasos en orden de prioridad

### 1. CORRAL annotator implementado (CRÍTICO)

Es el diferenciador metodológico clave vs SpotAgent/GeoVista. Stub ya implementado en sesiones pasadas (`research/synthesis/process_eval_design.md` + stub sobre traces E005).

Pasos:
1. Refinar el annotator stub con dimensiones CORRAL adaptadas a geo-investigación
2. Correr sobre traces existentes (E005, E010, E014) para validar
3. Documentar criterios + ejemplos worked-out en `research/examples/`

### 2. Cross-model run sobre el corpus consolidado (151 fotos)

Una vez el annotator funciona, correr eval cuantitativo:

```bash
# 4 modelos × 151 fotos × N=3 runs × min_steps=12, max_steps=30
# Estimación: ~1800 corridas, $300-500, ~6-12 horas en background
MODELS="gpt-5.4-mini,gpt-4o,claude-sonnet-4-6,claude-opus-4-6"
python scripts/run_multimodel_pilot.py \
    --candidates experiments/E007_sample_diverso/candidates_v2_final.json \
    --models $MODELS --n-runs 3 --min-steps 12 --max-steps 30
```

### 3. Process eval con annotator sobre las traces

Aplica CORRAL annotator a cada traza del cross-model run. Genera métricas process (no solo outcome).

### 4. (Opcional, después) Sampleo suplementario para escalar corpus

Si el cross-model muestra señal y queremos más power estadístico:
- Sampleo de buckets sub-representados (Europa-CentroEste/Mediterranea con 4-5 fotos)
- Usar `blacklist_cids.json` para excluir las 390 cids ya tocadas

### 5. (Opcional, después) Entrenar policy con GRPO sobre el environment

Si el ángulo final es "environment para RL training" (no solo benchmark), hay que mostrar al menos UNA policy entrenada.

---

## Comandos típicos

```bash
# Correr agente sobre fotos específicas
MODEL=gpt-5.4-mini MAX_STEPS=20 MIN_STEPS=12 CIDS="2165013" python scripts/run_e010_iteration.py

# Métricas post-hoc
python scripts/compute_metrics.py experiments/E010_iteration_pilot/results_*.json

# Viewer step-by-step (con sidebar navigation)
python scripts/build_iteration_viewer.py path/to/results.json --photos-dir corpus/photos

# Status del proyecto (skill)
# /status
```

---

## Documentos para orientarse al volver

Orden recomendado:

1. **`SESSION_RESUME.md`** (este doc)
2. **`research/synthesis/related_work.md`** — landscape competitivo 2025-2026
3. **`research/synthesis/process_eval_design.md`** — diseño del annotator CORRAL
4. **`CURRENT_STATE.md`** — panorama actual del proyecto
5. **GitHub issues abiertas** — siguiente trabajo (`gh issue list`)
6. **`CLAUDE.md`** — convenciones del repo

---

## Cambios importantes desde 2026-05-20

- Corpus expandido de 180 a 270 sampleadas con balanceo país × década (13 buckets, sin sesgo a Rusia)
- Selección manual → 151 fotos finales canónicas
- Atacante GPT-4o N=3 corrido sobre las 270 → 113 rechazadas (shortcut), 157 sobrevivientes (de ahí salieron las 151 + 26 need_reblur)
- Carpetas auxiliares en `corpus/` (`photos_rejected_v2/`, `photos_need_reblur/`) — locales, NO en git
- Blacklist consolidada de 390 cids para futuros sampleos

---

## Notas importantes / gotchas

- **Corpus blureado** es ahora canónico. En máquina nueva: download → apply_blur. No usar fotos sin blur.
- **`detections.json`** en `E011/sample270_v2/` es la fuente canon de bboxes — está en git, no hace falta re-correr el VLM detector.
- **Carpetas `corpus/photos_rejected_v2/`, `corpus/photos_need_reblur/`, `corpus/candidates_*/`, `corpus/a-remove/`** son locales, NO se sincronizan vía git. Si las necesitás en otra máquina, hay que rsync manual.
- **Results históricos contaminados**: E010, E012, E014 (excepto blurred_minsteps), E009 corrieron sobre fotos sin blur. **No usar como baseline canónico** del paper.
- **Issues abiertas relevantes**: #46 (corpus expansion — CERRARLO al volver), #34 (main run), #35 (estratificación), #39 (annotator E009/E010), #43 (ablations), #44 (validación E010).

---

## Comando sugerido al retomar en máquina nueva

```bash
git clone https://github.com/lucaspecina/geodetective-envs.git
cd geodetective-envs
# crear .env con AZURE_* y GOOGLE_MAPS_API_KEY
conda create -n geodetective python=3.11 -y && conda activate geodetective
pip install openai httpx pillow imagehash beautifulsoup4 lxml geopy pydantic ddgs zstandard huggingface_hub pygeohash
python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates_v2_final.json
python scripts/apply_blur_from_detections.py --candidates-filter experiments/E007_sample_diverso/candidates_v2_final.json
gh issue view 46    # o tu issue prioritario
```

Después de eso ya podés correr cualquier experimento sobre el corpus canónico.
