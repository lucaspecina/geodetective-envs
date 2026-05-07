# GeoBenchX — Deep Dive

> Research note. Investigación basada en el repo `Solirinai/GeoBenchX` (clonado en `/tmp/geobench/GeoBenchX/`, commit `bb3cd88` del 2025-11-18) y el paper en arxiv 2503.18129v2 (oct 2025), publicado en ACM SIGSPATIAL 2025 (GeoGenAgent '25). MIT license.

## Qué es

GeoBenchX es un benchmark suite (no es un environment de RL ni un framework reusable per se) que evalúa la capacidad de LLMs comerciales para resolver tareas geoespaciales multi-step usando function calling. Los autores (Krechetova, Kochedykov) construyeron un agente ReAct simple sobre LangGraph con 23 tools de análisis GIS clásico (carga de datasets tabulares/vectoriales/raster, joins espaciales, buffers, contour lines, choropleth maps, heatmaps), y un dataset de ~200 tareas etiquetadas con soluciones de referencia más 50 tareas de calibración.

El segundo artefacto importante es un harness de evaluación **LLM-as-Judge**: dado el código generado por el agente y un set de soluciones de referencia, un LLM evaluador (Claude/GPT/Gemini) puntúa 0/1/2 (no-match / partial / full match) usando un prompt con persona, taxonomía, instrucciones y 3 ejemplos in-context. Reportan 88-96% de acuerdo con anotación humana en 50 tareas.

El paradigma del benchmark es muy distinto al nuestro: tareas tipo "haz un mapa de GDP per cápita en África" o "cuántas instalaciones mineras en Argelia están en zonas con densidad >1000 hab/km²". Es output determinista (un mapa, una lista filtrada, un número). No hay tooling de OSINT, ni reverse image, ni Street View. La pieza relevante para nosotros es el **scaffolding de agente + harness de eval**, no las tools en sí.

## Repo y artefactos

- **Repo URL**: https://github.com/Solirinai/GeoBenchX
- **Paper**: https://arxiv.org/abs/2503.18129 (v2, 22-oct-2025). DOI: 10.1145/3764915.3770721. ACM SIGSPATIAL GeoGenAgent '25.
- **License**: MIT (Copyright 2025 Varvara Krechetova). Reusable sin fricción.
- **Último commit**: `bb3cd88` — 2025-11-18 ("Updated readme"). Repo activo, mantenimiento ligero. 24 commits totales en main.
- **Stack**:
  - Python (sin pin de versión en `requirements.txt` — bandera amarilla).
  - LangGraph + LangChain (`langgraph`, `langchain_core`, `langchain_anthropic`, `langchain_openai`, `langchain_google_genai`) — sin versiones.
  - SDKs: `anthropic`, `openai`, `google-generativeai`, `tiktoken`.
  - Geo: `geopandas`, `shapely`, `rasterio`, `folium`, `contextily`, `gdal`, `basemap`, `overpy`, `wbgapi`.
  - Plot/UI: `matplotlib`, `plotly`, `kaleido`, `streamlit`.
  - Otros: `pydantic`, `python-dotenv`, `scipy`, `statsmodels`, `scikit-learn`, `tqdm`, `nbformat`, `networkx`.
  - `requirements.txt` tiene entries inválidos (`pathlib`, `zipfile`, `html`, `gc` son módulos stdlib, no paquetes pip). Nadie lo está rodando con `pip install -r` limpio. Otra bandera amarilla.
- **Estructura**:
  ```
  GeoBenchX/
  ├── geobenchx/        # 11 archivos .py (~4440 LOC totales)
  │   ├── agent.py              (179 LOC)
  │   ├── tools.py              (2594 LOC)  ← el grueso
  │   ├── prompts.py            (24 LOC)
  │   ├── evaluation.py         (594 LOC)
  │   ├── generate_solutions.py (85 LOC)
  │   ├── dataclasses.py        (329 LOC)
  │   ├── constants.py          (56 LOC)
  │   ├── save_chats.py         (210 LOC)
  │   ├── tasks_editor.py       (276 LOC)  ← Streamlit task editor
  │   ├── utils.py              (93 LOC)
  │   └── __init__.py           (vacío)
  ├── benchmark_set/    # 200+ tasks JSON + 50 calibration tasks
  ├── data/             # 18 stat csv, 21 vector shp, 11 raster tif
  ├── notebooks/        # Benchmarking.ipynb, Generate_tasks.ipynb, Tune_evaluator.ipynb
  ├── results/          # outputs
  ├── assets/           # ejemplos HTML de conversation traces
  ├── requirements.txt
  ├── LICENSE
  └── README.md
  ```

## Arquitectura del agente ReAct

**Acopladísimo a LangGraph prebuilt — no hay un grafo custom**. Toda la lógica del loop ReAct se delega a `create_react_agent` de `langgraph.prebuilt`. Esto es bueno (poco código que entender, robusto) y malo (rigidez si querés meterte a customizar nodes/edges).

**Archivo clave**: `geobenchx/agent.py` (179 LOC). Pieza central, líneas 94-178:

```python
graph = create_react_agent(llm, tools=tools, state_schema=State,
                           state_modifier=SYSTEM_PROMPT + RULES_PROMPT)
inputs = {"messages": [("user", task_text)], "data_store": {},
          "image_store": [], "html_store": [], "visualize": True}
config = {"max_concurrency": 1, "recursion_limit": max_steps}
for s in graph.stream(inputs, stream_mode="values", config=config):
    ...
```

**State definition** (`geobenchx/tools.py:124-131`):
```python
class State(TypedDict):
    data_store: Dict[str, Any]      # DataFrames + GeoDataFrames vivos
    image_store: List[Dict[str, Any]]  # imágenes para conversation history
    html_store: List[Dict[str, Any]]   # HTML para mapas interactivos
    messages: Annotated[list, add_messages]
    remaining_steps: RemainingSteps   # de langgraph.managed.is_last_step
    visualize: bool
```

**Patrón notable**: las tools comparten un blackboard (`data_store`) accedido vía `InjectedState` de LangGraph. Un step `load_geodata(...)` mete un GeoDataFrame en `state["data_store"][output_geodataframe_name]`, y el siguiente step lo lee por nombre. Esto desacopla los argumentos (que pasan strings/JSON al LLM) del estado pesado (objetos pandas/geopandas que nunca tocan el contexto del modelo). **Patrón muy reusable** para nuestro caso: el agente OSINT puede mantener un dict de `evidence_store` con crops de imagen, candidatos, queries hechas, etc., sin spamear el contexto.

**Loop termination**:
- `recursion_limit = max_steps` (default 25). Si lo excede, `GraphRecursionError` se cachea silenciosamente (`agent.py:173-174`) y se devuelve la solución parcial.
- `reject_task` tool (tools.py:2384) que el agente puede llamar voluntariamente para declarar la tarea irresoluble. La firma es trivial — solo retorna un string. El loop no se corta automáticamente al llamarlo, pero la convención del prompt es que el agente para ahí.
- No hay un nodo "should_continue" custom ni un terminal state explícito. Es lo que viene out-of-the-box con `create_react_agent`.

**Tracking de output**: el `for s in graph.stream(...)` itera sobre estados, extrae cada `tool_call` y lo guarda como `Step(function_name, arguments)`. La `Solution` final es la lista de Steps. **Importante**: solo guardan el plan (qué tools, con qué args), NO los resultados intermedios — los resultados quedan en `data_store` pero no se persisten para evaluación. La eval compara solo los planes de tool calls vs los planes de referencia.

**Multi-LLM dispatch**: condicional sobre el nombre del modelo (agent.py:104-113). Soporta Claude (3.5/3.7/4 Sonnet, Haiku 3.5), GPT (4o/4.1/mini), o-series (o3-mini/o4-mini, sin temperature), Gemini (2.0 flash, 2.5 pro). Modelos hardcodeados en `constants.py:12-25`.

## Las 23 tools — categorización

Lista exacta extraída de `geobenchx/agent.py:67-92` (la 24a, `make_bivariate_map_tool`, está pero no se cuenta como una de las 23 — el README dice 23 pero el código importa 24). El paper cita 23.

| # | Tool | Qué hace | Categoría para geodetective |
|---|---|---|---|
| 1 | `load_data` | Carga CSV estadístico desde catálogo hardcoded a Pandas DF | **Fuera de scope** (catálogo cerrado de datasets World Bank) |
| 2 | `load_geodata` | Carga shapefile vectorial a GeoDataFrame | **Fuera de scope** (mismo issue) |
| 3 | `get_raster_path` | Resuelve path a GeoTIFF en catálogo | **Fuera de scope** |
| 4 | `get_raster_description` | Metadata + stats de bandas raster | **Fuera de scope** |
| 5 | `analyze_raster_overlap` | Stats sobre overlap entre dos rasters | **Fuera de scope** |
| 6 | `get_values_from_raster_with_geometries` | Mask raster con vector, calcula stats | **Fuera de scope** |
| 7 | `merge_dataframes` | Left join entre DFs por columna clave | Fuera de scope |
| 8 | `get_unique_values` | Distinct values de columna | Fuera de scope |
| 9 | `filter_categorical` | Filtro categórico sobre DF | Fuera de scope |
| 10 | `filter_numerical` | Filtro numérico (`df.query`) | Fuera de scope |
| 11 | `calculate_column_statistics` | Stats summary + quantiles | Fuera de scope |
| 12 | `create_buffer` | Buffer en metros (Web Mercator) sobre geometrías | **Adaptable** — útil para "lugares dentro de X km de coordenada candidata" |
| 13 | `make_choropleth_map` | Choropleth | Fuera de scope |
| 14 | `filter_points_by_raster_values` | Sample raster en puntos + threshold filter | Fuera de scope |
| 15 | `select_features_by_spatial_relationship` | `intersects/within/touches/...` entre dos GDFs | **Adaptable** — útil para razonamiento espacial sobre candidatos |
| 16 | `calculate_line_lengths` | Longitudes en km vía UTM proyectada | Fuera de scope |
| 17 | `calculate_columns` | Operaciones aritméticas col-vs-col | Fuera de scope |
| 18 | `scale_column_by_value` | Operaciones col-vs-escalar | Fuera de scope |
| 19 | `make_heatmap` | Heatmap interactivo plotly density_mapbox | Fuera de scope |
| 20 | `visualize_geographies` | Render multi-layer con basemap | **Adaptable** — útil como herramienta de visualización para debug/output del agente |
| 21 | `get_centroids` | Centroides de polígonos | Fuera de scope |
| 22 | `generate_contours_display` | Contour lines GDAL | Fuera de scope |
| 23 | `reject_task` | Declara tarea irresoluble; retorna mensaje fijo | **Reusable casi tal cual** — patrón crucial para nuestro caso (foto sin pistas) |
| 24 (extra) | `make_bivariate_map` | Mapa bivariado | Fuera de scope |

**Veredicto sobre las tools**: el ~95% son fuera de scope. Lo que necesitamos para geodetective (geocoding, reverse geocoding, Street View, places search por radius, web search, reverse image, archivos históricos) **NO está cubierto**. Las únicas reusables con adaptación son `create_buffer`, `select_features_by_spatial_relationship` y `visualize_geographies` para tareas de razonamiento espacial sobre regiones candidatas. Y `reject_task` como patrón.

**Lo que NO existe en GeoBenchX y necesitamos**:
- Llamadas a Google Maps Geocoding API.
- Street View Static API o panorama metadata.
- Places Nearby Search.
- Elevation API.
- Web search (no hay tool de web search; el agente no navega).
- Reverse image search (TinEye, Yandex).
- OCR sobre la foto.
- Acceso a archivos históricos (Library of Congress, Wikimedia Commons, etc.).
- Vision sobre la imagen target (el LLM tendría que verla, pero el harness no la pasa multimodal — solo hay `task_text`).

## Harness de evaluación

**Archivo**: `geobenchx/evaluation.py` (594 LOC). Es la pieza más interesante del repo, quizá más que el agente.

### Cómo evalúa
La función `score_task_solution(task, model, temperature)` (línea 274) toma una `Task` con `generated_solution` y `reference_solutions` (lista, puede haber múltiples soluciones aceptables), formatea el código de ambas como pseudo-Python (`utils.get_solution_code`), inyecta todo en un mega-prompt, y llama a un evaluator LLM via `create_react_agent` con `tools=[]` (sin tools — solo razona). Extrae el score con regex sobre tags `<MATCH SCORE>n</MATCH SCORE>`.

### Estructura del prompt evaluador (`evaluation.py:191-272`)
El `RESULT_CHECKING_PROMPT` se compone de:
1. **EVALUATOR_PERSONA** (l.191-196): "Quality control GIS specialist". Genérico/adaptable.
2. **TOOLS_DESCRIPTION** (l.198-203): generado dinámicamente iterando todos los tools y dumpeando `tool.args` y `tool.description`. **Hardcoded a las 23 tools**, pero el patrón de generar la descripción dinámicamente es reusable.
3. **EVALUATION_TAXONOMY** (l.209-216): la rúbrica 0/1/2.
4. **INSTRUCTIONS** (l.218-248): 30 líneas de criterios "qué cuenta como FULL/PARTIAL/NO match", muy específicos al dominio GIS (e.g., "if list of spatial predicates differ → partial match", "if data from different years and diff is 1 year → partial"). **Reescribir desde cero** para nuestro caso.
5. **EXAMPLES** (l.92-189): 3 ejemplos in-context con `<TASK>...<MATCH REASONING>...<MATCH SCORE>` mostrando el razonamiento. Súper específicos a tareas GIS.
6. Slot final con `task_text`, `reference_solutions`, `candidate_solution`.

**Output format**: tags XML-style:
```
<MATCH REASONING>...</MATCH REASONING>
<MATCH SCORE>0|1|2</MATCH SCORE>
```
Parseado con regex (`re.search(r'<MATCH SCORE>(.*?)</MATCH SCORE>', verdict, re.DOTALL)`).

### Métricas
`generate_eval_stats(taskset, alpha=0.05)` (l.373-436):
- Frecuencias de scores 0/1/2.
- **Diff relativo de longitud de solución**: `(len_candidate - len_reference) / len_reference`. Mean y median. Captura si el agente hace pasos de más o de menos.
- **Intervalos de confianza binomiales** (Wilson via `scipy.stats.binomtest.proportion_ci`) por cada score.

`compute_confusion_stats` (utils.py:57-93) compara LLM vs human scores con confusion matrix + accuracy + Wilson CI. Usado para tunear el evaluator contra ground truth humano.

`get_eval_stats_by_subsets` (l.483) y `get_eval_stats_by_pure_solvability` (l.546) permiten partir el set por labels o por "tareas irresolubles puras" (referencia única = `reject_task`).

### Multi-judge
**OJO al README vs código**: el README habla de "panel de 3 jueces" (Claude Sonnet 3.5, GPT-4.1, Gemini 2.5 Pro). El código en `evaluation.py` corre **un único evaluador a la vez** (parametrizado por `model`). El "panel" es una práctica de los autores (correr 3 veces con 3 modelos y comparar manualmente) — no hay aggregation automática en código. Si queremos panel real con voto/promedio, lo escribimos nosotros.

### Reusabilidad para evaluar trayectorias de geo-investigación
**Parcial pero la estructura sirve**. Lo que reusamos:
- El esqueleto de prompt (persona + taxonomy + instructions + few-shot + slots) ✅
- Output con tags XML-style + regex parsing ✅
- Stats + Wilson CI ✅
- Patrón de "evaluator agnóstico al provider" via `create_react_agent` con `tools=[]` ✅
- Partición por subsets (labels) ✅

Lo que reescribimos:
- TODO el contenido de INSTRUCTIONS y EVALUATION_TAXONOMY (criterios totalmente distintos: nuestra rúbrica es sobre **calidad de la trayectoria de investigación + corrección de la respuesta final geográfica**, no sobre matching de tool plans).
- Los EXAMPLES (3-5 ejemplos nuevos sobre geo-investigación).
- La taxonomía: 0/1/2 sobre matching de tool plans no aplica. Probablemente queramos algo más rico: distancia geográfica de la respuesta final + score cualitativo de razonamiento + uso eficiente de tools.

**Limitación importante**: el harness solo compara **planes de tool calls** vs **planes de referencia** (snippets de pseudo-código). No mira los outputs ni la respuesta final del agente al usuario. Para nosotros eso es problemático — un plan de "buscó street view en zonas A, B, C, descartó por X razón, concluyó Y" debería evaluarse por la **calidad del razonamiento y la respuesta final**, no por matching contra un plan canónico (que para tareas abiertas de OSINT no existe).

## Cosas que reusamos sí o sí

- **`agent.py:94-178` `execute_task`** como template: estructura del runner (LLM dispatch + `create_react_agent` + `graph.stream` + extracción de tool calls + token tracking + capture de history). Reescribir tools, copiar el shape.
- **`tools.py:124-131` `State` TypedDict**: el patrón `data_store + image_store + html_store + messages + remaining_steps` mapea casi 1:1 a nuestro `evidence_store + crops_store + map_html_store + messages`. Usar como base.
- **Patrón `InjectedState` para tools**: state pesado fuera del contexto del LLM, accedido por nombre. Crítico para no inflar tokens con base64 de imágenes / GeoDataFrames.
- **`reject_task` tool** (`tools.py:2384-2397`): patrón canónico para "no se puede resolver con lo que tengo". Imprescindible para nuestro caso (fotos sin pistas suficientes).
- **`evaluation.py:274-359` `score_task_solution`**: estructura del judge (LLM evaluador + prompt template + regex parsing). Adaptamos prompts.
- **`evaluation.py:373-436` `generate_eval_stats`**: stats binomiales con Wilson CI por categoría de score. Reusable casi sin cambios.
- **`utils.py:57-93` `compute_confusion_stats`**: confusion matrix + accuracy + Wilson CI para tunear evaluador contra humano.
- **`dataclasses.py` (`Step`, `Solution`, `Task`, `TaskSet`)**: schema Pydantic muy bien armado, con persistencia JSON, sampling estratificado por labels, etc. Lo reusamos como base de nuestro task spec con minor extensions (agregar `image_path`, `ground_truth_lat_lon`, `acceptable_radius_km`, etc.).
- **`save_chats.py`**: dump de conversation history a HTML interactivo. Útil para debug y para inspeccionar trayectorias del agente. Ver assets/ para ejemplo.
- **`prompts.py`**: estructura mínima `SYSTEM_PROMPT + RULES_PROMPT`. Adaptamos contenido. Patrón de inyectar `current_date` dinámicamente es útil.

## Cosas que reescribimos

- **Las 23 tools**: todas excepto `reject_task`, `create_buffer` (parcial), `select_features_by_spatial_relationship` (parcial), `visualize_geographies` (parcial). Necesitamos un set nuevo: `geocode`, `reverse_geocode`, `places_nearby`, `street_view_metadata`, `street_view_capture`, `elevation`, `web_search`, `reverse_image_search`, `read_image_metadata` (EXIF), `crop_image`, `ocr`, `historical_archive_search`, etc.
- **Catálogos `DATA_CATALOG`/`GEO_CATALOG`/`RASTER_CATALOG` en `tools.py:46-102`**: hardcoded a datasets de World Bank/USGS/etc. Borramos. Si queremos un "catálogo" para nuestro caso podría ser regiones/países con metadata, pero diferente.
- **Prompts**: `SYSTEM_PROMPT` ("eres un geógrafo que mapea respuestas") y `RULES_PROMPT` (reglas sobre dataset coverage) totalmente irrelevantes. Reescribir como "eres un detective de geo-localización OSINT, etc.".
- **Evaluator INSTRUCTIONS y EXAMPLES** (`evaluation.py:218-248`, `92-189`): 100% específicos a GIS. Reescribir.
- **TaskLabels enum** (`constants.py:43-55`): renombrar a nuestras categorías ("Vague terrain", "Distinctive landmarks", "Urban", "Rural", "Historical", etc.).
- **Modelos**: agregar lo que use el proyecto (e.g., Claude 4 con vision, GPT-4.1 con vision si aplica). El dispatch en `agent.py:104-113` es trivial de extender.
- **Multi-modal handling**: el agente actual SOLO recibe texto. Nuestro caso necesita pasar la imagen al LLM. Hay que reescribir el `inputs = {"messages": [("user", task_text)], ...}` para soportar mensajes multimodales (lista de content blocks `text` + `image`).

## Cosas que descartamos

- **`benchmark_set/`** entero: 200+ tareas GIS, ningún caso aplicable. Nos hacemos nuestro dataset desde cero.
- **`data/`**: 18 CSV + 21 shp + 11 tif. Nada útil. Pesa MB-GB.
- **`notebooks/Benchmarking.ipynb`**, **`notebooks/Generate_tasks.ipynb`**, **`notebooks/Tune_evaluator.ipynb`**: probablemente útiles como referencia de uso del API pero específicos al dataset GIS. Mirarlos una vez para entender flujo, no clonarlos.
- **`tasks_editor.py`**: editor Streamlit para curar tareas. Específico al schema y dataset de ellos. Si queremos un editor lo hacemos custom.
- **GDAL como dependencia**: dolor de instalación. Solo lo usan tools de raster que descartamos. Out.
- **`basemap`**: deprecated. Out.
- **Dependencias geoespaciales pesadas**: `geopandas`, `rasterio`, `shapely`, `contextily`, `wbgapi`, `overpy`, `folium` — solo si reusamos las tools espaciales adaptables; si no, fuera. Nuestro stack probablemente sea `googlemaps`, `httpx`, `Pillow`, `requests`, sin todo el zoo GIS.

## Plan de integración tentativo

Recomendación: **NO clonar el repo y modificar in-place**. Lo limpio es:

1. **No fork. Crear repo greenfield `geodetective-envs/`** con estructura propia.
2. **Copiar 4 archivos como base** (con ajustes inmediatos):
   - `geobenchx/agent.py` → `src/geodetective/agent.py`. Mantener `execute_task` skeleton, ajustar `State`, ajustar inputs para multimodal, eliminar imports de tools GIS.
   - `geobenchx/dataclasses.py` → `src/geodetective/schema.py`. Renombrar Pydantic models, agregar campos image/groundtruth.
   - `geobenchx/evaluation.py` → `src/geodetective/judge.py`. Mantener estructura de `score_task_solution` + `generate_eval_stats`, reescribir prompt.
   - `geobenchx/save_chats.py` → `src/geodetective/trace_html.py`. Reusar casi sin cambios.
3. **Construir de cero**:
   - `src/geodetective/tools/` con módulos por tool (maps, streetview, web, image, archive). Cada uno con `StructuredTool.from_function`.
   - `src/geodetective/prompts.py` con SYSTEM_PROMPT detective + RULES_PROMPT investigation.
   - `bench/cases/` con casos JSON (similar a `benchmark_set/` pero con campos `image_path`, `gt_lat_lon`, `acceptable_radius_km`, `hints`, `difficulty_label`).
4. **Integrar judge nuevo**:
   - Rúbrica multi-eje: distancia geográfica de la respuesta final (dura, métrica), calidad del razonamiento (LLM-as-judge, blanda), eficiencia de tool use (cuenta de calls + redundancia, métrica).
   - 3-5 few-shots inventados.
5. **Tool error handling**: agregar lo que falta — ver siguiente sección.

**Estimación gruesa**: ~2-3 semanas de trabajo full focus para llegar a un MVP integrado. La mayor parte del costo está en (a) implementar las tools nuevas (Maps APIs, Street View, etc.) y (b) curar un dataset de tareas con ground truth.

## Riesgos / preocupaciones

- **Multi-modal no está**. El agente actual de GeoBenchX es text-only en el message stream. Para nuestro caso (foto como input principal), necesitamos messages con content blocks mixtos. `create_react_agent` lo soporta vía LangChain messages, pero ojo — algunos providers (Gemini) tienen quirks en multimodal + tool calling. Hay que validar que funcione con Claude 4 + GPT-4.1 multimodal + tools. **Bandera amarilla**.
- **Tool error handling es flojo**. En `tools.py` hay try/except en algunas tools (`get_raster_description`, `analyze_raster_overlap`, `make_choropleth_map`) que retornan strings de error al LLM. **No hay retry explícito a nivel de tool**, no hay rate limiting handling, no hay distinción entre transient (429) y permanente (404). El loop de `generate_solutions.py:54-77` tiene `while not success: try ... except: try_count += 1` pero **sin máximo y sin sleep entre retries** — bug latente, infinite loop si el error es persistente. Para nuestro caso con APIs de Google Maps que rate-limitean, esto es insuficiente. **Tenemos que diseñarlo bien desde el día 1** (tenacity, exponential backoff, distinción de error types, presupuesto de calls por tarea).
- **Sin pin de versiones**. `requirements.txt` lista paquetes sin versiones, y mete entries inválidos (`pathlib`, `zipfile`, `html`, `gc` son stdlib). Garantizado que se rompe en algún momento. **Tenemos que pinear todo nosotros** (uv/poetry).
- **Costos de eval**. El prompt evaluador tiene ~24 tool descriptions + 3 ejemplos largos + tool calls del candidato + reference solutions = miles de tokens por task. Por 200 tasks × 3 jueces = ~$$ no trivial. Para nosotros las descripciones de tools serán más cortas, pero los traces de investigación serán más largos. Presupuestar.
- **No hay tests**. No vi ningún `tests/` ni archivo `test_*.py`. Los notebooks parecen ser el "test runner" implícito. Para nosotros: **escribir tests desde el día 1**, especialmente mocks de las APIs externas.
- **Streamlit task editor (`tasks_editor.py`)**: 276 LOC para editar tareas. Si lo usamos, es otra dependencia. Mejor saltearlo o usar un script CLI simple.
- **Acoplamiento al prebuilt `create_react_agent`**: si en algún momento queremos un grafo custom (ej: separar "planning node" de "execution node", o agregar un "verification node" antes de responder), tenemos que migrar. Ahora es una caja negra. No es bloqueante pero hay que saberlo.

## Decisión: apalancar / mirar / descartar

**Veredicto: APALANCAR PARCIALMENTE — copiar 4 archivos como base + reusar patrones, NO clonar el repo.**

GeoBenchX nos ahorra trabajo en (1) **scaffolding del agente ReAct con LangGraph + State con InjectedState pattern** (~150 LOC bien resueltos), (2) **harness de eval LLM-as-judge con stats binomiales y partición por subsets** (~600 LOC), y (3) **schema Pydantic de tasks con persistencia JSON y sampling estratificado** (~330 LOC). Eso es 1000+ LOC de código probado que copiamos y adaptamos en lugar de escribir desde cero. **Las tools GIS son irrelevantes (~95% out)**, los catálogos de datasets son irrelevantes, y los prompts/instructions del judge son específicos a GIS y se reescriben.

El paper aporta poco más allá de la confirmación de que el approach (ReAct simple + LangGraph + LLM-as-judge) funciona para tareas geo multi-step y un punto de comparación numérico (88-96% agreement evaluator vs human) que sirve como referencia de qué calidad de evaluator buscar.
