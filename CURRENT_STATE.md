# GeoDetective Envs — Estado Actual

> **Mayo 2026**: agente investigador funcional con stack completo de 12 tools end-to-end. Concepto del benchmark **VALIDADO** sobre fotos de PastVu (sweet spot identificado, filtro adversarial v2 funcionando, mejora 300x con tools en el caso ideal). **Corpus v2 cerrado** (2026-05-22): 151 fotos finales balanceadas país×década post-selección manual, blacklist consolidada de 390 cids para futuros sampleos. Pivote framing benchmark primario activo (env como deuda futura) — ver disclaimer en `PROJECT.md`.
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
│   ├── web_search.py            # Azure Responses API + Bing Grounding (post-Tavily)
│   ├── fetch_url.py             # Bajar páginas (texto y/o imágenes con hash)
│   ├── image_search.py          # DuckDuckGo (ddgs) + hash perceptual flagging (post-Tavily)
│   ├── geocode.py               # Nominatim OSM (free)
│   ├── historical_query.py      # OpenHistoricalMap Overpass temporal (free)
│   ├── crop_image.py            # Zoom local en regiones de la foto target
│   ├── static_map.py            # Google Maps Static (roadmap/satellite/terrain/hybrid)
│   └── street_view.py           # Google Street View Static
├── llm_adapter.py               # ⭐ Routea OpenAI vs Anthropic via MODEL_SPECS registry
├── eval/
│   ├── metrics.py               # Métricas post-hoc (distance/year/calibration)
│   └── belief_scoring.py        # ⭐ Proper scoring rules geodésicas (belief-state, E016 #47)
├── judge/                       # ⭐ Process eval annotator (CORRAL adapted)
│   ├── serialize_trace.py       # trace ReAct → texto [MSG N] consumible por judge
│   ├── prompts.py               # STAGE1 (nodes) + STAGE2 (edges) prompts
│   ├── annotator.py             # Orquesta Stage 1+2 LLM + Stage 3a structural
│   └── pattern_matcher.py       # 9 productive motifs + 8 breakdowns determinist
└── agents/
    └── react.py                 # Loop ReAct multi-paso via llm_adapter.complete()

scripts/
├── sample_pastvu.py             # Muestrear fotos de PastVu por bbox geográficas
├── test3_no_tools.py            # Test 3 (VLM sin tools) con N runs
├── test_clean_image.py          # Tests sintéticos del módulo corpus.clean_image
├── test_blacklist.py            # Tests sintéticos del módulo corpus.blacklist
├── test_models_smoke.py         # Smoke test text+vision+tools por modelo (pre-pilot)
├── test_adapter_smoke.py        # Smoke test adapter sobre 1 foto (OpenAI + Anthropic)
├── run_react_websearch.py       # Run agente ReAct con todo el stack (legacy E001)
├── run_react_pilot.py           # Run agente sobre corpus piloto v3
├── run_multimodel_pilot.py      # ⭐ Cross-model run con agentic_probe
└── run_annotator.py             # ⭐ CLI annotator process eval

