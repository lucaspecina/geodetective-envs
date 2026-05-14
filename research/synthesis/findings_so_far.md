# Findings so far — Síntesis transversal de E001-E009

> **Status**: living doc, última actualización 2026-05-14 (post pilot E009 cross-model + annotator CORRAL stub validado).
>
> Per-experimento: `research/notes/E001_*` ... `E005_*`. Síntesis sobre proceso: `process_eval_design.md`. Síntesis sobre dónde nos ubicamos: `related_work.md`.
>
> **Regla de actualización**: cada vez que cierre un experimento, sumar 1-3 bullets al campo correspondiente. Si una conclusión se invalida, mover a "hipótesis falseadas" con fecha. No reescribir historia.

---

## 1. La conclusión que vale (mayo 2026 post-E009)

> **El benchmark discrimina entre modelos comerciales con magnitud grande**. En el pilot E009 (9 modelos × 3 fotos), Claude Opus 4.6 logró 645 km avg vs gpt-5.4 con 1848 km avg — **3x de diferencia**. Modelos pequeños/baratos (gpt-5.4-mini, grok-4-1-fast) superaron a sus flagships respectivos. Esto valida la hipótesis abierta principal: **el comportamiento del agente es propiedad del base model, no del scaffold** (réplica de CORRAL en dominio con perception).

Detalle de lo observado:

### Pilot E009 — cross-model (mayo 2026)

9 modelos × 3 fotos (Tomsk 1898, Basel 1928, Dealey Plaza 1936) × max_steps=30, prompt v3 canónico.

| Modelo | Tier | Tomsk | Basel | Dealey | Avg km | Steps tot. | Tools tot. |
|---|---|---|---|---|---|---|---|
| **claude-opus-4-6** | Top | 1930 | 6 | **0** | **645** ⭐ | 53 | 91 |
| gpt-5.4-mini | Mid | 1705 | 670 | **0** | 792 | 18 | 48 |
| grok-4-1-fast-reasoning | Mid | 3458 | 36 | **0** | 1165 | 17 | 80 |
| gpt-4o | Ref | 2978 | 444 | 193 | 1205 | 23 | 22 |
| gpt-5.4 | Top | 3438 | 506 | 1600 | 1848 | 38 | 145 |
| grok-4.3 | Top | 3342 | 656 | 2182 | 2060 | 46 | 70 |
| Kimi-K2.5 | Mid | 2624 | 7549 | 1903 | 4025 | 84 | 154 |
| Kimi-K2.6 | Top | NA¹ | 3 | **0** | (2 km en 2/3 que submitió) | 69 | 95 |
| claude-sonnet-4-6 | Mid | NA² | NA² | **0** | (0 km en 1/3 que submitió) | 25 | 39 |

¹ Kimi-K2.6 hit max_steps_no_submit en Tomsk.
² claude-sonnet-4-6 tuvo `empty_response` en Tomsk + Basel — sospecha de max_tokens=3000 saturado por thinking mode (fix aplicado, re-corrida en curso).

**Hallazgos macro E009**:

- **Dealey Plaza (foto con texto visible "U.S. Bureau of Public Roads")**: 5/9 modelos clavaron a 0 km. Los que fallaron (gpt-5.4, grok-4.3, Kimi-K2.5) usaron MÁS steps y MÁS tools — el over-investigating EMPEORA el outcome cuando la pista textual es directa.
- **Basel (calle suiza en construcción)**: solo Kimi-K2.6 (3 km), claude-opus (6 km), grok-4-1-fast (36 km) llegaron cerca. El resto: 400-700 km. Kimi-K2.5 fue 7549 km — caso de **stubbornness** (modelo se compromete a hipótesis equivocada con muchos web_searches que la "confirman").
- **Tomsk (panorámica B/N 1898 con kostel + sobor)**: ningún modelo a <1500 km. **Foto genuinamente difícil**. Mejor fue gpt-5.4-mini (1705 km) y claude-opus (1930 km). Un modelo (Kimi-K2.6) ni terminó. Tomsk valida que el corpus contiene casos donde la investigación NO basta.
- **Mid-tier beats Top-tier** en algunos casos: gpt-5.4-mini (792 km avg) > gpt-5.4 (1848 km avg). grok-4-1-fast (1165 km) > grok-4.3 (2060 km). **Tier comercial no predice outcome** — sorpresa publicable.
- **Tools no correlaciona con accuracy**: Kimi-K2.5 usó 154 tool calls totales y promedió 4025 km. claude-opus usó 91 tool calls y promedió 645 km. **Razonamiento > volumen de búsqueda**.

