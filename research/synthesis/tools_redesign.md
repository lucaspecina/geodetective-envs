# Tools redesign — plan de mejoras v1

> **Status**: draft mayo 2026.
>
> Documento canónico de cambios al stack de tools del agente, motivados por:
> 1. Análisis cualitativo de uso real (1809 events de E005/E009/E010/E012) — ver `research/notes/tool_usage_audit.md`
> 2. Comparación con flujo humano experto (GeoWizard de GeoDetective, vía NotebookLM)
> 3. Hallazgos cualitativos de E010 (lock-in, queries descriptivas, tools visuales infrautilizadas)
>
> **Principio rector**: NO agregar tools nuevas. Enriquecer las tools existentes sin cambiar el schema que ve el agente.

---

## Contexto: el gap fundamental

Comparando comportamiento de los modelos con el de GeoWizard (humano experto):

| Aspecto | GeoWizard | Nuestros modelos hoy |
|---|---|---|
| Herramienta visual principal | **Google Earth** (3D terrain, rastreo libre de costas/montañas) | `static_map` snapshot estático |
| Street View | Navegación libre + uso intenso | 1-4 vistas estáticas por call |
| Profundidad en una fuente | 80+ minutos en Wikipedia leyendo | 3 segundos por página |
| Verificación visual | Comparación imagen vs candidato, triangulación | Saltos textuales sin verificación visual |
| Hipótesis competidoras | Mantiene múltiples, descarta con evidencia | Lock-in en 3/5 fotos (E010) |
| Caption + imagen | Conectado en el HTML que mira | **Desconectado**: las imágenes vienen sin caption |

El gap principal NO es "qué información existe", sino **PROFUNDIDAD de exploración** y **conexión texto↔imagen**.

---

## Las 5 mejoras (detalle)

### 1. `static_map` — vista enriquecida con contexto del lugar

**Motivación**: hoy el modelo recibe solo un snapshot del mapa. GeoWizard usa Google Earth para entender "qué hay alrededor". Nuestros agentes no tienen ese contexto.

**Cambios al backend** (mismo schema del tool):

- Por cada `static_map` exitoso, el payload agrega:
  - **POIs cercanos** (Places API Nearby Search en radio 200m): hasta 5 lugares con `name`, `type`, `distance_m`.
  - **Altitud** (Elevation API en el punto pedido): metros sobre nivel del mar.
  - **Terrain category** computada a partir de elevation samples en radio 1km: `flat` / `rolling` / `mountainous` (basado en std de elevación).
- Opcional: nuevo argumento `view="multi"` → devuelve **3 imágenes en una sola call** (sat + terrain + roadmap). Para uso intenso, ahorra calls.

**Costo incremental**: ~$0.02 por call (Places Nearby + Elevation).

**Por qué importa**:
- El modelo puede pedir `static_map(lat, lon)` y saber inmediatamente si la zona es montañosa (relevante para fotos rurales como Cáucaso) o costera, qué hay alrededor, sin gastar 3 tool calls separadas.

**Riesgos**:
- Places puede devolver POIs irrelevantes (publicidad/spam). Filtrar por `type` razonable.
- Elevation tiene rate limits propios.

---

### 2. `street_view` — más perspectiva, menos comprometido

**Motivación**: en E010 vimos que el modelo hace 1 street_view post-decisión "solo para confirmar". Eso no es verificación, es búsqueda confirmatoria. Si por default damos 4 vistas, lo forzamos a NO comprometerse a una sola dirección visual.

**Cambios al backend** (mismo schema):

- **`contact_sheet=True` por DEFAULT** (antes default era `False`, una sola imagen).
- Nuevo argumento opcional `nearby=True` (default `False`): devuelve además 3-4 panoramas de puntos en radio ~50m del centro pedido. Imita "caminar la cuadra".
- Payload agrega **POIs visibles** en el panorama (Places API en radio 30m): hasta 3 lugares con nombre + distancia.

**Costo incremental**:
- Por default con contact_sheet: 4 imágenes en vez de 1, +$0.06 por call (4× Street View Static).
- Con `nearby=True`: +4 panoramas más, +$0.06 adicional.
- POIs: +$0.01.

**Por qué importa**:
- El sesgo "ver solo una cara del lugar" se reduce automáticamente. 
- El modelo puede invocar `street_view(lat, lon, nearby=True)` cuando está investigando seriamente una hipótesis.
- POIs visibles le permiten verificar "Praça da Liberdade está cerca acá" sin otra tool call.

