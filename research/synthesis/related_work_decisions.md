# Related Work — Decisiones canónicas post-crítica

> **NOTA POSTERIOR (2026-05-07)**: este doc se escribió con framing "env de training" (post-crítica Codex sobre el sesgo a training recipes). El proyecto pivotó a **benchmark primario, env como deuda futura** (ver disclaimer en `PROJECT.md`). Implicaciones para este doc:
> - La sección "Contrato del environment — decisión abierta crítica" se vuelve **menos urgente** (el benchmark no necesita exponer contrato Gymnasium/OpenEnv; lo expone como deuda futura).
> - "NO son problema nuestro (relevantes para downstream users que entrenen)" sigue válida pero el público downstream cambia: ahora son **gente que evalúa** modelos, no que entrena.
> - Los proyectos que aportan a diseño de tools / reward / corpus / anti-shortcut **siguen siendo relevantes** sin cambio.
>
> El resto del documento sigue válido para guiar diseño del benchmark en su versión actual y deja preparado el terreno para la versión env futura.
>
> ---
>
> **Frame original**: construimos **environment + tools + reward signal + corpus filtrado**. NO entrenamos policies. NO trabajamos en mejorar a un agente que resuelva. Las decisiones de "qué apalancar" son exclusivamente sobre piezas que aporten al **diseño del environment**, no a entrenar agentes.
>
> Si una pieza es útil para entrenar (ej: receta GeoVista), la nombramos como referencia FYI para downstream users, pero NO consume tiempo de research nuestro.
>
> Este doc consolida decisiones post-crítica Codex (2026-05-07). Si choca con un note (`research/notes/*_deep_dive.md`, `leverage_landscape.md`), **este gana**.

---

## Resumen ejecutivo

### Aportan a diseño del environment (problema nuestro)

| Categoría | Proyectos / fuentes |
|---|---|
| **Patrón arquitectónico de tools** | OSM-MCP (jagan-shanmugam), Mapbox MCP oficial, Google Maps MCP (npm) |
| **Tools concretas a apalancar** | OpenHistoricalMap (Overpass temporal, CC0) ⭐ — Tier 1.5 |
| **Diseño de tool específica (Street View)** | Pigeon (Stanford): patrón heading/pitch/iters |
| **Diseño del reward signal** | GeoBrowse (penalizar tool spam), GeoRC (medir proceso), GeoAgent (verifier consistencia → inspiración para penalizadores) |
| **Datos primarios del corpus** | PastVu (gated por audit empírico), Smapshot (gated por verificar tamaño y license) |
| **Datos complementarios** | Library of Congress, OldNYC, OldSF, Historypin, Bundesarchiv, Europeana |
| **Pendientes de investigar (deuda)** | IIIF/navPlace, MapWarper, NYPL Map Warper, OldInsuranceMaps/Sanborn, USGS/NOAA aerials |

### NO son problema nuestro (relevantes para downstream users que entrenen con nuestro env)

| Categoría | Proyectos | Por qué los listamos |
|---|---|---|
| Recetas de training | GeoVista (SFT cold-start + GRPO), SpotAgent (multi-agent cold-start), GeoChain (pre-training CoT) | Para que docs futuros puedan apuntar usuarios al ecosistema. **NO consumen research nuestro.** |
| Frameworks de RL | Verifiers (Prime Intellect), TRL (HF), smolagents (HF) | Idem. Lo único nuestro asociado: que nuestro env exponga un **contrato consumible** por estos frameworks (ver §Contrato del environment). |

### Descartados

StreetLearn (DeepMind) · Autonomous GIS / LLM-Geo / LLM-Find · GeoBenchX como dependencia importable · `ccmdi/geobench` y similares (excepto como baselines de eval).

### Decisión arquitectónica abierta más importante

**Contrato del environment**: ¿OpenEnv (Meta)? ¿Gymnasium-style extendido? ¿API propia? Define cómo cualquier framework externo se conecta. Necesita spike (ver §Spikes).

---

## Reward signal — separación crítica

**Tensión**: `PROJECT.md` invariante 2 dice "reward continuo y geodésico" como no-negociable. La crítica del repaso señaló que solo geodésico entrena shortcuts. Hay que reconciliar.

**Resolución canónica** (refleja en `PROJECT.md` invariante 2):

```
Reward principal optimizable     = distancia geodésica (continuo, en km)
Penalizadores de proceso         = aditivos a la señal principal (no optimizables aislados)
LLM judge / rúbrica investigativa = SOLO eval offline; NO entra al training loop
```

Razón estructural: meter al judge como señal optimizable expone al sistema a **reward hacking** — el agente aprende a satisfacer al judge, no a investigar. El environment NO ofrece esa puerta.

**Componentes del reward que el env expone**:

| Componente | Qué mide | Rol | Inspiración |
|---|---|---|---|
| Geodesic distance | km al ground truth | Principal optimizable. Continuo. | GeoGuessr, GeoVista hierarchical reward |
| Tool spam penalty | calls > threshold sin progreso | Penalizador (resta a geodesic) | GeoBrowse: "coherent plans > more tool calls" |
| Tool error penalty | calls fallidos por mal uso | Penalizador (resta a geodesic) | Discrimina hipótesis genuinas de spam |
| Coherence penalty (opcional v2) | alineación hipótesis declaradas vs tools llamadas | Penalizador suave | GeoAgent verifier de consistencia |
| **Trajectory rubric (eval, no train)** | calidad investigativa de la trayectoria completa | **Solo eval offline** | GeoRC: VLMs alucinan razonamiento — necesidad de medir proceso |

Detalles concretos (thresholds, pesos, fórmula exacta) son trabajo de issue posterior.

---

## Anti-shortcut filtering — alcance

**Decisión canónica** (refleja en `PROJECT.md` invariante 1):

> El filtrado adversarial aplica al **corpus completo**, training incluido. NO solo al held-out.

Razón: si una foto está indexada por Yandex/Google y/o estaba en pretraining del modelo base, entrenar con ella **enseña memorización en lugar de investigación**, contaminando la policy aunque el held-out sea limpio.

**Implicación práctica**: si el filtrado deja 20-40% utilizable de PastVu, ese es el techo del corpus de training también. Cambia volúmenes de planificación.

**Tres tests adversariales** (por foto, antes de aceptarla al corpus, en orden de costo creciente):
1. Reverse image search (Google Lens, Yandex, TinEye) **no la resuelve**.
2. Descripción VLM de la foto **no la encuentra googleando**.
3. VLMs grandes (GPT-4o, Claude, Gemini) **no la ubican sin tools**.

Implementación de los 3 tests es deuda concreta — issue separada cuando arranque corpus pipeline.

**Filtros runtime adicionales** (durante uso del env, no durante curación):
- Bloquear dominios de origen del dataset (pastvu.com, smapshot.ch, etc.) en web search.
- Hash perceptual (`imagehash`) descarta resultados de búsqueda que contengan la imagen objetivo.

---

## Tools del environment — agrupación tentativa

Cada tool requiere diseño concreto en issue posterior. Lista tentativa para tener panorama:

| Categoría | Tool tentativa | Backend principal | Backend alternativo / complemento |
|---|---|---|---|
| Mapas estáticos | `static_map(coords, zoom, type)` | Google Maps Static Maps API | Mapbox Static / OSM raster tiles |
| Street View | `street_view(coords, heading, pitch)` | Google Street View Static API | Mapillary, KartaView |
| Geocoding | `geocode(query)`, `reverse_geocode(coords)` | Google Geocoding API | Nominatim (OSM) |
| Places search | `places_nearby(coords, type)`, `place_details(id)` | Google Places API | Overpass (OSM) |
| Elevation | `elevation(coords)` | Google Elevation API | SRTM, MERIT |
| **Histórico (clave)** ⭐ | `overpass_temporal(query, year_range)` | **OpenHistoricalMap** (CC0) — Overpass con `start_date`/`end_date` | Plain OSM como fallback (sin temporalidad) |
| Web search filtrada | `web_search(query)` con filtros anti-shortcut | Tavily / Brave / Serper | + Jina Reader / Firecrawl para extracción |
| Archives históricos | `archive_search(query, period, region)` | Library of Congress API | OldNYC, OldSF, SepiaTown, Historypin (custom wrapper) |
| Mapas históricos | `historical_map_overlay(coords, year)` | MapWarper, NYPL Map Warper | **DEUDA: pendiente investigar** |
| Aerials históricos | `historical_aerial(coords, year_range)` | USGS, NOAA, IGN | **DEUDA: pendiente investigar** |
| Image manipulation | `crop(image, region)`, `zoom_in(image, region)` | PIL local | — |

OpenHistoricalMap es el descubrimiento más relevante del repaso para diseño de tools.

---

## Contrato del environment — decisión abierta crítica

Nuestro env tiene que exponer una API consumible por frameworks externos de RL. Tres opciones principales:

| Opción | Pros | Contras |
|---|---|---|
| **OpenEnv** (Meta, github.com/meta-pytorch/OpenEnv) | Estándar emergente, compatible nativo con TorchTune y futuros frameworks | Inmaduro, riesgo de breaking changes |
| **Gymnasium-style extendido** | Estándar de facto en RL, compatible con TRL/smolagents/Verifiers vía adapters | Diseñado para single-modal / single-step; multi-turn + multi-modal requiere extensión |
| **API propia bien documentada** | Control total, contrato exacto que queremos | Cada framework downstream necesita adapter |