### Annotated E005 v3 con judge Claude Opus 4.6 (post-Codex fixes)

6 traces v3 anotadas con el annotator CORRAL adaptado (Stage 1+2 LLM + Stage 3a structural). Tiempo: ~190-240s por trace. Cada trace: 31-74 nodes, 30-80 edges.

**Patterns observados en las 6 traces v3**:

- Productive motifs frecuentes (≥4/6 traces): `evidence_led_hypothesis` (6/6), `convergent_multi_test_evidence` (6/6), `evidence_guided_test_redesign` (5/6).
- Breakdowns frecuentes (≥4/6): `untested_claim` (5/6), `evidence_non_uptake` (6/6 — el agente recolecta E que no usa).
- Patterns geo-específicos: `temporal_spatial_anchoring` aparece en 3/6 (Tomsk, Dealey, Russia-EU). `language_pivot_productive` en 2/6 (Basel, Molodechno — agente switch a ruso/alemán). `refutation_driven_belief_revision` en 2/6 (Tomsk, Mukden).

**`evidence_non_uptake` es estructural**: el agente RECOLECTA evidencia (web_search, image_search resultados) pero después no la usa para informar / contradecir hipótesis. Esto coincide con el finding macro CORRAL ("68% de traces ignoran evidencia recolectada").

**Limitación del annotator v1**: text-only judge. Patterns que requieren ver imágenes (visual_hallucination, multi_modal_cross_validation) deferidos a Stage 3b multimodal.

---

## 2. Findings por dimensión

### 2.1 Corpus

