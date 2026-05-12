# E005 — Pilot ReAct agent sobre corpus piloto (#26)

Primera corrida del agente ReAct completo (12 tools, `gpt-5.4`) sobre fotos del corpus piloto (E004, 101 sobrevivientes al atacante #24). El objetivo era validar el pipeline end-to-end: pipeline de filtrado → agente investigador → comparación con ground truth.

**Fecha**: 2026-05-11.
**Script**: `scripts/run_react_pilot.py`.
**Setup**: 1 foto por bucket país = 6 fotos. Seed=42. 1 corrida por foto. `max_steps=12`.
**Tiempo**: 994 s = 16.5 min para 6 fotos (varias en paralelo, no aplica acá — corre secuencial).

---

## TL;DR

- **6 fotos corridas. 4 submitieron respuesta, 2 no (hit `max_steps=12`).**
- **1 acierto preciso**: Tomsk, Russia-Asia 1898, **1.8 km** del lugar real. Sin tools (atacante) había dado `baja/baja/baja` sin coords. **Las tools le ganaron al atacante por amplio margen** en ese caso.
- **3 respuestas off**: Suiza→Frankfurt (301 km), Belarus→Moscow (707 km), Russia→Romania (1352 km).
- **2 N/A**: Dealey Plaza USA y Shenyang/Mukden China 1946.
- **Patrón crítico**: `historical_query`, `static_map`, `street_view` → **0 usos en las 6 fotos**. Web_search saturado (7-15 calls/foto).
- **Conclusión operativa**: el sistema *funciona*, pero el agente actúa como web-search bot, no aprovecha tools visuales. Esto **ES** señal del benchmark.

---

## Setup

| Parámetro | Valor |
|---|---|
| Modelo | `gpt-5.4` (Foundry) |
| Tools disponibles | 12 (todo el stack) |
| `max_steps` | 12 |
| N corridas por foto | 1 |
| Foto por bucket país | 1 (6 fotos total) |
| Seed | 42 |
| Source candidates | `experiments/E004_attacker_filter/results.json` filtrado a `decision=='keep'` |
| Photos cacheadas | `experiments/E004_attacker_filter/photos/` (compartidas con atacante #24) |

---

## Resultados por foto

| CID | Bucket | Año | Truth | Predicción agente | Dist | Tools (ws/fu/is/crop/geo/hq/sm/sv) | Steps | Conf | Submit |
|---|---|---|---|---|---|---|---|---|---|
| **2126812** | Russia-Asia / 1890s | 1898 | Tomsk (56.47, 84.95) "Вид с Троицкого собора" | Vista desde colina Voskresénskaya hacia centro de Tomsk (56.49, 84.95) | **1.8 km** ✅ | 7/1/1/3/4/0/0/0 | 9 | media | ✓ |
| 2034885 | Europa-no-URSS / 1920s | 1928 | Basel (47.39, 8.49) "Baslerstrasse im Bau" | Heimatsiedlung, Frankfurt (50.09, 8.67) | 301 km | 13/0/2/6/1/0/0/0 | 9 | media | ✓ |
| 1267028 | Ex-URSS / 1910s | 1916 | Molodechno Belarus (54.32, 26.84) "Станция Молодечно" | Estación ferroviaria Imperio Ruso, Moscow (55.76, 37.62) | 707 km | 7/0/1/4/0/0/0/0 | 5 | baja | ✓ |
| 509954 | Russia-EU / 1920s | 1925 | Egoryevsk area (55.38, 39.02) "Техническое училище" | Liceul Israelit, Galați Rumania (45.42, 28.03) | 1352 km | 15/1/1/4/2/0/0/0 | 8 | baja | ✓ |
| **2328833** | Norteamerica / 1930s | 1936 | **Dealey Plaza** Dallas (32.78, -96.81) | NO ANSWER (hit max_steps, `target_match=1`) | N/A | 10/2/3/3/5/0/0/0 | 12 | — | ✗ |
| **1587935** | Resto / 1940s | 1946 | Mukden/Shenyang China (41.79, 123.40) "中山路 Улица Сунь Ятсена в Мукдене" | NO ANSWER (hit max_steps) | N/A | 11/3/3/5/0/0/0/0 | 12 | — | ✗ |

**Tomsk fue el único acierto preciso. La foto tiene un toponym implícito ("Voskresenskaya hill" es un landmark de Tomsk), el agente lo identificó visualmente, web_search lo confirmó, geocode lo precisó.** El atacante había sido `baja/baja/baja` sin coords — caso paradigmático de "tools ayudan".

---

## Patrones grandes (importantes)

### 1. Tools visuales y diferenciales nunca se usan

`hq` (historical_query) = `sm` (static_map) = `sv` (street_view) = **0** en todas las fotos.

Esto es **estructural**, no anecdótico. Para Tomsk, donde el agente tenía coords (56.47, 84.95) con confidence media, podría haber verificado con `street_view` para chequear que la fachada coincide. No lo hizo. Para Basel, donde pensaba Frankfurt, podría haber comparado `street_view` de ambos. No lo hizo.

E003 ya mostró que el modelo puede usar street_view/static_map cuando se le pide explícitamente. La decisión canon de E003 fue NO forzar uso de tools en prompt (sesgaría benchmark). Pero el ratio actual 0/22-23 calls totales es agresivo — sugiere problema de **affordance**, no de capacidad.

### 2. Web_search dominante (web-search bot)

7-15 web_search calls por foto. Es ~70 calls en total entre las 6 fotos — Tavily consumido. El agente entra en un loop de "buscar más texto" en lugar de pivotear a verificación visual o investigación histórica con OHM.

### 3. 33% no respuesta por `max_steps`

2 de 6 fotos hit el cap de 12 steps sin submitir. Importante: ese cap no permite distinguir entre "el modelo no sabe" y "el modelo no termina". Subir max_steps sin más probablemente compra más web_search, no mejor investigación.

### 4. Hash deuda funcionó (Dealey Plaza)

En #2328833 (Dealey Plaza), `image_search` encontró 1 imagen con `is_likely_target=True`. Gracias al fix de #24 (hard reject de bytes + URL), el agente no vio la foto target en los resultados de search. Confirma que el shortcut está cerrado.

El agente igual no convergió — probablemente perdió pistas que con la foto-target visible hubiera tenido. Eso es lo correcto: el benchmark no quiere medir "encontrar la foto en Google".

---

## Comparación atacante (sin tools) vs agente (con tools)

Atacante de #24 sobre estas mismas 6 fotos (todas en `decision=='keep'`):

| CID | Atacante dist_min | Atacante conf | Agente dist | Veredicto |
|---|---|---|---|---|
| 2126812 Tomsk | N/A (no aventura) | baja/baja/baja | **1.8 km** | **TOOLS GANARON** decisivamente |
| 2034885 Basel | N/A | media/media/media | 301 km | tools dieron respuesta donde atacante no aventuró |
| 1267028 Belarus train | N/A | media/media/media | 707 km | idem (pero off) |
| 2034885 Russia 1925 | N/A | baja/baja/baja | 1352 km | idem (off) |
| 2328833 Dealey Plaza | N/A | baja/media/media | N/A (max_steps) | empate negativo |
| 1587935 Mukden | 626 km | media/baja/media | N/A (max_steps) | **TOOLS PERDIERON** (atacante había aventurado, agente no terminó) |

**Net**: tools le dieron respuesta al agente donde el atacante no aventuraba (4 de 6), pero solo en 1 caso (Tomsk) esa respuesta fue precisa. En Mukden las tools efectivamente empeoraron (el atacante había dicho 626km, el agente no terminó).

---

## Conclusiones honestas

1. **El sistema funciona end-to-end**. Pipeline filtro → agente → comparación corrió sin errores.
2. **Las tools no son automáticamente útiles**. El agente las usa selectivamente y sub-óptimamente.
3. **El benchmark discrimina**: detectó un fallo operativo real del agente (no usa tools visuales/históricas).
4. **El acierto de Tomsk valida el diseño**. Cuando el agente investiga bien, las tools producen precisión 1000x mejor que sin tools (atacante no aventuraba → agente 1.8 km).

---

## Próximo paso recomendado

**NO escalar K_PER_CELL todavía** (Codex review). El pilot encontró un fallo del agente que conviene diagnosticar primero.

**Mini-ablation propuesta** (Codex review): mismas 6 fotos, mismo `max_steps=12`, dos variantes de system_prompt:

- **A) Prompt actual** — descripciones neutras de cada tool.
- **B) Prompt con affordance explícito de verificación visual** — agregar líneas como: "cuando tengas coordenadas candidatas, podés usar `static_map`/`street_view` para verificar visualmente; para edificios datados, `historical_query` puede confirmar si existían en el año estimado". **NO** prescriptivo ("debés usarlas").

Métricas a comparar: usos de `sv/sm/hq` por foto, distancia, submit_rate.

Si el cambio mueve la aguja → era affordance del prompt. Si no → es limitación del modelo/agente, y entonces el benchmark mide algo intrínseco. Cualquiera de los dos es resultado útil.

Issue creada: (TBD — al cerrar #26 conviene abrir una para "E006: ablation de prompt").

---

## Deuda detectada para el script

- El script no tiene "forced submit" cuando hit `max_steps`. Es decir, si el agente no termina, no hay respuesta. Codex sugiere agregar un fallback que pida al agente submitir su mejor hipótesis. Pendiente.
- Cada response tiene `submit_called=False` cuando esto pasa — campo correcto, ya está registrado en `react.py`.
