# E003 — ReAct con stack completo de tools (12 tools)

> Experimento iterativo de validación end-to-end del concepto del benchmark con stack expandido.
> Fecha: 2026-05-07.

## Objetivo

Validar el comportamiento del agente con stack expandido de 12 tools (vs solo `web_search` en E002).
Caracterizar:
- ¿Las tools nuevas mejoran resultados?
- ¿El agente las usa estratégicamente o ignora unas?
- ¿Cómo varía el comportamiento entre runs?

## Stack de tools (12 total)

### Investigación textual
1. `web_search(query)` — Tavily backend con `search_depth="advanced"`. Filtros anti-shortcut.
2. `fetch_url(url)` — entrar a página específica y leer texto completo.

### Investigación visual
3. `fetch_url_with_images(url)` — entrar y ver imágenes embebidas (con hash perceptual flagging).
4. `image_search(query)` — Google-Images-style con Tavily images + hash perceptual flagging.
5. `crop_image(x, y, w, h)` — zoom en región específica de la foto target.
6. `crop_image_relative(region)` — zoom en región nombrada (top_right, center, etc.).

### Geo
7. `geocode(query)` — Nominatim OSM (free, sin API key).
8. `reverse_geocode(lat, lon)` — Nominatim.
9. `historical_query(bbox, year, preset)` — OpenHistoricalMap Overpass (free, dimensión temporal).
10. `static_map(lat, lon, zoom, type)` — Google Maps Static API. type=terrain muestra relieve 2D.
11. `street_view(lat, lon, heading, pitch)` — Google Street View Static API.

### Final
12. `submit_answer(...)` — terminal.

## Setup

- **Modelo**: gpt-5.4 vía Azure Foundry.
- **Max steps**: 12. Tools como OpenAI function calling format.
- **Hash perceptual** sobre la foto target con `imagehash.phash`. Imágenes con hamming<8 = `is_likely_target=true`.
- **Anti-shortcut por filtro de dominio**: pastvu.com, smapshot.ch, etoretro.ru, humus.livejournal.com, oldnyc.org, oldsf.org, historypin.org, commons.wikimedia.org, upload.wikimedia.org, flickr.com, vk.com, lens.google.com, yandex.com, tineye.com, imgur.com, postimg.cc.

## Datos disponibles

### Batch parcial (cancelado por costo Tavily) — 9 runs sobre 3 fotos

| CID | Foto | YR | Run 1 | Run 2 | Run 3 | E001 (sin tools) | Verdict |
|---|---|---|---|---|---|---|---|
| 1748874 | SP barrio anónimo | 1996 | 8.5 km | **2.3 km** | 7.3 km | 2573 km | ✅ tools cierran 300x |
| 1101385 | Volga deep rural | 1987 | 2617 km | 2835 km | 14224 km | 11994 km | ≈ similar (universo enorme) |
| 1459395 | iglesia rural Volga | 1956 | 209 km | 209 km | 559 km | 103 km | ⚠️ tools EMPEORAN |

### Test 1 run con stack completo (12 tools)

| CID | Run | Steps | Web | Crop | IS | Geo | SM | SV | Hist | Dist (km) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1748874 | 1 | 8 | 11 | 3 | 1 | 2 | **0** | **0** | **0** | **1493** | Identificó "Strahov Praga" sin verificar visualmente |

## Hallazgos

### 1. Las tools NO siempre ayudan — y eso ES una métrica del benchmark

Patrón claro de los 3 perfiles testados:

