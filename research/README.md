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

### `synthesis/`
- `related_work_decisions.md` — canon post-crítica Codex sobre qué apalancar / replicar / descartar. Si choca con un note, este gana.
- `viability_assessment.md` — evaluación técnica de viabilidad. 9 bloqueadores con veredicts. Conclusión: viable, pero stack primario debe ser open (Google Maps = opcional con user key + non-training default por TOS). Anti-shortcut filtering reconceptualizado como best-effort tiered, no resistencia absoluta.

### `examples/`
*(vacío hasta que haya ejemplos canónicos)*

### `archive/`
*(vacío)*
