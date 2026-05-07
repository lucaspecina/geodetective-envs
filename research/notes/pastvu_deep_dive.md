# PastVu — Deep Dive

> Investigación inicial sobre la fuente principal de datos para GeoDetective Envs.
> Autor: Claude (Opus 4.7). Fecha: 2026-05-07.
> Status: research-only — no se descargó el dataset, todo es metadato + docs públicas.

---

## Qué es

**PastVu** ([pastvu.com](https://pastvu.com)) es una plataforma rusa de crowdsourcing dedicada a recolectar, geolocalizar, atribuir y discutir fotografías históricas (y en menor medida pinturas, dibujos y postales) del "hábitat de la humanidad". Fue fundada en **2009** por Ilya Varlamov y Alexey Duk, originalmente como dos sitios separados — `oldmos.ru` (Moscú) y `oldsp.ru` (San Petersburgo) — que en **2013** se fusionaron bajo el dominio actual y abrieron el alcance al mundo entero. El proyecto se volvió **open source en 2020** (backend Node.js + MongoDB + Redis, frontend Knockout.js + Leaflet) bajo licencia AGPL-3.0, con el contenido bajo **CC-BY 4.0** según la documentación oficial.

La comunidad sube imágenes con coordenadas y dirección de toma (azimut), y un equipo jerárquico de moderadores regionales y globales aprueba o rechaza cada submission. Hay reglas estrictas: mínimo 700 px en el lado mayor, máximo 10 MB, no fotos posteriores a 2000 (ni tomadas ni creadas, en el caso de pinturas, después de 1980), no contenido mejorado con IA, no fotos familiares sin contexto geográfico, no exhibits de museo, no páginas escaneadas de revistas. Hitos de crecimiento publicados:

- 2013: ~110k imágenes públicas
- 2017: 500k
- 2019: 800k
- 2020: 1M (+ open source)
- 2021: PastVu 2.0 con mejor manejo de geo-data
- 2024: campaña de crowdfunding completada en 24h

El **dataset en HuggingFace** es [`nyuuzyou/pastvu`](https://huggingface.co/datasets/nyuuzyou/pastvu), un volcado snapshot del **2025-07-23** (también disponible vía [Academic Torrents](https://academictorrents.com/details/8cf94961303049e94ed82374221602aba17f6926)). Empaqueta ~2.09 M imágenes en formato WebDataset (tar shards) más un archivo único de metadatos JSONL comprimido.

---

## Volumen y formato

- **Total de samples**: ~**2,093,000** entradas (1 split: `train`).
- **Tamaño total declarado**: **1.8 TB** (academic torrent) — es el volumen completo con imágenes en máxima resolución original.
- **Discrepancia importante**: el árbol visible de archivos en HuggingFace (al consultar el repo directamente) muestra solo ~47 tar shards visibles (~14.7 GB) más `pastvu.jsonl.zst` (296 MB). Esto **NO** coincide con el "1.8 TB / 2,094 shards" del README. Hipótesis: el listing del Hub está paginado y solo expone una porción — hay que confirmar con `huggingface_hub list_repo_files` o `git ls-remote`. **Acción pendiente**: ejecutar `huggingface-cli scan` o equivalente antes de planificar storage.
- **Cuántos georreferenciados con (lat, lon)**: el README dice "geographical coordinates are provided for **most** images". No hay número exacto publicado, pero como las reglas de upload exigen geolocalización (al menos país/región/asentamiento más cercano si no hay coordenada exacta), la fracción con `geo: [lat, lon]` numérico debería ser **alta — estimación 85-95%**. Hay que verificar empíricamente sobre el JSONL.
- **Cuántos con fecha**: similar — el field `year` (int64) es obligatorio implícitamente porque PastVu rechaza fotos que no se puedan datar siquiera aproximadamente. `year2` aparece cuando hay rango (ej. "1920-1925"). Estimación >95% con `year` válido.
- **Resolución**: imágenes descargadas a "best available resolution from original source". Mínimo de upload en PastVu es 700 px lado mayor. Promedio probable 1-2 MP.

### Formato WebDataset por sample

Cada shard es un `.tar` con grupos por `cid` (content ID):

```
{cid}.jpg     ← imagen
{cid}.json    ← metadatos
```

Convención WebDataset estándar: el dataloader agrupa por basename. La metadata completa también se duplica en `pastvu.jsonl.zst` (un JSON por línea, comprimido con zstd) — útil para **filtrar antes de descargar shards de imágenes**, que es lo que vamos a hacer nosotros.

### ⚠️ Bug del schema reportado

El dataset viewer de HF está roto: tira `ArrowTypeError` porque el field `frags[].h` está tipado como `int64` en algunos shards y como `double` en otros. **Implica**: no se puede usar `datasets.load_dataset(..., streaming=True)` ingenuamente sin un schema custom. Hay que parsear con `webdataset` library directamente o post-procesar el JSONL manualmente.

---

## Distribución temporal

**No hay histograma publicado** ni en el card de HF ni en docs.pastvu.com. Lo que sabemos:

- Rango: **1826 - 2000** (174 años).
- "Peak periods: Soviet era (1920s-1990s) with extensive documentation" (README).

**Estimación cualitativa** (basada en cómo funcionan estos archivos comunitarios):

| Período | Estimación grosso modo | Notas |
|---|---|---|
| 1826-1839 | <100 imágenes | Pre-fotografía. Casi seguro pinturas/grabados, no fotos reales. |
| 1840-1900 | ~3-8% | Daguerrotipos, calotipos, albúminas. Mayoría rusas. |
| 1900-1940 | ~20-30% | Era zarista tardía + post-revolución + entreguerras. |
| 1940-1960 | ~15-25% | Guerra + reconstrucción. |
| 1960-2000 | **~40-55%** (mayoría) | Era soviética tardía + perestroika. Probablemente la mayor parte del corpus. |

**Acción crítica**: hay que generar este histograma real en la primera pasada sobre el JSONL. Es trivial (`year` está en cada record) y necesario para entender qué chunks son aprovechables.

**⚠️ Pre-1839 = pinturas, no fotografías**. La fotografía se inventa en 1839 (Daguerre). PastVu admite explícitamente "photography, painting, drawing, or engraving" en sus reglas. El field `type` (int) las distingue. **Hay que filtrar por `type` para quedarnos solo con fotos reales** si queremos que el agente entrene sobre fotografías. La codificación exacta del `type` (qué entero = foto vs pintura) **no está documentada en el card de HF** — hay que inspeccionarla en el JSONL o ver el código del repo PastVu (AGPL en GitHub: [PastVu/pastvu](https://github.com/PastVu/pastvu)). Como pista: el endpoint `photo.giveNearestPhotos` de la API acepta `type: "photo"` o `type: "painting"` como string, lo que sugiere que internamente hay 2-3 valores enteros mapeables.

---

## Distribución geográfica

**No hay breakdown publicado por país en el card**, pero las señales convergen fuertemente hacia **sesgo masivo a Rusia / ex-URSS**:

- Origen del proyecto: oldmos.ru (Moscú) → oldsp.ru (San Petersburgo) → PastVu global. Las dos primeras ciudades arrastran masa crítica histórica.
- Idioma primario de metadata: **ruso**. Inglés es secundario.
- Comunidad: rusoparlante, moderadores regionales mayoritariamente rusos.
- Nombres de regiones en metadata: `title_ru` y `title_en` (los dos siempre presentes para regiones soviéticas, no necesariamente para fuera).
- Cita textual del card: "primarily focused on Russia and former Soviet territories, though it includes photographs from around the world".

**Estimación** (sin datos duros, pero alineada con cómo crecieron Wikimapia, oldNYC, etc.):

| Bloque | Estimado |
|---|---|
| Rusia (Moscú + SPb + resto) | **55-70%** |
| Ex-URSS (Ucrania, Bielorrusia, Bálticas, Cáucaso, Asia Central) | **15-25%** |
| Europa Occidental | **5-10%** |
| Resto del mundo | **<5%** |

El field `regions[]` por sample tiene una jerarquía multinivel (continente → país → región administrativa → ciudad → barrio) con `cid`, `title_en`, `title_ru`, y conteos `phc/pac/cc`. Esto permite agrupar fácilmente por país una vez tengamos el JSONL parseado.

**Acción crítica**: contar samples por `regions[0].cid` o por el primer nivel administrativo. Esencial para decidir balanceo geográfico.

---

## Metadata por sample

Lista completa de fields (extraída del README de HF):

### Identificación
- `cid` — Content ID único (int64). Sirve como filename y para construir URL pública (`https://pastvu.com/p/{cid}`).
- `type` — Integer; codifica foto vs pintura vs dibujo vs grabado. **Mapeo no documentado, hay que decodificar.**
- `s` — Status / quality flag (int64).

### Imagen
- `file` — URL relativa al imagen original (sirve a través de `https://img.pastvu.com/d/{file}` standard, `/a/{file}` original, `/h/{file}` thumbnail).
- `w`, `h` — dimensiones originales en px.
- `ws`, `hs` — dimensiones escaladas.
- `frags[]` — regiones de interés / fragmentos anotados con `{cid, h, l, t, w}` (top-left + size, normalizadas).

### Temporal
- `year` — año primario (int64). **Field clave**.
- `year2` — año final si es rango.
- `y` — string repr del año (probablemente para rangos textuales tipo "1920-е").
- `adate`, `cdate`, `ldate`, `ucdate` — timestamps de upload / creación / modificación / cambio de usuario en PastVu (no del fotógrafo).

### Geográfico
- `geo: [lat, lon]` — **Field clave**. Doubles. Convención: latitud primero.
- `r2d` — array de doubles, datos de referencia geográfica adicionales. Probablemente relacionado con la dirección de toma o radio. **No documentado en el card, hay que reverse-engineer.** Posible significado: 2D rotation / direction reference.
- `dir` — orientación / dirección de la imagen (string). Casi seguro azimut de la dirección hacia la que apunta la cámara, en grados.
- `regions[]` — jerarquía de regiones administrativas con `cid`, `title_en`, `title_ru`, `phc`, `pac`, `cc`.

### Texto
- `title` — título / descripción corta (idioma original, mayormente ruso).
- `desc` — descripción larga.
- `author` — fotógrafo o autor.

### Comunidad / atribución
- `user{login, avatar, disp, sex, ranks[]}` — uploader info.
- `album` — album ID si pertenece a uno.

### Watermark
- `waterh`, `waterhs`, `watersignText`, `watersignTextApplied` — info sobre marca de agua aplicada por PastVu. **Importante para nosotros**: si las imágenes en el dataset están marcadas con "PastVu" como watermark, es una **fingerprint de contaminación** para reverse image search.

---

## Calidad y limitaciones

### Calidad de la georreferenciación

- **Qué representa la coordenada**: el "shooting point" (punto de toma del fotógrafo), no el sujeto. Esto está implícito en la API (`photo.giveNearestPhotos` ordena por distancia al shooting point) y en el feature de "dirección de toma" (`dir`). Para nuestro caso es **lo que queremos** — el agente debe predecir dónde estaba parado el fotógrafo.
- **Precisión esperada**: la UI de PastVu permite arrastrar un pin en un mapa de Leaflet. Asumiendo zoom típico de calle, precisión ~10-50 m en zonas urbanas, peor en zonas rurales. **No hay metadata explícita de precisión** (no hay un field tipo `geo_accuracy_m`).
- **Errores conocidos**: la moderación es comunitaria; las reglas exigen al menos país+región+asentamiento. Hay garantía de país correcto pero no de precisión sub-ciudad.

### Pinturas / grabados / dibujos mezclados con fotos

PastVu admite explícitamente "photography, painting, drawing, or engraving". El field `type` los distingue. Para nuestro proyecto:

- **Pre-1839**: descartar todo (no son fotos). Se filtra con `year >= 1839` y `type = photo`.
- **1839-1900**: filtrar `type = photo` para excluir pinturas que ilustran ese período.
- **Post-1900**: `type = photo` también, pero menos crítico.

**Hay que decodificar el mapeo de `type`** antes de cualquier cosa. Tres caminos:
1. Inspeccionar `pastvu.jsonl.zst` y agrupar por `type` distintos, mapear contra muestras visuales.
2. Mirar el código del modelo Mongoose en [github.com/PastVu/pastvu](https://github.com/PastVu/pastvu).
3. Llamar a `photo.giveForPage` para una serie de `cid`s con tipos conocidos y observar el campo.

### Otras limitaciones

- **Watermark de PastVu** posiblemente impreso en la imagen renderizada (no la original). Si el snapshot del dataset tiene watermarks, los modelos pueden aprender atajos. Hay que ver muestras antes de entrenar.
- **Schema inconsistency** en `frags[].h` (int vs double) → cuidado con el loader.
- **Calidad heterogénea**: imágenes de 700 px son aceptadas. Hay que filtrar por resolución mínima si queremos calidad visual decente.
- **Idioma ruso**: si vamos a usar el `title`/`desc` para nada (ej. señales débiles para training, o data filtering), necesitamos traducción. Para *evaluación adversarial* (¿una descripción es googleable?) hay que traducir y probar contra Google.

---

## License y términos de uso

- **PastVu (sitio)**: contenido bajo **CC-BY 4.0** según docs.pastvu.com (texto explícito en la home de la doc).
- **HF dataset**: marcado como `license: other`. El card aclara que los copyrights varían: muchas son public domain por antigüedad, otras tienen copyright vigente. Recomienda atribución a fotógrafo + PastVu. **Uso comercial: requiere permiso del copyright holder de cada imagen específica.**
- **Código del proyecto PastVu**: AGPL-3.0+.

**Implicancias para GeoDetective Envs**:
- Para uso de investigación interna y entrenamiento: ✅ OK con CC-BY 4.0 (atribución).
- Para distribución pública del environment / dataset derivado: ⚠️ revisar caso por caso. Muy probable que necesitemos guardar metadata de atribución por sample y propagarla.
- Para uso comercial directo (ej. una API paga): ❌ no sin caso por caso.

---

## API de PastVu

Base: `https://api.pastvu.com/api2` (o el deprecado `https://pastvu.com/api2`). **No requiere autenticación**. **Rate limits no documentados** — hay que probar empíricamente y cachear agresivamente. Recomendación: ≤2 req/s para no abusar (es un sitio comunitario sin sponsor masivo).

Endpoints documentados:

| Método | Qué hace | Params clave |
|---|---|---|
| `photo.giveForPage` | Obtener una foto por ID | `cid` |
| `photo.giveNearestPhotos` | K-NN de fotos cercanas a (lat, lon) | `geo`, `distance` (≤1M m), `year`, `year2`, `type` (photo/painting), `limit` (≤30) |
| `photo.getByBounds` | Fotos dentro de un bounding box / GeoJSON | `geometry`, `z` (zoom), `isPainting`, `year/year2` |
| `comment.giveForObj` | Hilo de comentarios de una foto | `cid` |

Los endpoints de stats globales que probé (`index.giveStat`) **no existen** (404 con `NO_SUCH_RESOURCE`). No hay un endpoint público para "dame el total".

URLs de imagen:
- Mostrada con watermark: `https://img.pastvu.com/d/{file}`
- Original: `https://img.pastvu.com/a/{file}`
- Thumbnail: `https://img.pastvu.com/h/{file}`

**Para nosotros**: el HF snapshot es la fuente principal. La API sirve para (a) refrescar samples, (b) traer `desc`/`comments` que pueden faltar en el dump, (c) verificar contaminación (¿la imagen sigue online en pastvu.com hoy?).

---

## Riesgos para nuestro proyecto

### 1. Contaminación por reverse image search 🔴 Alto

**Toda imagen en PastVu está pública en `pastvu.com/p/{cid}` con coordenadas adyacentes en el HTML.** Esto significa:

- **Yandex Images** (motor ruso, indexa pastvu.com agresivamente): probablemente >70% de hits para fotos pre-2020.
- **Google Lens / Images**: indexación parcial, depende de si el sitio en cuestión está crawleado. Estimo 30-50% match exacto.
- **TinEye**: hits exactos para imágenes idénticas (mismo hash perceptual). Estimo 40-60%.
- **Descripción VLM googleable**: el agente describe "iglesia ortodoxa con cúpulas verdes en plaza con tranvías" → google → si el sitio está indexado, primer hit es PastVu con coords. Estimo 20-40% para fotos con contenido distintivo.
- **VLM grande sin tools (e.g. GPT-5/Claude)**: para fotos famosas (ej. Plaza Roja 1950), reconocimiento directo. Estimo 5-15%.

**Estimación combinada**: si hacemos el filtrado adversarial agresivo (los 3 tests + VLM), **probablemente sobrevivan 20-40%** del corpus original (~400k - 800k de los 2M). Es un orden de magnitud razonable, pero requiere infra de filtrado seria (Yandex API, Google Lens automation, TinEye API, VLM batch).

**Mitigación adicional**:
- Cropping aleatorio + flip horizontal + recompresión JPEG distinta puede romper hashes perceptuales débiles (TinEye), pero **no rompe a Yandex/Google Lens** que tienen modelos de embeddings robustos.
- Quitar watermarks de PastVu si están impresos en las imágenes (cuidado con artefactos).

### 2. Sesgo geográfico a Rusia 🔴 Alto

Si entrenamos solo con PastVu, el agente será excelente en Moscú/SPb y mediocre en todo lo demás. Para un environment "global" de geolocalización, esto es un problema serio.

**Opciones**:
- **(A) Solo Rusia/ex-URSS**: aceptamos el sesgo y vendemos el agente como "Eastern European time machine". Honesto, focused. Reduce el corpus a ~70-80% del original (~1.5M imágenes), todas con contexto cultural coherente.
- **(B) Balancear con datasets externos**: Smapshot (Suiza, ~30k aerial — limitado), Library of Congress (USA, ~100k+ georef), OldNYC (50k, NYC), OldSF (13k, SF), Historypin (mixed quality, global, ~500k+), Europeana (millones, Europa). **Recomendado**.
- **(C) Subsamplear PastVu para balancear**: tomar máximo N samples por país. Reduce volumen pero da equilibrio. Combinable con (B).

### 3. Pinturas, grabados, dibujos contaminando "fotos"

Resuelto fácil con `type` filter una vez decodifiquemos el mapeo. **Costo**: probablemente perdemos 5-15% del corpus.

### 4. Duplicados con otros datasets

PastVu tiene política de "fotos no publicadas en otros sitios" en sus rules pero la realidad es que muchas son re-uploads de archivos como Library of Congress, Bundesarchiv, Pastvu local archives, etc. **No conozco análisis publicado** de overlap PastVu × LoC × Smapshot. Hay que dedupear con perceptual hashes (pHash, dHash) cross-dataset antes de armar el split de eval.

### 5. Calidad inconsistente

Mínimo 700 px → muchas imágenes son apenas pasables. Filtrar por `min(w, h) >= 1024` reduce el corpus pero levanta calidad. Para entrenar VLM, ~512 px es lo mínimo viable; 1024 es seguro.

### 6. Fingerprint de PastVu en imágenes

Watermark visible (`watersignText`) en imágenes renderizadas. Si está impreso, el modelo aprende "si veo 'pastvu' en la esquina, sé que es PastVu y puedo memorizar". **Hay que verificar si el HF dump usa la imagen original (`/a/{file}`) o la marcada (`/d/{file}`)**. El card dice "best available resolution from original source" → probablemente original sin watermark, pero hay que confirmar visualmente.

---

## Plan de integración tentativo

Pipeline propuesto, en orden:

### Fase 1 — Solo metadatos (días)

1. Descargar **solo** `pastvu.jsonl.zst` (296 MB). Es barato y permite todo el filtrado upstream.
2. Parsear con `zstandard` + `json.loads` línea a línea. Volcar a Parquet/DuckDB para queries rápidas.
3. **Análisis exploratorio** (notebook):
   - Histograma temporal por año / década.
   - Histograma por `type` (foto/pintura/dibujo) — decodificar enteros.
   - Distribución por país (`regions[0]` o equivalente).
   - Cobertura `geo` not null.
   - Cobertura `year` not null.
   - Cobertura `dir` not null (importante: si tenemos azimut, podemos hacer tasks más interesantes).
   - Distribución de resolución (`w`, `h`).
   - Watermark presence.
4. **Decodificar `type`**: agrupar por valores únicos, samplear 5-10 cid por valor, llamar `photo.giveForPage` y observar visualmente.
5. **Decodificar `r2d`**: idem. Hipótesis: rotación 2D (azimut + tilt).

### Fase 2 — Filtrado pre-descarga (días)

Aplicar filtros sobre el JSONL antes de tocar shards:

```
keep_mask =
    (year >= 1839)              # post-invención fotografía
    AND (year <= 2000)
    AND (type == FOTO_INT)      # solo fotos reales
    AND (geo is not null)
    AND (min(w, h) >= 1024)     # calidad mínima
    AND (status == APPROVED)    # filtrar por `s` si hay flag de no-aprobado
```

Esto probablemente reduce 2M → 1.0-1.4M.

Subsamplear por país si vamos por la opción (C) de balanceo.

### Fase 3 — Filtrado adversarial de contaminación (semanas)

Solo sobre imágenes que pasen Fase 2. Pipeline de 4 tests:

1. **TinEye API** (exact + near-duplicate). Threshold: any match con dominio pastvu.com → reject.
2. **Yandex Images** (vía Yandex Search API o scraping headless). Threshold: pastvu.com en top-20 → reject.
3. **Google Lens** (vía SerpAPI o scraping). Threshold: pastvu.com en top-20 → reject.
4. **VLM probe**: pasar la imagen por GPT-5/Claude/Gemini-3 sin tools, preguntar "¿en qué ciudad fue tomada?". Si responde correctamente → reject (es trivial para modelos sin tools, no aporta señal de tools).

Cost estimate (rough): si filtramos 1M imágenes y cada test cuesta ~$0.005 entre todos, son **~$5k**. Si pasamos a un setup donde corremos los reverse searches solo sobre samples preliminares para calibrar, mucho menos.

Sobreviven: **~200k - 500k**. Este es nuestro **training set "limpio"**.

### Fase 4 — Descarga selectiva de imágenes

Solo descargar los shards que contienen `cid`s sobrevivientes. Como WebDataset agrupa por shard secuencial, esto puede ser ineficiente (1 cid por shard => bajamos todo el shard). **Alternativa**: descargar solo los `cid`s vía la URL pública (`https://img.pastvu.com/a/{file}`) con concurrencia moderada (≤4 req/s) y respeto. Estimación: 500k imágenes × 200 KB promedio = **100 GB**, doable.

### Fase 5 — Eval set

PastVu **no es** nuestro held-out. Nuestro eval debe ser:
- **Postales escaneadas** (set externo, ej. eBay scrapes con metadata, o colecciones de la Library of Congress > Postcard Collection).
- **Fotos de archivo de instituciones específicas** (Library of Congress Prints & Photographs, Bundesarchiv, Bibliothèque nationale de France) que no estén en PastVu.

PastVu va al training set. Punto.

---

## Datasets complementarios necesarios

Si vamos por balanceo geográfico (recomendado), hace falta combinar:

| Dataset | Cobertura | Volumen | Calidad geo | Notas |
|---|---|---|---|---|
| **PastVu** | Rusia + ex-URSS | ~2M (~500k post-filtros) | Buena (shooting point + dir) | Source primaria. Sesgada. |
| **Library of Congress P&P** | USA | ~100k+ georef en PPOC | Variable | API estable. Public domain. Imprescindible. |
| **OldNYC** (Vanderkam) | NYC | ~50k | Buena (calle) | NYPL Milstein Collection. Público. |
| **OldSF** (Vanderkam) | SF | ~13k | Buena | SF Public Library. Público. |
| **Smapshot** (EPFL/HEIG-VD) | Suiza + 6DoF | ~10k-50k | Excelente (6DoF georef) | Pequeño pero ultra-preciso. Bueno para *eval*. |
| **Historypin** | Global | ~500k+ | Variable | Calidad inconsistente, dedup obligatorio. |
| **Europeana** | Europa | Millones | Variable | Burocracia institucional. Vale la pena escarbar. |
| **Bundesarchiv** | Alemania | 1M+ | Variable | API/dump existe. CC BY-SA 3.0 DE. |
| **Wikimedia Commons** (cat: Historical_photographs) | Global | Millones | Variable | Sufre contaminación VLM masiva. Solo subsets. |

**Mix tentativo de training**:
- 40% PastVu (Rusia / ex-URSS / Europa Este)
- 20% LoC + OldNYC + OldSF (Norteamérica)
- 15% Bundesarchiv + Europeana (Europa Occidental)
- 15% Historypin / Wikimedia subsets (resto del mundo, después de dedup)
- 10% un dataset externo de Latinoamérica + Asia + África si encontramos uno (gap conocido — investigar)

**Eval**: Smapshot (preciso, contaminación baja por nicho académico) + scraped postcards + curated holdout de LoC.

---

## Decisión: apalancar / mirar / descartar

**Veredicto: APALANCAR — pero con asterisco grande.**

**Por qué apalancar**:
- 2M imágenes con (lat, lon) + año + dirección de toma + descripción es **excepcional**. No hay otro dataset histórico de este tamaño con esta calidad de metadata.
- Open dataset, license workable (CC-BY 4.0 + atribución por imagen), formato standard (WebDataset).
- Comunidad y moderación activa → calidad de geolocalización decente baseline.
- Field `dir` (azimut) habilita tasks ricas más allá de solo (lat, lon): predicción de orientación, alineación con StreetView, etc.

**El asterisco**:
- **No usar como held-out / eval**. Riesgo de contaminación demasiado alto (Yandex indexa pastvu.com nativamente).
- **Hace falta filtrado adversarial agresivo** (los 4 tests). Probablemente sobreviven 20-40% para training.
- **Hay que balancear geográficamente** con LoC, OldNYC, Bundesarchiv, etc. Solo PastVu ⇒ agente sesgado a Rusia.
- **Hay que decodificar `type` y `r2d`** antes de cualquier otra cosa. El card de HF está incompleto.
- **Verificar discrepancia 1.8TB vs 14.7GB visible en HF tree** antes de planear storage.
- **Confirmar que las imágenes del HF dump no tienen watermark de PastVu** (fingerprint que enseñaría atajos al modelo).

**Próximos pasos sugeridos** (en orden de impacto):

1. Descargar `pastvu.jsonl.zst` (296 MB). Notebook de exploración. **1-2 días**.
2. Decodificar `type`, `r2d`, distribución temporal / geográfica real. **1 día**.
3. Verificar shards completos en HF (¿son 47 o 2094?). **1 hora**.
4. Bajar 5-10 shards muestrales para inspeccionar imágenes (watermarks, calidad, tipos). **1 día**.
5. Diseñar pipeline de filtrado adversarial — empezando por TinEye sobre 1k samples para calibrar. **1 semana**.
6. Decisión informada: ¿solo Rusia o multi-source? **1 semana de discusión + 2 semanas de integración**.

---

## Apéndice: preguntas abiertas que requieren empirismo

1. ¿`type` mapea a {1: foto, 2: pintura, 3: dibujo, 4: grabado}? Lo más simple, pero hay que verificar.
2. ¿`r2d` es `[direction_deg, tilt_deg]` o algo más?
3. ¿Las imágenes en el HF dump tienen watermark visible?
4. ¿Cuántas imágenes con `geo` válida realmente?
5. ¿Distribución temporal real?
6. ¿Cuál es la verdadera tasa de contaminación con Yandex / Google Lens?
7. ¿Cuál es el overlap real con LoC / Bundesarchiv / Europeana? (perceptual hashing cross-dataset).
8. ¿Hay rate limits soft en api.pastvu.com? (probar empíricamente con backoff).
9. ¿El field `s` (status) realmente filtra fotos no-aprobadas o el dump ya solo trae aprobadas?
10. ¿Están todas las imágenes pre-1839? Las que existan, ¿son grabados o pinturas? (trivial verificar con `year < 1839` en el JSONL).

---

## Fuentes consultadas

- [HuggingFace dataset card — nyuuzyou/pastvu](https://huggingface.co/datasets/nyuuzyou/pastvu)
- [HuggingFace dataset README.md](https://huggingface.co/datasets/nyuuzyou/pastvu/blob/main/README.md)
- [HuggingFace dataset file tree](https://huggingface.co/datasets/nyuuzyou/pastvu/tree/main)
- [Academic Torrents — PastVu 2025-07-23](https://academictorrents.com/details/8cf94961303049e94ed82374221602aba17f6926)
- [PastVu API docs](https://docs.pastvu.com/en/dev/api)
- [PastVu about / introduction](https://docs.pastvu.com/en/about)
- [PastVu rules](https://docs.pastvu.com/en/rules)
- [PastVu GitHub repo](https://github.com/PastVu/pastvu)
- [Smapshot platform](https://smapshot.heig-vd.ch/)
- [OldNYC / OldSF](https://www.oldnyc.org/)
- [Library of Congress P&P Online Catalog](https://www.loc.gov/pictures/)
- [IM2GPS benchmark + MP-16 / YFCC100M context](http://graphics.cs.cmu.edu/projects/im2gps/)
