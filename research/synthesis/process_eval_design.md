# Process Evaluation Design — CORRAL adaptado a geo-detective

> **Status**: CANON (draft inicial 2026-05-12). Define cómo se evalúa el **proceso investigativo** del agente, no solo el outcome final. Mapping del framework de Ríos-García et al. (CORRAL, 2026) al dominio geo-detective con ejemplos reales del pilot E005.
>
> Documento hermano: `related_work.md` (posiciona vs CORRAL + geo-loc agents) · `findings_so_far.md` (corpus de evidencia experimental). Origen del framework: `synthetic-research-envs/research/synthesis/related_work_corral.md` (síntesis del paper completo).
>
> **Implementación**: este doc es diseño. El annotator stub se construye en otra iteración una vez aprobado el mapping (task #6).

---

## 1. Motivación

Hoy GeoDetective mide **distancia geodésica** y **error de año**. Eso captura "qué tan cerca llegó" pero no "qué tan bien investigó". Dos trazas con la misma distancia pueden tener calidad de proceso muy distinta:

- Trace A: usa 12 tools en orden coherente, formula 3 hipótesis competidoras, descarta una con evidencia contradictoria, somete a 50 km.
- Trace B: hace 12 `web_search` consecutivos, nunca abre `street_view`, somete capital del país a 50 km.

Hoy ambas son indistinguibles. **Una policy entrenada con reward = -distance aprende B**, porque es más barato. Eso es exactamente el patrón observado en E005 (pilot ReAct sobre 6 fotos): el agente actúa como web-search bot.

CORRAL ("AI scientists produce results without reasoning scientifically", Ríos-García et al. 2026) introduce un framework para evaluar el proceso epistemológico de un agente vía grafos de su trayectoria. **Replicamos su metodología en nuestro dominio**, agregamos patterns específicos que CORRAL no captura (perception + open brief + dating-locating dual), y conectamos process metrics con outcome metrics.

> **La afirmación que el paper de GeoDetective puede sostener** (revisada post-Codex, paper landscape verificado): somos el primer benchmark **agéntico** de geo-investigación sobre **foto histórica** que **integra anti-shortcut filtering explícito** y **proceso epistemológico estilo CORRAL** además de outcome. **GTPred** (Li et al. 2026, 370 imgs / 120 años) ya mide reasoning chains en foto geo-temporal pero no es agentic. **GeoBrowse** (2026) mide tool-use trajectories agentic pero su corpus no es histórico específicamente. La hipótesis empírica derivada de CORRAL (base model >> scaffold) es testeable aquí en un dominio con perception, no solo en química/física simulada.

---

## 2. Vocabulario CORRAL — definiciones operativas

### 2.1 Nodos (6 tipos)

| Sigla | Nombre | Definición CORRAL | Adaptación geo-detective | Ejemplo del E005 |
|---|---|---|---|---|
| **H** | Hypothesis | "candidate explanation or working assumption about the system, a revisable claim, proposal, suggestion, or current best guess" | Afirmación revisable sobre dónde / cuándo fue tomada la foto, o sobre features visuales identificables. | Tomsk v1 step 3: "ciudad provincial siberiana con kostel a la izquierda y sobor blanco al centro" |
| **T** | Test | "procedure designed/proposed to evaluate a hypothesis" | Tool call invocada con el fin de probar/refinar una hipótesis específica. | Tomsk v1 step 5a: `web_search("костел слева собор справа Тобольск")` para testear hipótesis "Tobolsk" |
| **E** | Evidence | "observation, computational result, or factual statement obtained from the environment" | Output de tool call **o input perceptual primario** (foto target, crops). Modalidad anotada (`textual` / `visual_primary` / `visual_crop` / `coords` / `osm_feature`). | Tomsk v1 step 6: web result "Воскресенская гора Томск" (`textual`). Step 1: foto target inicial (`visual_primary`). Step 1 crops: kostel a la izquierda (`visual_crop`). |
| **J** | Judgment | "qualitative assessment / evaluation over evidence" | Inferencia del agente sobre evidencia: "esto se parece a", "esto descarta", "los tranvías indican pre-1940". | Molodechno v1 step 4: "el marcaje М-ЖД sugiere ferrocarril del Imperio ruso" |
| **U** | Update | "revision of a prior belief: explicit recognition that a previous H is wrong / refined / superseded" | Statement de revisión: "los tranvías no calzan con 1940, lo cambio a 1910s". Distinto del H nuevo (que es lo que sigue al U vía edge `updating`). | Tomsk v3 thinking step 5: "la kalanchá de Grodno no coincide con el patrón → descarto Grodno" (preludio del switch a Tomsk). |
| **C** | Commitment | "decision or final conclusion, or sub-conclusion treated as settled" — el `submit_answer` es un **C terminal** (atributo `terminal=true`), no un nodo separado. | `submit_answer` invocado (C terminal), o decisión interna tipo "voy a comprometerme con Tomsk" (C no-terminal). | Molodechno v1 step 5: submit con Moscú como proxy (C terminal). |

**Nota importante sobre evidencia visual primaria**: nuestro dominio se distingue de CORRAL en que la **foto target** entra al trace como input perceptual del primer mensaje, no como output de una tool. Eso la hace `E` de modalidad `visual_primary`, anotada al `msg_idx=1` (initial user message). Los `crop_image` son tool calls que generan `E` `visual_crop`. Sin este matiz el grafo queda sesgado a traces tool-textual-heavy y pierde el corazón perceptual del benchmark.

### 2.2 Edges (6 tipos)

| Edge | Definición CORRAL | Adaptación geo-detective | Ejemplo |
|---|---|---|---|
| **testing** | "Test directly addresses Hypothesis' claim, attempts to falsify or verify" | H → T donde el tool call está motivado explícitamente por la H. | "creo que es Tobolsk → search 'Tobolsk kostel'" |
| **observing** | "Test produces Evidence" | T → E: tool devolvió output. Trivial salvo cuando hay errors (timeout, 403). | `geocode("Wyoming Ave Detroit")` → 0 resultados |
| **informs** | "Evidence provides info relevant to Hypothesis or Judgment" | E → H or E → J: agente usa el resultado para refinar/sostener. | Tomsk step 6: web result "Воскресенская гора Томск" → informa H "Tomsk" |
| **contradicting** | "Evidence contradicts Hypothesis or Judgment" | E que es inconsistente con H previa. | Hipotético: SV de SP devuelve paisaje rural → contradice H "Mooca urbano" |
| **competing** | "H1 competes with H2 under same evidence" | Coexistencia de hipótesis rivales en el mismo punto. | Tomsk: "Tobolsk vs Tomsk vs Yeniseysk" entre steps 5-6 |
| **updating** | "U transforms H1 into H2 (Popperian belief revision)" | Edge entre el nodo `U` (la revisión explícita) y la nueva `H2`. | Tomsk step 5b: el U "descarto Tobolsk" se conecta vía `updating` a H2 "Tomsk". |

**Nota terminológica resuelta** (post Codex review 2026-05-12): el vocabulario oficial CORRAL es **H/T/E/J/U/C** (6 nodos) con **U como nodo** (no edge, no F separado). El `submit_answer` se representa como `C` con atributo `terminal=true`, no como nodo nuevo. Versión previa de este doc había mezclado el inventario; corregido.

---

## 3. Productive motifs (7) — patterns de razonamiento sano

Cada motif es un template de grafo. Lista basada en Table H.14 del paper, con ejemplos reales del E005 cuando se observaron.

| # | Motif | Template gráfico | Adaptación geo-detective | Observado en E005? |
|---|---|---|---|---|
| 1 | **Evidence-led hypothesis generation** | E → H (evidencia antes que hipótesis) | Agente abre la foto, cropea, observa elementos, **después** formula "esto se parece a X". No commitea antes de mirar. | Sí: Tomsk v1 step 1-2 (crop → image_search) precede H "Siberia" en step 3 |
| 2 | **Hypothesis reranking** | H1 competes H2 + E reorder | Mantiene 2+ hipótesis simultáneas y las prioriza según evidencia. | Parcial: Tomsk v1 steps 5a-5c (Tobolsk vs Tomsk vs Yeniseysk) |
| 3 | **Refutation-driven belief revision** | H1 → T → E (contradicting) → updating → H2 | Después de evidencia contradictoria al hilo principal, el agente abandona H1 y formula H2. | **No observado** en las 6 trazas del pilot. v3 muestra updates verbalizados pero no claramente disparados por contradicción. |
| 4 | **Explore-then-test transition** | exploración libre → formación H → testing | Primero abre crops y busca features visuales sin commit, después formula hipótesis y testea con tools dirigidas. | Sí: Tomsk v1. Crops + image_search general en steps 1-2, formación de H lingüística + testing en steps 3-5. |
| 5 | **Convergent multi-test evidence** | H con T1, T2, T3 independientes → E coherente | Una hipótesis se sostiene con evidencia desde tools de canales distintos (web + OSM + SV). | Parcial: Tomsk usó web + geocode (2 canales). Ningún caso de E005 usó 3+ canales independientes. |
| 6 | **Fixed hypothesis test tuning** | H fijo, T iterativamente refinado | El agente mantiene una H y reformula la búsqueda (idioma, sinónimos) sin saltar a otra. | Sí: Dealey v1 steps 4-6 (Detroit Ford Expressway con variantes de geocoding) |
| 7 | **Evidence-guided test redesign** | J motiva nuevo T → nueva E | Una evaluación cualitativa lleva al agente a diseñar un test distinto. | Sí: Tomsk v1 step 3 (J "fuentes en inglés no traen nada relevante" → T web_search en cirílico). |

### Motifs geo-detective-específicos

**Honesto sobre novedad** (post Codex review): muchos de estos son **subtipos o instancias** de motifs CORRAL existentes, no patterns nuevos. Etiquetar como subtipos defendibles para diagnóstico de dominio, no como aporte conceptual al framework.

| # | Motif geo-detective | Relación con CORRAL | Definición | Ejemplo E005 |
|---|---|---|---|---|
| 8 | **Language pivot productive** | NUEVO (CORRAL es monolingüe inglés) | T en idioma X → E vacía → J → T en idioma local (cirílico, chino) → E informativa. | Tomsk step 2 → 3: inglés sin hit, switch a cirílico, hit. |
| 9 | **Temporal-spatial anchoring** | NUEVO (CORRAL no tiene componente temporal) | H temporal y H espacial se refinan en paralelo usando E que data Y localiza (vehículos, vestimenta, OSM `start_date`). | Parcial: Molodechno datea (9 SET 17 → 1917) pero falla en localizar. |
| 10 | **Multi-modal cross-validation** | SUBTIPO de `convergent_multi_test` con eje "modalidad" | H se confirma combinando E `visual_crop` + E `coords` (geocode) + E `textual` (web). | No observado en pilot. Hipotético: identificar SP por arquitectura via crop + confirmar con SV + geocode. |

Solo **8 y 9** son aportación genuina al inventario (perception+multilingual y dating+locating dual no están en CORRAL). **10** es CORRAL `convergent_multi_test_evidence` aplicado a un eje de diversidad nuevo (modalidad).

---

## 4. Reasoning breakdowns (10+1) — patterns de razonamiento roto

Lista basada en Table H.15 del paper. CORRAL declara 10 patterns; la tabla literal lista 11 incluyendo `stalled_revision` (marcado como variante discontinua de `fixed_belief_trace`). Lo incluimos por completitud y notamos la inconsistencia del paper.

### Hypothesis handling

| # | Breakdown | Definición CORRAL | Adaptación geo-detective | Ejemplo E005 |
|---|---|---|---|---|
| 1 | **Untested claim** | H sin edge testing a ningún T | Agente afirma "esto es Mooca" en un mensaje pero nunca lo testea con tool. | A revisar en trazas. Posible en Molodechno: H "Imperio ruso" no se testea geográficamente. |
| 2 | **One-sided confirmation** | C sin evidencia contradictoria considerada | Submitea sin haber considerado alternativas explícitamente. | Molodechno v1 step 5: submit Moscú sin que ningún E haya descartado otras ciudades del Imperio. |
| 3 | **Contradiction without repair** | E contradicting sin U ni H2 | SV devuelve algo inconsistente, agente sigue con misma H. | No observado claramente en pilot. |
| 4 | **Premature commitment** | C sin T antes | Submit en step 1-3, casi sin tools. | No observado en E005 (todos usaron ≥5 steps). Pero **típico riesgo** del benchmark. |

### Evidence handling

| # | Breakdown | Definición | Adaptación | Ejemplo E005 |
|---|---|---|---|---|
| 5 | **Evidence non-uptake** | E recolectada sin edges informs/contradicting | Tool devuelve algo relevante, el agente no lo usa para nada. | Posible en Dealey: image_search step 2b devolvió 1 target match (hash hit), agente no lo capitalizó porque el hash matchea se ocultó del modelo (#24 hard reject). |
| 6 | **Disconnected evidence** | E sin ningún edge | Tool output ignorado completamente. | A revisar. |
| 7 | **Unsupported judgment** | J sin E que la soporte | Agente afirma cualitativamente algo sin tool output que lo respalde (i.e., alucinación). | **Riesgo VLM crítico**: identificar landmarks de memoria sin verificar con tool. |
| 8 | **Uninformative test** | T sin E observada | Tool call falla (timeout, 403, 0 resultados). | Dealey: 4+ geocode calls con 0 resultados, fetch_url con 403 y timeout. |

### Inquiry control

| # | Breakdown | Definición | Adaptación | Ejemplo E005 |
|---|---|---|---|---|
| 9 | **Fixed belief trace** | Trace sin ningún U (update) | Toda la trace mantiene la H inicial sin revisión. | A medir empíricamente: cuántas E005 traces tienen 0 updating edges. |
| 10 | **Precommitted test plan** | C antes de recolectar E | Plan de búsqueda decidido en step 1, ignora E intermedia. | A revisar en v1 vs v3. |
| 11 | **Stalled revision** | U → H2 nunca testeado | Agente revisa hipótesis pero nunca testea la nueva. | No observado claramente. |

### Breakdowns geo-detective-específicos

**Honesto sobre novedad** (post Codex review): la mayoría son **subtipos / anti-motifs / instancias** de CORRAL breakdowns ya existentes. Solo 1 es genuinamente nuevo. Los nombramos para diagnóstico, no para reclamar aporte conceptual al framework.

| # | Breakdown geo-detective | Relación con CORRAL | Definición | Ejemplo E005 |
|---|---|---|---|---|
| 12 | **Proxy substitution** | SUBTIPO de `one_sided_confirmation` (+ rastro de `unsupported_judgment`) | Evidencia insuficiente → agente submitea centroide representativo (capital/ciudad principal) en vez de marcar incertidumbre o de abandonar. Es el `one_sided_confirmation` de geo-loc en su instancia más típica. | Molodechno v1 step 5: submit Moscú (capital del Imperio) cuando la foto es Belarus, error 707 km. |
| 13 | **Tool channel mismatch** | NUEVO (sub-variante de inquiry control no contemplada en CORRAL) | El agente tiene tools de canales distintos (textual / visual / geográfico / temporal) pero usa solo uno cuando la H actual demanda otro. Distinto de `fixed_test_plan`: no es ceguera al plan, es **sesgo de canal**. | Generalizado en E005: ratio web_search/visual_tools sesgado fuerte a web. 0 usos de SV en algunas trazas con coords concretas que se beneficiarían. |
| 14 | **Geocoding/query loop sin H-update** | ANTI-MOTIF de `fixed_hypothesis_test_tuning` | En CORRAL `fixed_hypothesis_test_tuning` es productive (refinar T con misma H). Esta es la versión unproductive: T iteradas con variantes léxicas sin que la E negativa repercuta en J ni U. | Dealey v1 steps 6-10: 4 geocode calls iterando sobre Wyoming/Michigan Ave sin hit; H "Detroit Ford Expressway" no se actualiza. |
| 15 | **Language monolingual fixation** | ANTI-MOTIF de `language_pivot_productive` | Agente persiste en idioma X cuando E sugiere que la fuente primaria está en idioma local. | Simétrico inverso del motif 8. No observado claramente en E005 pero riesgo conocido. |

**Visual hallucination**: lo dropeamos como pattern geo-específico. Es **instancia** de `unsupported_judgment` de CORRAL para agentes con visión (no exclusivo a geo-loc). Lo anotamos como tag dentro de `unsupported_judgment` cuando el J refiere a una identificación visual no respaldada por tool — útil para diagnóstico de fallas VLM, pero no es aporte conceptual.

Solo **#13 (tool_channel_mismatch)** es propuesta genuina al framework. Los demás son instancias / anti-motifs nombrados para diagnóstico.

---

## 5. Diseño del annotator

### 5.1 Modelo judge

CORRAL usó **Claude 4.5 Sonnet** con 95.7% agreement vs humanos. Para nosotros:

- **Preferencia text-only**: Claude 4.7 Opus (1M ctx) si disponible vía API directa. Si presupuesto justo, Claude 4.6 Sonnet o el propio Claude 4.5.
- **Preferencia multimodal** (necesario para patterns visuales — ver §5.3): Claude 4.7 Opus con vision habilitado, recibiendo las imágenes de input perceptual (foto target, crops, SV panoramas, static_maps) como contenido binario en el contexto.
- **Anti-pattern**: usar el mismo modelo que ejecutó el agente como judge — riesgo de blind spots compartidos.
- **Razonable**: GPT-5 o gpt-5.4 si Anthropic queda fuera. Reportar siempre en el paper qué modelo se usó.

### 5.2 Input format

**Versión canónica del prompt: `v3_thinking_visible`**. v1_mechanical y v2_descriptive fueron versiones exploratorias del pilot E005 que se descartaron: v1 no verbaliza razonamiento, v2 verbaliza muy poco. Solo v3 captura los eventos `thinking` necesarios para que el annotator construya nodos H/J/U desde texto explícito del agente. **Cualquier corrida futura del benchmark usa v3.** Las trazas de v1/v2 quedan como artefactos históricos en `experiments/E005_react_pilot/results_v1_*.json` / `results_v2_*.json` para reproducibilidad, no para análisis comparativo de proceso.

**Formato de input al annotator** (sobre trazas v3 con thinking capturado):

```json
{
  "trace_id": "{cid}_{prompt_version}_{model}",
  "ground_truth": { "lat": ..., "lon": ..., "year": ... },
  "evidence_inputs": {
    "target_image_path": "...",          // foto target = E modalidad visual_primary
    "crops": [{ "path": "...", "step": N }]
  },
  "messages": [
    { "msg_idx": 0, "role": "system", "content": "<system prompt>" },
    { "msg_idx": 1, "role": "user", "content": "<task brief + reference a target_image>" },
    { "msg_idx": 2, "role": "assistant",
      "thinking": "<verbalización>", "tool_calls": [...] },
    { "msg_idx": 3, "role": "tool", "tool_name": "web_search", "args": {...},
      "modality": "textual", "content": "<resumen>" },
    { "msg_idx": 4, "role": "tool", "tool_name": "street_view", "args": {...},
      "modality": "visual", "content_text": "<metadata>", "content_image_path": "..." },
    ...
    { "msg_idx": N, "role": "assistant", "content": "<submit_answer call>" }
  ]
}
```

**Decisiones de serialización**:

- Tool outputs textuales: incluir completos (web results, OSM features, geocoder).
- Tool outputs visuales (image_search, fetch_url_with_images, static_map, street_view, crop): incluir **path al archivo** + descripción textual + URLs/coords + flag `is_likely_target` redactado. El judge multimodal carga las imágenes; el text-only ve la descripción.
- `thinking` events de v3: incluir todos. Marcador `[thinking]`.
- System prompts: incluir como metadata (`prompt_version`) — informativo para el judge, no como mensaje regular del trace.

### 5.3 Pipeline multi-stage

**Stage 1 — Nodos** (text-only judge alcanza):
- System: "You are a careful annotator. You MUST only extract information explicitly present in the provided messages."
- User prompt con definiciones operativas de H/T/E/J/U/C adaptadas a geo-detective.
- Output JSON: `{ "nodes": [{"node_id", "type", "time" (msg_idx), "modality" (para E), "text" (normalized), "support": [{"msg_idx", "quote" (verbatim)}]}] }`.
- Sliding window: 20 mensajes / stride 15. **Nuestras trazas típicas tienen ≤30 mensajes** → en práctica una sola pasada alcanza. Parametrizar igual.
- Temperature 0.7 (como CORRAL).

**Stage 2 — Edges** (text-only judge alcanza):
- System: "You MUST only add edges supported by explicit text."
- User prompt con definiciones de los 6 edges + restricciones de combinación.
- Output JSON: `{ "edges": [{"src", "dst", "relation", "time", "support": [{"msg_idx", "quote"}]}] }`.

**Stage 3a — Pattern detection graph-structural** (Python determinista, no LLM):
- Input: grafo Stage 1 + Stage 2.
- Detecta patterns cuya definición es **puramente estructural** sobre el grafo:
  - Productive: evidence_led_hypothesis, hypothesis_reranking, refutation_driven_belief_revision, explore_then_test, convergent_multi_test_evidence, fixed_hypothesis_test_tuning, evidence_guided_test_redesign.
  - Breakdowns: untested_claim, premature_commitment, contradiction_without_repair, disconnected_evidence, uninformative_test, fixed_belief_trace, stalled_revision.
  - Geo-específicos estructurales: temporal_spatial_anchoring (H temporal + H espacial coexisten y se actualizan), language_pivot_productive (T en idioma A → E vacía → T en idioma B → E informativa via patron lexical).
- Salida: booleano por pattern + nodos involucrados.

**Stage 3b — Pattern detection semantic** (LLM-judge, multimodal cuando aplique):
- Input: grafo + serialized trace + imágenes (cuando relevante).
- Detecta patterns que requieren **juicio normativo** o **interpretación de contenido**:
  - Breakdowns: one_sided_confirmation (counterfactual: ¿hay alternativas no consideradas?), evidence_non_uptake (interpretación: ¿la E es relevante a la H actual?), unsupported_judgment (¿la J está respaldada por E?), precommitted_test_plan, **proxy_substitution** (¿el agente substituyó por un default cuando E era insuficiente?), **tool_channel_mismatch** (¿la H actual demandaba otra modalidad de E?), **geocoding/query_loop** (¿variantes léxicas sin H-update?), **language_monolingual_fixation**.
  - Patterns con E visual_primary o visual_crop necesitan judge multimodal: visual_hallucination (subtipo de unsupported_judgment para identificaciones visuales), multi-modal_cross_validation.
- Salida: booleano por pattern + justificación textual + (si aplica) quote / image reference.

**División graph-structural vs semantic es importante**: la estructural es reproducible 100%, la semantic depende del judge. En el paper reportar ambas separadas; la primera sirve de "núcleo robusto", la segunda como capa interpretativa.

**Stage 4 — Reporte crudo de patterns** (NO process_score agregado en v1):
- Por trace: vector binario de patterns detectados (productive + breakdowns) + lista de quotes/justifications.
- Cross-trace: prevalencia por pattern, breakdown más frecuente, distribución por prompt-version, distribución por modelo.

**Process_score agregado**: **defer a fase posterior**. Con n=18 traces (E005) o n=6×N_modelos, un score combinado es overcommit. Reportar **prevalencias crudas** + **comparaciones binarias por pattern**. Cuando n≥50 traces estratificadas, considerar score agregado con sensitivity analysis sobre pesos.

### 5.4 Output format del annotator

```json
{
  "trace_id": "...",
  "ground_truth": {...},
  "outcome": { "distance_km": ..., "year_err": ..., "submit_called": ... },
  "graph": {
    "nodes": [{"node_id": "N1", "type": "H", "time": 2, ...}],
    "edges": [{"src": "N1", "dst": "T1", "relation": "testing", ...}]
  },
  "patterns_structural": {
    "productive": {"explore_then_test": true, "convergent_multi_test_evidence": false, ...},
    "breakdowns": {"untested_claim": false, "fixed_belief_trace": true, ...}
  },
  "patterns_semantic": {
    "productive": {"language_pivot_productive": {"present": true, "justification": "..."}},
    "breakdowns": {"proxy_substitution": {"present": true, "justification": "...", "quote": "..."}}
  },
  "judge_metadata": {
    "stage1_2_model": "claude-opus-4-7",
    "stage3b_model": "claude-opus-4-7 (with vision)",
    "tokens_in": ..., "tokens_out": ..., "cost_usd": ...
  }
}
```

### 5.5 Validación

Plan de validación **revisado post-Codex** — el original (5 traces / 1 anotador / PABAK ≥85%) era subpowered.

1. **Stratified sample de 15-20 traces** del corpus (E005 trazas v3 + corridas cross-model cuando estén). Estratificación por (modelo, outcome_class: acierto / off-medio / off-grande / max_steps). Como hoy solo tenemos 6 trazas v3, el sample inicial es esas 6 + lo que sume el cross-model run.
2. **2 anotadores humanos** (vos + otra persona, o vos + sesión separada propia con día de pausa para reducir bias). Anotan independientemente.
3. **Agreement granular por dimensión**:
   - Inter-human por **nodo** (Cohen κ o PABAK; target ≥0.80).
   - Inter-human por **edge** (target ≥0.75 — más subjetivo).
   - Inter-human por **pattern detectado** (target ≥0.80 productive, ≥0.75 breakdown).
4. **Solo después** de tener ground truth humano fiable: medir agreement LLM-vs-humano. Si LLM-vs-human < min(human-human, 5pp), iterar prompt del judge.
5. **PABAK puede inflarse con labels raros**: reportar también percent agreement plain + Cohen κ por separado.

**Costo del protocolo**: ~2-4 h de anotación humana por trace × 20 traces × 2 anotadores = 80-160 h-persona. Real. Vale la pena para defender el paper.

### 5.6 Costo del judge LLM

Trace típica E005 (post patch): ~25-35 mensajes con thinking, ~10K-25K tokens serializados (excluyendo imágenes). Imágenes (cuando multimodal): ~5-10 imágenes × ~1500 tokens/imagen ≈ 7.5K-15K tokens visuales.

Stage 1+2 (text-only Claude Opus): ~$0.05-0.15 / trace.
Stage 3b (multimodal Claude Opus): ~$0.10-0.30 / trace.
**Total ~$0.15-0.45 / trace**.

Pilot E005 actual (18 traces existentes + ~6-12 más cross-model): **$5-20 USD**. Trivial.

Corpus escalado (#25, 720 fotos × 3 modelos × 1 corrida = 2160 traces): **$300-1000 USD**. Aceptable para paper.

---

## 6. Conexión con outcome metrics

> **Postura canónica alineada con PROJECT.md**: el process eval es **eval offline only**. NO entra al reward del environment. Esto es invariante 4 de PROJECT.md ("reward optimizable separado de penalizadores de proceso") y la propia recomendación del paper CORRAL (no integrar process-graph annotation al training loop por costo + hackeabilidad).
>
> Versión previa de este doc sugería un `reward = α·(-distance) + β·process_score`. **Corregido**: el process_score no se optimiza; se reporta. Cualquier integración futura como reward shaping queda como deuda explícita post-paper.

Lo que sí podemos hacer (eval-only) es **cruzar process metrics con outcome metrics** para interpretar resultados. Con n suficiente (≥50 traces estratificadas, deuda hacia corpus escalado), el cruce 2D agente×outcome permite leer:

- **Process alto + distancia baja**: investiga bien y acierta. Ideal.
- **Process alto + distancia alta**: foto genuinamente difícil. **Señal del benchmark** — el agente intentó bien y aun así no llegó. Define el techo actual.
- **Process bajo + distancia baja**: posible memory shortcut. El atacante GPT-4o (#24) filtra parcialmente esto, pero el agente con tools puede recaer.
- **Process bajo + distancia alta**: peor caso. Investigación pobre + outcome malo.

**Con el n actual del pilot (E005: 18 traces, 6 fotos × 3 prompts)**, este cruce no es estadísticamente significativo. Reportable como **plot exploratorio** con N anotado, no como conclusión cuantitativa. La aspiración cuantitativa requiere n≥50 traces estratificadas.

**Hipótesis derivada del cruce, falsable con corpus escalado**: una policy entrenada con reward = -distance migra a "distancia baja" pero no necesariamente a "process alto"; modelos con buen pretraining para razonamiento (Claude Opus, GPT-5) ya están más arriba en el eje process incluso sin training. Esta hipótesis es la **réplica directa del finding CORRAL** ("base model >> scaffold") en dominio con perception.

---

## 7. Roadmap operativo

1. **Aprobación del mapping** (este doc): user revisa, valida ejemplos.
2. **Implementación del annotator stub** (task #6): código en `src/geodetective/judge/` o similar. Tests sintéticos sobre traces fabricadas antes de correr sobre las 6 trazas v3 del E005. Implementa Stage 1+2+3a primero (Stage 3a es Python determinista, no requiere LLM). Stage 3b queda para iteración 2 (necesita multimodal judge + `.env`).
3. **Validación humana** (task derivada, §5.5): 15-20 traces estratificadas + 2 anotadores + agreement granular (nodo, edge, pattern). NO solo PABAK global.
4. **Primera corrida real Stage 1-3a**: annotator sobre las 6 trazas v3 del pilot. Output: 6 grafos + patterns estructurales detectados (sin semantic todavía). Plot exploratorio (con N anotado).
5. **Stage 3b** (multimodal, cuando `.env` vuelva): semantic patterns + visual judge. Reportar separado.
6. **Cross-model + corpus escalado** (task #7): el annotator se aplica igual. Todas las corridas en v3. Permite reportar process metrics por modelo.

---

## 8. Open questions

- **Updates implícitos vs verbalizados**: v3 capta updates verbalizados. ¿Detectamos también cambios sutiles de target en queries sucesivas (H reemplazada silenciosamente)? Por simplicidad en v1 del annotator, solo verbalizados. Si vemos que el agente sí cambia de hipótesis sin decirlo, agregar detector heurístico en iteración 2.
- **Threshold de pesos del process_score**: postpuesto hasta tener n suficiente (≥50 traces estratificadas). En v1 del annotator, reporte crudo de patterns sin score agregado.
- **Posición filosófica vs CORRAL**: CORRAL mide razonamiento sobre tarea bien definida (te dicen qué investigar). Nosotros sumamos brief abierto. Esa diferencia se desarrolla en `related_work.md`.
- **Validación cruzada inter-judge**: ¿el grafo es robusto si lo anotamos con Claude vs GPT-5? Si agreement alto, defendemos robustez. Si bajo, la elección de judge influye el resultado y hay que reportar sensitivity.

---

## Referencias

- **CORRAL paper**: Ríos-García et al., "AI scientists produce results without reasoning scientifically", arXiv:2604.18805v1, April 2026.
- **Código MIT**: https://github.com/lamalab-org/corral
- **Datasets HF**: https://huggingface.co/collections/jablonkagroup/corral
- **Síntesis canon previa** (proyecto sister): `synthetic-research-envs/research/synthesis/related_work_corral.md`.
- **Fulltext extraído**: `synthetic-research-envs/research/notes/corral_paper_fulltext.txt` (4822 líneas).
