# Findings so far — Síntesis transversal de E001-E005

> **Status**: living doc, ultima actualización 2026-05-12. Captura conclusiones honestas a través de experimentos. Reemplaza el reflejo a "qué cuenta el paper" con "qué sabemos hoy".
>
> Per-experimento: `research/notes/E001_*` ... `E005_*`. Síntesis sobre proceso: `process_eval_design.md`. Síntesis sobre dónde nos ubicamos: `related_work.md`.
>
> **Regla de actualización**: cada vez que cierre un experimento, sumar 1-3 bullets al campo correspondiente. Si una conclusión se invalida, mover a "hipótesis falseadas" con fecha. No reescribir historia.

---

## 1. La conclusión que vale (mayo 2026)

> **El pipeline funciona end-to-end y produjo un patrón empírico inesperado: sobre 6 fotos pilot, el agente nunca usó `static_map`, `street_view`, ni `historical_query`. La hipótesis de por qué (modelo vs scaffold vs affordance) sigue abierta y es testeable.**

Detalle de lo observado (no de la interpretación):
- Corpus piloto filtrado adversarialmente: **180 fotos sampleadas → 101 sobreviven al atacante GPT-4o (56%)**. El filtro corre y produce ratios consistentes (60/79 rejects dispararon las 3 corridas).
- Sobre 6 fotos del piloto, agente ReAct con 12 tools, gpt-5.4: **1 acierto preciso** (1.8 km, Tomsk), 3 off (301/707/1352 km), 2 hit max_steps sin submit. **0 usos** de `static_map`, `street_view`, `historical_query` en las 6 trazas.
- Ablación de prompt v1/v2/v3 (mechanical, descriptive, thinking-visible): activa tools visuales **solo en 1 de 6 fotos** (Basel). v3 nailed Dealey Plaza (0 km) pero perdió Tomsk (2 → 3743 km).

**Lo que TODAVÍA NO sabemos** (movido a hipótesis abiertas §3.3): si el comportamiento "web-search bot" es propiedad del base model (réplica del finding CORRAL "base 41.4% varianza vs scaffold 1.5%"), o limitación del prompt actual, o artifact de affordance, o n=6 demasiado chico para conclusión. Requiere cross-model run + n mayor para responder.

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
| Sobre 6/6 fotos del pilot E005 v1: 0 usos de `street_view`, `static_map`, `historical_query` | E005 v1 trace counters | Patrón consistente en pilot (n=6); falta saber si es propiedad del modelo (gpt-5.4) o del scaffold/prompt. Hipótesis abierta §3.3. |
| Variancia run-to-run alta (factor 7x) | E001-E003 | N=3 corridas mínimo para conclusiones robustas. Solo 1 corrida en E005 → no robusto. |
| El modelo decide cuándo parar | E001-E005 | Cap 12 steps; típicamente usa 3-8 cuando submitea. 33% hit max_steps en E005. |
| Forzar uso de tools en prompt sesga el benchmark | E003 decisión + Codex review | Confirmado: el prompt es descriptivo, no prescriptivo. |
| Prompt descriptivo (v2) vs mechanical (v1) activa tools visuales **solo en 1 de 6 fotos** | E005 ablación | Affordance ayuda marginalmente. La hipótesis "el modelo no las conoce" queda parcialmente falseada. |
| Verbalización ReAct (v3) genera updates visibles pero **pierde aciertos** | E005 v3 vs v1 Tomsk | Trade-off. La verbalización no es siempre ganancia. |
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
| Output formatting estable (`results.json` schema versionable por `PROMPT_VERSION`) | E005 ablación | Pipeline de análisis post-hoc no fragmenta el output. |

---

## 3. Hipótesis explícitas

### 3.1 Validadas (con evidencia)

| Hipótesis | Evidencia | Confianza |
|---|---|---|
| El pipeline end-to-end corre sin errores técnicos | E002 + E003 + E005 corrieron sin error | Alta |
| El atacante GPT-4o tiene un patrón consistente (no es ruido) | 60/79 rejects con 3/3 triggering runs (E004) | Alta |
| `clean_image` + blacklist per-photo + hash hard reject cierran los shortcuts más obvios | Tests sintéticos + E005 Dealey Plaza con `target_match=1` y agente ciego al match | Alta para los shortcuts cubiertos. No descarta vectores aún no testeados (threat model #10). |
| Foto histórica cotidiana sin landmarks tiene reject rates bajos del atacante (sweet spot del corpus) | E001 sweet spot + E004 Russia-Asia reject 13% vs Norteamerica 80% | Media-Alta. Diferencia entre buckets es consistente con la hipótesis, pero atribución causal (landmarks vs familiarity de pretraining vs algo más) sigue confounded. |
| **Existe el efecto "tools mejoran dramáticamente vs no-tools" al menos en 1 caso** (Tomsk) | E002: 2573→8.5 km (300x); E005 Tomsk: atacante no aventuró → agente 1.8 km | Media. n=2 instancias. **No conclusión sobre la magnitud típica** — eso requiere más samples. |

### 3.2 Falseadas o parcialmente refutadas

| Hipótesis original | Evidencia que la contradice | Estado |
|---|---|---|
| "El modelo no usa tools visuales porque no las conoce" | Ablación v2/v3 movió 1/6 fotos; el modelo SÍ las conoce cuando se le pide | Parcialmente falseada. La razón sigue abierta (entrenamiento? incentivo? overconfidence en web_search?). |
| "Subir max_steps va a mejorar la investigación" | Hipótesis previa Codex review — NO escalada todavía | Pendiente test. Codex review afirmó "compraría más web_search". |
| Sesgo Rusia 70-95% (claim genesis) | Audit empírico: 62% Rusia, 74% ex-URSS | Falseada. Updated. |
| 47 shards de imágenes PastVu (claim pastvu_deep_dive) | Audit empírico: 2094 shards | Falseada. Updated. |

### 3.3 Abiertas y testeables

| Hipótesis | Cómo testearla | Costo |
|---|---|---|
| El comportamiento "web-search bot" es propiedad del base model, no del scaffold (réplica CORRAL en geo-loc) | Cross-model run: gpt-4o, gpt-5, gpt-5.4 (mínimo). Idealmente claude-opus, gemini. Mismas 6 fotos, mismo prompt. | Bajo — está bloqueado por .env (task #7). |
| Process score discrimina entre modelos donde distance no lo hace | Annotator CORRAL-style sobre traces E005 v1/v2/v3 + cross-model | Medio — annotator + judge LLM. Task #6 sobre task #3 design. |
| Subir max_steps de 12 a 30 sí mejora si combinado con prompt que activa tools visuales | A/B sobre 6 fotos: (12 steps, prompt v1) vs (30 steps, prompt v1) vs (30 steps, prompt v3) | Bajo — bloqueado por .env. |
| Multi-modal judge (Claude con vision) anota mejor que text-only judge | Comparar 2 anotaciones del annotator sobre las mismas trazas | Bajo si tenemos Anthropic API. |
| El `process_score` × `distance_km` produce 4 cuadrantes interpretables (process_eval_design §6) | Plot de E005 traces anotadas + N corridas más | Medio — requiere annotator corriendo. |

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
