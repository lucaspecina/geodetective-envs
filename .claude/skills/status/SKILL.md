---
name: status
description: Quick project status overview for GeoDetective Envs. Reads Project v2 board, recent commits, recent experiments, and stack capabilities. Use when the user asks 'qué hay', 'status', 'dónde estamos'.
---

# /status — Project status overview

Resumen rápido de dónde está el proyecto.

## Pasos

1. Leer estado del Project v2 (issues por Status):

```bash
gh project item-list 6 --owner lucaspecina --format json --limit 50 \
  | jq -r '.items[] | "[\(.status // "—")] #\(.content.number // "?") \(.content.title // .title)"' \
  | sort
```

2. Últimos 5 commits:

```bash
git log --oneline -5
```

3. Issues abiertas:

```bash
gh issue list --state open --limit 20
```

4. Branch actual + estado git:

```bash
git status -sb
```

5. Experimentos disponibles:

```bash
ls experiments/ 2>/dev/null
```

6. Resumir al usuario en español:
   - Qué está `In Progress` y en qué worktree.
   - Qué hay top en `Todo`.
   - Últimos cambios (commits + experimentos).
   - Capacidades actuales (tools del agente, qué corre HOY) — apuntar a `CURRENT_STATE.md`.
   - Sugerencias de próximos pasos (1-3 opciones).

## Contexto: capacidades actuales

A 2026-05-07 el proyecto tiene:
- **11 tools del agente** implementadas (web_search, fetch_url + variants, image_search, geocode, OHM, crop, static_map, street_view, submit_answer).
- **ReAct loop** funcional con OpenAI tool calling sobre Foundry (gpt-5.4).
- **Anti-shortcut**: domain blacklist + hash perceptual flag.
- **3 experimentos**: E001 (sin tools, 17 fotos), E002 (web_search inicial), E003 (stack completo, 12 tools).
- **Concepto del benchmark VALIDADO** end-to-end (mejora 300x en sweet spot del corpus).

Detalle exhaustivo: `CURRENT_STATE.md`.
