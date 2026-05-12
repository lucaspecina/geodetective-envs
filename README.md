# GeoDetective Envs

**Benchmark de evaluación de agentes geo-investigativos sobre fotografías históricas.** Se le pasa una foto antigua a un modelo, el modelo investiga con tools (Maps, Street View, web, archivos históricos OSM) en un loop ReAct, y se mide qué tan cerca llegó del lugar real y qué tan genuinamente investigó.

> ⚠️ **Framing actual: BENCHMARK primario. El environment de RL queda como deuda futura.**
>
> La idea original era exponer esto como **environment de RL** consumible por Verifiers / TRL / OpenEnv para training de policies. Pero la evaluación de viabilidad (mayo 2026) confirmó tres bloqueadores duros para esa versión:
>
> - **Google Maps TOS** prohíbe usar Maps Content para training/validating ML.
> - **Reverse image search web-scale** no tiene solución a costo razonable para filtrado adversarial sobre 1M+ fotos.
> - **Costo de una corrida RL seria** con tools comerciales: $30K-$80K USD.
>
> Ninguno bloquea la versión benchmark (1K-10K fotos, costo trivial, ToS de inference es zona aceptable). Por eso el proyecto construye primero el benchmark; el env de RL queda como objetivo posterior.
>
> El nombre "GeoDetective **Envs**" refleja la idea original. Renombrar es deuda explícita.

## LA PREGUNTA

> **1. ¿Por qué este caso todavía no es una investigación geo-detectivesca real? ¿Qué le falta?**
>
> **2. ¿Por qué un modelo entrenado con RL sobre este environment todavía no aprendería buen juicio investigativo geo-espacial?**

Aplica al evaluar, diseñar, priorizar, revisar. Detalle + presiones evolutivas en `PROJECT.md`.

## Estado

- **v0 (mayo 2026, en curso)**: agente ReAct funcional con 12 tools, corpus PastVu auditado (2M records → 676K elegibles), sample diverso de 180 fotos (6×6 país×década), filtrado adversarial con GPT-4o (101 sobrevivientes), pilot E005 end-to-end. Concepto validado.
- **v1**: corpus de producción + eval suite formal + rúbrica investigativa + comparación entre modelos.
- **v2** (futuro): el env de RL real, sobre dataset alternativo si Google Maps queda fuera de scope.