**Riesgos**:
- 4× más costo por default. Aceptable para benchmark.
- Si `nearby=True` se usa mucho en min_steps altos, podría disparar acumulación de imágenes (mitigada por cleanup automático ya implementado).

---

### 3. `web_search` — más resultados, más metadata

**Motivación**: el humano de GeoWizard scrollea decenas de resultados; el modelo ve 5. Las queries que generan son largas y específicas — necesitan más resultados para encontrar el match relevante.

**Cambios**:

- **Default `max_results=10`** (era 5).
- **Snippets más largos**: instruir al helper (gpt-4.1-mini) a devolver 1500-2000 chars por resultado (era ~800).
- **Metadata enriquecida** por resultado:
  - `site_name` (ej "Wikipedia", "fotopolska.eu", "archive.org") destacado
  - `date_published` (si lo encuentra)
  - `language`
  - `type` (article / wikipedia / archive / blog / social)

**Costo incremental**: ~$0.01 por call (helper produce más output).

**Por qué importa**:
- Más resultados = más oportunidad de encontrar el match. 
- Metadata permite priorizar fuentes confiables ("wikipedia > random blog") sin tener que hacer `fetch_url` a cada una.
- Snippets más largos reducen la necesidad de hacer `fetch_url` para detalles que el snippet ya contiene.

**Riesgos**:
- Más tokens del helper, ligeramente más costo. Insignificante.

---

### 4. `fetch_url_with_images` — conexión texto↔imagen (el upgrade más jugoso)

**Motivación**: gap CRÍTICO descubierto en el análisis de tools. Cuando el modelo abre una página con imágenes embebidas, recibe la imagen pero **NO el caption ni el alt text** del HTML. La página dice *"Eléctrico nº 73 en la Praça da Liberdade, 1947"* en un `<figcaption>` y el modelo recibe la imagen completamente desconectada de ese contexto.

**Cambios al backend** (mismo schema):

- Por cada imagen extraída del HTML, extraer y conectar:
  - `alt` text del `<img>`
  - `figcaption` si está en un `<figure>`
  - **Texto del párrafo inmediato anterior** (~200 chars)
- Inyectar como **label antes de cada imagen** en el siguiente turn:

```
[Imagen de https://archives.pt/img/123.jpg
 Caption: "Eléctrico nº 73 en la Praça da Liberdade, 1947"
 Alt text: "Lisbon tram"
 Contexto cercano: "Esta vista muestra el tranvía circulando por la avenida..."]
[IMAGEN]
```

- **Aumentar cap de 5 a 10 imágenes** por página.
- **Hacer este el default** de `fetch_url`. Renombrar el actual `fetch_url` (text-only) a `fetch_url_text_only` o eliminarlo del schema.

**Costo incremental**: $0 (todo es parsing más completo del HTML, sin más calls externos).

**Por qué importa**:
- Hoy: el modelo abre una página, ve fotos sueltas, no sabe qué dicen.
- Mañana: ve foto + caption en la misma "tarjeta" → puede confirmar/descartar inmediatamente.
- **Esto cierra el bug semántico más grande de las tools actuales**.

**Riesgos**:
- HTML mal estructurado puede dar alt/caption ruidosos. Mitigación: límite de chars + sanitización.
- 10 imágenes por página puede sumar al límite de 50 imágenes en contexto. Cleanup automático ya lo maneja.

---

### 5. `image_search` — grilla 4×4 con zoom on-demand

**Motivación**: el flujo humano en Google Images es "ver 50 thumbnails → escanear visualmente → clickear los interesantes". Nuestro modelo ve 3-5 imágenes con peso completo. Esto es un desbalance crítico: el modelo procesa cada imagen como si fuera la foto target.

**Cambios al backend** (con validación empírica previa):

**Pre-requisito empírico**: smoke test (~$0.10, 30 min) para validar que los VLMs (gpt-5.4-mini, gpt-4o, claude-sonnet-4-6) pueden leer grillas numeradas 4×4. Si fallan → re-pensar (más resolución por celda, menos celdas).

**Si valida**:
- `image_search(query)` devuelve **grilla 4×4 como UNA imagen** (16 celdas 256×256, numeradas con borde sólido).
- Metadata por celda: URL fuente, hamming distance vs foto target, alt text si disponible.
- Tool implícita: `image_search(query, pick=[3, 7])` → devuelve las celdas elegidas en alta resolución 512×512 (slot por imagen).
- Backend baja 50 imágenes en paralelo, hace pHash check ANTES de componer la grilla (anti-shortcut), descarta matches con foto target, samplea las top-16 por diversidad.