experiments/
├── E001_test3_pastvu/           # legacy: 19 fotos sin tools
├── E002_react_websearch/        # legacy: ReAct con tools inicial
├── E004_attacker_filter/        # atacante GPT-4o → 180→101 sobrevivientes
├── E005_react_pilot/            # 6 fotos × prompt v3 (canónico) + annotated_*.json
├── E006_pastvu_audit/           # dump 282MB + audit metadata
├── E007_sample_diverso/         # 180 fotos balanceadas país×década
├── E008_multimodel/             # 5 modelos × 3 fotos (pre-adapter, DeepSeek vision broken)
├── E009_multimodel/             # 9 modelos × 3 fotos × v3 + agentic_probe.json (post-adapter)
├── E010_iteration_pilot/        # gpt-5.4-mini × 5 fotos con payload_to_model completo + ablation blur
├── E011_text_overlay_detection/ # VLM detector overlay (4 modelos × 30 + Sonnet × 185 + sample270_v2)
├── E012_min_steps/              # ablation min_steps {0, 15, 30} gpt-5.4-mini × 10 fotos
└── E015_attacker_v2/            # atacante GPT-4o sobre las 270 v2 → results.json reconstruido del log
```

```
corpus/                          # ⭐ canónico (gitignored)
├── photos/                      # {cid}_raw.jpg + {cid}_clean_v1.jpg (185 fotos hoy)
└── README.md
```

### Stack y credenciales

- **Python 3.11** + conda env `geodetective`.
- **LLM adapter propio** (`src/geodetective/llm_adapter.py`): rutea modelos OpenAI-compatible (gpt-4o, gpt-4.1, gpt-5, gpt-5.4, gpt-5.4-mini, grok-4.x, Kimi-K2.x, DeepSeek-V3.2) vs Anthropic (claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5) via Foundry.
- **Azure OpenAI Responses API + Bing Grounding** para `web_search` (post-Tavily, helper gpt-4.1-mini, ~$0.03/call).
- **DuckDuckGo via `ddgs`** para `image_search` (post-Tavily, gratis sin API key).
- **Google Maps Platform**: Maps Static API + Street View Static API.
- **Nominatim, OpenHistoricalMap**: free, sin API key.
- **PIL, geopy, httpx, pydantic, imagehash, beautifulsoup4, lxml, zstandard, huggingface_hub, pygeohash**.

Credenciales en `.env` (gitignored):
- `AZURE_INFERENCE_CREDENTIAL`, `AZURE_FOUNDRY_BASE_URL`, `AZURE_MODEL`
- `GOOGLE_MAPS_API_KEY` (con cuota restrictiva: 500/día Static, 200/día Street View)
- (`TAVILY_API_KEY` ya no se usa — migrado a Azure/DDG)

### 12 Tools del agente

| # | Tool | Backend | Free? |
|---|---|---|---|
| 1 | `web_search` | **Azure Responses API + Bing Grounding** (helper gpt-4.1-mini) | Paga (~$0.03/call) |
| 2 | `fetch_url` | httpx + bs4 | ✅ |
| 3 | `fetch_url_with_images` | httpx + bs4 + imagehash | ✅ |
| 4 | `image_search` | **DuckDuckGo via `ddgs`** + imagehash | ✅ |
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

**Piloto del pipeline validado (K=5, ver `research/notes/E004_attacker_filter.md`)**: el pipeline completo (sample → atacker → filtro) corrió end-to-end sobre 180 fotos (K_PER_CELL=5 en sample_diverso.py). 101 sobrevivieron al atacante GPT-4o (56%). Output en `experiments/E004_attacker_filter/results.json` (gitignored). **No es el corpus de producción** — para eso hay que escalar K_PER_CELL (issue #25).

**Pilot E005 — ReAct end-to-end sobre 6 fotos** (`research/notes/E005_react_pilot.md`): exploración inicial con 3 variantes de SYSTEM_PROMPT (v1 mechanical, v2 descriptive, v3 thinking_visible). **v3 quedó como versión canónica** del prompt; v1 y v2 deprecadas (no capturan thinking events necesarios para process eval). Resultados en v3: 1 acierto preciso (Dealey Plaza 0 km), Tomsk perdido (3743 km vs 2 km que había logrado en v1), uso mínimo de tools visuales (1 `static_map` en Basel, 0 `street_view`, 0 `historical_query`). **Hallazgo principal**: incluso con prompt verbalizado, web_search sigue dominante. Reports HTML interactivos en `experiments/E005_react_pilot/report_v3_thinking_visible.html` (canónico) + `report_v1_mechanical.html` / `report_v2_descriptive.html` / `report_compare.html` (históricos exploratorios).

**Diseño de process eval CORRAL adaptado** (`research/synthesis/process_eval_design.md`, mayo 2026): framework para anotar grafo epistemológico H/T/E/J/U/C de las trazas + 7 motifs / 10+1 breakdowns adaptados + diseño del annotator multi-stage (Stage 1+2 LLM judge, Stage 3a Python determinista, Stage 3b LLM judge multimodal para patterns visuales). Process eval es **offline only** (no entra al reward). Implementación pendiente (task #6).

**Mayo 2026 — estado post-E010/E011/E012**:

- **Corpus canónico** en `corpus/photos/`: 185 fotos limpias balanceadas país×década (1890s-1940s). Source-of-truth para evaluación. Gitignored, regenerable con `scripts/download_corpus_photos.py`.
- **LLM adapter funcional** (commit `7e663ca`): OpenAI-compatible + Anthropic via Foundry. 9 modelos probados en E009.
- **E010 — hallazgos cualitativos clave** (gpt-5.4-mini × 5 fotos): first-hypothesis lock-in en 3/5 (Lisboa→Porto, Bogotá→México, Cracovia→Varsovia); queries demasiado descriptivas; tools visuales (street_view, static_map) infrautilizadas; submit prematuro con confidence inflada; verification_checks ficticios.
- **E011 — detector de overlays textuales**: Sonnet sobre 185 fotos → 84/185 (45%) tienen al menos un `archive_overlay` (caption, sello, watermark). Ablation sobre 5 fotos E010: blur mejora drásticamente (Cáucaso -204km), empeora donde el texto era pista real (Volga +116km, Bogotá +14146km), no afecta lock-in semántico (Lisboa). Conclusión: blur necesario pero no suficiente; lock-in semántico es otro problema.
- **E012 — ablation min_steps {0, 15, 30}**: implementado bloqueo `submit_answer` antes de step N. Vimos que forzar más steps revela **bug del scaffold**: con `min_steps≥15` el modelo acumula >50 imágenes en contexto → Azure rechaza. Hay que limpiar contexto.
- **Process eval annotator** (`src/geodetective/judge/`): construido y aplicado a E005 v3. Pendiente correr sobre E009/E010.
- **Paralelismo entre modelos** en E009 (commit `7bdc490`): rate limits por deployment, no agregados → 5 modelos en paralelo × 3 fotos cada uno = hasta 15 calls simultáneas. Speedup ~3-5×.

**Junio 2026 — pivote belief-state en curso (E016, #47)**: el reward principal pasa de distancia puntual a **proper scoring rules sobre distribuciones de creencia** (mezcla vMF geodésica + reward denso por paso = ganancia de información verificada, sin LLM judge). Diseño completo en `research/synthesis/belief_state_redesign.md`. Implementado: scorer (`src/geodetective/eval/belief_scoring.py`) + tests sintéticos (`scripts/test_belief_scoring.py`, 9/9 OK — incluye properness por Monte Carlo y la divergencia log-score vs energy score ante el confiado-equivocado); belief-mode en el scaffold (`react.py`: tool `report_belief` + `evidence_chain` en submit + nudge, todo detrás de `belief_mode=True` — el brazo OFF queda idéntico al canónico; sin scoring en runtime, ground truth no entra al loop; tests en `scripts/test_belief_tool.py`). Budget económico v1 en scaffold (`tool_budget` opt-in, cobro por invocación, report_belief/submit gratis, bloqueo al agotarse). **Smoke tests validados** (gpt-5.4-mini): Estocolmo 1916 → 1.5 km con curva que expone lock-in narrativo en datación (web evidence arregló ubicación y contaminó año); Montevideo 1907 con budget=25 → 0.1 km, geocodes baratos como test discriminante, bloqueo y cierre graceful. 10 fotos pilot seleccionadas (`experiments/E016_belief_pilot/pilot_photos.json`, 1 por bucket × 6 décadas). Pendiente: certificación hindsight de las 10, corridas pilot 3 modelos × N=3 × {on, off}, verificador de claims, viewer mapa de calor.

**Próximos pasos (priorizados)**:
1. **Ejes experimentales documentados**: ver `research/synthesis/experiment_design.md`.
2. **Bug scaffold: clear context >50 imágenes** (bloquea forzar más steps).
3. **Métricas year + calibration**: ya las pedimos pero no las medimos.
4. **Tool review v1**: auditar uso real (sub/sobre-utilización), decidir qué queda/sacar/agregar.
5. **Prompt iteration**: variantes anti-lock-in + verificación obligatoria.
6. **Estratificación por tier de dificultad** (vía atacante GPT-4o) sobre las 185.
7. **Annotator CORRAL sobre E009/E010** (process metrics cross-model).

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
| Hallazgos cualitativos E010 (gpt-5.4-mini × 5 fotos) | `research/notes/E010_iteration_findings.md` |
| Detector text overlays + ablation blur (E011) | `research/notes/E011_text_overlay.md` |
| Ablation min_steps (E012) | `research/notes/E012_min_steps.md` |
| Ejes experimentales canónicos | `research/synthesis/experiment_design.md` |
| Trabajo pendiente con prioridad | [Project v2](https://github.com/users/lucaspecina/projects/6) |
| Operativa de Claude Code | `CLAUDE.md` |
| Idea original (semilla histórica) | `research/notes/genesis-intro.md` |
| Historial de cambios | `CHANGELOG.md` |