**Decisión pendiente**: spike comparativo. Hipótesis de partida: **OpenEnv si el spike confirma estabilidad razonable, Gymnasium-style si OpenEnv tiene mucho riesgo, API propia solo como último recurso**.

Esta es **LA decisión arquitectónica grande** que define todo lo que viene. Va antes que cualquier código de tools.

---

## Decisiones por proyecto

### Apalancan diseño del environment

| Proyecto | Aporte concreto | Decisión |
|---|---|---|
| **OSM-MCP** (jagan-shanmugam) | Shape FastMCP + lifespan + tools tipadas | **Replicar patrón.** No importar como dependencia (código tiene problemas: cero retries/timeouts/rate limit, cache nunca usado, etc.). |
| **OpenHistoricalMap** ⭐ | Overpass temporal con `start_date`/`end_date`, CC0 | **Tier 1.5 — tool histórica de primera línea.** Hallazgo más importante del repaso. |
| **Pigeon** (Stanford) | Street View parametrizable (heading, pitch, 5 iters) | Aplicar al diseño de la tool `street_view`. |
| **GeoBrowse** | "coherent plans > more tool calls" | Aplicar al diseño del tool spam penalty. |
| **GeoRC** | VLMs alucinan razonamiento | Motivación para penalizadores de proceso + judge en eval. |
| **GeoAgent** | Verifier de consistencia | Inspiración para diseño de penalizadores de proceso (no implementamos su verifier — adoptamos la idea de medir consistencia). |
| **Mapbox MCP** oficial, **Google Maps MCP** (npm `@modelcontextprotocol/server-google-maps`) | Schemas de referencia para nuestras tools | Mirar cómo expusieron las APIs; copiar buenos diseños de schemas. |

### Sobre GeoBenchX (pieza de scaffolding)

Codex bajó las expectativas: el código está pensado para GIS clásico, sin tests, deps rotas, text-only. Conclusión: **reimplementar limpio** (~400 LOC) en lugar de clonar. Mirar GeoBenchX solo como referencia para 2 patrones puntuales:

- `InjectedState` blackboard: tools comparten datos sin saturar el contexto del LLM.
- Idea general de eval harness LLM-as-judge.

NO clonar el repo. NO importar como dependencia.

### NO son problema nuestro (FYI para downstream users)

Los siguientes proyectos son útiles **para alguien que quiera entrenar un agente usando nuestro env**. Las nombramos para que documentación posterior pueda apuntarlos, pero **no consumen tiempo de research nuestro**:

| Proyecto | Qué aporta a downstream users |
|---|---|
| GeoVista (paper, modelo HF) | Receta SFT cold-start + GRPO multi-turno con hierarchical reward |
| SpotAgent | Pipeline 3-stage (SFT + agentic cold-start vía multi-agent + RL con filtering espacial) |
| GeoChain (EMNLP'25) | 1.46M imgs Mapillary + 30M Q&A en 21 pasos. Posible pre-training de CoT |
| Verifiers (Prime Intellect) | Framework RL multi-turn con tool calls |
| TRL (HuggingFace) | Framework alternativo de RL |
| smolagents (HuggingFace) | Para baseline o generación de trayectorias SFT |
| GEO-Detective (paper, nov 2025) | Adaptive strategy selection. **Conflicto de naming** — verificar si renombrar nuestro proyecto. Baja prioridad. |

Lo único de esta lista que sí toca diseño nuestro: **garantizar que nuestro env sea consumible por estos frameworks** vía contrato (ver §Contrato del environment).

### Datasets complementarios (balanceo de sesgo PastVu)

| Dataset | Volumen | License | API | Estado |
|---|---|---|---|---|
| Library of Congress | Alto | Public domain (mostly) | API JSON pública (Codex marcó 403 al WebFetch — verificar) | Apalancar para v1.5 |
| OldNYC | ~40k | Variable | Web | Apalancar como source de NYC |
| OldSF | ~13k | Variable | Web | Apalancar como source de SF |
| Historypin | Variable, crowd | Variable por imagen | API | Apalancar con cuidado de license |
| Bundesarchiv | Alto, alemán | Variable | API | Apalancar para balancear Alemania |
| Europeana | Muy alto, paneuropeo | Variable por institución | APIs activas | **Apalancar fuertemente** para balancear sesgo Rusia |
| Smapshot | **CONTRADICCIÓN entre docs**: 10-50K vs 200K. License "CC" sin verificar | API | **Resolver antes de comprometerse**. Si confirmado, apalancar para 6DoF |

### Descartados

| Proyecto | Razón |
|---|---|
| StreetLearn (DeepMind) | Solo 3 ciudades, repo 2018, problema distinto (navegación) |
| Autonomous GIS / LLM-Geo / LLM-Find / LLM-Cat (Penn State) | Workflows GIS heavy, fuera de scope |
| GeoBenchX como dependencia | Reimplementar limpio sale más barato (ver arriba) |
| `ccmdi/geobench` y repos one-shot | Solo útiles como baselines de eval, no como infra |

---

## Spikes técnicos previos a v1 (ordenados por dependencia)

Los **arquitectónicos** primero (decisiones nuestras que destraban todo lo demás), después **validaciones del corpus**, después **diseño concreto de tools**.

### Decisiones arquitectónicas (nuestras)

1. **Contrato del environment**: OpenEnv vs Gymnasium-style vs API propia. Spike comparativo. **LA decisión grande, antes que cualquier tool**.
2. **Threat model anti-shortcut formal**: listar shortcuts explícitamente, mapear defensas (corpus filter, runtime filter, reward shape, judge). No solo "los 3 tests adversariales".
3. **Auditoría legal/TOS**: por fuente y tool (Google Maps, PastVu, archives, Mapillary). Antes de scale, no después.
4. **Diseño v0 de tool schemas**: empezar con 4-5 tools tipadas con Pydantic v2 (`static_map`, `street_view`, `geocode`, `places_nearby`, `web_search` filtrada). Schema antes que implementación.
5. **Eval suite mínima**: cómo medimos que el env es bueno (no que un agente es bueno). Probablemente: trayectorias canónicas + métricas de coverage del espacio de tools + análisis de presiones evolutivas (`PROJECT.md`).

### Validaciones del corpus

6. **Spike PastVu real**: descargar `pastvu.jsonl.zst` (296 MB), notebook exploratorio. Verificar volumen real, distribución temporal, distribución geográfica (¿70-95% Rusia?), watermark impreso, field `type` (foto/grabado/pintura).
7. **Resolver contradicción Smapshot**: 10-50K vs 200K, license real (CC vs CC BY 4.0). Verificar empíricamente.
8. **Spike OpenHistoricalMap**: verificar cobertura para fotos antiguas en regiones target. Si solo cubre US/UK, es nice-to-have; si cubre Europa/LatAm, es game-changer.
9. **Spike Library of Congress API**: el 403 que vio Codex puede ser auth/rate limit — confirmar acceso programático.

### Investigación pendiente (deuda)

10. IIIF / navPlace / georef — estándar para imágenes culturales con georef.
11. MapWarper, NYPL Map Warper, OldInsuranceMaps/Sanborn — mapas históricos georreferenciados.
12. USGS / NOAA / IGN historical aerials.

Estos spikes deberían convertirse en issues concretas en Project v2 (no se hace antes porque cada uno es 1-2 días de trabajo, agruparlos como mega-issue impide trabajar en paralelo).

---

## Lo que NO es problema del proyecto (recordatorio explícito)

Para evitar drift de framing en futuras sesiones:

- ❌ NO trabajamos en mejorar a un agente que resuelva tareas.
- ❌ NO entrenamos policies.
- ❌ NO elegimos "el framework de RL que vamos a usar" (a lo sumo: garantizamos que nuestro env sea consumible por varios).
- ❌ NO optimizamos hyperparameters de training.
- ❌ NO comparamos modelos entre sí.

✅ Trabajamos en: tasks, tools tipadas, reward signal, corpus filtrado, anti-shortcut, contrato del env, eval suite del env.

Si algo se inclina al lado izquierdo, recortarlo o moverlo a "FYI para downstream users".

---

## Cambios concretos a otros docs derivados

- ✅ `PROJECT.md` invariante 1 — clarifica que filtrado aplica al corpus completo (training incluido).
- ✅ `PROJECT.md` invariante 2 — separa reward outcome de penalizadores de proceso; LLM judge solo eval.
- ✅ `PROJECT.md` invariante 4 — refuerza anti-shortcut con penalizadores de proceso.
- ⏳ Cuando arranque código: agregar OpenHistoricalMap a `CLAUDE.md` tech stack.
- ⏳ Cuando exista `ARCHITECTURE.md`: poner ahí el contrato concreto del env.

---

## Fuentes externas verificadas durante la crítica

- [OpenHistoricalMap Overpass](https://wiki.openstreetmap.org/wiki/OpenHistoricalMap/Overpass)
- [Mapbox MCP](https://docs.mapbox.com/api/guides/mcp-server/)
- [Google Maps MCP npm](https://www.npmjs.com/package/%40modelcontextprotocol/server-google-maps)
- [OpenEnv (meta-pytorch)](https://github.com/meta-pytorch/OpenEnv)
- [Europeana APIs](https://www.europeana.eu/en/apis)
