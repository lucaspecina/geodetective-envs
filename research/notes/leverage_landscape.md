# Landscape de proyectos para apalancar — fuera de Tier 1

> Tier 1 (GeoBenchX, OSM-MCP, PastVu) tiene deep dives separados en este mismo directorio.
> Este doc cubre Tier 2-5 + trabajos recientes (últimos 6-12 meses).
>
> Fecha de armado: 2026-05-07. Autor: investigación inicial para GeoDetective Envs.

---

## TL;DR — Tabla maestra de decisiones

| Proyecto | Tier | Qué da | Decisión |
|---|---|---|---|
| **GeoVista** (arxiv 2511.15705) | 2 | Receta SFT cold-start + RL con hierarchical reward, modelo open + benchmark | **Apalancar como receta principal de training**. Replicar pipeline en v2. |
| **GeoAgent** (arxiv 2602.12617) | 2 | Geo-similarity reward + consistency-agent verifier | **Apalancar como receta de reward shaping** (especialmente el consistency check). |
| **Pigeon-eval / Stanford** (arxiv 2502.14412) | 2 | Patrón de agente que controla heading/pitch de Street View Static API en 5 iteraciones | **Apalancar como patrón de tool design** (Street View como tool con parámetros). |
| **GeoRC** (arxiv 2601.21278) | 2 | Benchmark de cadenas de razonamiento de expertos GeoGuessr; documenta hallucinations | **Mirar en serio**: motivacional + ideas de eval de la cadena de razonamiento. |
| **Verifiers** (Prime Intellect) | 3 | Librería Python para envs RL multi-turn con tool calls + rubric | **Apalancar como código** (probable backbone de v1 o v2). |
| **TRL** (HuggingFace) | 3 | GRPOTrainer con multi-turn tool loop + OpenEnv | **Mirar como alternativa mainstream**; puede ser fallback si Verifiers no funciona. |
| **smolagents** (HuggingFace) | 3 | Framework liviano de agentes (Code/ToolCalling) | **Apalancar para prototipado rápido del baseline antes de RL**. |
| **StreetLearn** (DeepMind) | 4 | Panoramas Manhattan/Pittsburgh + grafo de adyacencia | **Descartar**: solo NYC y Pittsburgh, paper de 2018, requiere request del dataset, no histórico. |
| **LLM-Geo / LLM-Find / LLM-Cat** (Penn State) | 4 | Agentes de workflow GIS desde NL | **Descartar para v1**; mirar de reojo si entran tools de análisis GIS más adelante. |
| **Smapshot** | 4 | 200K imágenes con 6DoF pose + API REST + CC | **Apalancar para v1.5 / v2**: tiene pose 3D completa, ideal para reward de fine-grained location. |
| **Library of Congress P&P** | 4 | Decenas de miles de fotos históricas con metadata, API JSON pública | **Apalancar para dataset**: complementa PastVu en geografía US/global. |
| **OldNYC / OldSF** | 4 | ~50K (NYC) + ~13K (SF) fotos plotted en mapa, JSON público | **Apalancar como dataset secundario** (fácil de scrapear, foco urbano US). |
| **SepiaTown** | 4 | Mapped historical images global, sin API moderna documentada | **Mirar y descartar a menos que aparezca API**. |
| **Historypin** | 4 | Crowdsourced photos + API documentada | **Apalancar como dataset**: API pública, gratis, global, geotagged + fechado. |
| **ccmdi/geobench** | 5 | Repo chico de benchmark GeoGuessr para LLMs | **Solo como referencia de baseline one-shot**. No infra. |
| **GeoBrowse** (arxiv 2604.04017) | reciente | Benchmark agéntico con 5 tools de imagen + 4 tools de conocimiento, traces anotadas | **Leer en serio**. Es el más cercano conceptualmente a lo que queremos construir. |
| **SpotAgent** (arxiv 2602.09463) | reciente | Pipeline 3-stage: SFT + agentic cold-start + RL con filtering espacial | **Leer en serio** como receta de training complementaria a GeoVista. |
| **GEO-Detective** (arxiv 2511.22441) | reciente | Agente 4-step con visual reverse search; ángulo privacidad | **Mirar abstract**; coincidencia de nombre con nuestro proyecto pero foco distinto (privacy). |
| **GeoChain** (arxiv 2506.00785, EMNLP'25) | reciente | 1.46M imágenes Mapillary + 30M Q&A pairs en 21-step CoT | **Mirar dataset**: posible fuente para SFT cold-start pre-tuning. |
| **GeoReasoner** (arxiv 2406.18572) | reciente | LVLM augmented con human inference para Street View geo | Mirar abstract; predecesor. |

---

## Tier 2 — Papers / patterns conceptuales

### GeoVista — Web-Augmented Agentic Visual Reasoning for Geolocalization
- **URL paper**: https://arxiv.org/abs/2511.15705 (v1: 2025-11-19, revisado 2025-12-18).
- **URL repo**: https://github.com/ekonwang/GeoVista (Apache-2.0, ~76 commits).
- **URL modelo**: HuggingFace `GeoVista-RL-6k-7B` + dataset `GeoVista-Bench`.
- **Autores**: Yikun Wang, Zuyan Liu, Ziyi Wang, Han Hu, Pengfei Liu, Yongming Rao (Fudan, Tencent Hunyuan, Tsinghua, Shanghai Innovation Institute).
- **Receta de training**:
  - Stage 1: cold-start SFT sobre trayectorias multi-turn para enseñar formato ReAct y patrón de tool-use.
  - Stage 2: RL (no especifica explícitamente GRPO en el abstract, pero la arquitectura es compatible) sobre hierarchical reward.
- **Tools**:
  - `image_zoom`: magnificar región de interés de la imagen.
  - `web_search`: buscar info contextual relacionada.
- **Reward**: hierarchical, multi-level geográfico (probablemente país → región → ciudad → coords; el abstract no detalla la fórmula pero el árbol jerárquico es la idea central).
- **Benchmark**: GeoBench (fotos + panoramas globales + subset satelital de varias ciudades).
- **Performance**: comparable a Gemini-2.5-flash y GPT-5 en la mayoría de métricas, mejor que open-source agentic models existentes.
- **Aporte para nosotros**: la receta SFT cold-start → RL con hierarchical reward es **exactamente** el camino que tenemos planificado. El modelo de 7B con weights públicos puede servir de baseline open.
- **Limitación**: el environment de RL no parece estar publicado completo (el repo tiene `scripts/sft.py` pero el RL pipeline no está claro). Hierarchical reward function probablemente hay que recrear desde el paper.
- **Decisión**: **APALANCAR** el paper como receta principal de training en v2. Replicar reward jerárquico. Usar GeoVista-RL-6k-7B como uno de los baselines open en eval.

### GeoAgent — Learning to Geolocate Everywhere with Reinforced Geographic Characteristics
- **URL**: https://arxiv.org/abs/2602.12617 (feb 2026).
- **Aporte clave**: dos componentes de reward novedosos:
  - **Geo-similarity reward**: spatial similarity (función de distancia) + semantic similarity (textual similarity entre predicción y ground truth).
  - **Consistency reward**: un agente verificador independiente intenta derivar la respuesta del CoT del agente principal sin conocer la pregunta. Si lo logra, el CoT se considera "well-grounded" y se incentiva.
- **Dataset**: GeoSeek (CoT data anotada por geo-experts y players profesionales).
- **Aporte para nosotros**: el **consistency-agent verifier es un patrón muy útil** para evitar el problema de GeoRC (VLMs aciertan pero alucinan razonamiento). Podemos meter un consistency check en la rubric.
- **Limitación**: dataset de training no necesariamente público; foco en geolocalización moderna.
- **Decisión**: **APALANCAR como receta de reward shaping**. Implementar consistency-agent en v1.5 o v2 como segunda señal además de la distancia.

### Pigeon-eval — Evaluating Precise Geolocation Inference Capabilities of VLMs (Stanford)
- **URL**: https://arxiv.org/abs/2502.14412 (feb 2025; ya tiene un año pero es referencia base).
- **Dataset**: 1,602 imágenes Street View en 1,563 ciudades / 88 países, distribución global.
- **Patrón clave del agente**:
  - VLM con acceso a Street View Static API como tool.
  - Itera 5 veces: predicción → ajuste de heading/pitch → request de nueva imagen → refinamiento.
  - Reduce error en 30.6% vs single-shot.
  - Con 3 guesses supera a humanos GeoGuessr "Champion Division".
- **Findings**: PIGEON (modelo dedicado de geo) sigue siendo mejor que el agente VLM, pero la distancia se acorta.
- **Aporte para nosotros**: patrón de **tool design para Street View**: no es "una imagen", es un endpoint parametrizable (lat, lon, heading, pitch, fov) que el agente debe aprender a controlar. Esto es una decisión de diseño importante para nuestras tools.
- **Decisión**: **APALANCAR como patrón de tool**. Diseñar nuestro `street_view` tool con args (lat, lon, heading, pitch) y dejar que el agente itere.

### GeoRC — Benchmark for Geolocation Reasoning Chains
- **URL**: https://arxiv.org/abs/2601.21278.
- **Contenido**: 800 cadenas de razonamiento "ground truth" de Champion-tier GeoGuessr experts (incluyendo el world champion actual) sobre 500 escenas.
- **Findings clave**:
  - Closed-source VLMs (Gemini, GPT-5) **rivalizan con humanos en predecir locación**, pero **fallan en producir razonamiento auditable**.
  - Small open-weight VLMs (Llama, Qwen) catastróficamente mal: similar a un baseline donde un LLM **alucina la cadena de razonamiento conociendo la respuesta** (sin imagen).
  - Identifica fallas: hallucinations, geographical misattributions, red herrings, axiomatic irrelevances, falla en reconocer atributos low-pixel.
- **Eval**: LLM-as-judge / VLM-as-judge para scoring; Qwen 3 LLM-as-judge correlaciona mejor con expertos.
- **Aporte para nosotros**:
  - Motivacional: confirma que **la cadena de razonamiento importa tanto como la respuesta**. Nuestro environment debería rewardear razonamiento auditable, no solo distancia.
  - Provee LLM-as-judge benchmarkable para reasoning quality.
  - Las 800 chains pueden servir como SFT cold-start dataset.
- **Decisión**: **MIRAR EN SERIO**. Considerar incluir GeoRC en eval suite. Las trazas pueden alimentar nuestro cold-start SFT.

---

## Tier 3 — Frameworks de RL multi-turn con tool calls

### Verifiers (Prime Intellect)
- **URL repo**: https://github.com/PrimeIntellect-ai/verifiers
- **License**: MIT.
- **Último release**: v0.1.14 (2026-05-07, hoy mismo — proyecto muy activo).
- **PyPI**: `pip install verifiers`.
- **Stack interno**:
  - Soporta multi-turn tool calls nativo.
  - Trainer propio: `vf.RLTrainer` (renombrado desde `vf.GRPOTrainer` en versiones recientes; "nano" trainer interno).
  - Integración tight con `prime-rl` (training framework distribuido) — v0.1.7+ tiene quickstart con prime-rl.
  - RLM (Recursive Language Model) harness con auto-compaction de contexto.
  - Tags oficiales: agentic-rl, agents, environments, eval, grpo, harness, llm, multi-turn, reinforcement-learning, rl, tool-use, train.
- **Abstracciones clave**:
  - **Environment**: dataset + harness + rubric.
  - **Taskset / Harness**: define el protocolo multi-turn y manejo de tools/sandbox.
  - **Rubric**: funciones de reward.
  - **Rollouts**: trayectorias multi-turn con token accounting.
- **Multimodal**: la documentación NO confirma soporte explícito de imágenes. **Riesgo**: hay que verificar antes de comprometerse. Si VLM no está soportado out-of-the-box, hay que extender.
- **Por qué nos importa**: específicamente diseñado para nuestro caso de uso (multi-turn + tool calls + reward final + RL). Más adecuado que TRL para envs custom.
- **Decisión**: **APALANCAR como código**. Probable backbone de v1 / v2. **Acción crítica**: validar soporte multimodal en v1 con un experimento de 1 día antes de comprometerse — si no soporta imágenes nativamente, evaluar fork vs alternativa.

### TRL (HuggingFace)
- **URL repo**: https://github.com/huggingface/trl
- **GRPO con tool calls**: soportado vía `tools=[...]` argument en `GRPOTrainer`. Hay un `_tool_call_loop` interno.
- **Multi-turn**: hay un `environment_factory` recomendado donde definís una clase Environment con tool methods, y el trainer maneja generación + parsing + loop multi-turn automáticamente.
- **OpenEnv integration**: TRL tiene integración oficial con OpenEnv (Meta) — https://huggingface.co/docs/trl/main/en/openenv — para training con environments externos.
- **Limitación**: `max_completion_length` aplica al total de tokens en TODA la conversación multi-turn, no por generación. Hay que tunear cuidadoso.
- **Multimodal**: soporta VLMs vía mismo trainer (Qwen2.5-VL, etc.).
- **Por qué nos importa**: alternativa mainstream y bien soportada. Si Verifiers tiene problemas con multimodal, TRL es plan B sólido.
- **Decisión**: **MIRAR como alternativa**. Plan B si Verifiers no funciona. Probablemente más fricción para multi-turn complejo pero mejor soporte multimodal.

### smolagents (HuggingFace)
- **URL repo**: https://github.com/huggingface/smolagents
- **License**: Apache-2.0.
- **Filosofía**: librería minimalista (~1000 líneas core) para correr agents en pocas líneas.
- **Dos paradigmas**:
  - **CodeAgent**: agente escribe acciones como snippets de Python ejecutados en sandbox (E2B, Modal, Docker, Pyodide+Deno WebAssembly).
  - **ToolCallingAgent**: usa native tool-calling JSON (estilo OpenAI/Anthropic).
- **Modelos**: cualquier LLM (transformers local, Ollama, HF Inference, OpenAI, Anthropic, vía LiteLLM).
- **Por qué nos importa**: para construir el **baseline no-RL** muy rápido (un agente con Claude/GPT que use nuestras tools y resuelva la task) antes de invertir en training. Sirve también para generar trayectorias para SFT cold-start.
- **Decisión**: **APALANCAR para prototipado rápido**. v0 baseline = smolagents + Claude/Gemini + nuestras tools. Usar trayectorias exitosas como SFT data.

---

## Tier 4 — Probablemente NO usamos

### StreetLearn (DeepMind)
- **URL repo**: https://github.com/google-deepmind/streetlearn
- **License**: Apache-2.0.
- **Estado**: **stagnante**. El paper es de NeurIPS 2018; el repo tiene solo 13 commits y no muestra actividad reciente.
- **Cobertura**: Manhattan (56k panoramas), Pittsburgh (58k), Manhattan TOUCHDOWN (29k). Solo 2 ciudades + foco TOUCHDOWN.
- **Acceso al dataset**: hay que **pedirlo** vía formulario en el sitio del proyecto, no es bulk-download.
- **Disclaimer**: "This is not an official Google product".
- **Por qué se descarta**:
  - Solo NYC y Pittsburgh (no global).
  - Foco en navegación (RL clásica con grafo de adyacencia), no en visual reasoning.
  - Panoramas modernos (no históricos). No alinea con nuestro foco 1826-2000.
  - Sin actividad reciente.
- **Decisión**: **DESCARTAR**.

### Autonomous GIS — LLM-Geo / LLM-Find / LLM-Cat (Penn State, gladcolor)
- **URLs**:
  - LLM-Geo: https://github.com/gladcolor/LLM-Geo (workflow GIS desde NL).
  - LLM-Find: https://github.com/gladcolor/LLM-Find (data retrieval GIS, OSM/Census/ESRI/etc.).
  - LLM-Cat: https://github.com/gladcolor/LLM-Cat (cartography agent vía GPT-4o vision).
- **Foco**: agentes que ejecutan workflows GIS (análisis espacial, retrieval, cartografía) desde lenguaje natural, no geolocalización de fotos.
- **Aporte indirecto**: muestran patrones de agente que invoca herramientas GIS — relevantes si en v3 metemos tools de análisis (buffer, intersect, demographic overlay) pero no para v1.
- **Decisión**: **DESCARTAR para v1**. Mirar de reojo si en v2/v3 queremos enriquecer la familia de tools.

### Smapshot
- **URL API**: https://smapshot.heig-vd.ch/api/v1/docs/
- **URL repo API**: https://github.com/MediaComem/smapshot-api
- **Tamaño**: 200K imágenes 3D-georreferenciadas (paper FOSS4G 2022 ya hablaba de >150K, hoy en torno a 200K).
- **Pose**: 6DoF (x/y/z + roll/pitch/yaw + focal length) — no solo lat/lon, **pose completa**.
- **API**: REST, OpenAPI documented, NodeJS + PostgreSQL/PostGIS. Permite query por footprint, metadata (owner, title, date), o búsqueda por radio.
- **License**: open-sourced (verificar exacta antes de uso comercial).
- **Por qué importa**:
  - Para **fine-grained reward**: con pose 3D, podemos evaluar no solo "ubicó la foto" sino "matchea la línea de visión".
  - Imágenes históricas crowdsourced, suelen ser pre-2000.
- **Riesgo**: cobertura sesgada hacia Suiza/Europa (es proyecto suizo).
- **Decisión**: **APALANCAR para v1.5 / v2**. Para v1 alcanza con PastVu; pero Smapshot da una capa de evaluación más rica (pose) que vale la pena integrar después.

### Library of Congress / OldNYC / OldSF / SepiaTown / Historypin

| Fuente | Volumen | API | License | Decisión |
|---|---|---|---|---|
| **Library of Congress P&P** | Decenas de miles con geo metadata; mucho más sin geo | JSON HTTP API público (https://www.loc.gov/apis/) — fetch directo bloqueó pero está documentado en `LibraryOfCongress/data-exploration` GitHub | Public domain en su mayoría (varía por item) | **Apalancar como dataset** — complementa PastVu, foco US/global pre-2000. |
| **OldNYC** | ~50K fotos NYC (NYPL Milstein Collection) plotted | JSON estático en el sitio (Vanderkam liberó el geocoding como JSON) | Underlying data NYPL public domain | **Apalancar como dataset secundario** — fácil de scrape, foco urbano US. |
| **OldSF** | ~13K geo-located de 40K SF Public Library | JSON liberado por los autores | Underlying data SFPL public domain | **Apalancar igual que OldNYC**. |
| **SepiaTown** | "Thousands" mapped historical images global | Sin API moderna documentada (sitio viejo) | No claro | **Mirar y descartar** a menos que confirmemos API o scrape factible. |
| **Historypin** | Crowdsourced global, geotagged + dated | API documentada: https://historypin.github.io/api-docs/ | Mixed (varía por uploader) | **Apalancar como dataset** — API pública, cobertura global, fechas explícitas. |

Estrategia datasets: PastVu (Tier 1) como core ruso/europa-este → LoC + OldNYC + OldSF para US → Historypin para resto del mundo + crowdsourced → Smapshot (v1.5) para pose 3D rica.

---

## Tier 5 — Baselines one-shot

### ccmdi/geobench
- **URL**: https://github.com/ccmdi/geobench
- **License**: MIT.
- **Qué es**: repo chico (~49 commits) que corre LLMs (Claude, Gemini, GPT, Llama) sobre fotos de 5 mapas de GeoGuessr. Devuelve coords + país. Score por distancia.
- **Limitación**: one-shot, sin tools, sin trayectorias. Es un harness de evaluación, no un environment de RL.
- **Decisión**: **referencia de baseline**. Podemos comparar nuestro modelo vs LLMs frontier en este benchmark. **No es infra reusable**.

### Otros similares (no perseguidos)
- Repos varios en GitHub (búsqueda "geoguessr llm benchmark") tienden a ser one-off, sin mantención. No vale la pena profundizar.

---

## Trabajos recientes (últimos 6-12 meses)

Selección curada — 6 trabajos que valen la pena más allá de los Tier 2.

### 1. GeoBrowse — Geolocation Benchmark for Agentic Tool Use with Expert-Annotated Reasoning Traces
- **URL**: https://arxiv.org/abs/2604.04017
- **Repo**: https://github.com/ornamentt/GeoBrowse
- **Autores**: Xinyu Geng, Yanjing Xiao, Yuyang Zhang, Hanwen Wang, Xinyan Liu, Rui Min, Tianqing Fang, Yi R. Fung.
- **Fecha**: 2026-04-05 (v1).
- **License**: CC BY-NC-SA 4.0 (no comercial).
- **Resumen**: benchmark de geolocalización agéntico con dos niveles. Provee:
  - 5 tools "think-with-image" (visuales).
  - 4 tools "knowledge-intensive" (multi-hop verification).
  - Workflow agéntico GATE.
  - **Trazas paso-a-paso anotadas por expertos**, ground en evidencia verificable, para análisis trayectorial.
  - Level 1 = composición de cues fragmentados; Level 2 = long-tail knowledge + entidades obfuscadas.
- **Finding clave**: **planes coherentes de tool-use level-specific** > más tool calls. Más no es mejor.
- **Por qué nos importa**: es el trabajo más cercano conceptualmente a lo que queremos construir. Las trazas anotadas por expertos son material de SFT cold-start de altísima calidad. El framework GATE puede inspirar nuestra arquitectura de tools.
- **Decisión**: **LEER EN SERIO** + revisar repo + considerar incluir su benchmark en eval suite.

### 2. SpotAgent — Grounding Visual Geo-localization through Agentic Reasoning
- **URL**: https://arxiv.org/abs/2602.09463 (v3: 2026-03-02).
- **Autores**: Furong Jia, Ling Dai, Wenjin Deng, Fan Zhang, Chen Hu, Daxin Jiang, Yu Liu.
- **Resumen**: pipeline de **post-training en 3 etapas**:
  1. SFT inicial.
  2. **Agentic Cold Start** con trayectorias sintetizadas vía multi-agent framework.
  3. RL con **Spatially-Aware Dynamic Filtering** strategy.
  - Tools: web search + maps. Patrón ReAct.
- **Por qué nos importa**: receta de training **complementaria a GeoVista**. La idea de generar trayectorias de cold-start con un multi-agent framework (en vez de anotación humana) es escalable y aplicable a nosotros. El "Spatially-Aware Dynamic Filtering" probablemente filtra rollouts por calidad espacial — útil para nuestro reward.
- **Decisión**: **LEER EN SERIO**. Comparar con GeoVista para decidir cuál pipeline replicar primero o si combinar.

### 3. GEO-Detective — Unveiling Location Privacy Risks in Images with LLM Agents
- **URL**: https://arxiv.org/abs/2511.22441 (2025-11-27).
- **Autores**: Xinyu Zhang, Yixin Wu, Boyang Zhang, Chenhao Lin, Chao Shen, Michael Backes, Yang Zhang.
- **Resumen**: agente con procedimiento de 4 pasos que **selecciona estrategia adaptativa según dificultad de la imagen**. Tools: visual reverse search (emula cómo humanos buscan clues geográficos externos). +11.1% mejora a country level, +5.2% a fine-grained vs baseline.
- **Por qué nos importa**:
  - Coincidencia nominal con nuestro proyecto (atención: "GEO-Detective" ≠ "GeoDetective Envs", chequear si hay risk de confusión).
  - El **adaptive strategy selection según dificultad** es una idea fuerte: el agente elige qué tools usar según la imagen, no follow-up rígido. Nos sirve.
  - Visual reverse search como tool central — algo que probablemente queramos integrar.
  - Foco privacidad/social media (no histórico) — diferente al nuestro pero la mecánica de tools es transferible.
- **Decisión**: **MIRAR ABSTRACT + leer secciones de tools y procedure**. Posible inspiración para "tool selection adaptativa".

### 4. GeoChain — Multimodal Chain-of-Thought for Geographic Reasoning (EMNLP 2025 Findings)
- **URL**: https://arxiv.org/abs/2506.00785
- **Resumen**: benchmark **muy grande**:
  - 1.46M imágenes de Mapillary (street-level).
  - 30M+ pares Q&A en cadenas de 21 pasos.
  - 4 categorías de razonamiento: visual, spatial, cultural, precise geolocation.
  - Anotación con segmentación semántica (150 clases) + visual locatability score.
  - Eval sub-set de 2,088 imágenes para frontier MLLMs (GPT-4.1, Claude 3.7, Gemini 2.5).
- **Findings**: modelos frontier **fallan en visual grounding, razonamiento errático, peor con complejidad creciente**.
- **Por qué nos importa**: **dataset enorme** que puede alimentar SFT pre-tuning antes de cold-start. Las cadenas de 21 pasos son material de razonamiento estructurado abundante y barato.
- **Limitación**: imágenes Mapillary modernas, no históricas. Pero el patrón de razonamiento se transfiere.
- **Decisión**: **MIRAR DATASET**. Posible fuente de pre-training para reasoning patterns. Bajo prioridad inmediata, alta prioridad si tenemos un modelo subentrenado en CoT.

### 5. GeoReasoner — Geo-localization with Reasoning in Street Views using a LVLM
- **URL**: https://arxiv.org/abs/2406.18572 (jun 2024 — fuera de la ventana 6-12 meses pero referenciado por todos los recientes; relevante).
- **Resumen**: predecesor conceptual. LVLM augmented con conocimiento de inferencia humana para Street View. Establece el paradigma "reasoning-first".
- **Por qué nos importa**: trabajo seminal del paradigma. Citado por GeoVista, GeoRC, SpotAgent. Vale leer una vez como contexto.
- **Decisión**: **MIRAR ABSTRACT** como background, no profundizar.

### 6. Doxing via the Lens — Privacy Leakage in Image Geolocation for Agentic MLRMs
- **URL**: https://arxiv.org/abs/2504.19373 (abr 2025, v2 reciente).
- **Resumen**: estudio de privacidad sobre cómo agentes multimodales con razonamiento pueden hacer doxing efectivo desde imágenes. Identifica vulnerabilidades.
- **Por qué nos importa**: obligación ética. Si nuestro proyecto produce un agente bueno geolocalizando, tenemos que pensar en abuso. El paper documenta los vectores. Útil para sección de responsabilidad/ética del repo.
- **Decisión**: **MIRAR ABSTRACT** + considerar para sección Ethics del README cuando llegue el momento.

---

## Síntesis

### Lo que apalancamos como receta (no código)
- **GeoVista**: SFT cold-start + RL con hierarchical reward → **receta principal**.
- **GeoAgent**: consistency-agent verifier + geo-similarity reward → **complemento de reward**.
- **Pigeon-eval**: Street View como tool parametrizable (heading/pitch/fov), no como imagen estática → **diseño de tool**.
- **SpotAgent**: trayectorias de cold-start sintetizadas vía multi-agent (en vez de anotar humanas) + filtering espacial dinámico en RL → **receta complementaria**.
- **GeoBrowse**: separación de tools "think-with-image" vs "knowledge-intensive" + planes level-specific > más calls → **arquitectura de tools**.
- **GeoRC**: razonamiento auditable importa, no solo distancia; LLM-as-judge para reasoning quality → **eval de cadena de razonamiento**.

### Lo que apalancamos como código / paquete reusable (más allá de Tier 1)
- **Verifiers** (Prime Intellect, MIT, muy activo): backbone candidato para nuestro environment de RL multi-turn. **Validar multimodal antes de comprometerse**.
- **TRL** (HuggingFace, Apache-2.0): plan B con `GRPOTrainer` + OpenEnv si Verifiers falla en multimodal.
- **smolagents** (HuggingFace, Apache-2.0): para construir baseline v0 sin RL, generar trayectorias para SFT cold-start, y prototipar tool design rápido.
- **Smapshot API** (open-source, REST): para v1.5 — pose 3D enriquece el reward más allá de lat/lon.
- **Library of Congress JSON API** + **OldNYC/OldSF JSON dumps** + **Historypin API**: datasets secundarios complementarios a PastVu.

### Lo que descartamos y por qué
- **StreetLearn** (DeepMind): solo NYC + Pittsburgh, no histórico, paper de 2018, repo stagnante, dataset por solicitud.
- **LLM-Geo / LLM-Find / LLM-Cat** (Penn State): foco workflow GIS, no geolocation de fotos. Posible reconsideración en v3 si entran tools de análisis espacial.
- **SepiaTown**: sin API moderna documentada, sitio aparenta abandonado.
- **ccmdi/geobench y similares one-shot**: solo como referencia de baseline; no infra reusable.

### Cosas inesperadas que valen la pena destacar
1. **Verifiers v0.1.14 fue liberado HOY (2026-05-07)** — proyecto en desarrollo extremadamente activo. Riesgo: API churn. Oportunidad: tracking close puede destrabar features que necesitemos.
2. **GeoBrowse libera trazas anotadas por expertos** (CC BY-NC-SA): material de altísima calidad para SFT cold-start. Probablemente lo más cerca que vamos a estar de "data lista" para nuestra primera ronda de SFT.
3. **GeoRC encuentra que VLMs aciertan pero alucinan**: confirma fuertemente la tesis de que **rewardear la cadena de razonamiento** (no solo la coordenada) es la diferencia. Esto cambia el diseño del reward.
4. **SpotAgent sintetiza cold-start data con multi-agent framework**: alternativa a anotar humanos. Si funciona, escala mucho más rápido. Receta directamente aplicable.
5. **GeoBrowse's finding "coherent plans > more tool calls"**: impacta nuestro reward — penalizar tool spam, premiar planes coherentes.
6. **Smapshot pose 6DoF**: la mayoría de datasets de geo dan lat/lon; Smapshot da línea de visión completa. Esto habilita métricas mucho más finas.

### Lo que falta investigar (deuda)
- **Verifiers multimodal**: confirmar con un experimento de 1 día si soporta imágenes nativamente. Es el bloqueante crítico de la decisión Tier 3.
- **GeoBrowse repo (`ornamentt/GeoBrowse`)**: inspeccionar tools concretos (5 visuales + 4 knowledge) para diseñar nuestro tool set.
- **License exacta de Smapshot images**: confirmar antes de incluir en dataset de training (pueden tener restricciones por uploader).
- **Library of Congress fetch directo**: la API devolvió 403 al WebFetch — probablemente requiere User-Agent custom o headers. Validar acceso programático antes de comprometerse al dataset.
- **PastVu cross-check**: el deep dive de Tier 1 debería confirmar si efectivamente PastVu tiene tantas fotos histórico-georeferenciadas como creemos. Si no, **LoC + Historypin + OldNYC/OldSF + Smapshot** suben de prioridad.
- **GeoRC chains acceso**: el paper dice "open-sourced". Verificar si las 800 chains están descargables. Si sí, son SFT data de oro.
- **Doxing via the Lens**: leer en serio antes de release público — nuestra postura ética debe estar clara.
- **Hierarchical reward en GeoVista**: el abstract no detalla la fórmula. Hay que leer el paper completo para replicar bien.

---

## Fuentes

- [GeoVista — arxiv 2511.15705](https://arxiv.org/abs/2511.15705)
- [GeoVista — repo](https://github.com/ekonwang/GeoVista)
- [GeoVista — sitio](https://ekonwang.github.io/geo-vista/)
- [GeoAgent — arxiv 2602.12617](https://arxiv.org/abs/2602.12617)
- [Pigeon-eval — arxiv 2502.14412](https://arxiv.org/abs/2502.14412)
- [GeoRC — arxiv 2601.21278](https://arxiv.org/abs/2601.21278)
- [Verifiers — repo](https://github.com/PrimeIntellect-ai/verifiers)
- [Prime Intellect Docs — environments](https://docs.primeintellect.ai/tutorials-environments/environments)
- [TRL — repo](https://github.com/huggingface/trl)
- [TRL GRPO docs](https://huggingface.co/docs/trl/grpo_trainer)
- [TRL OpenEnv](https://huggingface.co/docs/trl/main/en/openenv)
- [smolagents — repo](https://github.com/huggingface/smolagents)
- [StreetLearn — repo](https://github.com/google-deepmind/streetlearn)
- [LLM-Geo — repo](https://github.com/gladcolor/LLM-Geo)
- [LLM-Find — repo](https://github.com/gladcolor/LLM-Find)
- [LLM-Cat — repo](https://github.com/gladcolor/LLM-Cat)
- [Smapshot API repo](https://github.com/MediaComem/smapshot-api)
- [Smapshot API docs](https://smapshot.heig-vd.ch/api/v1/docs/)
- [Smapshot — paper FOSS4G 2022](https://isprs-archives.copernicus.org/articles/XLVIII-4-W1-2022/217/2022/isprs-archives-XLVIII-4-W1-2022-217-2022.pdf)
- [Library of Congress APIs](https://www.loc.gov/apis/)
- [LoC data-exploration (notebooks)](https://github.com/LibraryOfCongress/data-exploration)
- [OldNYC](https://www.oldnyc.org/)
- [Historypin API docs](https://historypin.github.io/api-docs/)
- [SepiaTown](https://sepiatown.com/)
- [ccmdi/geobench](https://github.com/ccmdi/geobench)
- [GeoBrowse — arxiv 2604.04017](https://arxiv.org/abs/2604.04017)
- [SpotAgent — arxiv 2602.09463](https://arxiv.org/abs/2602.09463)
- [GEO-Detective — arxiv 2511.22441](https://arxiv.org/abs/2511.22441)
- [GeoChain — arxiv 2506.00785](https://arxiv.org/abs/2506.00785)
- [GeoReasoner — arxiv 2406.18572](https://arxiv.org/abs/2406.18572)
- [Doxing via the Lens — arxiv 2504.19373](https://arxiv.org/abs/2504.19373)
