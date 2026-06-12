# Harness review post-pivote belief — ¿las tools y el entorno sirven para lo que queremos medir?

> **Status**: working doc, junio 2026. Revisión crítica del harness (tools + entorno + task) a la luz del pivote belief-state (#47), con evidencia de E005-E012 + smokes E016.
>
> **Scope**: NO mejorar el solver (es un benchmark). La pregunta es si el HARNESS permite que la estrategia óptima sea investigar — y si lo que medimos es del modelo y no un artefacto nuestro.
>
> **Refs**: `tool_usage_audit.md` (1809 events), `tools_redesign.md` (v1 mayo, implementado), `belief_state_redesign.md` (las 4 condiciones), smokes E016 (Estocolmo ×2, Montevideo).

---

## 0. El marco: qué le pide el pivote belief al harness

Las 4 condiciones para que la política óptima sea investigación secuencial:
1. Ninguna acción individual resuelve.
2. **Las hipótesis intermedias son testeables.**
3. Las acciones tienen costo. ✅ (budget v1)
4. La informatividad depende del estado de creencias.

El belief reward mide ganancia de información por tool call. Eso solo tiene sentido si el harness ofrece **tests discriminantes reales** para las hipótesis típicas. Lente operativa para cada tool: *¿qué pregunta discriminante permite responder, y a qué costo?*

**Principio que sale de esta review**: el harness hoy hace el **lookup barato y fuerte, y la verificación cara y débil**. Para forzar investigación tiene que ser al revés: verificación barata y potente, lookup acotado.

---

## 1. Evidencia nueva (smokes E016) que los docs de mayo no tenían

### 1.1 `image_search` está DEGRADADO — esto es bug de harness, no comportamiento
En los 3 smokes, las grillas volvieron casi vacías o filtradas:
- Montevideo: 2 búsquedas → **grillas de 1 celda**; 1 búsqueda → `all_filtered`.
- Estocolmo: 3 de 4 grillas con **1 celda**; solo 1 con 16.

El flujo "escanear 16 → pick" que diseñamos en mayo no está ocurriendo porque el backend (DDG via `ddgs`) devuelve poco y el filtrado (blacklist + phash) come el resto. **Consecuencia grave**: la ruta de comparación visual — central para datación y verificación — está rota en la práctica, y empuja a los modelos a web_search. Parte de la "infrautilización de tools visuales" que atribuimos al modelo puede ser racional ante una tool que devuelve 1 thumbnail.

### 1.2 Budget quemado contra la blacklist sin feedback útil
Estocolmo: 3 `web_search site:wikimedia.org ...` consecutivas → 0 results (filtered 15-16/16) cada una. El modelo no sabe que wikimedia está en la blacklist GLOBAL y reintenta. Con budget activo, esto es plata quemada por **opacidad del harness**, no mala estrategia. Fix barato: cuando TODOS los resultados de una query caen por blacklist (especialmente con `site:`), el payload debe decir "dominio bloqueado por el benchmark para esta foto — no insistas con esta fuente".

### 1.3 La datación no tiene NINGUNA tool — y el lock-in narrativo lo explota
Hallazgo replicado (Estocolmo ×2): la evidencia web arregla ubicación y contamina año. Mirá el toolset: **las 12 tools sirven a la ubicación; ninguna sirve a la datación**. `historical_query` (OHM) es la única dating-aware (1.0% de uso, cobertura pobre fuera de Europa/US). Para datar, el agente solo puede: (a) percibir (ropa/autos/tipografía — sin referencia externa contra la cual testear), o (b) heredar la fecha de la narrativa textual que encontró — exactamente el shortcut que observamos. El eje temporal es NUESTRO diferenciador declarado (PROJECT.md, landscape §5) y es el peor servido por el harness. No es coincidencia que ahí esté la patología.

### 1.4 `web_search` mete un segundo LLM dentro de la observación
El backend es Azure Responses + Bing Grounding con **helper gpt-4.1-mini que redacta los snippets**. O sea: la "evidencia" que recibe el agente ya pasó por la interpretación de otro modelo (riesgo confirmado: "match alucinatorio en Bing", E010). Para un benchmark de juicio investigativo esto contamina la medición — parte de lo que medimos es gpt-4.1-mini, y un claim del evidence_chain puede ser fiel al snippet pero el snippet infiel a la fuente. Mínimo: documentarlo como limitación; mejor: instruir al helper a modo **extractivo puro** (citas textuales + URL, cero síntesis), o medir su tasa de infidelidad en una muestra.

---

## 2. Veredicto tool por tool

| Tool | Uso (audit) | Veredicto | Nota |
|---|---|---|---|
| `web_search` | 51.1% | **FIX** | Dominante por diseño: barata, fuerte, sin fricción. Helper LLM = confounder (§1.4). Feedback de blacklist opaco (§1.2). Con budget, su precio relativo es LA palanca para rebalancear. |
| `image_search` | 15.0% | **FIX URGENTE** | Backend degradado (§1.1). Es la tool de la que dependen datación y verificación visual. Auditar: ¿cuántas grillas de E009/E010 tenían <4 celdas útiles? |
| `crop_image(_relative)` | 12.1% | KEEP | Funciona y se usa bien (lectura de carteles, detalles). Barata, local. |
| `geocode/reverse` | 7.7% | KEEP | El smoke Montevideo la consagró: test discriminante a 1 punto. Exactamente lo que el budget debe premiar. |
| `static_map` | 4.3% | KEEP (post-v1) | Enriquecida en mayo (POIs/elevation/multi). Esperar datos del pilot. |
| `fetch_url(_with_images)` | 5.5% | KEEP (post-v1) | El fix de captions de mayo fue el correcto. |
| `street_view` | 3.3% | KEEP + WATCH | Infrautilización es en parte racional (era-mismatch: el edificio de 1916 no está). La metadata `verifiability` oculta (§4.3 del redesign) va a permitir separar "no verifica pudiendo" de "no puede". |
| `historical_query` (OHM) | 1.0% | WATCH | Única tool dating-aware. ¿1% es por cobertura OHM, por fricción del schema (bbox), o por el modelo? El pilot con budget da señal: si nadie la usa ni con presupuesto, evaluar reemplazo/refuerzo. |
| `submit_answer` | — | KEEP | evidence_chain agregado (#47). |
| `report_belief` | — | KEEP | Nueva (#47). Validada en smokes. |

---

## 3. Gaps priorizados

### P0 — antes del pilot completo (o como parte de su análisis)
1. **Auditar y reparar `image_search`**: medir sobre E009/E010/smokes el % de grillas con <4 celdas útiles. Causas candidatas: `ddgs` flaky/ratelimited, params de región, filtrado excesivo. Opciones: tunear ddgs, backend alternativo, relajar filtrado de suspicious (no de phash). Sin esto, el pilot mide modelos contra una tool rota.
2. **Feedback explícito de blacklist**: payload claro cuando una query muere entera por filtrado (§1.2). Una línea de código, elimina una fuente de ruido en la métrica de eficiencia.

> **UPDATE 2026-06-12 — TODO LO DE ABAJO YA ESTÁ ARREGLADO** (misma sesión, ver commit):
> - `image_search`: el diagnóstico encontró cosas peores que lo previsto — (a) `_do_pick` crasheaba SIEMPRE con AttributeError (campos renombrados en refactor #45, tragado por el except genérico del scaffold → el modo zoom estuvo muerto desde mayo); (b) páginas 2+ se renderizaban como grillas negras (posicionamiento por número global) Y sus celdas eran impickeables (validación contra 16); (c) canvas 4×4 completo para 1 celda; (d) confirmado por diagnóstico directo: DDG devuelve ~1 resultado crudo para queries largas (vs 35 para cortas) → fallback transparente con query simplificada + aviso al modelo. Tests unit sin red: `scripts/test_image_search_unit.py`.
> - `web_search`: early-block de `site:` sobre dominio bloqueado (corta antes de pagar la call), nota explicativa cuando todo cae por blacklist, y helper en modo EXTRACTIVO (citas literales, prohibido sintetizar — mitiga §1.4).
> - Audit del resto del harness (agente + verificación): (1) `invalid_submit` no terminaba el episodio y dejaba tool_calls huérfanas → 400 de API; (2) `street_view nearby` prometido en prompt pero jamás cableado (schema no lo declaraba, react no lo pasaba, imágenes nearby nunca se inyectaban) — cableado completo; (3) default real de web_search era 5 vs 10 prometido; (4) `year` string crasheaba historical_query; (5) flag `truncated` de OHM casi siempre true falso; (6) hard cap "step 18-19" hardcodeado en prompt vs max_steps=50 real → reescrito dinámico.
>
> Implicación: **la conclusión "tools visuales infrautilizadas" de E005-E012 está parcialmente confundida por harness roto** (pick muerto, nearby muerto, grillas vacías). Re-evaluar tras el pilot con harness reparado.

### P1 — corto plazo, alto valor
3. **`compare_images` — la primitiva de verificación que falta.** Verificar ES comparar (GeoWizard: lado a lado, triangulación). Hoy el agente ve la foto target y el candidato en TURNOS DISTINTOS y compara de memoria — y el pruning de contexto (>45 imágenes) le borra los pixels viejos. Propuesta: toda imagen que entra al contexto recibe un id estable (`img_001`); `compare_images(ids=[...], regions=[...])` compone un side-by-side local (PIL, gratis) y lo devuelve como UNA imagen. Bonus: resuelve también el re-acceso post-pruning (hoy el marker dice "invocá la tool original", que puede costar budget y no ser reproducible). No le hace el razonamiento al agente — le da la mesa de trabajo del detective.
4. **`web_search` extractivo** (§1.4): snippets = citas textuales de la fuente, sin síntesis del helper. Reduce el confounder y hace los claims del evidence_chain verificables contra texto real.

### P2 — diseño, para la siguiente iteración del benchmark
5. **Verificación EN EL PASADO fuera de Europa**: OHM no cubre; street_view es presente. El slot histórico real son **mapas históricos georreferenciados** (MapWarper / NYPL / Sanborn — ya identificados en viability §bloqueador 9) y archivos (LoC API). Es la inversión que haría única la capacidad de verificación del benchmark. Esfuerzo medio-alto.
6. **Revisar la blacklist de Wikimedia/Commons**: hoy GLOBAL block. Mata al archivo público más grande del mundo como fuente de referencia datada legítima (fotos históricas con fecha para comparar estilos/vehículos). Tensión real: el target puede estar mirrorreado en Commons con coords. Opciones a evaluar: permitir Commons solo en `image_search`/`fetch_url_with_images` con phash hard-reject (ya existe) + supresión de metadata estructurada de coordenadas en el payload. Decisión con datos: ¿cuántas fotos del corpus tienen match phash en Commons?
7. **Costos del budget como instrumento de diseño**: con datos del pilot, recalibrar la tabla para que el precio relativo verificación/lookup empuje la estrategia deseada (ej: si web_search sigue dominando, subirla a 4-5; mantener geocode/crop/compare baratas).

---

## 4. Qué NO hacer (y por qué)

| Idea (GeoBrowse u otras) | Razón |
|---|---|
| Super-resolution / pixel analysis | Invita alucinación de detalle; crop + visión nativa ya decidido (CURRENT_STATE). |
| Rotate / auxiliary lines | Valor marginal en fotos históricas (no son panos esféricos); compare_images cubre el caso real. |
| Code interpreter | Abre superficie enorme de shortcut (scraping arbitrario) y rompe el contrato de tools tipadas. |
| Tools de "análisis" (date_this_car, architectural_style) | Le hacen el razonamiento al agente — exactamente lo que el benchmark debe medir, no proveer. |
| Browser real | Esfuerzo enorme; reevaluar recién si fetch_url+image_search reparadas se quedan cortas. |

**Línea roja conceptual**: toda tool nueva debe proveer **evidencia o composición de evidencia**, nunca interpretación. Si la tool opina, contamina la medición.

---

## 5. Cómo decide esto el pilot (ya instrumentado)

El pilot E016 produce por corrida: tools usadas por step + beliefs antes/después + budget. Eso da directamente:
- **Ganancia de información por tool** (Δscore atribuible al step que la usó): ranking empírico de qué tools compran información — la versión cuantitativa de este review.
- **image_search usefulness**: % de grillas con celdas útiles (cruza con §1.1).
- **historical_query/street_view bajo presupuesto**: si con budget nadie las toca, no es pereza — es que no compran información para estas fotos (o el modelo no sabe extraérsela; el brazo on/off + verifiability metadata separan las hipótesis).

**Decisión propuesta**: P0 se hace ya (fix barato + audit). P1.3 (compare_images) y P1.4 (web_search extractivo) se deciden CON los datos del pilot — si la ganancia-por-tool confirma que la ruta visual está muerta, son la inversión siguiente. P2 entra al roadmap del paper como "harness v2".
