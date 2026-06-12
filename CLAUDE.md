# GeoDetective Envs — Claude Code Configuration

## START HERE — Read these docs first

1. **README.md** — Entry point + navegación.
2. **PROJECT.md** — Estrella polar: visión, LA PREGUNTA, invariantes.
3. **CURRENT_STATE.md** — Qué corre HOY (honesto sobre gaps).
4. **CHANGELOG.md** — Historial.
5. **ARCHITECTURE.md** — Contratos entre módulos + storage-as-canon principle + schemas.

Para roadmap y trabajo pendiente: [Project v2 "GeoDetective Envs Roadmap"](https://github.com/users/lucaspecina/projects/6).

---

## LA PREGUNTA

> **1. ¿Por qué este caso todavía no es una investigación geo-detectivesca real? ¿Qué le falta?**
>
> **2. ¿Por qué un modelo entrenado con RL sobre este environment todavía no aprendería buen juicio investigativo geo-espacial?**

Aplicar al evaluar, diseñar, priorizar, revisar. Detalle completo + presiones evolutivas en `PROJECT.md`.

---

## Comunicación

- **Idioma:** Español, siempre.
- **Tono:** Directo, técnico pero accesible. Sin filler.
- **Aprobación:** Nunca commitear sin "si" explícito (excepción: autoresearch).

---

## Where to find what

| Necesito... | Ir a |
|---|---|
| Visión, principios, invariantes | `PROJECT.md` |
| Qué corre HOY | `CURRENT_STATE.md` |
| Trabajo pendiente / prioridades | [Project v2](https://github.com/users/lucaspecina/projects/6) + `gh issue list` |
| Historial de cambios | `CHANGELOG.md` |
| Idea original (semilla) | `research/notes/genesis-intro.md` |
| Investigación, debates | `research/notes/` |
| Conclusiones consolidadas | `research/synthesis/` |
| Ejemplos canónicos | `research/examples/` |
| Cómo trabajar en este repo | Este archivo |
| Workflow general (ciclo, docs, codex, autoresearch) | `~/.claude/skills/dev-workflow/SKILL.md` |

---

## Project overview

Environment de RL para entrenar agentes geo-investigativos sobre fotos históricas. Provee environment + tools tipadas + reward geodésico. NO entrena policies. Detalle: `PROJECT.md`.

---

## Environment setup

```bash
conda create -n geodetective python=3.11 -y
conda activate geodetective
# pip install -e ".[dev]"   # cuando exista pyproject.toml
```

Variables de entorno (`.env`, gitignored):

```
# Azure Foundry (LLM)
AZURE_INFERENCE_CREDENTIAL=...
AZURE_FOUNDRY_BASE_URL=https://amalia-resource.openai.azure.com/openai/v1
AZURE_MODEL=gpt-5.4

# Google Maps Platform (Static Maps + Street View Static)
GOOGLE_MAPS_API_KEY=...

# Tavily (LEGACY — ya no se usa; web_search→Azure Bing Grounding, image_search→DuckDuckGo)
# TAVILY_API_KEY=...

# Otros (legacy de arcagi3 .env compartido)
ARC_API_KEY=...
```

Modelos confirmados disponibles en Foundry: `gpt-4o`, `gpt-4.1`, `gpt-5`, `gpt-5.4` (todos con visión).

---

## Tech stack (implementado)

- **Python 3.11** + **conda** (env: `geodetective`).
- **OpenAI SDK** (`openai`) — cliente para Foundry. Adapter propio rutea a Azure OpenAI vs Anthropic Foundry endpoint.
- **httpx** — clientes HTTP (Nominatim, Overpass, Google Maps, etc.).
- **Pillow + imagehash** — manipulación de imágenes y hash perceptual `phash` para anti-shortcut.
- **BeautifulSoup4 + lxml** — parsing HTML para `fetch_url`.
- **geopy** — distancia geodésica.
- **ddgs** — DuckDuckGo search SDK (backend de `image_search`).
- **zstandard** — descompresión del dump PastVu.
- **huggingface_hub** — descarga del dump PastVu.
- **pygeohash** — buckets espaciales del sampler.
- **pydantic** — schemas (instalado, uso minimal por ahora).
- **`.env`**: parseo manual (no usamos `python-dotenv`).

Pendiente / planeado:
- **LangGraph** — NO se usa por ahora (decisión: plain Python suficiente para v1, evaluar Verifiers/LangGraph en Fase 6).
- **pytest + ruff** — sin tests todavía.
- **`pyproject.toml`** — pendiente, todas las deps en pip por ahora.

Removed:
- **tavily-python** — migrado: `web_search`→Azure Bing Grounding, `image_search`→DuckDuckGo (commits `444ebe9`, `7570aa3`).

---

## Tools del agente (12 implementadas)

Ver `src/geodetective/tools/` y `src/geodetective/agents/react.py`.

| # | Tool | Backend |
|---|---|---|
| 1 | `web_search` | **Azure OpenAI Responses API + Bing Grounding** (helper gpt-4.1-mini) |
| 2 | `fetch_url` | httpx + bs4 |
| 3 | `fetch_url_with_images` | httpx + bs4 + imagehash |
| 4 | `image_search` (con hash flag) | **DuckDuckGo via `ddgs`** (gratis, sin API key) |
| 5 | `geocode` / `reverse_geocode` | Nominatim OSM |
| 6 | `historical_query` ⭐ | OpenHistoricalMap Overpass (CC0) |
| 7 | `crop_image` / `crop_image_relative` | PIL local |
| 8 | `static_map` | Google Maps Static (roadmap/satellite/terrain/hybrid) |
| 9 | `street_view` | Google Street View Static + metadata |
| 10 | `submit_answer` | terminal |

---

## Project structure

```
.
├── README.md, PROJECT.md, CLAUDE.md, CURRENT_STATE.md, CHANGELOG.md, ARCHITECTURE.md, AUTORESEARCH.md
├── .env                            # gitignored: AZURE_*, GOOGLE_MAPS_API_KEY
├── corpus/                         # ⭐ canónico: fotos del benchmark (gitignored)
│   ├── photos/                     # {cid}_raw.jpg + {cid}_clean_v{N}.jpg (185 fotos hoy)
│   └── README.md                   # cómo poblar, sincronizar, regenerar
├── src/geodetective/
│   ├── corpus/                     # pipeline de filtrado (#21)
│   │   ├── clean_image.py          # Paso 0: strip EXIF + crop watermark + RGBA→RGB (#22)
│   │   └── blacklist.py            # blacklist runtime per-photo (#23)
│   ├── llm_adapter.py              # rutea OpenAI-compatible vs Anthropic Foundry endpoint
│   ├── eval/
│   │   ├── metrics.py              # métricas post-hoc (distance/year/calibration)
│   │   └── belief_scoring.py       # ⭐ proper scoring rules geodésicas (belief-state, E016 #47)
│   ├── judge/                      # annotator CORRAL-adapted (process eval)
│   ├── tools/                      # 12 tools del agente
│   └── agents/
│       └── react.py                # ReAct loop multi-paso (max_steps + min_steps + thinking)
├── scripts/
│   ├── download_pastvu_dump.py     # baja jsonl.zst 282MB de HF
│   ├── download_corpus_photos.py   # bajada paralela + clean → corpus/photos/
│   ├── sample_diverso.py           # sampler balanceado país×década (#17)
│   ├── audit_pastvu_metadata.py    # audit del dump (#3)
│   ├── run_attacker_filter.py      # atacante GPT-4o sin tools (#24)
│   ├── run_multimodel_pilot.py     # E008/E009 cross-model con paralelismo entre modelos
│   ├── run_e010_iteration.py       # single-model debug con payload_to_model + min_steps
│   ├── run_e012_min_steps.py       # ablation min_steps
│   ├── detect_text_overlays.py     # VLM detector + blur archive_overlay (E011)
│   ├── run_belief_smoke.py         # smoke belief-mode + scoring post-hoc (E016 #47)
│   ├── build_belief_viewer.py      # ⭐ viewer trayectorias belief: timeline + mapa por step
│   ├── build_iteration_viewer.py   # HTML viewer step-by-step de trazas
│   ├── build_overlay_comparison.py # comparativo N modelos detector
│   ├── build_corpus_viewer.py      # grid HTML del corpus
│   ├── build_multimodel_report.py  # report cross-model (E008/E009)
│   └── ...
├── experiments/                    # gitignored excepto JSONs canónicos (ver .gitignore)
│   ├── E004_attacker_filter/       # atacante GPT-4o (#24) — 180→101 sobrevivientes
│   ├── E005_react_pilot/           # piloto ReAct end-to-end + annotated v3
│   ├── E006_pastvu_audit/          # dump 282MB + results.json del audit (#3)
│   ├── E007_sample_diverso/        # 180 fotos balanceadas (#17) candidates.json
│   ├── E008_multimodel/            # primer smoke cross-model
│   ├── E009_multimodel/            # cross-model post-adapter (9 modelos × 3 fotos)
│   ├── E010_iteration_pilot/       # single-model debug (gpt-5.4-mini × 5 fotos) + ablation blur
│   ├── E011_text_overlay_detection # detector overlays (gpt-5.4/gpt-4o/claude-sonnet/opus + 185 con Sonnet)
│   └── E012_min_steps/             # ablation min_steps {0, 15, 30}
├── research/
│   ├── notes/                      # working docs, deep dives, audits, resultados por experimento
│   ├── synthesis/                  # conclusiones canon (related_work, viability, findings_so_far)
│   ├── examples/                   # ejemplos canónicos worked-out
│   └── archive/                    # superseded
└── .claude/
    └── skills/
        ├── test/                   # /test — correr tests
        └── status/                 # /status — resumen rápido del estado
```

---

## Issue tracking

- **Source of truth**: [Project v2 "GeoDetective Envs Roadmap"](https://github.com/users/lucaspecina/projects/6).
- **Modelo**: Epic (meta cerrable) → sub-issue(s) → Issue concreta (1 PR). Sub-issues vía API nativa de GitHub (no "Part of #N" en body).
- **Campos custom obligatorios**: `Status` (Todo / In Progress / Done), `Worktree` (`main`, `none`, +nombres de worktrees activos).
- **Labels acotados**: `bug`, `blocked`, `parked`, `research`, `design`. NO usar `area:*` ni `prio:*`.
- **Branch**: `issue/NNN-slug`. PR body empieza con `Closes #NNN`. Commits: `Refs #NNN <descripción>`.
- **Al empezar trabajo**: mover Status a `In Progress` ANTES de codear (otras sesiones leen el board).
- **Project v2 IDs** (para queries via GraphQL): ver "Project v2 reference" abajo.

Detalle del workflow general: `~/.claude/skills/dev-workflow/issue-tracking.md`.

### Project v2 reference

- **Project ID**: `PVT_kwHOAiGijs4BXAnu` (number 6, owner `lucaspecina`)
- **Status field**: `PVTSSF_lAHOAiGijs4BXAnuzhSQfdo`
  - Todo: `f75ad846` · In Progress: `47fc9ee4` · Done: `98236657`
- **Worktree field**: `PVTSSF_lAHOAiGijs4BXAnuzhSQfnA`
  - main: `203e9ca9` · none: `230901d3`

---

## Commit workflow — MANDATORIO

```
1. ANALYZE   — leer código relevante PRIMERO
2. STRATEGY  — para tareas no triviales: proponer approach (consultar Codex si aplica)
3. IMPLEMENT — código + tests
4. VALIDATE  — pytest + ruff (cuando exista código)
5. REVIEW    — Codex review (mandatorio si MCP disponible)
6. PRESENT   — explicar en español, esperar "si"
7. DOCS      — actualizar docs afectados (ver tabla abajo)
8. COMMIT    — con Co-Authored-By + Refs/Closes #N
```

Excepción: autoresearch saltea PRESENT y commitea autónomamente en branch dedicada.

---

## Document maintenance — trigger table

Después de cada cambio, escanear esta tabla. Si alguna fila aplica, actualizar.

| Qué cambió | Documentos a actualizar |
|---|---|
| Empecé a trabajar en una issue | Mover Status → `In Progress`. |
| Completé un paso significativo | Comentar en la issue. |
| Cerré una issue | Status → `Done` (auto via PR merge). `CHANGELOG.md` con ref `#N`. |
| Cambió qué corre / qué se puede hacer | `CURRENT_STATE.md`. |
| Agregué/saqué archivo o módulo | `CLAUDE.md` project structure. `CURRENT_STATE.md`. |
| Renombré/saqué función o módulo | Buscar refs en TODOS los docs/skills/scripts → actualizar o eliminar. |
| Agregué dependencia | `pyproject.toml` + `CLAUDE.md` tech stack. |
| Cambió convención | `CLAUDE.md`. |
| Cambió scope o visión | `PROJECT.md` primero, propagar a `CLAUDE.md` y CURRENT_STATE. |
| Investigación profunda | `research/notes/` + ref desde issue. |
| Conclusión consolidada | `research/synthesis/`. |
| Conclusión sube a decisión de proyecto | `PROJECT.md`. Mover notas a archive si corresponde. |

Detalle completo: `~/.claude/skills/dev-workflow/doc-maintenance.md`.

---

## Cleanup y mantenimiento

- "Actualizar" incluye TODO el ecosistema: docs, skills (`.claude/skills/`), memorias, scripts, configs.
- Si un cambio deja código/tests/scripts obsoletos → **ELIMINAR**. Git tiene historia. Nada de "por las dudas".
- Si un doc referencia un archivo/función que ya no existe → fix la referencia.
- Después de milestones: cleanup pass (refs viejas, dead code, archivos huérfanos).

---

## Autoresearch

- Config en `AUTORESEARCH.md` (status ON/OFF + run config).
- Branch dedicada: `autoresearch/<topic>-<date>` desde base explícita.
- Commits + pushes en la branch de autoresearch sin frenar.
- Stop conditions obligatorias.
- NO actualizar docs globales (PROJECT, CURRENT_STATE) en autoresearch — eso se hace al merge.
- Detalle: `~/.claude/skills/dev-workflow/autoresearch.md`.

---

## Quality assurance — niveles

- **Nivel 1 — pre-commit**: `pytest tests/<file>::<test> -v` + `ruff check`. Solo del código tocado.
- **Nivel 2 — system validation**: correr el environment end-to-end con foto real, ver trayectoria del agente, evaluar que efectivamente investigó.
- **Nivel 3 — external validation**: una policy entrenada con este environment, ¿geolocaliza mejor fotos históricas held-out vs misma policy sin entrenar?

Detalle: `~/.claude/skills/dev-workflow/quality-levels.md`.

### Tests — reglas

- Solo correr tests DESPUÉS de cambiar código.
- NUNCA correr la suite completa salvo pedido explícito del usuario.
- Si fallan imports: arreglar el import, no re-correr.
- Ante duda: NO correr, preguntar.

---

## Code conventions (planeadas)

- Type hints en funciones públicas.
- `__all__` en cada `__init__.py`.
- Tests mirror src: `src/geodetective/tools/X.py` → `tests/tools/test_X.py`.
- Imports: stdlib → third-party → local, separados por línea en blanco.
- Comunicar con el usuario en **español**.

---

## Codex collaboration

- **Mandatorio** code review post-implementación si MCP disponible.
- **Recomendado** estrategia para tareas no triviales.
- **Skip** para doc-only o trivialidades.
- **Claude lidera, Codex asesora.** Formar opinión propia ANTES de consultar.
- Detalle: `~/.claude/skills/codex-collab/SKILL.md`.

---

## Git conventions

- **Nunca** push sin aprobación explícita del user (excepción: autoresearch).
- Branch: `issue/NNN-slug` para trabajo concreto.
- Commits: `Refs #NNN <descripción>` (no cierra) o `Closes #NNN` (cierra al merge).
- PR: `Closes #NNN` en la primera línea del body.
- Squash merge preferido.
- Sesiones paralelas: una worktree por sesión (`claude --worktree <name>`).