Detalle honesto de qué corre HOY: `CURRENT_STATE.md`. Historial: `CHANGELOG.md`. Roadmap: [Project v2](https://github.com/users/lucaspecina/projects/6).

---

## Setup

```bash
conda create -n geodetective python=3.11 -y && conda activate geodetective
pip install openai httpx pillow imagehash beautifulsoup4 lxml geopy pydantic tavily-python
```

`.env` en la raíz del repo (gitignored):

```
AZURE_INFERENCE_CREDENTIAL=...
AZURE_FOUNDRY_BASE_URL=https://amalia-resource.openai.azure.com/openai/v1
AZURE_MODEL=gpt-5.4
TAVILY_API_KEY=...
GOOGLE_MAPS_API_KEY=...
```

---

## Paso a paso — pipeline completo del benchmark

> Este es el orden canónico para construir el corpus filtrado y evaluar un modelo sobre él. Cada paso lee del output del anterior. Los pasos 1-3 **ya están corridos** sobre el sample piloto (180 fotos, K_PER_CELL=5). Re-ejecutalos si querés escalar K, regenerar con otra seed, o aplicar a otra fuente.

### 1. Audit metadata PastVu (#3) — UNA VEZ

Baja `pastvu.jsonl.zst` (282 MB) de HF y streamea para entender el dump completo.

```bash
python scripts/audit_pastvu_metadata.py
# Output: experiments/E006_pastvu_audit/results.json
# Lee:    HF nyuuzyou/pastvu (descarga 1 vez, cachea)
# Tiempo: ~35s
```

### 2. Sample diverso (#17) — re-ejecutar si cambia K o seed

Filtra eligibles (type=1 + geo + year + 1890-1949), arma celdas país×década (6×6), de-duplica por geohash5, y sortea K fotos por celda.

```bash
python scripts/sample_diverso.py
# Default: K_PER_CELL=5, SEED=42 → 180 candidatos
# Output:  experiments/E007_sample_diverso/candidates.json + audit_summary.json
```

Para escalar el corpus (issue #25 abierta): `K_PER_CELL=20 python scripts/sample_diverso.py`.

### 3. Filtro adversarial — atacante GPT-4o (#24)

Para cada foto del sample, baja, limpia (strip EXIF + crop watermark + RGBA→RGB), corre N=3 llamadas a GPT-4o sin tools en paralelo, y descarta si en ALGUNA corrida cumple `dist<10km AND conf≥media`.

```bash
python scripts/run_attacker_filter.py
# Default:  N_WORKERS=8
# Output:   experiments/E004_attacker_filter/results.json
#           experiments/E004_attacker_filter/photos/  (cache limpio)
# Tiempo:   ~6 min sobre 180 fotos
```

Smoke test sobre 10 fotos: `MAX_PHOTOS=10 python scripts/run_attacker_filter.py`.

### 4. Correr el agente ReAct sobre el corpus filtrado (#26)

Lee los `decision=='keep'` del paso 3, samplea N por bucket país, y corre el ReAct loop completo (12 tools, max_steps=12).

```bash
python scripts/run_react_pilot.py
# Default: SEED=42, N_PER_BUCKET=1, REACT_MODEL=gpt-5.4 → 6 fotos
# Output:  experiments/E005_react_pilot/results.json
# Tiempo:  ~15 min
```

Variantes útiles:

```bash
# Más fotos por bucket
N_PER_BUCKET=3 python scripts/run_react_pilot.py

# Fotos específicas por cid
python scripts/run_react_pilot.py 2126812 1748874

# Cambiar modelo
REACT_MODEL=gpt-4o python scripts/run_react_pilot.py
```

### 5. Ablación de prompt (opcional)

Mismas fotos, distintas versiones del SYSTEM_PROMPT, output separado por versión.

```bash
PROMPT_VERSION=v1_mechanical    python scripts/run_react_pilot.py
PROMPT_VERSION=v2_descriptive   python scripts/run_react_pilot.py
PROMPT_VERSION=v3_thinking_visible python scripts/run_react_pilot.py
# Output: results_v1_mechanical.json, results_v2_descriptive.json, etc.
```

### 6. Generar reports HTML interactivos

Frontend con mapa Leaflet + trayectoria step-by-step + crops inline + imágenes/mapas embebidos.

```bash
# Report por versión (selector de foto, panel de tools, trayectoria)
python scripts/build_pilot_report.py v1_mechanical
python scripts/build_pilot_report.py v2_descriptive
python scripts/build_pilot_report.py v3_thinking_visible

# Comparación cruzada (mapa central + 3 columnas v1/v2/v3)
python scripts/build_compare_report.py

# Stdout viewer para inspección rápida
python scripts/analyze_pilot_trajectories.py v1_mechanical
python scripts/compare_pilots.py
```

Reports en `experiments/E005_react_pilot/report_*.html`. Abrir con el browser:

```powershell
# Windows / PowerShell — abre con el browser default
start experiments\E005_react_pilot\report_compare.html

# O el folder en explorer
explorer experiments\E005_react_pilot
```

Tip: en Cursor / VS Code, `Ctrl+Shift+V` sobre un `.html` abre preview embebido.

---

## Pipelines alternativos / legacy

### Baseline sin tools (Test 3, E001)

VLM sin herramientas — sirve como floor del benchmark.

```bash
N_RUNS=3 python scripts/test3_no_tools.py
# Lee:    experiments/E001_test3_pastvu/candidates.json
# Output: experiments/E001_test3_pastvu/results.json
```

### ReAct sobre corpus E001 (legacy, sample manual por bbox)

```bash
python scripts/sample_pastvu.py                              # samplea por bbox manual
N_RUNS=3 python scripts/run_react_websearch.py 1748874       # ReAct sobre cids
```

### Tests sintéticos de los módulos de corpus

```bash
python scripts/test_clean_image.py    # 13 escenarios
python scripts/test_blacklist.py      # 14 grupos, 65 checks
```

---

## Navegación rápida

| Si querés... | Andá a |
|---|---|
| Visión, LA PREGUNTA, invariantes | `PROJECT.md` |
| Qué corre HOY (estado honesto) | `CURRENT_STATE.md` |
| Operativa de Claude Code en este repo | `CLAUDE.md` |
| Trabajo pendiente / roadmap | [Project v2](https://github.com/users/lucaspecina/projects/6) · `gh issue list` |
| Investigación, debates, related work | `research/README.md` |
| Resultados experimentales (E001-E005) | `research/notes/` |
| Conclusiones consolidadas | `research/synthesis/` |
| Historial de cambios | `CHANGELOG.md` |

## Estructura

```
src/geodetective/
├── corpus/          # clean_image (#22), blacklist runtime per-photo (#23)
├── tools/           # 12 tools del agente
└── agents/react.py  # ReAct loop con OpenAI tool calling

scripts/             # pipeline + baselines + reports
experiments/         # gitignored excepto candidates/results.json + E005 reports
research/            # notes, synthesis, examples, archive
.claude/skills/      # /test, /status
```
