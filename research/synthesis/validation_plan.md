# Validation Plan — paso a paso para validar viabilidad de todos los componentes

> **Frame**: el proyecto es un **benchmark** de evaluación de agentes geo-investigativos sobre fotos antiguas (no env de training). Este doc enumera las fases con gates concretos.
>
> Plan revisado post-crítica Codex (sin fase legal — queda como deuda futura). Si choca con un note, este es canon.

---

## Estado actual (mayo 2026)

- ✅ **Stack base** verificado: Python 3.11 + conda env `geodetective`, OpenAI SDK + Foundry (gpt-5.4), Tavily, PIL, geopy, httpx.
- ✅ **Fase 0** (concepto manual) completada via E001 → confirmado que el problema es interesante.
- ✅ **Filtro v2** validado parcialmente con 17 fotos: source + dist_min<10km AND conf≥media.
- ✅ **Primer ReAct + web_search** funcionando — E002 muestra mejora 300x en una foto sobreviviente.

## Plan de fases (revisado)

### Fase 0 — Concepto (✅ completada)
- ✅ E001: 17 fotos PastVu en gpt-5.4 sin tools. Resultado: filtro v2 funciona, sweet spot identificado (urbano-no-landmark + rural).
- ✅ E002: ReAct + web_search en #1748874. Resultado: 2573 km → 8.5 km.
- **Gate**: ¿el problema es interesante? **SÍ** — el benchmark discrimina.

### Fase 1 — Datos + cobertura + contrato preliminar (en curso)
- ⏳ Spike PastVu real: descargar `pastvu.jsonl.zst` 296 MB y caracterizar. (Issue #3, pendiente)
- ⏳ Cobertura Street View en sample del corpus filtrado. (Issue dentro de #6)
- ⏳ Resolver contradicción Smapshot. (Issue #4)
- ⏳ Verificar API LoC. (Issue #5)
- ⏳ Decisión contrato del environment / benchmark — SE POSTERGA: por ahora plain Python, evaluar Verifiers/OpenEnv en Fase 6.
- **Gate**: ¿hay metadata suficiente y buckets balanceables pre-filtrado? Pendiente.

### Fase 2 — Tools individuales (en curso)
- ✅ `web_search` con anti-shortcut filter (Tavily) — funcional.
- ⏳ `geocode` / `reverse_geocode` (Nominatim OSM) — pendiente.
- ⏳ `search_places` (Overpass OSM) — pendiente.
- ⏳ `historical_query` (OpenHistoricalMap Overpass temporal) — pendiente. **Pieza diferencial.**
- ⏳ `static_map` (Google + Mapbox/OSM fallback) — requiere user API key.
- ⏳ `street_view` (Google + Mapillary fallback) — requiere user API key.
- ⏳ `ocr` tiered (Tesseract + TrOCR) — pendiente.
- ⏳ `crop_image` / `zoom_in` (PIL local) — pendiente.

**Gate por tool**:
- VLM consume el output sin error.
- Latencia p50/p95 conocida.
- Costo por call medido.
- Failure modes tipados.
- Cacheability (legal y técnica) clara.
- Aporta evidencia no-shortcut.

### Fase 3 — Anti-shortcut estratificado
- ⏳ Validar filtro v2 en sample más grande (50-100 fotos).
- ⏳ **Estratificar por bucket**: fuente / país / década / rural-vs-urbano. NO promedio global.
- ⏳ Implementar Test 1 sampleado (TinEye) para spot-check.
- ⏳ Implementar Test 4 (CLIP local + index de fuentes públicas conocidas).
- **Gate**: survival ≥ 30% en cada bucket relevante AND costo proyectado < $X. Si algún bucket queda < 10%, replantear.

### Fase 4 — Loop end-to-end con rúbrica
- ⏳ Rúbrica investigativa formal (qué se considera "buen razonamiento"):
  - Hipótesis rivales generadas y testeadas.
  - Evidencia visual usada (no inventada).
  - Pivoteo cuando contradicción.
  - No tool spam.
  - Calibración de incertidumbre (confidence honesta).
- ⏳ Conectar 5+ tools al ReAct loop.
- ⏳ Probar 20-50 fotos del corpus filtrado.
- **Gate**: el agente cumple la rúbrica en ≥70% de las trayectorias.

### Fase 5 — Reward implementation
- Spec reward ya definida en `PROJECT.md` invariante 2:
  - **Principal optimizable**: distancia geodésica (km).
  - **Penalizadores de proceso**: tool spam, tool error.
  - **NO en training loop**: LLM judge / rúbrica investigativa (solo eval).
- ⏳ Implementación Python con tests unitarios sobre 5-10 trayectorias sintéticas.
- **Gate**: el reward ordena correctamente: agente bueno > investigador con errores > adivinador > spammer.

### Fase 6 — Eval suite + baselines + ablations
- ⏳ Curar 50-100 fotos canonical (con ground truth + diversidad geográfica/temporal).
- ⏳ Correr 3-4 modelos top end-to-end (Claude Opus, GPT-5.x, GPT-4o, Gemini si disponible).
- ⏳ **Baselines obligatorios**:
  - Baseline humano pequeño (1-2 personas resolviendo 10-20 fotos).
  - Baseline VLM-no-tools.
  - Baseline random / nearest-city (cualquier coord aleatoria, o el centroide del país adivinado).
  - Ablations por tool (qué pasa si quitamos web_search? si quitamos OHM?).
- ⏳ Decisión arquitectónica: ¿migrar a Verifiers / OpenEnv para publicación?
- **Gate**: el benchmark **discrimina** entre modelos AND **separa** investigación genuina de adivinanza con conocimiento previo.

---

## Cambios respecto al plan v1 (post-Codex)

| Cambio | Razón |
|---|---|
| Eliminada Fase -1 (legal/TOS) | Decisión usuario: postpone hasta validar técnicamente. Deuda futura registrada. |
| Contrato del env movido a Fase 6 (era Fase 1) | Plain Python suficiente para validación. Decisión Verifiers/OpenEnv depende del scope final. |
| Fase 1 gate cambiado | "buckets balanceables pre-filtrado" en lugar de "<10K tras filtrado" (que era circular). |
| Fase 2 gate apretado | Métricas reales (latencia, costo, failure modes) en lugar de "VLM interpreta output". |
| Fase 3 estratificado | Survival por bucket, no promedio global. |
| Fase 4 con rúbrica formal | Definida ANTES de eval, no por vibes. |
| Fase 6 con baselines | Humano + no-tools + random + ablations obligatorios. |

## Estimación temporal

- Fase 0: ✅ hecha (1 día efectivo).
- Fase 1: ~1-2 semanas (en curso).
- Fase 2: 3-4 semanas (5-7 tools).
- Fase 3: 2-3 semanas (sample grande + estratificación).
- Fase 4: 2 semanas (rúbrica + 20-50 fotos).
- Fase 5: 1 semana.
- Fase 6: 2-3 semanas.

**Total estimado**: ~12-15 semanas hasta v1 publicable.

## Hipótesis a validar en cada fase (criterios falsables)

- **F1**: PastVu tiene ≥10K fotos balanceables tras filtrado (~70-95% no-Rusia, ≥3 décadas).
- **F2**: Cada tool agrega evidencia útil al agente sin shortcut.
- **F3**: Filtro v2 deja ≥30% survival en cada bucket.
- **F4**: Agente con tools cierra distancia en ≥80% de fotos sobrevivientes.
- **F5**: Reward discrimina los 4 perfiles de agente.
- **F6**: Benchmark separa modelos top entre sí AND separa "memoria" de "investigación".

Si alguna falsea, replanteamos.
