# Viability Assessment — ¿se puede técnicamente construir el environment?

> **NOTA POSTERIOR (2026-05-07)**: este doc se escribió con framing "env de training". El proyecto pivotó a **benchmark primario, env como deuda futura** (ver disclaimer en `PROJECT.md`). Para el framing benchmark, varios bloqueadores se relajan significativamente:
> - **Bloqueador 1 (3D)** — el ToS issue sobre "machine interpretation" sigue siendo zona gris, pero en escala benchmark con uso live es defendible.
> - **Bloqueador 2 (reverse image search)** — sigue siendo el más serio. Filtrado tiered best-effort. Pero a escala 1K-10K fotos del corpus benchmark, los costos bajan ~100x ($100-$200 USD vs $10K-$20K).
> - **Bloqueador 4 (cost projection)** — para benchmark, costos pasan de $30K-$80K a probablemente <$500 USD por suite completa de evaluación.
> - **Bloqueador 5 (ToS Google vs RL training)** — irrelevante para benchmark de inference live.
>
> Bloqueadores 6-9 siguen aplicando. El documento mantiene el análisis completo porque (a) el framing env es deuda futura y vamos a volver a estos números, (b) los hallazgos legales y de costo son independientes del framing.
>
> ---
>
> **Frame original (env de training)**: este proyecto provee environment + tools + reward + corpus filtrado. NO entrena policies. La pregunta de este doc es: ¿se pueden exponer todas las piezas que necesitamos como tools tipadas consumibles por LLMs con vision, a costo y complejidad razonable, sin violar ToS?
>
> Fuente principal: crítica de Codex (2026-05-07) sobre 4 bloqueadores identificados + bloqueadores adicionales que él flaggeó. URLs y números reflejan estado conocido a la fecha.

---

## TL;DR — Veredicto general

**El proyecto es viable, pero con un re-framing crítico**: **Google Maps NO puede ser el backbone primario** del env si queremos que sea usable para entrenamiento RL. Los TOS de Google prohíben explícitamente usar Maps Content para entrenar/validar/fine-tunear modelos ML. Implicación: **el stack primario es open (OSM, OpenHistoricalMap, Mapillary, open DEM, archives); Google Maps queda como tool opcional con user-supplied key y flag explícito "non-training mode"**.

**Mapa de bloqueadores**:

| # | Bloqueador | Veredicto | Implicación |
|---|---|---|---|
| 1 | Vista 3D / relieve | 🔥 ToS Google bloquea ML interpretation. Técnico es resoluble | v0 con `terrain` 2D + open DEM. 3D tiles solo si legal aprueba. |
| 2 | Reverse image search adversarial | 🔥 No hay solución web-scale a costo razonable | NO prometer "resiste Lens/Yandex". Filtrado **tiered best-effort**. |
| 3 | Cobertura Street View histórica/rural | ⚠️ Resoluble con curado | Agregar `streetview_available` como feature del corpus; agente pivota a OSM/archivos cuando no hay cobertura. |
| 4 | Cost projection a escala training | 🔥 Costo manejable, **ToS/training es el killer** | Google = opcional con user key. Stack primary open. |
| 5 (nuevo) | TOS Google vs RL training | 🔥 Explícito en TOS | Legal memo antes de comprometerse. |
| 6 (nuevo) | Cache pipeline no trivial | ⚠️ | Diseño explícito antes. |
| 7 (nuevo) | Licencias del corpus | ⚠️ | Auditoría por imagen / fuente. |
| 8 (nuevo) | OCR histórico multilingüe | ⚠️ | Tool dedicada (Cirílico, gótico, baja resolución). |
| 9 (nuevo) | Histórico real necesita OHM temprano | ⚠️ | Integrar OpenHistoricalMap + georef desde v1, no v1.5. |

---

## Bloqueador 1 — Vista 3D / relieve de montañas

