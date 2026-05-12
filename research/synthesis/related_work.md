# Related Work — Posición de GeoDetective Benchmark

> **Status**: draft 2026-05-12. Documento orientado a publicación: compara GeoDetective vs benchmarks de geo-localización **y** vs frameworks de evaluación del proceso de razonamiento. Identifica el hueco que llenamos.
>
> No es el mismo doc que `related_work_decisions.md` — ese es **interno** (qué piezas apalancar para construir el environment). Este es **externo** (qué papers citar, dónde nos ubicamos, qué afirmamos como contribución).
>
> Material de referencia: `research/notes/leverage_landscape.md` (24 proyectos), `research/notes/geobenchx_deep_dive.md`, `synthetic-research-envs/research/synthesis/related_work_corral.md`.

---

## 1. El paisaje en una tabla

Categorización revisada post-Codex 2026-05-12 (taxonomía original mezclaba ejes). Las familias son ortogonales: un paper puede caer en varias.

### 1.A — Geo-localización por outcome

| Familia | Ejemplos | Qué miden |
|---|---|---|
| **CNN/VLM single-shot tradicional** | PlaNet (Weyand 2016), Im2GPS, GeoEstimation, GPT-4V/Gemini geo demos | Distancia geodésica; foto moderna; no separa memoria de inferencia |
| **Agentic geoloc moderno** | GeoVista (Wang 2025), GeoAgent (2026), Pigeon-eval (Stanford 2025), SpotAgent (2026), GeoChain (2025) | Distancia + parcial trace metrics; corpus Street View / Mapillary contemporáneo |

### 1.B — Reasoning-chain benchmarks (eval de cadenas de razonamiento)

| Ejemplos | Qué miden | Limitación |
|---|---|---|
| **GeoRC** (2026) — 800 chains GeoGuessr champions sobre 500 escenas | Quality del razonamiento via LLM-as-judge holístico | Modern photos; no graph descompuesto; no agentic con tools |
| **GTPred** (Li et al. 2026) — 370 imgs / 120 años / 15 modelos | Reasoning chains con ground-truth annotated **+** geo-temporal prediction | No es agentic (single-shot MLLM o CoT); corpus chico; no anti-shortcut explícito |

### 1.C — Agentic benchmarks con trayectorias anotadas

| Ejemplos | Qué miden | Limitación |
|---|---|---|
| **GeoBrowse** (2026) — agentic workflow GATE, 5 image-tools + 4 knowledge-tools, **expert-annotated stepwise traces** con verifiable evidence | Tool-use plan + reaching annotated key evidence steps + accuracy | Corpus no específicamente histórico; eval step-level, no grafo epistemológico tipo CORRAL |
| **GeoBenchX** (Krechetova 2025) | Plan correcto de tool calls vs referencia | Datos preloaded; tareas GIS analíticas, no investigación abierta |

### 1.D — Process-graph eval frameworks (no específicos a geo)

| Ejemplos | Qué miden |
|---|---|
| **CORRAL** (Ríos-García et al. 2026) | Grafo epistemológico H/T/E/J/U/C + 7 motifs + 10 breakdowns; dominio: química/física simulada |

### 1.E — Datasets de foto histórica (sin benchmark estándar)