**Costo incremental**:
- 50 imágenes bajadas en paralelo en backend: ligeramente más slow (~5-10s vs 2s actual).
- Para el modelo: 1 slot por la grilla + N slots por los picks = típicamente 3 slots vs 3 actuales. Sin cambio en contexto.

**Por qué importa**:
- Replica el flujo humano "escanear grid → descartar 90% → ahondar en lo relevante".
- El modelo NO procesa 16 imágenes con peso completo — las escanea como UNA imagen y luego pide profundizar en 1-3.

**Riesgos**:
- VLMs pueden no leer grillas con suficiente precisión. **Validación empírica obligatoria primero**.
- Resolución por celda limitada (256×256). Detalles finos (cartel pequeño, marca de auto) podrían perderse en el escaneo.
- Stale index entre `image_search` y `pick` — necesita cache estable.

---

## Lo que NO hacemos en esta tanda (y por qué)

| Idea | Razón de exclusión |
|---|---|
| **Aerial View API** (videos pre-renderizados 3D) | Cobertura limitada a localizaciones populares, valor incremental cuestionable vs `static_map(view=multi)` |
| **Photorealistic 3D Tiles + viewer** | Esfuerzo grande (CesiumJS, server con WebGL); mejor postergar a v2 cuando evaluemos browser-use real |
| **Street View histórico (timeline)** | Nuestras fotos son anteriores a 2007 (cobertura Street View). Inútil. |
| **Wikipedia search dedicado** | `web_search` con metadata enriquecida + `type=wikipedia` ya prioriza Wikipedia |
| **`draw_on_image` (triangulación tipo MS Paint)** | Específico de GeoWizard, no es flujo general. Postpuesto. |
| **Tools nicho** (vehicle_lookup, uniform_lookup, architectural_style) | Solo aplican a algunas fotos. Costo/beneficio bajo |
| **Browser real (playwright + visión)** | Esfuerzo MUY grande. Nivel 3 — para v2 del benchmark |

---

## Plan de implementación (post-review Codex agentId aef3afc603c09f3fa)

### Cambios post-review aplicados al plan

| Original | Update post-Codex |
|---|---|
| Fase 1: web_search primero | **`fetch_url_with_images` primero** (el bug más claro) |
| `contact_sheet=True` default permanente | **Como flag/ablation primero**, no cambio permanente (multiplica costo sin cambiar schema) |
| Alt + figcaption + párrafo previo | **Más fuentes**: title, aria-label, srcset, data-*, link padre, filename, OG/Twitter, JSON-LD schema.org. Buscar en ancestor semántico (`<figure>`, `<article>`), no previous-sibling literal |
| Eliminar `fetch_url` text-only | **NO eliminar** — mantener `include_images="auto"|false|true` con back-compat |
| `view="multi"` = 3 imágenes separadas | **Composición 2×2 o 3-panel en UNA imagen** (Azure cuenta cada imagen como slot) |
| POIs top-5 por distancia | **Top-5 por relevancia tipada**: monumentos, estaciones, iglesias, puentes, plazas > cafés/restaurantes |
| Terrain category sola | **Categoría + samples raw resumidos** (auditabilidad ante terreno local raro) |
| `nearby=True` → contact_sheet=False auto | **Pocos panoramas bien elegidos** con 1-2 headings por pano. Usar Street View metadata para panoramas reales sobre calles (no cardinales desde coords arbitrarias) |
| Grilla 4×4 sin acceso post-pick | **Mantener grilla visible + picks zoomeados** (numeración como referencia) |
| Smoke: 16 imágenes random | **Mezcla**: 2-3 plausibles + distractores visuales + distractores textuales + crops + pHash bloqueados |
| Sin cache | **Cache compartida obligatoria ANTES de escalar** (Places/Elevation a 1800+ events es problema serio) |

### Fase 1 — Cambio más jugoso primero (1-2 días)

1. **`fetch_url_with_images`** — **prioridad #1**:
   - Extraer fuentes semánticas: alt, title, aria-label, srcset/picture, data-caption/data-*, link padre, filename, OpenGraph/Twitter image, JSON-LD `ImageObject`
   - Buscar contexto narrativo en ancestor semántico (`<figure>`, `<article>`, `<main>`, cards) — `<p>` más cercano con >50 chars
   - Cap 5→10 imágenes
   - Mantener `fetch_url` text-only con flag `include_images="auto"|false|true` (back-compat)
   - **NO eliminar la versión text-only**

