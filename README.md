# GeoDetective Envs

Environment de RL para entrenar y evaluar agentes geo-investigativos sobre fotografías —especialmente históricas— que descubren dónde fueron tomadas usando tools (Maps, Street View, web, archivos históricos) en un loop ReAct.

GeoDetective Envs **provee el environment + los rewards**. NO entrena policies — eso lo hace otro sistema (RL framework + agente).

## Estado del proyecto

| Versión | Paradigma | Estado |
|---|---|---|
| **v0** | Bootstrap + diseño inicial | **En curso (mayo 2026)**. No corre nada todavía. |
| v1 | MVP environment funcional: dataset PastVu filtrado + tools mínimas (Static Maps, Street View, web search) + reward geodésico + loop ReAct. | Diseño. |
| v1.5 | Filtrado adversarial completo del corpus + tool de archivos históricos. | Futuro. |
| v2 | Entrenamiento RL real con Verifiers/TRL sobre el environment. | Futuro lejano. |

## Cómo navegar este repo

| Si querés... | Andá a |
|---|---|
| Visión, LA PREGUNTA, invariantes | `PROJECT.md` |
| Qué corre HOY (estado real) | `CURRENT_STATE.md` |
| Operativa de Claude Code en este repo | `CLAUDE.md` |
| Trabajo pendiente / roadmap | [Project v2 "GeoDetective Envs Roadmap"](https://github.com/users/lucaspecina/projects/6) · `gh issue list` |
| Investigación, debates, related work | `research/README.md` |
| Historial de cambios | `CHANGELOG.md` |

## Setup mínimo

```bash
conda create -n geodetective python=3.11 -y && conda activate geodetective
# pip install -e ".[dev]"  # cuando exista pyproject.toml
```

Variables de entorno (`.env` en root, todavía no creado):

```
GOOGLE_MAPS_API_KEY=...
TAVILY_API_KEY=...        # o BRAVE_SEARCH_API_KEY / SERPER_API_KEY
AZURE_FOUNDRY_BASE_URL=...
AZURE_INFERENCE_CREDENTIAL=...
```

## Estructura

```
research/        # análisis, debates, ejemplos, archivo
experiments/     # gitignored: experimentos con manifest.yaml
.claude/skills/  # skills del proyecto (/test, /status)
```

Más detalle de qué corre y cómo: `CURRENT_STATE.md`.