### Lo que confirmamos
- **Google Photorealistic 3D Tiles** existe, está documentada como parte del Map Tiles API. OGC 3D Tiles format.
- **Pricing oficial**: 1k tiles gratis/mes, después $6/1k tiles hasta 100k, escalonado por volumen.
- **Quota**: 12k QPM + 10k root requests/día.
- Camino técnico limpio: **CesiumJS + headless Chromium/Playwright** para renderizar a JPEG. MVP 1-2 semanas. Servicio robusto con cache, queues, timeouts, cámaras reproducibles: 4-6 semanas.
- Three.js / deck.gl son alternativas pero más integración custom.

### El problema crítico
**Map Tiles Policy prohíbe usos no visuales tipo image analysis / machine interpretation.** O sea: renderizar tiles 3D y mandárselas a un VLM para que las "analice" choca con la policy.

Fuentes:
- [Google pricing](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Map Tiles docs](https://developers.google.com/maps/documentation/tile/3d-tiles-overview)
- [Map Tiles policies](https://developers.google.com/maps/documentation/tile/policies)

### Veredicto: 🔥 técnicamente resoluble, ToS puede matar uso con Google.

### Recomendación
- **v0**: `maptype=terrain` (2D, curvas de nivel) + Google Elevation API o open DEM (SRTM, MERIT, USGS). No es "ver el relieve inmersivo" pero sirve para "esta zona es montañosa, esa es plana".
- **3D tiles**: spike SOLO si legal/ToS review aprueba. Si no, ignorar y usar alternativas open (Mapbox 3D Terrain con DEM open).

---

## Bloqueador 2 — Reverse image search para filtrado adversarial

### Lo que confirmamos
- **TinEye web global API**: pricing actualizado 2026 no confirmable, pero el pricing histórico documentado da **1M búsquedas ≈ $10k USD**.
- **TinEye MatchEngine** ($500/mes plan Basic, 30k searches, overage $0.005/search): es para **TU PROPIA colección**, no índice web global. NO sirve para "¿está esta imagen en internet?".
- **Bing Visual Search está MUERTO**: Bing Search APIs retiradas el **11 agosto 2025**. Reemplazo "Grounding with Bing" no da reverse image y cuesta $14/1k transactions.
- **Google Lens / Yandex**: NO hay API oficial. Wrappers no oficiales son frágiles + contra ToS.
- **CLIP local "casi todo Google"**: NO realista. DataComp-1B son 1.39B rows / 8.86TB metadata. DataCompDR embeddings: 134TB. 1B embeddings 768-d fp16 ≈ 1.5TB **antes** de FAISS/index. Y NO cubre Lens / Yandex / imágenes caídas.

Fuentes:
- [TinEye blog pricing](https://blog.tineye.com/new-image-search-pricing/)
- [MatchEngine signup](https://services.tineye.com/signup/matchengine_basic)
- [Microsoft Bing Search retirement](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)
- [Grounding with Bing pricing](https://www.microsoft.com/en-us/bing/apis/grounding-pricing)
- [DataComp-1B HF](https://huggingface.co/datasets/mlfoundations/datacomp_1b)
- [DataCompDR-1B HF](https://huggingface.co/datasets/apple/DataCompDR-1B)

### Veredicto: 🔥 filtrado adversarial web-scale serio es el mayor bloqueador técnico/costo del proyecto.

### Recomendación: filtrado **tiered best-effort**, NO promesa de "resiste Lens/Yandex"

Reformular invariante 1 de PROJECT.md: el corpus es filtrado con **best effort tiered**, no resistencia absoluta a búsqueda web. Capas (en orden de costo creciente):

| Tier | Filtro | Costo aprox 1M imgs | Cubre |
|---|---|---|---|
| 1 | **VLM-no-tools test** (GPT-4o, Claude, Gemini sin herramientas) | $5-15K en API | Memorización del pretraining |
| 2 | **CLIP local + index de fuentes conocidas** (PastVu, Wikimedia, LoC, Smapshot) | ~$1-2K cómputo | Duplicados directos contra fuentes públicas conocidas |
| 3 | **Búsquedas textuales** (descripción VLM → Tavily/Brave) | ~$0.5-2K | Indexación textual |
| 4 | **TinEye sampleado** (subset de 50k-100k del corpus, no completo) | $500-$1k | Spot check, no completo |
| ❌ | "Garantía Google Lens / Yandex" | imposible / no escalable | — |

**Total filtrado realista**: $10-20K USD para curar 1M imágenes con confidence "razonable", NO "garantizada".

Esto es deuda explícita: el invariante actual ("antes de aceptar una foto al dataset, debe resistir tres tests") es operacional pero **NO garantizado al 100%**. Hay que ser honesto en la doc.

---

## Bloqueador 3 — Street View cobertura

### Lo que confirmamos
- **No hay análisis público granular** confiable por urbano/rural/país/década. Para corpus hay que medirlo nosotros.
- **Street View Image Metadata endpoint** NO se cobra (según pricing). Ahí podemos hacer hit rate audit barato.
- **Mapillary**: 2.4B+ imágenes, API disponible. Cobertura buena pero desigual.
- **KartaView**: ~384M imágenes (dato viejo), servicio con señales de fragilidad.
- **Rusia/ex-URSS** (problema de PastVu): cobertura existe pero **probablemente irregular y políticamente frágil**. NO asumir.

Fuentes:
- [Google Street View SKU](https://developers.google.com/maps/billing-and-pricing/sku-details?hl=en)
- [Mapillary intro](https://help.mapillary.com/hc/en-us/articles/115001770269-An-Introduction-to-Mapillary)
- [KartaView OSM wiki](https://wiki.openstreetmap.org/wiki/KartaView)

### Veredicto: ⚠️ resoluble con curado fuerte.

### Recomendación
- **Spike obligatorio**: muestrear 10k coordenadas de PastVu, hacer hit rate audit con Street View metadata API por país/década/urbano-vs-rural. Esto da el techo real del corpus utilizable con SV.
- Agregar `streetview_available` como feature del corpus.
- Agente: si SV no tiene cobertura, **debe pivotear** a OSM Overpass + OpenHistoricalMap + archives + web search, NO fallar.
- Mapillary como complemento de primera, KartaView solo si la cobertura específica de Mapillary es insuficiente.

---

## Bloqueador 4 — Cost projection a escala training

### Lo que confirmamos
- **Static Street View** pricing oficial:
  - 10k gratis/mes
  - $7/1k hasta 100k
  - $5.60 / $4.20 / $2.10 / **$0.53 >5M** (escalado por volumen)
- **Places Search Pro**: $32/1k inicial.
- **1M episodios × 10-20 calls × 70% cache hit = 3M-6M paid calls**.
  - Si todo es Street View: ~$9k-$14k USD.
  - Si 20-30% son Places Search: $30k-$80k USD fácil.
- **Scrapeear Google Maps a escala**: NO. TOS prohíbe scraping, bulk download, caching long-term, **y específicamente prohíbe usar Maps Content para entrenar/testear/validar/fine-tunear ML.**

Fuentes:
- [Google Maps pricing](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Google Maps Platform Terms](https://cloud.google.com/maps-platform/terms?hl=en%3D)

### Veredicto: 🔥 costo es manejable; ToS/caching/training es el killer.

### Recomendación
**Re-arquitectura de la oferta de tools**:
- **Stack primario open**: OSM (Overpass), OpenHistoricalMap (CC0), Mapillary, open DEM (SRTM/MERIT), archives (LoC, OldNYC, etc.).
- **Google Maps tools = OPCIONAL**, con:
  - **User-supplied API key** obligatoria (downstream user paga, no nosotros).
  - **Flag explícito de modo**: "non-training mode" (default) vs "training mode" (avisa que viola TOS, bloquea ejecución por defecto).
  - Documentación clara del riesgo legal.

Esto es alineado con invariante 7 actual de PROJECT.md ("Compliance con TOS") pero requiere apretar la redacción.

---

## Bloqueador 5 (nuevo) — TOS Google vs RL training

**Codex flaggeó esto explícitamente**: el TOS de Google Maps Platform prohíbe usar Maps Content para "entrenar, testear, validar, o fine-tunear modelos ML". Combinado con Map Tiles Policy contra "machine interpretation" del bloqueador 1, **Google Maps es legalmente cuestionable como backbone** de un env de RL.

### Veredicto: 🔥 explícito en TOS.

### Recomendación
- **Antes de comprometerse**: legal memo formal por nuestra parte (review de TOS específico para nuestro caso de uso).
- **Mientras tanto**: arquitectura asume Google = opcional / non-training default (ver bloqueador 4).
- **Issue urgente**: "Auditoría legal/TOS por fuente y tool" — debería ser una de las primeras issues técnicas en Project v2.

---

## Bloqueador 6 (nuevo) — Cache pipeline no trivial

Cache no es "redis con TTL". Hay que diseñar:
- **TTL apropiado por tipo de tool** (geocoding casi inmutable; Places puede cambiar; Street View cambia con el tiempo).
- **Dedupe** de queries (mismo lat/lon con precision distinta = misma query?).
- **Audit** de hits/misses para tracking de cost.
- **Compliance con TOS** (Google permite cache muy limitado — ver bloqueador 4).
- **Costo del cache mismo** (storage + invalidation logic).

### Veredicto: ⚠️ resoluble pero requiere diseño explícito ANTES de scale.

### Recomendación
Diseñar la cache layer como contrato explícito (interfaz + storage + audit) en una issue de architecture, antes de armar las primeras tools.

---

## Bloqueador 7 (nuevo) — Licencias del corpus

PastVu, Smapshot, OldNYC, Library of Congress, Historypin, etc. — **cada uno tiene términos distintos por instancia y por uso**:
- CC-BY / CC-BY-SA (la mayoría) requieren atribución y a veces share-alike.
- Algunas (Historypin, ciertas LoC) tienen rights reserved per-image.
- Redistribución de thumbnails / derivados puede ser distinto que del original.
- Si entrenamos un modelo y se monetiza, zona gris.

### Veredicto: ⚠️ tractable pero deuda real.

### Recomendación
- **Auditoría legal/license** por fuente, antes de scale.
- **El env publicado NO incluye las imágenes**: las fetchea en runtime con keys/credenciales del usuario downstream. Esto reduce nuestro riesgo de redistribución.
- Documentar claramente qué fuentes son seguras para qué tipo de uso.

---

## Bloqueador 8 (nuevo) — OCR histórico multilingüe

Carteles en fotos antiguas son una pista clave (idioma, alfabeto, palabras). Pero:
- **Cirílico** (PastVu): Tesseract lo maneja, pero baja resolución / variantes ortográficas pre-revolucionarias rusas son duras.
- **Gótico fraktur** (fotos alemanas pre-WWII): específico, requiere modelo dedicado.
- **Baja resolución** general: Tesseract degrada mucho.
- **Google Vision API** OCR: maneja todo lo anterior pero **mismo problema de TOS con Maps**.

### Veredicto: ⚠️ tractable, requiere tool dedicada con fallbacks.

### Recomendación
- Tool `ocr(image, region)` con stack tiered: Tesseract local primero (free), open-source modelos (TrOCR, etc.) como fallback, API comercial como último recurso opcional.
- NO depender de Google Vision API (mismo problema de TOS).

---

## Bloqueador 9 (nuevo) — Histórico real necesita OHM temprano

OSM moderno **no basta** para fotos antiguas: edificios cambiaron, calles se renombraron, países dejaron de existir. La integración con **OpenHistoricalMap (Overpass temporal, CC0)** y mapas históricos georreferenciados (MapWarper, NYPL Map Warper) tiene que ocurrir **temprano**, idealmente en v1, no en v1.5 como se planeaba.

### Veredicto: ⚠️ shift de prioridad.

### Recomendación
- **OpenHistoricalMap como tool de v1**, no v1.5.
- **Spike de OHM cobertura** prioritario (ya en lista de spikes).
- MapWarper / NYPL como tools posteriores pero diseñadas en el roadmap desde el principio.

---

## Implicaciones arquitectónicas (cambios al plan)

Lo siguiente debería reflejarse en `PROJECT.md` y sucesivamente en arquitectura, después de discusión:

### 1. Stack primario open, Google opcional
- Tools de v1 basadas en OSM, OHM, Mapillary, open DEM, archives.
- Google Maps tools (Static Maps, Street View, Places, Geocoding) **opcionales** con user-key + flag non-training default.
- Implicación para invariante 6 ("environment es reusable y open source"): el env DEFAULT debe correr completo sin necesitar Google API keys.

### 2. Anti-shortcut filtering = best-effort tiered, no garantizado
- Reformular invariante 1 para reconocer que filtrado adversarial es tiered (VLM-no-tools + CLIP local + text search + TinEye sampling), NO "resiste Lens/Yandex al 100%".
- Documentar qué confidence level damos.

### 3. Cobertura Street View como feature de corpus
- `streetview_available` como metadata de cada foto del corpus.
- Agente debe poder pivotar a OSM/archives cuando no hay SV.

### 4. Cache layer como contrato architectónico de primer ciclo
- No agregar después; diseñar antes de implementar tools.

### 5. OpenHistoricalMap a v1, no v1.5
- Roadmap conceptual de PROJECT.md ajusta.

---

## Spikes técnicos previos a v1 (revisados)

Reordenado por dependencia, post-bloqueadores:

### Decisiones legales/arquitectónicas (críticas, antes de codear)

1. **Legal/TOS audit** por fuente y tool (Google Maps, PastVu, archives, Mapillary, OHM).
2. **Decisión: contrato del environment** (OpenEnv vs Gymnasium-style vs API propia).
3. **Threat model anti-shortcut formal** y diseño tiered de filtrado.
4. **Diseño cache layer** (interfaz + storage + audit + compliance).

### Validaciones empíricas

5. **Spike PastVu** — descargar `pastvu.jsonl.zst` (296 MB), notebook explorando volumen real, distribución temporal/geográfica.
6. **Spike Street View coverage** — muestrear 10k coords de PastVu, hit rate audit por país/década.
7. **Spike OpenHistoricalMap** — verificar cobertura para regiones target.
8. **Resolver contradicción Smapshot** — 10-50K vs 200K, license real.
9. **Spike Library of Congress API** — verificar acceso programático (Codex marcó 403).

### Diseños de tools

10. **v0 tool schemas** — Pydantic v2 para 5-7 tools open: OSM Overpass, OHM Overpass temporal, Mapillary, web search filtrada, Elevation open DEM, OCR tiered, archive_search.

### Investigación pendiente

11. IIIF / navPlace / georef.
12. MapWarper, NYPL Map Warper, OldInsuranceMaps/Sanborn.
13. USGS / NOAA / IGN historical aerials.

---

## Cosas que NO son problema de viabilidad (resueltas)

- LLM con vision (Claude, GPT-4o, Gemini) consumiendo imágenes via tools.
- Loop ReAct con tool calls (LangGraph, smolagents).
- Wrapping de APIs como tools tipadas con Pydantic + httpx.
- Web search general (Tavily, Brave, Serper).
- Web fetch + content extraction (Jina Reader, Firecrawl).
- Image manipulation y hashing (PIL, imagehash).
- EXIF extraction.

---

## Fuentes externas verificadas durante la evaluación

- [Google Maps pricing](https://developers.google.com/maps/billing-and-pricing/pricing)
- [Google Map Tiles 3D overview](https://developers.google.com/maps/documentation/tile/3d-tiles-overview)
- [Google Map Tiles policies](https://developers.google.com/maps/documentation/tile/policies)
- [Google Street View SKU details](https://developers.google.com/maps/billing-and-pricing/sku-details?hl=en)
- [Google Maps Platform Terms](https://cloud.google.com/maps-platform/terms?hl=en%3D)
- [TinEye blog pricing](https://blog.tineye.com/new-image-search-pricing/)
- [TinEye MatchEngine signup](https://services.tineye.com/signup/matchengine_basic)
- [Bing Search API retirement](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)
- [Grounding with Bing pricing](https://www.microsoft.com/en-us/bing/apis/grounding-pricing)
- [DataComp-1B HF](https://huggingface.co/datasets/mlfoundations/datacomp_1b)
- [DataCompDR-1B HF](https://huggingface.co/datasets/apple/DataCompDR-1B)
- [Mapillary intro](https://help.mapillary.com/hc/en-us/articles/115001770269-An-Introduction-to-Mapillary)
- [KartaView OSM wiki](https://wiki.openstreetmap.org/wiki/KartaView)
