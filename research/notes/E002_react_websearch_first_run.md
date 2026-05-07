# E002 — ReAct + web_search (single photo proof of concept)

> Primer experimento del agente con tools. Validación end-to-end del concepto del benchmark.
> Artefactos: `experiments/E002_react_websearch/results.json`.

## Objetivo

Verificar que un agente ReAct con `web_search` (filtrada anti-shortcut) puede **cerrar distancia** en una foto que sobrevivió al filtro v2 — i.e., una foto que gpt-5.4 sin tools NO podía ubicar bien.

Si funciona, valida el concepto entero del proyecto: **el benchmark mide la diferencia entre razonamiento sin tools (memoria del modelo) y razonamiento con tools (investigación)**.

## Setup

- **Modelo**: gpt-5.4 vía Foundry, con tool calling nativo (OpenAI format).
- **Tools disponibles**:
  - `web_search(query, max_results)` — Tavily backend con filtros de dominio (pastvu.com, wikimedia, flickr, vk, lens, yandex, tineye bloqueados).
  - `submit_answer(location, lat, lon, year, reasoning, confidence)` — terminal.
- **Stack del scaffolding**: plain Python, sin framework. ~200 LOC. Decidido evaluar Verifiers en fase posterior.
- **Foto target**: `#1748874` — barrio anónimo San Petersburgo, 1996, calle Серебристый бульвар, ground truth (60.006, 30.283). Esta foto tenía dist_min=2573 km en E001 (sin tools).
- **Max steps**: 10. **Max iterations** sin submit: 10.

## Resultado

| | Sin tools (E001) | Con web_search ReAct (E002) |
|---|---|---|
| Coords predichas | 55.756, 37.617 (Moscow Plaza Roja) | **59.934, 30.335 (San Petersburgo)** |
| Distancia geodésica | **2573 km** (mejor de 3 runs) | **8.5 km** ✅ |
| Año predicho | "1990s genérico" / "Europa del Este" | "1993-1998" |
| Año error | 4 (mediana) | **0** |
| Steps usados | 1 | 3 |
| Web searches | 0 | 6 |
| Confidence | baja | baja |

**Mejora: ~300x más cerca** (2573 → 8.5 km).

## Trayectoria del agente

### Step 1 — Identificación amplia (3 búsquedas paralelas)
1. `"Soviet era long slab apartment building horizontal white bands 9 storey birch trees Russia 1980s 1990s hostel dormitory"` (inglés, descripción visual amplia).
2. `"panelák long white facade horizontal stripes dormitory Eastern Europe 9 floors"` (probó terminología checa-soviética).
3. `"общежитие длинное белое здание 9 этажей горизонтальные полосы березы СССР"` (**en ruso directo** — el agente eligió el idioma apropiado).

Resultados retornados: artículos sobre "Brezhnevka", "Khrushchevka", "Panelák" (Wikipedia genéricos sobre tipos de paneles soviéticos).

### Step 2 — Discriminación entre Moscow y SP (3 búsquedas)
1. `"Russia hostel dormitory white horizontal bands long slab building birch trees shipping container yard 'общежитие'"` (refinó descripción).
2. `"Санкт-Петербург общежитие длинное белое здание горизонтальные полосы 9 этажей"` (**eligió SP específicamente**).
3. `"Moscow dormitory long white facade horizontal stripes 9 storey Soviet hostel"` (**comparó con Moscow**).

Resultados: para SP encontró `citywalls.ru` (DB de edificios SP) y `prawdom.ru` — más fuertes que las de Moscow.

### Step 3 — Submit
Confidence baja, justificación honesta: "no hay carteles legibles ni hitos únicos, sólo bloque residencial soviético típico, abedules, contenedores, ropa 90s; mejor estimación zona residencial periférica SP."

## Análisis cualitativo

### Comportamientos observados (todos buenos para el benchmark)
- ✅ **Hipótesis rivales testeadas**: explícitamente comparó Moscow vs SP.
- ✅ **Idioma apropiado**: cambió a ruso para datos rusos.
- ✅ **Búsqueda en paralelo eficiente**: 3 queries en step 1 cubriendo distintos ángulos.
- ✅ **Calibración honesta**: confidence baja pese a haber acertado, porque las pistas reales son débiles.
- ✅ **No spam de búsquedas**: paró en 6 después de discriminar.
- ✅ **Datación clavada**: 1996 → "1993-1998".

### Filtros anti-shortcut funcionaron
- 0/5 bloqueadas en mayoría de queries.
- 1/5 bloqueada en una (probablemente vk.com o similar).
- El agente **NO pudo** pedir "buscame esta foto en la web" — los dominios shortcut estaban bloqueados, así que tuvo que razonar desde pistas visuales.

### Lo que NO se observó
- No alucinó URLs ni info inventada.
- No insistió en hipótesis equivocadas.
- No spammeó tools sin propósito.

## Implicaciones para el proyecto entero

### 1. El concepto del benchmark VALIDA
- La diferencia 2573 km → 8.5 km es **medible y reproducible**.
- El benchmark va a discriminar: modelos con mejor uso de tools cerrarán distancia, modelos peores fallarán.

### 2. Web search filtrada es suficiente para muchos casos
- En este caso, el agente cerró la mayor parte de la distancia con SOLO web search.
- Para llegar a < 1 km probablemente hace falta Maps + Street View.
- Pero ya el delta 2573 → 8.5 es enorme y demuestra el concepto.

### 3. Stack plain Python es suficiente para pruebas
- 200 LOC, funciona, debugeable.
- Decisión: posponer Verifiers a fase posterior cuando tengamos 4-5 tools y querramos publicar.

### 4. El filtro de blacklist funciona sin sabotear
- El agente NUNCA intentó "buscar la foto" — fue por contexto desde el principio.
- Cero búsquedas significativas perdidas por el filtro.

### 5. La rúbrica de confidence se confirma como señal usable
- El agente dijo "baja" pese a haber acertado → es honesto sobre lo débil de las pistas.
- Esto es buen comportamiento investigativo y separa "acertar por suerte / razonamiento débil" de "acertar con evidencia fuerte".

## Limitaciones de este experimento

- **N=1 foto** — necesitamos al menos 5-10 para confirmar el patrón.
- **Solo 1 modelo** — gpt-5.4 puede ser excepcional; gpt-4o, Claude, etc. quizás no.
- **Solo 1 tool** — no testeamos qué pasa con Maps, Street View, OHM.
- **Sin baselines tontos** — no comparamos contra "agente que adivina random" o "humano".

## Próximos pasos

- Correr ReAct sobre las **otras 4 fotos sobrevivientes** del E001 para confirmar patrón.
- Después: agregar más tools (geocode + OHM) y ver si cierra los 8.5 km que quedan.
- En paralelo: documentar patrones del agente para refinar el system prompt.