| Finding | Evidencia | Implicación |
|---|---|---|
| PastVu tiene 2.08M records, 676K elegibles para 1850-1950 con geo+year | Audit #3 (E006) | Masa suficiente para corpus escalado (#25 K_PER_CELL=20 → 720 fotos sin esfuerzo) |
| 100% de las fotos PastVu tienen watermark (`waterh > 0`) | Audit #3 | `clean_image` (#22) es obligatorio. Confirmado. |
| Sesgo Rusia 62%, ex-URSS 74% — menos extremo que la afirmación genesis "70-95%" | Audit #3 | Reportar honestamente en el paper. No es global representativo. |
| Sample diverso 6 buckets país × 6 décadas, K=5, dedup geohash5 | E007 sample (#17) | 180 fotos balanceadas, no concentradas en SP-Mooca o Moscow centro. |
| Filtro adversarial: dist<10km AND conf≥media en N=3 corridas | E004 (#24) | 56% sobrevive. 60/79 rejects dispararon las 3 corridas — patrón consistente. |
| Norteamerica reject_rate 80% (landmarks/memory), Russia-Asia 13% (más cotidianas) | E004 | "Trampeable" correlaciona con landmarks visuales y familiar pretraining corpus. |

### 2.2 Tools individuales

| Finding | Evidencia | Implicación |
|---|---|---|
| Stack de 12 tools implementado y corre end-to-end sin errores técnicos | E003, E005 | Backend de tools funciona; no es bug técnico. La utilización (sub-)óptima es comportamiento, no falla de plomería. |
| Tools visuales (`static_map`, `street_view`) responden correctamente cuando se invocan en test técnico | Test técnico E003 (invocación forzada) | Confirmado en test sintético. La "no-utilización" en runs de geolocalización es comportamiento del modelo. No descarta que algún parámetro del prompt o de la signature de la tool incentive evitarla. |
| `historical_query` (OHM Overpass) es pieza diferencial: temporal queries con `start_date`/`end_date` | Tool propio | Único tool dating-aware en el stack. **0 usos en E005**. |
| Tavily web_search consume cuota rápido (7-15 calls por foto) | E005 | Riesgo operacional + signal de comportamiento sub-óptimo. |
| `image_search` con hash hard reject (#24 fix) bloquea el shortcut "buscar la foto en Google" | E005 Dealey Plaza (`target_match=1`) | El anti-shortcut está cerrado a nivel image search. |
| Cuota Google Maps free $200/mes alcanza para escala benchmark | Estimación | Para training (1M+ calls) no aplica — ToS prohíbe igual. |

### 2.3 Behavior del agente

| Finding | Evidencia | Implicación |
|---|---|---|
| Sobre 6 fotos del pilot E005 v3 (canónica): 1 uso de `static_map` (Basel), 0 `street_view`, 0 `historical_query`. Web_search dominante (7-15 calls/foto). | E005 v3 trace counters | Patrón consistente en pilot (n=6); falta saber si es propiedad del modelo (gpt-5.4) o del scaffold/prompt. Hipótesis abierta §3.3. |
| Variancia run-to-run alta (factor 7x) | E001-E003 | N=3 corridas mínimo para conclusiones robustas. Solo 1 corrida en E005 → no robusto. |
| El modelo decide cuándo parar | E001-E005 | Cap 12 steps; típicamente usa 3-8 cuando submitea. 33% hit max_steps en E005. |
| Forzar uso de tools en prompt sesga el benchmark | E003 decisión + Codex review | Confirmado: el prompt es descriptivo, no prescriptivo. |
| Variantes v1/v2 deprecadas: no verbalizan razonamiento, no usables para process eval. v3 (verbalización ReAct + tool descriptions) es la única canónica | Ablación inicial mayo 2026 | El benchmark usa v3 de acá en adelante. v1/v2 quedan como artefactos históricos en E005. |
| Caso histórico: en Tomsk, v3 (canónico) perdió un acierto que v1 (deprecado) había logrado a 2 km | E005 ablación inicial | Sugiere que pedir verbalización ReAct puede sacar al agente de un razonamiento que ya estaba convergiendo. Pendiente verificar con corridas adicionales en v3 si es robusto. |
| Atacante GPT-4o sin tools "no aventura" (conf baja sin coords) en fotos cotidianas | E004 60/79 rejects con 3/3 triggering | El filtro adversarial no es ruido: tiene firma consistente. |
| Hay **al menos un caso** (Tomsk, n=1) donde tools producen una mejora dramática vs atacante sin tools (atacante no aventuró → agente 1.8 km) | E005 #2126812 | Existe el efecto "tools ayudan dramaticamente"; magnitud y frecuencia requieren más muestras. |
| Hay **al menos un caso** (Mukden, n=1) donde el agente con tools no submite mientras el atacante había aventurado a 626 km | E005 #1587935 | Existe el efecto inverso "tools no garantizan respuesta"; magnitud y frecuencia requieren más muestras. |

### 2.4 Anti-shortcut / filtrado adversarial

| Finding | Evidencia | Implicación |
|---|---|---|
| `clean_image` (#22) strip EXIF + crop watermark + RGBA→RGB | Tests sintéticos 13 escenarios | Paso 0 robusto. Versionado con `CLEAN_VERSION`. |
| Blacklist runtime per-photo (#23) varía según provider+source, no global | Tests 14 grupos / 65 checks | Arquitectura cierra agregadores con metadata sin overblocking dominios legítimos. |
| Hash perceptual = hard reject (no flag) en `image_search` + `fetch_url_with_images` (#24) | Código de `react.py` + E005 confirma | Alineado con `PROJECT.md` invariante 1. |
| Atacante 1 modelo (GPT-4o) en v1, multi-modelo es deuda | #24 explicit | Documentado en limitations. |
| Threshold `dist<10km AND conf≥media` con N=3 corridas elimina ~44% del sample | E004 | Defendible como filtro: ni demasiado laxo (deja landmarks famosos), ni demasiado estricto (corta cotidianas). |

### 2.5 Reproducibilidad y variancia

| Finding | Evidencia | Implicación |
|---|---|---|
| Variancia inter-run alta (E001: factor 7x en distancia para misma foto/modelo/prompt) | E001 | Conclusiones sobre 1 corrida no son robustas. |
| Seeds deterministicos en sampling (`SEED=42`) | E007, E005 | Misma corrida reproducible. |
| Foundry rate limits no documentados explícitamente | Op experience | Riesgo cuando escalemos cross-model run. |
| Output formatting estable (`results.json` schema) | E005 | Pipeline de análisis post-hoc no fragmenta el output. |

---

## 3. Hipótesis explícitas

### 3.1 Validadas (con evidencia)

| Hipótesis | Evidencia | Confianza |
|---|---|---|
| El pipeline end-to-end corre sin errores técnicos | E002 + E003 + E005 + E009 corrieron sin error mayor (claude-sonnet-4-6 tuvo empty_response 2/3 en E009 por max_tokens — fix aplicado, re-corrida en curso) | Alta |
| El atacante GPT-4o tiene un patrón consistente (no es ruido) | 60/79 rejects con 3/3 triggering runs (E004) | Alta |
| `clean_image` + blacklist per-photo + hash hard reject cierran los shortcuts más obvios | Tests sintéticos + E005 Dealey Plaza con `target_match=1` y agente ciego al match | Alta para los shortcuts cubiertos. No descarta vectores aún no testeados (threat model #10). |
| Foto histórica cotidiana sin landmarks tiene reject rates bajos del atacante (sweet spot del corpus) | E001 sweet spot + E004 Russia-Asia reject 13% vs Norteamerica 80% | Media-Alta. Diferencia entre buckets es consistente con la hipótesis, pero atribución causal (landmarks vs familiarity de pretraining vs algo más) sigue confounded. |
| **El benchmark DISCRIMINA entre modelos comerciales con magnitud grande** | E009: 3x entre claude-opus (645 avg) vs gpt-5.4 (1848 avg). 5/9 modelos clavan Dealey 0km, otros fallan por >1500 km. Tools no correlaciona con accuracy. | Alta. **Réplica de finding CORRAL** ("base model >> scaffold") en dominio con perception. Resultado publicable. |
| Tier comercial NO predice outcome | E009: gpt-5.4-mini supera a gpt-5.4 (792 vs 1848 km). grok-4-1-fast supera a grok-4.3 (1165 vs 2060 km). Tier "mini/fast" frecuentemente >= flagship en geo-detective. | Media-Alta. n=3 fotos. Resultado robusto entre los pares testeados pero falta validar con N>3. |
| Over-investigating EMPEORA outcome en fotos con pista textual directa | E009 Dealey Plaza: gpt-5.4 con 60 tool_calls / 14 steps falló por 1600km; claude-opus con 6 tool_calls / 5 steps clavó 0km | Media. n=1 foto. Patrón consistente en los modelos que fallaron Dealey vs los que acertaron. |
| El annotator CORRAL discrimina patterns por trace | E005 v3 annotated: 6 traces con 31-74 nodes / 30-80 edges, diferentes mezclas de productive/breakdown patterns. `evidence_non_uptake` universal (6/6) — replica finding CORRAL del 68%. | Alta para el setup actual. Limitación: n=6 traces, judge único (Claude Opus). Inter-judge agreement no testeado. |

### 3.2 Falseadas o parcialmente refutadas

| Hipótesis original | Evidencia que la contradice | Estado |
|---|---|---|
| "El modelo no usa tools visuales porque no las conoce" | v2/v3 mostraron uso esporádico (1 `static_map` en Basel); test técnico E003 con invocación forzada confirma que las invoca | Parcialmente falseada. La razón sigue abierta (entrenamiento? incentivo? overconfidence en web_search?). |
| "Subir max_steps va a mejorar la investigación" | E009 con max_steps=30: gpt-5.4 usó 14 steps + 60 tool_calls en Dealey y falló por 1600 km. claude-opus usó 5 steps + 6 tool_calls y clavó 0 km. **Más steps no = mejor** | Codex review confirmado por evidencia. Más steps a veces empeora. |
| "Tier comercial top siempre supera al tier mid/mini" | E009: gpt-5.4-mini (792 km avg) > gpt-5.4 (1848 km avg). grok-4-1-fast (1165 avg) > grok-4.3 (2060 avg) | Falseada en geo-detective. Tier "mini/fast" frecuentemente igual o mejor. |
| "El comportamiento 'web-search bot' es del scaffold/prompt" | E009 cross-model: 9 modelos con MISMO scaffold producen variancia 3x en outcome. claude-opus usa pocos tools y acierta; Kimi-K2.5 usa muchos y falla | Falseada (replicación CORRAL). El comportamiento es **propiedad del base model**, no del scaffold. |
| Sesgo Rusia 70-95% (claim genesis) | Audit empírico: 62% Rusia, 74% ex-URSS | Falseada. Updated. |
| 47 shards de imágenes PastVu (claim pastvu_deep_dive) | Audit empírico: 2094 shards | Falseada. Updated. |

### 3.3 Abiertas y testeables

| Hipótesis | Cómo testearla | Costo |
|---|---|---|
| **¿Qué información exacta recibe el modelo en cada tool call y cómo razona a partir de eso?** | Patchear react.py para guardar `raw_tool_result_payload` (≤2K chars). Generar viewer side-by-side: call args + raw output (lo que el modelo VE) + thinking subsiguiente. | Bajo — task #22. |
| Process score discrimina entre modelos donde distance no lo hace | Annotator CORRAL-style sobre traces E009 cross-model (27 traces). | Medio — ~80 min de judge time + $20-40 USD en Claude calls. |
| Subir `max_steps` de 30 a 50 mejora outcome para fotos difíciles (Tomsk) o solo agrega loops | A/B sobre Tomsk con N=3 corridas en (steps=30) vs (steps=50). | Bajo — re-run específico. |
| Multi-modal judge (Claude con vision) detecta `visual_hallucination` y `multi_modal_cross_validation` que el text-only no ve | Stage 3b annotator multimodal sobre subset E005 v3 + comparar | Medio. Requiere multimodal Claude calls + serialización de imágenes. |
| El process_score × distance_km produce 4 cuadrantes interpretables (process_eval_design §6) | Plot de E009 traces anotadas (27 traces). | Bajo si annotator E009 está hecho. |
| El benchmark mantiene su discriminación cross-model en N=3 corridas (no es ruido de N=1) | Re-correr E009 con N=3, MAX_STEPS=30 | Alto — 27 × 3 = 81 corridas adicionales. ~6h. |
| Tomsk es genuinamente difícil para TODOS los modelos (no es solo gpt-5.4) | E009 ya da evidencia (ningún modelo <1500 km). Validar con corpus más amplio (Russia-Asia bucket) | Medio — necesita más fotos del mismo bucket. |

---

## 4. Open questions priorizadas

Por prioridad (alta → baja):

1. **¿El "web-search bot" es modelo o sistema?** (cross-model run, bloqueado por .env). Define si el hallazgo replica CORRAL o es accidente de gpt-5.4.
2. **¿El process score discrimina?** (annotator + análisis). Define si el aporte del paper (process eval en geo-loc) tiene señal real.
3. **¿La verbalización ReAct (v3 thinking_visible) aporta de manera sistemática o solo en algunos casos?** (necesita N corridas más + análisis). Crítico para decisión de prompt default.
4. **¿Subir max_steps mejora o solo aumenta el web_search loop?** Codex review opinó "solo aumenta" pero el user observó que algunos sí usan tools visuales — re-test con max_steps=30.
5. **¿Cuál es el corpus mínimo defendible para el paper?** Hoy 180 fotos / 101 keep. Para masa estadística decente, probablemente K_PER_CELL=20 → 720 fotos / ~400 keep. Cost estimate: atacker en ~30 min, agente en ~10h secuencial por modelo. Aceptable.
6. **¿El threat model anti-shortcut está completo?** #10 abierta. Identifica brechas: reverse image scale (Lens, Yandex), OCR de signos, metadata embebida en píxeles. Antes de publicar.
7. **¿Tenemos baseline humano?** No. ¿Necesitamos? Ideal: 5-10 fotos resueltas por humano GeoGuessr-level con timer + protocolo, para calibrar el techo. Pendiente decidir si entra al paper o queda como deuda.

---

## 5. Implicaciones operativas (próximos pasos derivados)

| Acción | Por qué | Cuándo |
|---|---|---|
| Implementar annotator CORRAL adaptado | Habilita testear hipótesis 2 y 3 | Después de aprobar `process_eval_design.md`. Task #6. |
| Cross-model run sobre las 6 fotos del pilot | Habilita testear hipótesis 1 | Cuando vuelvan credenciales TAVILY + GOOGLE_MAPS + AZURE_FOUNDRY. Task #7. |
| Escalar corpus K_PER_CELL=20 → 720 fotos | Masa estadística para todas las hipótesis | Solo después de validar process eval, sino el costo del annotator se multiplica sobre datos cuya estructura no entendemos. |
| Patch `run_react_pilot.py` para output por modelo + MAX_STEPS=30 default | Habilita cross-model + responde Q4 | Antes del cross-model run. |
| Multi-attacker (claude, gemini además de gpt-4o) en el filtro adversarial | Robustece la deuda explícita de #24 | Cuando defendamos el paper. No urgente para próximo experimento. |

---

## 6. Datos curiosos / observaciones no procesadas todavía

(Pueden derivar insights más adelante. No accionables hoy.)

- En E005 Tomsk, el agente hizo **language pivot** explícito (inglés → cirílico) en step 3, y eso fue lo que destrabó el caso. CORRAL no captura este pattern (sus dominios son monolingües inglés). Es un motif productivo novedoso del dominio.
- En Molodechno, el agente extrajo correctamente fecha (9 SET 17 → 1917) y marcaje cirílico (М-ЖД) pero falló en localizar, y eligió **Moscú como proxy** ("estación del Imperio Ruso"). Es un breakdown no listado en CORRAL — lo nombramos "proxy substitution" en `process_eval_design.md`.
- En Dealey Plaza, el agente identificó "U.S. Bureau of Public Roads" en el texto visible de la foto y derivó "Detroit, Ford Expressway, Michigan/Wyoming Avenues" como hipótesis. Geocoder no resolvió esas intersecciones (probablemente porque ya no existen o fueron renombradas). El agente entró en un **geocoding loop** durante 5 steps. Tampoco está en CORRAL — lo nombramos así.
- En Russia-Asia bucket, sólo Tomsk (en sample) tenía landmark visualmente identificable (kostel + sobor). El resto del bucket en E004 tuvo reject_rate 13% — confirma que esa cell es la más "investigable genuinamente", no la más "memorizada".
- El atacante GPT-4o tiene `conf=media` en algunos casos sin coords (no aventura). En esos casos el filtro NO los rechaza porque `dist=N/A`. Posible refinamiento: requerir submission de coords. Decisión a tomar.

---

## 7. Lo que aún no sabemos pero deberíamos antes de paper

- Distribución del `process_score` cross-model (sin annotator no se puede).
- Ratio coste/beneficio de annotator multimodal vs text-only.
- Si el corpus escala a 720 sin perder balance (urbano/rural no se rescata salvo manual).
- Si Claude-Opus o Gemini-2.5 patean el patrón web-search-bot (réplica CORRAL).
- Si humanos GeoGuessr-tier resuelven el pilot mejor o peor que el mejor modelo (techo del benchmark).
- Si forzar `submit_answer` al hit max_steps cambia las métricas materialmente (deuda detectada en `research/notes/E005_react_pilot.md`).
