---
name: test
description: Run tests for the GeoDetective Envs project. Use when the user asks to test, validate, or run pytest. Filters by argument when provided.
---

# /test — Run project tests

Corre los tests del proyecto. Acepta argumentos para filtrar.

## Estado actual

**No hay tests automáticos todavía** (sin pyproject.toml, sin `tests/`, sin pytest configurado). La validación actual se hace via:

1. **Test de tools en aislamiento** — scripts ad-hoc en `scripts/` que prueban cada tool.
2. **Experimentos integrales** — corridas del agente sobre fotos del corpus con métricas (ver `experiments/`).
3. **Verificación manual de resultados** — los results.json se inspeccionan a mano.

## Para correr el experimento principal (ReAct con stack completo)

```bash
conda activate geodetective

# Una foto:
python scripts/run_react_websearch.py 1748874

# N=3 runs sobre default 5 fotos:
N_RUNS=3 python scripts/run_react_websearch.py
```

## Para correr el baseline (sin tools)

```bash
N_RUNS=3 python scripts/test3_no_tools.py
```

## Para sample nuevo de PastVu

```bash
python scripts/sample_pastvu.py
```

## Reglas

- **Solo después de cambiar código.** No como ritual.
- **Cuidado con Tavily** (1000 calls/mes free). Cada run de ReAct full-tools usa ~10 calls.
- En duda: NO correr, preguntar.

## Cuando exista pytest

```bash
conda activate geodetective && pytest $ARGUMENTS -v
```

Linter (cuando se configure):

```bash
ruff check src/ tests/
```