2. **`web_search`**: max_results=10, snippets 1500-2000, metadata enriquecida (site_name, date, language, type)

3. **`street_view`** `contact_sheet=True` **como flag opt-in con ablation**, NO default cambiado. Documentar como variante a probar.

### Fase 2 — APIs nuevas + cache compartida (2 días)

4. **Cliente Google común con cache compartida** (PRE-requisito de #5):
   - Módulo nuevo `src/geodetective/tools/google_api.py` con cliente unificado
   - Cache por endpoint con key cuantizada (lat/lon redondeados a ~10m precision)
   - TTL por tipo (Places: 1h; Elevation: indefinido — terrain no cambia; Static Maps: 1h)
   - Error handling parcial NO-FATAL: si Places falla, `static_map` devuelve igual sin POIs

5. **`static_map` enriquecido**:
   - POIs top-5 filtrados por tipo (monumentos > estaciones > iglesias > puentes > plazas > parques > cafés/restaurantes último)
   - Elevation API: altitud + samples raw resumidos + categoría computada
   - `view="multi"` → UNA imagen compuesta (2×2 grid de sat + terrain + roadmap + hybrid)

6. **`street_view`** opcional `nearby=True`:
   - Usar **Street View metadata API** para encontrar panoramas reales más cercanos sobre calles (no construir cardinales desde coords arbitrarias)
   - 3-4 panoramas con 1-2 headings cada uno (no full contact_sheet)
   - Payload llama "nearby POIs" (no "POIs visibles" — Places radius no garantiza visibilidad)

### Fase 3 — `image_search` rediseño (con validación)

7. **Smoke empírico de grilla** (30 min, $0.10):
   - Construir grilla 4×4 con **mezcla intencional**: 2-3 verdaderamente plausibles + distractores visualmente cercanos + distractores textualmente cercanos + distintos crops + 1-2 casi-duplicadas pHash-bloqueadas
   - Test sobre gpt-5.4-mini, gpt-4o, claude-sonnet-4-6
   - Comparar 4×4 vs 2×4 (más simple, menos slots)

8. Si valida 4×4: implementación
   - pHash check ANTES de componer (anti-shortcut)
   - Cache estable de grillas por query (índices reproducibles)
   - `pick=[3,7]` devuelve picks en alta res + **grilla original sigue visible** (referencia)

### Fase 4 — Ablation controlada antes de cambiar defaults

9. **A/B tests sobre subset de 5-10 fotos**:
   - Comparar `contact_sheet=False` default vs `True` default (medir si confunde con vistas irrelevantes)
   - Comparar `fetch_url` text-only vs `include_images="auto"`
   - Si A/B muestra mejora consistente → mover a default. Si no → mantener como flag opcional.

### Fase 5 — Validación end-to-end + métricas de lock-in

10. Re-correr E010 (gpt-5.4-mini × 5 fotos) con todas las mejoras. Las métricas críticas:

---

## Métricas a medir post-implementación

**⚠️ Lo más importante** (insight Codex): NO basta con "más información" — hay que medir si **reduce el lock-in observado en E010**.

- **🔑 Lock-in rate**: % de fotos donde la hipótesis principal del step 1 == hipótesis del submit. Esperamos: BAJE. **Si esto no baja, las mejoras agregaron contexto sin mejorar pivote.**
- **🔑 Hypothesis pivots**: ¿el modelo verbaliza al menos 2 hipótesis competidoras en algún momento? Esperamos: SUBA.
- **Tool usage shift**: ratio web_search vs tools visuales. Esperamos: tools visuales suban.
- **Verification depth**: chars de `verification_checks` que citan evidencia visual concreta (POIs verificados, comparación con street view candidatas). Esperamos: suba.
- **Distance metrics**: media + std + buckets (1/5/25/100/500 km). Mejora esperable marginal — las tools no resuelven lock-in semántico solo.

Si lock-in rate NO baja después de Fase 5, el problema es de **prompt/comportamiento del modelo**, no de tools. En ese caso pivotamos a issue #31 (prompt iteration) con prioridad alta.

---

## Refs

- `research/notes/tool_usage_audit.md` — análisis cuantitativo + ejemplos por tool
- `research/notes/E010_iteration_findings.md` — 5 patrones del modelo
- `research/synthesis/experiment_design.md` — ejes experimentales canónicos
- `research/synthesis/findings_so_far.md` — hallazgos transversales
- Comentario NotebookLM sobre GeoWizard (en hilo de chat, 2026-05-18) — flujo humano experto