- **Foto urbana sin landmark con pistas concretas (#1748874)**: tools cierran muchísimo (300x mejora). Sweet spot ideal.
- **Foto rural genérica (#1101385)**: el universo de candidatos es enorme. Tools no ayudan a discriminar — el agente vuela hemisferios.
- **Foto rural identificable parcialmente (#1459395 iglesia)**: tools EMPEORAN. El agente se "compromete" a hipótesis específicas equivocadas (monasterios famosos a 200-559 km del lugar real).

### 2. El agente NO siempre usa las tools óptimamente

En el test all-tools del SP barrio:
- Usó intensivamente: web_search (11), crop_image (3), image_search (1), geocode (2).
- **NO usó**: street_view, static_map, historical_query, fetch_url.
- Concluyó "Strahov Praga" basado en match TEXTUAL débil sin verificación visual.

→ Si hubiera usado `street_view` sobre Strahov vs Серебристый habría visto visualmente que NO matchea.

**Esto NO es bug — es comportamiento que el benchmark va a medir**. Modelos más sofisticados (Claude Opus 5, gpt-5.5+) probablemente hagan mejor uso de tools visuales. La diferencia es señal del benchmark.

### 3. Variancia run-to-run alta (consistente con E001)

Mismo patrón que sin tools: factor 7x entre runs. La hipótesis del agente puede arrancar muy distinta y bajar por caminos divergentes.

### 4. Hash perceptual funciona técnicamente

En las pruebas, ninguna imagen devolvió `is_likely_target=true` — porque las búsquedas no encontraron la foto target específicamente. El flag está conectado correctamente y se reporta al modelo. Cuando aparezca un match, el modelo puede decidir qué hacer.

### 5. Cobertura Street View mejor de lo esperado

Sorpresa positiva: Street View tiene cobertura en:
- Plaza de Mayo BA ✅
- Volga rural (#1459395 ground truth) ✅
- SP barrio anónimo (#1748874) ✅

→ La preocupación de "Street View no cubre zonas históricas/rurales" es menos grave de lo asumido. Spike de cobertura sigue siendo deuda pero no bloqueante.

### 6. OHM cobertura desigual (validado)

`historical_query` funciona técnicamente pero:
- BA churches: 1 result (Catedral Metropolitana, 1852).
- BA buildings year=1900: 0 results (filtro estricto).
- SP buildings year=1990: 0 results.

Confirma deuda en issue #16: cobertura OHM por región necesita audit antes de comprometerse a casos de uso específicos.

## Implicaciones para el benchmark

### Lo que valida E003

1. ✅ **Concepto del benchmark funciona** end-to-end con stack completo.
2. ✅ **Discriminación entre fotos**: sweet spot vs casos imposibles vs casos donde tools empeoran.
3. ✅ **Filtros anti-shortcut**: domains blocked correctamente, hash perceptual flagging conectado.
4. ✅ **Tools técnicamente correctas**: las 12 funcionan, schemas válidos para OpenAI tool calling.
5. ✅ **Comportamiento medible**: el agente decide qué tools usar, eso ES la diferencia entre modelos.

### Lo que NO debe hacerse (anti-pattern)

❌ **Forzar al agente a usar tools específicas en system prompt**. Esto sesga el benchmark.
- Si forzamos "usá street_view antes de submit", medimos al humano que escribió la regla, no al modelo.
- El benchmark debe medir capacidad de **decidir** qué tool usar, no obediencia.

### Deudas registradas

- **Run-to-run variance**: necesitamos N=3-5 runs por foto para conclusiones robustas. Tavily quota es el bottleneck.
- **Métrica de "uso de tools"**: contar cuántas tools distintas usó cada run, qué proporción visual vs textual, etc.
- **Comparación entre modelos**: el benchmark va a discriminar gpt-4o vs gpt-5.4 vs Claude Opus etc. en uso de tools.

## Costo del experimento

- **Tavily**: ~80-100 calls (15% del cuota mensual de 1000 free).
- **Azure Foundry (gpt-5.4)**: token consumption variable pero manejable.
- **Google Maps**: $0 (uso minimal).

## Próximos pasos (no urgente)

1. **Batch limpio en otra sesión** sobre 5-10 fotos diversas con N=3 runs (cuando Tavily se reinicie o decidamos backend alternativo).
2. **Comparar 2+ modelos** sobre las mismas fotos (gpt-4o vs gpt-5.4) para empezar a ver discriminación entre modelos.
3. **Documentar la rúbrica** que el benchmark va a usar para evaluar el "uso investigativo" de tools.
4. **Decisión Verifiers vs custom** queda postpuesta hasta tener más data.

---

## Anexo — Iteración E003-v2 (post-fixes Codex)

Aplicamos los fixes propuestos por Codex (commit `06b4a9a`):
- System prompt 100% **descriptivo** (no prescriptivo): solo describe qué hace cada tool, sin recomendar estrategia ni "sé eficiente". Decisión de no sesgar al modelo.
- `submit_answer` schema expandido: `visual_clues`, `external_evidence`, `rejected_alternatives`, `verification_checks`, `uncertainty_reason`.
- `historical_query` preset `churches` expandido a 6 tags + `temporal_confidence` per-feature + flag `require_dated`.
- `street_view` modo `contact_sheet=true` (4 imágenes auto N/E/S/W) + `pano_date` + `distance_to_pano_m`.
- Image dimensions `WxH` inyectadas al user prompt inicial (para crops válidos).
- Blacklist expandida: 17 → 39 dominios (+ Pinterest, Reddit, Telegram, Alamy, Getty, Shutterstock, eBay, etc.).

### Resultado run #1748874 con prompt minimal + schema rich

Distancia: **1494 km** (mismo Strahov Praga que antes — anclaje persistente).

**Pero ahora el modelo respondió completamente los campos nuevos del submit_answer**:

| Campo | Output |
|---|---|
| `confidence` | `baja` (auto-calibrado vs antes que era `media`) |
| `visual_clues` | 5 items concretos (bloque 8-9 plantas, ventanas, abedules, ropa 90s, prefab) |
| `external_evidence` | 2 items con fuentes (TripAdvisor Strahov, image_search) |
| `rejected_alternatives` | "Rusia/ex-URSS: plausible por arquitectura, descartada por evidencia textual a Praga" + "Paneláks Chequia: descartado por escala" |
| `verification_checks` | 2 items honestos (contrasté tipología, busqué referencias específicas) |
| `uncertainty_reason` | "No apareció match exacto e inequívoco. Identificación basada en tipología parcial" |

→ **El schema expandido actúa como rúbrica forzada SIN SESGAR**. El modelo decide cómo investigar pero **debe estructurar su razonamiento**. Esto es **ORO para el benchmark** — permite medir:
- Calibración (confidence vs distancia real).
- Diversidad de hipótesis (cuántas alternativas consideró).
- Profundidad investigativa (verification_checks count).
- Honestidad (cross-check verification_checks vs tools usadas).

### Test técnico: las tools de Maps SÍ funcionan al 100%

Antes de concluir que el modelo "ignora" las tools de Google Maps, hicimos test directo:
- Prompt: "usá street_view contact_sheet + static_map satellite sobre Plaza Mayor Madrid".
- Resultado: ✅ ambas tools llamadas con args correctos, ✅ imágenes ejecutadas y devueltas (4 SV imágenes a 2m, satellite 640x640), ✅ modelo describió correctamente "estatua ecuestre, edificios rojos con arcadas, casco histórico denso".

→ **NO es bug técnico**. Es decisión del modelo en el contexto de geolocalización: prioriza razonamiento textual sobre verificación visual con Maps. **Eso ES el comportamiento que el benchmark va a medir** entre modelos (gpt-5.4 vs gpt-5.5+ vs Claude Opus 5+).

### Idea registrada para v2 — submit_tentative iterativo (issue #20)

Patrón "frío/caliente" tipo Wordle. El agente puede llamar `submit_tentative(lat, lon)` y recibir feedback ("estás >1000 km", "100-1000 km", "<10 km"), iterando hasta `submit_final`. Postergada a v2 — primero validar one-shot.

Tradeoffs y variantes documentadas en issue #20.