| Recurso | Tamaño | Tiene benchmark? |
|---|---|---|
| **PastVu** | 2.08M records, 676K elegibles 1850-1950 (audit #3) | No, lo armamos nosotros |
| **Smapshot** | 200K imágenes + 6DoF pose | No, API REST |
| **Library of Congress P&P** | Decenas de miles | No, API JSON |
| **OldNYC / OldSF / SepiaTown / Historypin / Bundesarchiv** | Variable | No |

### 1.F — General agent benchmarks (referencia, no comparable directo)

| Ejemplos | Comentario |
|---|---|
| **GAIA** (Mialon et al. 2023) | Multi-step web research + tool use; outcome binario; cited como antecedente metodológico de agentic benchmarks. NO mide proceso. |
| **AgentBench** (Liu et al. 2023) | 8 dominios; outcome task-specific. NO mide proceso. |

### Dónde nos ubicamos

GeoDetective combina simultáneamente: **agentic geoloc** (1.A) + **reasoning chain eval** (1.B) + **agentic con trazas anotadas** (1.C) + **process-graph framework CORRAL adaptado** (1.D) + **corpus histórico con anti-shortcut filtering explícito** (1.E con engineering propio). Cada antecedente cubre parte; **la intersección no está cubierta**.

---

## 2. Geo-localización agéntica moderna (lo más cercano)

### GeoVista — Web-Augmented Agentic Visual Reasoning for Geolocalization
- **Wang et al., 2025** (arXiv:2511.15705). Fudan / Tencent Hunyuan / Tsinghua.
- **Tools**: `image_zoom`, `web_search`. Stack mínimo.
- **Receta**: cold-start SFT sobre trayectorias multi-turn + RL con **hierarchical reward** (país → región → ciudad → coords).
- **Modelo open**: `GeoVista-RL-6k-7B`. Compete con Gemini-2.5-flash y GPT-5.
- **Corpus**: GeoBench-Vista, fotos + panoramas globales modernos.
- **Lo que les falta vs nosotros**: corpus histórico, dating, tools temporal-aware (OpenHistoricalMap), eval del proceso, brief abierto.

### GeoAgent — Reinforced Geographic Characteristics
- **arXiv:2602.12617**, feb 2026.
- **Reward novedoso**: (a) geo-similarity (spatial + semantic) y (b) **consistency-agent verifier**: un segundo agente intenta reproducir la respuesta desde el CoT del primero sin ver la pregunta. Si lo logra, el CoT está "well-grounded".
- **Corpus**: GeoSeek (CoT anotado por geo-experts).
- **Lo relevante vs nosotros**: el consistency check es un anti-hallucination que **complementa** lo que mediríamos vía grafo CORRAL (otra forma de detectar `unsupported judgment`).
- **Lo que les falta**: foto histórica, brief abierto, anti-shortcut adversarial sobre corpus.

### Pigeon-eval — VLMs precise geo via Street View iteration
- **Stanford, arXiv:2502.14412**, feb 2025.
- **Patrón clave de tool**: el agente controla `heading`, `pitch`, `fov` de Street View Static API, itera 5 veces refinando. Reduce error 30.6% vs single-shot.
- **Lo que aprovechamos**: nuestro `street_view` tool sigue ese patrón (heading/pitch/contact_sheet) — lo documentamos en `related_work_decisions.md`.
- **Lo que les falta**: foto histórica (Street View no la ve), reasoning chain auditable, tools más allá de SV.

### GeoRC — Benchmark for Geolocation Reasoning Chains
- **arXiv:2601.21278**, 2026.
- **Contenido**: 800 cadenas de razonamiento de Champion-tier GeoGuessr (incluye el world champion actual) sobre 500 escenas.
- **Hallazgos clave**:
  - Closed-source VLMs (Gemini, GPT-5) rivalizan con humanos en **predecir locación** pero **fallan en producir razonamiento auditable**.
  - Small open-weight VLMs (Llama, Qwen) están al nivel de un baseline que **alucina la cadena conociendo la respuesta** (sin imagen).
  - Documenta: hallucinations, misattributions, red herrings, fallas en atributos low-pixel.
- **Eval**: LLM-as-judge para scoring del razonamiento (Qwen 3 correlaciona mejor con expertos).
- **Lo más relevante para nosotros**: confirma empíricamente que **outcome ≠ proceso**. Es el antecedente más directo de nuestro process_eval.
- **Lo que les falta**: foto histórica, no aplican CORRAL-style epistemic graphs (su eval es LLM-as-judge holístico, no descomponen el grafo). Su LLM-judge es nuestro complemento natural — podemos comparar metodologías.

### GeoBrowse — Agentic Benchmark con tools de imagen + conocimiento
- **arXiv:2604.04017**, 2026.
- **Setup**: workflow agentic "GATE" con **5 think-with-image tools** + **4 knowledge-intensive tools** sobre 2 difficulty levels (L1: visual cue extraction; L2: long-tail knowledge con entidades obfuscadas).
- **Eval**: **expert-annotated stepwise traces grounded in verifiable evidence**, scoring de tool-use **plans** (no solo más tool calls) + reaching annotated key evidence steps + reliability en integrar evidencia a la decisión final.
- **Lo más cercano conceptualmente a nosotros**: tiene anti-shortcut implícito (L2 obfusca entidades) + process metrics step-level + agentic geoloc. Es el antecedente más directo del eje agentic con trazas anotadas.
- **Lo que les falta vs nosotros**: corpus no específicamente histórico (timeline/scale del corpus unstated en abstract — verificar al hacer deep dive); eval step-level y plan-based, no descompuesto en grafo epistemológico H/T/E/J/U/C; sin dating como ground truth dual.
- **Acción**: deep dive pendiente para entender escala del corpus y si tienen foto histórica.

### SpotAgent / GeoChain / GeoReasoner
- Recetas de training (SFT + RL) para geo-loc moderno. Datasets propios. No son benchmarks de evaluación primarios — son agentes que reportan resultados sobre datasets establecidos.
- Útiles para **comparación**: cuando nuestro benchmark esté maduro, estos modelos open-source son baselines naturales (subset de fotos modernas de nuestro corpus si lo construimos, o cualquier eval transferible).

### GEO-Detective (privacy angle)
- **arXiv:2511.22441**, 2025. **Coincidencia de nombre**, foco totalmente distinto: privacidad — qué tan fácil es localizar a alguien desde su foto de redes sociales con un agente OSINT. 4 steps con reverse image search.
- **Nada que tomar** salvo el nombre — es advertencia de que nuestro proyecto necesita rename eventualmente, ya está en deuda explícita.

---

## 3. Geo-localización histórica — el panorama

**Corrección post-Codex** (2026-05-12): el framing previo de "desierto histórico" era overclaim. **GTPred** (Li et al. 2026) existe y cubre geo-temporal (370 imágenes, 120 años, foto moderna + histórica, reasoning chains anotadas). Ajustamos el reclamo.

### Trabajos relevantes

| Paper / Dataset | Tipo | Histórico? | Agentic? | Process eval? | Anti-shortcut? |
|---|---|---|---|---|---|
| **GTPred** (2026) | Benchmark MLLM | Sí (120 años) | No (CoT/single-shot) | Sí (annotated reasoning chains) | No reportado |
| **GeoBrowse** (2026) | Benchmark agentic | No reportado | Sí (9 tools) | Sí (stepwise traces) | Implícito (L2 obfusca entidades) |
| **PastVu, Smapshot, LoC P&P, OldNYC, OldSF, Historypin, Bundesarchiv, Europeana** | Datasets crowdsourced | Sí | — | — | — |

### Lo que GeoDetective aporta sobre estos

| Aporte | Antecedente parcial | Nuestra extensión |
|---|---|---|
| Anti-shortcut filtering **explícito** sobre corpus histórico | GTPred (sin pipeline reportado), GeoBrowse (entity obfuscation L2) | Pipeline completo documentado: clean_image (#22), blacklist runtime per-photo (#23), hash perceptual hard reject (#24), atacker adversarial GPT-4o N=3 con threshold canon (#24) |
| **Agentic** sobre foto histórica | GTPred (no agentic), GeoBrowse (no específicamente histórico) | 12 tools incluyendo `historical_query` OHM temporal-aware |
| **Grafo epistemológico CORRAL** sobre geoloc | GeoRC (LLM-as-judge holístico), GeoBrowse (step-level plan eval) | H/T/E/J/U/C + motifs/breakdowns (process_eval_design.md) |
| **Dating + locating dual** como ground truth | GTPred (geo-temporal, sí) | Iguala el dual; ganamos en el otro eje (agentic + CORRAL) |

**Lo que aún podemos defender como aporte distintivo**: somos el primer benchmark **agéntico sobre foto histórica** que combina **anti-shortcut filtering explícito + process eval estilo CORRAL**. Cada componente tiene antecedente parcial; la **intersección** sigue vacía. No es "primer benchmark histórico" — es "primer benchmark con esta combinación específica de propiedades". Más honesto, sigue defendible.

---

## 4. Process evaluation de agentes LLM

### CORRAL — AI scientists produce results without reasoning scientifically
- **Ríos-García et al., 2026** (arXiv:2604.18805). Friedrich Schiller University Jena / IIT Delhi. **109 páginas, MIT license, código + datasets en HF.**
- **Aporte central**: framework para anotar **grafos epistemológicos** de trazas (6 nodos H/T/E/J/U/C + 6 edges) + inventario de **7 productive motifs y 10 breakdowns** (Tabla H.15 lista 11 con `stalled_revision` como variante discontinua de `fixed_belief_trace`). Auto-anotador Claude 4.5 Sonnet con 95.7% agreement vs humanos.
- **Hallazgos en química/física**: base model explica 41.4% de la varianza, scaffold solo 1.5%. 68% evidence non-uptake, solo 26% refutation-driven belief revision.
- **Cita textual clave** del paper: *"Until reasoning itself becomes a training target, the scientific knowledge produced by such agents cannot be justified by the process that generated it."*
- **Nuestra relación**: replicamos su metodología en geo-detective (ver `process_eval_design.md`) y **agregamos 5 patterns** específicos del dominio (proxy substitution, tool channel mismatch, geocoding loop, visual hallucination, language pivot productive).
- **Posicionamiento honesto**: somos consumidores de su framework, no inventores. La novedad nuestra está en **aplicarlo a perception+reasoning + brief abierto**, no en el framework en sí.

### GAIA — General AI Assistants Benchmark
- **Mialon et al., 2023** (arXiv:2311.12983). Meta + HuggingFace.
- **Contenido**: 466 preguntas requiring multi-step web research, tool use, multimodal. Outcome-based (exact match en respuesta).
- **Lo que les falta**: no descomponen el grafo de razonamiento. Process eval = inexistente más allá de "respondió o no". Casi todos los agentes actuales sub-50% accuracy.
- **Posición nuestra**: GeoDetective es como GAIA pero (a) dominio único, (b) con process metrics estilo CORRAL, (c) outcome continuo (distancia) no binario.

### AgentBench
- **Liu et al., 2023** (arXiv:2308.03688). Tsinghua.
- 8 dominios (OS, DB, web, etc.). Outcome metrics task-specific. No process graph.
- **Relevancia**: ejemplo de benchmark multi-dominio que se cita en intro. No es competencia directa.

### Otros (mencionados sin deep dive)
- **AppWorld** (Trivedi 2024): app interaction tasks, outcome-based.
- **WebArena** (Zhou 2023): web navigation, outcome-based.
- **ProcessBench** (Zheng 2024): step-level math error detection — más cercano a process eval pero específico a matemática y formal proofs, no a investigación abierta.

---

## 5. Anti-shortcut adversarial filtering en benchmarks

Pieza menos cubierta en literatura. Lo que existe:

- **LMSYS / Chatbot Arena**: contaminación de testset por leakage en pretraining, soluciones ad-hoc.
- **GeoVista** discute brevemente filtering de fotos con metadata extractable. No publica el filtro.
- **CORRAL** no usa adversarial filtering — sus simuladores generan tareas sintéticas que no pueden filtrarse por "memoria de pretraining".

**Nuestra contribución metodológica** (epic #21):
- **Paso 0 clean_image** (#22): strip EXIF + crop watermark + RGBA→RGB. Quita shortcut metadata.
- **Blacklist runtime per-photo** (#23): dominios bloqueados varían por foto (provider + source).
- **Hash perceptual hard reject** (#24): si una tool devuelve un hit que matchea el target, se oculta. No solo flag.
- **Atacante adversarial GPT-4o sin tools** (#24): N=3 corridas, threshold `dist<10km AND conf≥media`. Sobre 180 fotos del sample: 101 sobreviven (56%).

Es **el threat model más explícito** que vimos en geo-loc agentic benchmarks. Material publicable per se.

---

## 6. Posicionamiento de GeoDetective (revisado post-Codex)

GeoDetective es el primer benchmark que combina simultáneamente:

| Dimensión | Antecedente más fuerte | Lo que sumamos |
|---|---|---|
| **Agentic + open brief + perception VLM** | CORRAL (sin perception), GeoVista (sin open brief), GeoBrowse (sin open brief, su corpus aparenta ser dirigido) | VLM perception + brief libre "¿dónde y cuándo?" con 12 tools tipadas |
| **Foto histórica con dating + locating dual + filtrado adversarial documentado** | GTPred (geo-temporal, sin filtro), Smapshot + LoC (datasets sin benchmark) | Tools temporal-aware (`historical_query` OHM CC0) + ground truth dual + pipeline #21 documentado |
| **Process eval estilo grafo epistemológico CORRAL en geo-loc** | GeoRC (LLM-as-judge holístico, no grafo), GeoBrowse (step-level plan eval, no grafo H/T/E/J/U/C) | Grafo CORRAL adaptado + 2 motifs nuevos + 1 breakdown nuevo + 4 subtipos/anti-motifs (proceso_eval_design.md) |

Cada uno individualmente está cubierto parcialmente; **la intersección sigue vacía y defendible**. Reframing: no afirmamos novelty per-dimensión, afirmamos novelty per-combinación.

### Limitaciones honestas que el paper debe declarar

- **Single attacker** (GPT-4o) en el corpus actual. Multi-modelo es deuda (#24 reported).
- **Process annotator es Claude-judged**: no es ground truth, validado por agreement humano sobre subset.
- **Foto histórica geográficamente sesgada** (62% Rusia post-audit #3). Distribución no representativa global.
- **Tool stack acotado** (12 tools); no cubre archivos institucionales (LoC API, MapWarper, Sanborn). Deuda explícita.
- **ToS Google Maps** prohíbe usar Maps Content para training/validating ML. Versión benchmark es defendible para inference; versión env de RL no — está deuda futura.
- **El environment de RL** queda como deuda explícita; este paper presenta el **benchmark**, no la versión training.

---

## 7. Estructura de citas tentativa para el paper

| Sección | Citas core |
|---|---|
| Intro — motivación | CORRAL (process matters), GeoRC (VLMs alucinan razonamiento), Pigeon (humans use heading control) |
| Related work — geo-loc | PlaNet, GeoVista, GeoAgent, Pigeon-eval, GeoRC, SpotAgent, GeoBrowse |
| Related work — process eval | CORRAL, GAIA, AgentBench, ProcessBench |
| Related work — corpus histórico | PastVu (dataset paper si existe), Smapshot, Library of Congress |
| Related work — anti-shortcut | GeoVista (filtering casual), CORRAL (synthetic immunity) |
| Method — corpus filtering | Nuestro work (#21-#24). Único antecedente directo: GeoVista filtering. |
| Method — tool stack | OpenHistoricalMap (CC0 tool), Google Maps Static (Pigeon pattern), Tavily, Nominatim |
| Method — process eval | CORRAL framework adoptado con extensiones documentadas en `process_eval_design.md` |
| Eval | GeoVista benchmark (comparación parcial si hay overlap), GeoRC reasoning chain quality |
| Discussion — limitations | ToS Google Maps (TOS doc), CORRAL (process scoring caveats) |

---

## 8. Pendientes — papers a leer / verificar antes de citar formalmente

**Importante** (post-Codex): si un paper no está leído deep, no puede usarse para framing fuerte en el paper. Soft-mention OK; comparación específica NO. Esta sección lista honestamente qué tenemos y qué no.

### Leídos a profundidad (cita robusta)

1. **CORRAL** (Ríos-García et al. 2026) — leído deep en `../synthetic-research-envs/research/notes/corral_paper_fulltext.txt`. Síntesis canon en sister project.
2. **GeoVista** (Wang 2025) — leído deep dive (`research/notes/leverage_landscape.md`). Verificar últimos updates del repo antes de citar.

### Verificados via abstract (cita soft OK, no framing fuerte)

3. **GTPred** (Li et al. 2026) — verificado via WebFetch arxiv abstract (2026-05-12). 370 imgs, 120 años, annotated reasoning. **Deep dive pendiente** antes de comparación cuantitativa.
4. **GeoBrowse** (2026) — verificado via WebFetch arxiv abstract (2026-05-12). 9 tools agentic + expert-annotated stepwise traces. **Deep dive pendiente** antes de comparar corpus size / scope.

### Vistos en leverage_landscape (abstract solo, NO leídos paper)

5. **GeoAgent** (arXiv:2602.12617) — consistency-agent verifier; reward design relevante.
6. **Pigeon-eval** (Stanford 2025) — Street View iteration pattern.
7. **GeoRC** (arXiv:2601.21278) — 800 reasoning chains, LLM-as-judge para reasoning quality.
8. **SpotAgent** (arXiv:2602.09463) — SFT + agentic cold-start + RL training recipe.
9. **GeoChain** (arXiv:2506.00785) — 1.46M Mapillary, 30M Q&A in 21-step CoT.

**Acción**: si los citamos en related work del paper, hacer deep dive de los 5 pendientes (item 3 y 5-9) en `research/notes/`. Hasta entonces solo mencionar como contexto, no como punto de comparación específico.

### No leídos (referencia metodológica solamente)

10. **GAIA** (Mialon et al. 2023), **AgentBench** (Liu et al. 2023), **ProcessBench** (Zheng 2024) — mencionar como antecedente metodológico de agentic benchmarks / process-level eval. NO comparación específica.
11. **PastVu como dataset paper** — chequear si existe paper formal o solo el sitio + scraping reports. Probable que segundo. Cite el sitio (`pastvu.com`) + el audit propio (#3 / E006).
