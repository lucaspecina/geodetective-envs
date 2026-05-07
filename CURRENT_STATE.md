# GeoDetective Envs — Estado Actual

> **Mayo 2026**: en validación de viabilidad técnica. Ya hay primer prototipo end-to-end del agente con tools sobre fotos PastVu. El proyecto pivotó a **benchmark primario** (env como deuda futura) — ver disclaimer en `PROJECT.md`.
>
> Para visión y norte: `PROJECT.md` · Para roadmap: [Project v2](https://github.com/users/lucaspecina/projects/6) · Para historial: `CHANGELOG.md`.

---

## 1. Qué corre HOY

### Código operacional

```
src/geodetective/
├── tools/
│   └── web_search.py          # Tavily backend + filtros anti-shortcut
└── agents/
    └── react.py               # Loop ReAct multi-paso con tool calling
```

```
scripts/
├── sample_pastvu.py           # Muestrear fotos de PastVu por bbox geográficas
├── test3_no_tools.py          # Test 3 (VLM sin tools) con N runs
└── run_react_websearch.py     # Run agente ReAct + web_search
```

```
experiments/
├── E001_test3_pastvu/         # 19 candidatos, 17 testeados, results.json
└── E002_react_websearch/      # 1 foto testeada (proof of concept)
```

### Stack

- **Python 3.11** + conda env `geodetective`.
- **OpenAI SDK** vía Azure Foundry (`https://amalia-resource.openai.azure.com/openai/v1`).
- **Modelos disponibles**: gpt-4o, gpt-4.1, gpt-5, gpt-5.4 (visión OK).
- **Tavily** para web search (1000 calls/mes free tier).
- **PIL, geopy, httpx, pydantic** para utilidades.

### Capacidades validadas

1. ✅ **Sample de fotos PastVu** por API (bbox geográficas, mix de zonas).
2. ✅ **Test 3 (VLM sin tools)** con N runs por foto, métricas de distancia + año.
3. ✅ **Filtro adversarial v2** (source blacklist + dist_min<10km AND conf≥media) — sample 17 fotos, 53% sobrevive.
4. ✅ **ReAct loop con tool calling** sobre Foundry (gpt-5.4).
5. ✅ **Web search filtrada** (Tavily + blacklist de dominios shortcut).
6. ✅ **Agente investigativo end-to-end**: sobre 1 foto sobreviviente, cerró 2573 km → 8.5 km de distancia (300x mejor que sin tools).

### Lo que NO corre todavía

- ❌ Tools adicionales: geocoding (Nominatim), places search (Overpass), OpenHistoricalMap, Static Maps, Street View, OCR, image manipulation.
- ❌ Reward / scoring formal.
- ❌ Eval suite con baselines.
- ❌ Filtrado adversarial estratificado en sample grande.
- ❌ Tests automáticos (pytest).
- ❌ `pyproject.toml` con deps formal.
- ❌ Rúbrica investigativa formal.
- ❌ Decisión Verifiers vs custom (postpuesta a Fase 6).

---

## 2. Cómo usar el sistema hoy

### Setup

```bash
cd geodetective-envs
conda activate geodetective  # Python 3.11
# .env tiene: AZURE_INFERENCE_CREDENTIAL, AZURE_FOUNDRY_BASE_URL, AZURE_MODEL=gpt-5.4, TAVILY_API_KEY
```

### Samplear fotos

```bash
python scripts/sample_pastvu.py
# Genera: experiments/E001_test3_pastvu/candidates.json
```

### Correr Test 3 (sin tools) en N runs

```bash
python scripts/test3_no_tools.py
# Genera: experiments/E001_test3_pastvu/results.json
# Tabla resumen en stdout
```

### Correr ReAct con web_search sobre fotos específicas

```bash
python scripts/run_react_websearch.py 1748874  # cid de foto
# O sin args: usa default (5 fotos sobrevivientes).
# Genera: experiments/E002_react_websearch/results.json
```

---

## 3. Qué se está construyendo

**Foco inmediato**: validación incremental por fases. Ver `research/synthesis/validation_plan.md` para detalle.

- **Fase 0** ✅ — concepto manual (E001 + E002).
- **Fase 1** ⏳ — datos + cobertura (issues #3, #4, #5).
- **Fase 2** ⏳ — más tools (geocode, OHM, places, etc.).
- **Fase 3-6** — anti-shortcut estratificado, loop con rúbrica, reward, eval suite.

**Próximo paso lógico**: correr ReAct + web_search en las **otras 4 fotos sobrevivientes** del E001 para confirmar el patrón en más casos.

---

## 4. Donde mirar para qué

| Si querés... | Andá a |
|---|---|
| Por qué existe el proyecto, invariantes | `PROJECT.md` |
| Plan paso a paso de validación | `research/synthesis/validation_plan.md` |
| Decisiones canónicas post-crítica Codex | `research/synthesis/related_work_decisions.md` |
| Análisis de viabilidad técnica | `research/synthesis/viability_assessment.md` |
| Resultados E001 (test sin tools) | `research/notes/E001_test3_no_tools_results.md` |
| Resultados E002 (ReAct + web search) | `research/notes/E002_react_websearch_first_run.md` |
| Trabajo pendiente con prioridad | [Project v2](https://github.com/users/lucaspecina/projects/6) |
| Operativa de Claude Code | `CLAUDE.md` |
| Idea original (semilla histórica) | `research/notes/genesis-intro.md` |
| Historial de cambios | `CHANGELOG.md` |
