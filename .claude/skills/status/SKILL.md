---
name: status
description: Quick project status overview for GeoDetective Envs. Reads Project v2 board, recent commits, and open issues. Use when the user asks 'qué hay', 'status', 'dónde estamos'.
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

5. Resumir al usuario en español:
   - Qué está `In Progress` y en qué worktree.
   - Qué hay top en `Todo`.
   - Últimos cambios.
   - Sugerencias de próximos pasos (1-3 opciones).
