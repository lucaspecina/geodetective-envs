# Research

Working docs y conclusiones del proyecto. Espacio para investigar antes de decidir.

## Estructura

| Dir | Qué va |
|---|---|
| `notes/` | Working docs, debates, exploración. Efímero, puede borrarse o moverse a archive. |
| `synthesis/` | Conclusiones consolidadas. Canon. Perdura. |
| `examples/` | Ejemplos canónicos worked-out (cómo se ve un caso bien resuelto). |
| `archive/` | Superseded — se mantienen por contexto histórico, no como referencia activa. |

## Flujo natural (izquierda → derecha)

```
notes/ (exploración)  →  synthesis/ (decantación)  →  PROJECT.md (decisión)
                                                ↘  GitHub Issue (trabajo concreto)
```

Una idea entra por `notes/`. Si se decanta y vale la pena consolidar → pasa a `synthesis/`. Cuando hay unidad PR-sized con criterio de cierre claro → recién ahí se vuelve issue.

## Índice

### `notes/`
- `genesis-intro.md` — semilla del proyecto, idea original con motivación, datasets, infraestructura, related work.
- `geobenchx_deep_dive.md` — análisis del repo Solirinai/GeoBenchX. Veredicto: apalancar parcialmente (4 archivos como base, no clonar entero).
- `osm_mcp_deep_dive.md` — análisis del repo jagan-shanmugam/open-streetmap-mcp. Veredicto: replicar el patrón FastMCP + lifespan + tools tipadas, no apalancar como dependencia.
- `pastvu_deep_dive.md` — dataset principal. Veredicto: apalancar con asterisco (solo training, nunca held-out; requiere filtrado adversarial agresivo + balanceo multi-fuente por sesgo a Rusia).
- `leverage_landscape.md` — Tier 2-5 y trabajos recientes (últimos 6-12 meses). Cubre GeoVista, GeoAgent, Pigeon, GeoRC, Verifiers, TRL, smolagents, StreetLearn, datasets secundarios, GeoBrowse, SpotAgent, GEO-Detective, GeoChain.
- `E001_test3_no_tools_results.md` — Test 3 (VLM sin tools) sobre 17 fotos PastVu, N=3 runs. Filtro v2 simplificado (source + VLM-no-tools). 53% sobrevive. Sweet spot = cotidiano sin landmark.
- `E002_react_websearch_first_run.md` — Primer ReAct + web_search en #1748874 (SP barrio). Mejora 300x: 2573 km → 8.5 km. Concepto del benchmark validado.

### `synthesis/`
- `related_work_decisions.md` — canon post-crítica Codex sobre qué apalancar / replicar / descartar. Si choca con un note, este gana.
- `viability_assessment.md` — evaluación técnica de viabilidad. 9 bloqueadores con veredicts. Conclusión: viable, pero stack primario debe ser open (Google Maps = opcional con user key + non-training default por TOS). Anti-shortcut filtering reconceptualizado como best-effort tiered, no resistencia absoluta.
- `validation_plan.md` — plan de validación paso a paso, 6 fases con gates falsables. Estimación: 12-15 semanas hasta v1.

### `examples/`
*(vacío hasta que haya ejemplos canónicos)*

### `archive/`
*(vacío)*
