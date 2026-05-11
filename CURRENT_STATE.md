# GeoDetective Envs — Estado Actual

> **Mayo 2026**: agente investigador funcional con stack completo de 12 tools end-to-end. Concepto del benchmark **VALIDADO** sobre fotos de PastVu (sweet spot identificado, filtro adversarial v2 funcionando, mejora 300x con tools en el caso ideal). Pivote framing benchmark primario activo (env como deuda futura) — ver disclaimer en `PROJECT.md`.
>
> Para visión y norte: `PROJECT.md` · Para roadmap: [Project v2](https://github.com/users/lucaspecina/projects/6) · Para historial: `CHANGELOG.md`.

---

## 1. Qué corre HOY

### Estructura del código

```
src/geodetective/
├── corpus/
│   ├── clean_image.py           # Paso 0 del filtrado: strip EXIF + crop watermark + RGBA→RGB
│   └── blacklist.py             # GLOBAL minimal + PROVIDER_DOMAINS + per-photo runtime
├── tools/
│   ├── web_search.py            # Tavily backend con search_depth=advanced + filtros
│   ├── fetch_url.py             # Bajar páginas (texto y/o imágenes con hash)
│   ├── image_search.py          # Buscar imágenes con hash perceptual flagging
│   ├── geocode.py               # Nominatim OSM (free)
│   ├── historical_query.py      # OpenHistoricalMap Overpass temporal (free)
│   ├── crop_image.py            # Zoom local en regiones de la foto target
│   ├── static_map.py            # Google Maps Static (roadmap/satellite/terrain/hybrid)
│   └── street_view.py           # Google Street View Static
└── agents/
    └── react.py                 # Loop ReAct multi-paso con OpenAI tool calling

scripts/
├── sample_pastvu.py             # Muestrear fotos de PastVu por bbox geográficas
├── test3_no_tools.py            # Test 3 (VLM sin tools) con N runs
├── test_clean_image.py          # Tests sintéticos del módulo corpus.clean_image (13 escenarios)
├── test_blacklist.py            # Tests sintéticos del módulo corpus.blacklist (14 grupos, 65 checks)
└── run_react_websearch.py       # Run agente ReAct con todo el stack

experiments/
├── E001_test3_pastvu/           # 19 fotos sin tools, results.json
└── E002_react_websearch/        # ReAct con tools, results.json
```

### Stack y credenciales

- **Python 3.11** + conda env `geodetective`.
- **OpenAI SDK** (vía Azure Foundry): `gpt-4o`, `gpt-4.1`, `gpt-5`, `gpt-5.4` confirmados (todos visión OK).
- **Tavily** para web search + image search (free tier 1000 calls/mes).
- **Google Maps Platform**: Maps Static API + Street View Static API (free tier $200/mes, ~$0 esperado).
- **Nominatim, OpenHistoricalMap**: free, sin API key.
- **PIL, geopy, httpx, pydantic, imagehash, beautifulsoup4, lxml** para utilidades.

Credenciales en `.env` (gitignored):
- `AZURE_INFERENCE_CREDENTIAL`, `AZURE_FOUNDRY_BASE_URL`, `AZURE_MODEL`
- `TAVILY_API_KEY`
- `GOOGLE_MAPS_API_KEY` (con cuota restrictiva: 500/día Static, 200/día Street View)

### 12 Tools del agente

| # | Tool | Backend | Free? |
|---|---|---|---|
| 1 | `web_search` | Tavily (advanced) | API key (Tavily free tier) |
| 2 | `fetch_url` | httpx + bs4 | ✅ |
| 3 | `fetch_url_with_images` | httpx + bs4 + imagehash | ✅ |
| 4 | `image_search` | Tavily images + imagehash | API key |
| 5 | `geocode` | Nominatim OSM | ✅ |
| 6 | `reverse_geocode` | Nominatim OSM | ✅ |
| 7 | `historical_query` ⭐ | OpenHistoricalMap Overpass | ✅ |
| 8 | `crop_image` / `crop_image_relative` | PIL local | ✅ |
| 9 | `static_map` | Google Maps Static | API key |
| 10 | `street_view` | Google Street View Static + metadata | API key |
| 11 | `submit_answer` | terminal | — |

### Capacidades validadas (E001 + E002 + E003)

1. ✅ **Sample de fotos PastVu** por API (10+ zonas geográficas).
2. ✅ **Test sin tools** (E001): 19 fotos, N=3 runs, métricas distancia + año.
3. ✅ **Filtro adversarial v2** (source + dist_min<10km AND conf≥media): 53% sobrevive en sample.
4. ✅ **ReAct loop con tool calling** sobre Foundry, 12 tools, max 12 steps.
5. ✅ **Filtros anti-shortcut**: 17 dominios blacklist + hash perceptual flag (no bloqueo, solo flag).
6. ✅ **Inyección de imágenes en messages**: cuando una tool devuelve imágenes (image_search, fetch_url_with_images, crop_image, static_map, street_view), se inyectan como user message para que el modelo las vea visualmente.
7. ✅ **Concepto del benchmark validado** end-to-end: foto SP barrio anónimo pasó de 2573 km sin tools a **2.3-8.5 km** con tools (mejora 300x).

### Hallazgos clave

- **Sweet spot del corpus**: fotos cotidianas sin landmark + rurales URSS/Cáucaso/Kazajstán + pre-1950.
- **Las tools NO siempre ayudan** — y eso ES una métrica del benchmark. En foto sin pistas concretas (rural genérico) tools no ayudan; en foto identificable parcialmente, tools pueden EMPEORAR (modelo se compromete a hipótesis específicas equivocadas).
- **Variancia run-to-run alta** (factor 7x). N=3 runs mínimo para conclusiones robustas.
- **Modelo decide cuándo parar**. Cap 12 steps; típicamente usa 3-8.
- **NO forzar uso de tools en prompt** — sesga el benchmark, mide al humano que diseñó el prompt en lugar del modelo.

### Lo que NO corre todavía

- ❌ Tests automáticos (pytest).
- ❌ `pyproject.toml` con deps formal (todas las deps en pip + .env, sin packaging).
- ❌ Eval suite formal con baselines + ablations.
- ❌ Filtrado adversarial estratificado en sample grande (>50 fotos).
- ❌ Comparación entre modelos (gpt-4o vs gpt-5.4 vs Claude Opus).
- ❌ Reward / scoring formal con tests sintéticos.
- ❌ Rúbrica investigativa formal documentada.
- ❌ Decisión Verifiers vs custom (postpuesta a Fase 6).
- ❌ Tools requiriendo OCR (decidido: visión nativa + crop alcanza).

---

## 2. Cómo usar el sistema hoy

### Setup

```bash
cd geodetective-envs
conda activate geodetective  # Python 3.11
# .env tiene credenciales (gitignored). Ver "Stack y credenciales" arriba.
```

### Samplear fotos

```bash
python scripts/sample_pastvu.py
# Genera: experiments/E001_test3_pastvu/candidates.json
```

### Correr Test 3 (sin tools, baseline) en N runs

```bash
N_RUNS=3 python scripts/test3_no_tools.py
```

### Correr ReAct con todo el stack sobre fotos específicas

```bash
# Una foto:
python scripts/run_react_websearch.py 1748874

# Múltiples fotos con N=3 runs:
N_RUNS=3 python scripts/run_react_websearch.py 1748874 1101385 1459395

# Default (sin args): 5 fotos sobrevivientes del E001
```

### Inspeccionar resultados

```python
import json
results = json.load(open("experiments/E002_react_websearch/results.json"))
# Cada result tiene: candidate, runs[], stats (dist_min/median/max)
```

---

## 3. Qué se está construyendo

**Foco actual**: validación incremental por fases. Ver `research/synthesis/validation_plan.md`.

- **Fase 0** ✅ — concepto manual (E001 + E002).
- **Fase 1** 🟡 en curso — datos + cobertura. Pendiente: spike PastVu metadata real (#3), Smapshot (#4), LoC API (#5), sample diverso (#17).
- **Fase 2** 🟡 en curso — tools individuales. **11 implementadas** (de las planeadas). Faltan: nada crítico para v1.
- **Fase 3** ⏳ — anti-shortcut estratificado en sample grande.
- **Fase 4** ⏳ — loop end-to-end con rúbrica investigativa formal.
- **Fase 5** ⏳ — reward/scoring formal con tests sintéticos.
- **Fase 6** ⏳ — eval suite + baselines + ablations + decisión contrato del env.

**Epic #21 — pipeline de filtrado del corpus**: ✅ **CERRADO** (2026-05-11). Sub-issues #22 (clean_image), #23 (blacklist runtime per-photo), #3 (audit metadata), #17 (sample diverso), #24 (atacante GPT-4o) — todas cerradas. Deuda hash perceptual implementada como hard reject en `react.py`.

**Piloto del pipeline validado (K=5, ver `research/notes/E004_attacker_filter.md`)**: el pipeline completo (sample → atacker → filtro) corrió end-to-end sobre 180 fotos (K_PER_CELL=5 en sample_diverso.py). 101 sobrevivieron al atacante GPT-4o (56%). Distribución por bucket país: Russia-EU 22, Russia-Asia 26, Ex-URSS 19, Europa-no-URSS 15, Norteamerica 6, Resto 13. Por bucket década: 1890s 13, 1900s 14, 1910s 19, 1920s 19, 1930s 21, 1940s 15. Output en `experiments/E004_attacker_filter/results.json` (gitignored). **No es el corpus de producción** — para eso hay que escalar K_PER_CELL (cada celda tiene de 247 a ~3700 unique geohashes disponibles).

**Próximos pasos posibles**:
- Probar end-to-end con el agente ReAct sobre algunas fotos del piloto (issue a crear).
- Escalar K_PER_CELL para corpus de producción (issue a crear).
- Eval suite formal con baselines + ablations (Fase 6 del plan de validación).
- Rúbrica investigativa formal (Fase 4).

---

## 4. Donde mirar para qué

| Si querés... | Andá a |
|---|---|
| Por qué existe el proyecto, invariantes | `PROJECT.md` |
| Plan paso a paso de validación | `research/synthesis/validation_plan.md` |
| Decisiones canónicas qué apalancar | `research/synthesis/related_work_decisions.md` |
| Análisis de viabilidad técnica | `research/synthesis/viability_assessment.md` |
| Resultados E001 (sin tools) | `research/notes/E001_test3_no_tools_results.md` |
| Resultados E002 (web_search inicial) | `research/notes/E002_react_websearch_first_run.md` |
| Resultados E003 (stack completo 12 tools) | `research/notes/E003_react_full_tools.md` |
| Trabajo pendiente con prioridad | [Project v2](https://github.com/users/lucaspecina/projects/6) |
| Operativa de Claude Code | `CLAUDE.md` |
| Idea original (semilla histórica) | `research/notes/genesis-intro.md` |
| Historial de cambios | `CHANGELOG.md` |
