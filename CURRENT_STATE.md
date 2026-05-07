# GeoDetective Envs — Estado Actual

> **Hoy no corre nada todavía.** El proyecto está en bootstrap (mayo 2026): docs y estructura armadas, código por venir.
>
> Para visión y norte: `PROJECT.md` · Para roadmap: [Project v2](https://github.com/users/lucaspecina/projects/6) · Para historial: `CHANGELOG.md`.

---

## 1. Qué corre HOY

**Nada ejecutable todavía.** Lo que existe:

- Set de docs raíz (`README.md`, `PROJECT.md`, `CLAUDE.md`, `CURRENT_STATE.md`, `CHANGELOG.md`, `AUTORESEARCH.md`).
- Estructura de directorios (`research/`, `experiments/`, `.claude/skills/`).
- Project v2 en GitHub con `Status` + `Worktree` configurados.
- Skills mínimas de Claude Code (`/test`, `/status`).
- Memoria del proyecto inicializada.
- Documento semilla con la idea original en `research/notes/genesis-intro.md`.

No hay todavía:

- `pyproject.toml` ni dependencias instalables.
- Código en `src/`.
- Tests.
- Dataset descargado o filtrado.
- Tools implementadas.
- Loop ReAct funcionando.

---

## 2. Cómo usar el sistema hoy

No hay sistema runneable todavía. El uso actual es **navegacional**:

```bash
# clonar repo
git clone https://github.com/lucaspecina/geodetective-envs.git
cd geodetective-envs

# leer la visión
$EDITOR PROJECT.md

# ver qué hay pendiente
gh issue list
gh project view 6 --owner lucaspecina --web
```

---

## 3. Qué se está construyendo

**Foco inmediato (próximas issues, sujeto a priorización en Project v2):**

1. Setup de stack Python (`pyproject.toml` con conda env `geodetective`, dependencias core).
2. Exploración inicial del dataset PastVu (descargar dump de Hugging Face `nyuuzyou/pastvu`, inspeccionar formato webdataset, evaluar tamaño y splits).
3. Spike de related work: replicar baseline de GeoBenchX local para tener el esqueleto ReAct funcionando.
4. Primer prototipo de tools mínimas envueltas como functions Python (Static Maps, Street View Static, web search).

**Fuera de scope inmediato (futuro):**

- Filtrado adversarial completo (los 3 tests anti-contaminación) → v1.5.
- Tool de archivos históricos custom → v1.5.
- Entrenamiento RL real → v2.

Para detalle del roadmap: `PROJECT.md` sección "Roadmap conceptual" + Project v2.

---

## 4. Donde mirar para qué

| Si querés... | Andá a |
|---|---|
| Por qué existe el proyecto, invariantes | `PROJECT.md` |
| Trabajo pendiente con prioridad | [Project v2](https://github.com/users/lucaspecina/projects/6) |
| Operativa de Claude Code | `CLAUDE.md` |
| Idea original (semilla histórica) | `research/notes/genesis-intro.md` |
| Análisis de related work cuando se haga | `research/synthesis/` |
| Historial de cambios | `CHANGELOG.md` |
