# Experiment Design — ejes canónicos del benchmark

> **Status**: draft inicial mayo 2026. Documenta los ejes experimentales (ablations / dimensiones) que vamos a medir sistemáticamente para el paper.
>
> **Refs**: `findings_so_far.md` (running log), `validation_plan.md` (plan por fases), `process_eval_design.md` (segunda capa de métricas).

---

## Resumen

Variables que vamos a medir para producir un benchmark publicable:

| Eje | Valores a probar | Prioridad |
|---|---|---|
| **Modelos** | 5-7 modelos diversos (familia × tamaño) | ⭐⭐⭐ |
| **N runs por (modelo, foto)** | 1, 3, 5 | ⭐⭐⭐ no es opcional para paper |
| **min_steps (piso de pasos forzados)** | 0 (libre), 15, 30 | ⭐⭐ |
| **Estratificación por dificultad** | Tier 1 (atacante resuelve fácil), Tier 2, Tier 3 | ⭐⭐⭐ |
| **Blur on/off** | con/sin overlay textual removido | ⭐⭐ (ya validado en pequeño) |
| **Tool ablations** | quitar individual: web_search, street_view, historical_query, crop | ⭐ |
| **System prompt variants** | v3_canon, anti-lock-in, verificación obligatoria | ⭐ |

---

## 1. Ejes principales (deben estar en el paper)

### 1.1 Modelos

**Por qué**: ranking principal del benchmark. ¿Qué modelos son mejores investigadores geo? ¿Hay diferencias por familia o solo por tamaño?

**Modelos a comparar** (todos deployados en Foundry, OpenAI-compatible o Anthropic):
- OpenAI: `gpt-4o`, `gpt-5.4-mini`, `gpt-5.4`
- Anthropic: `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-opus-4-6`
- xAI: `grok-4.3` o `grok-4-1-fast-reasoning`
- Moonshot: `Kimi-K2.6`
- Opcional: DeepSeek-V3.2 como text-only (forced no-vision baseline)

**Notas**:
- Cobertura: 2-3 familias × 2-3 tamaños → 6-7 modelos
- Foundry rate limits son por deployment; podemos correr varios modelos en paralelo (commit `7bdc490`)
- Costo: gpt-5.4 vs claude-opus difiere ~3-5×, hay que documentar Pareto frontier

### 1.2 N runs por (modelo, foto)

**Por qué**: sin esto **no hay paper**. Single-seed N=1 no permite reportar varianza, std, CI. Cualquier reviewer fuerte lo va a cuestionar.

**Valores**: probar N=3 mínimo. Validar si N=5 da estimaciones materialmente distintas.

**Costo**: lineal (3× corridas).

**Métricas derivadas**:
- Distancia media + std + CI95
- Stability across seeds (qué tan consistente es cada modelo)
- ¿Hay modelos que son "sólidos" (low variance) y otros "volátiles" (high variance)?

### 1.3 min_steps (piso forzado de pasos)

**Por qué**: vimos en E010 que gpt-5.4-mini submitea en 4-7 steps sobre budget 50. ¿Pensar más tiempo realmente ayuda?

**Implementación**: bloqueo "hard" de `submit_answer` antes del step N. Si el modelo intenta terminar antes, recibe mensaje pidiéndole seguir investigando.

**Valores**: 0 (libre), 15, 30. Quizás 5 si queremos curva más fina.

**Hallazgos preliminares E012** (gpt-5.4-mini × 10 fotos):
- min_steps=0 → 5.5 avg steps, 10/10 submit, varianza enorme
- min_steps=15 → 13 avg steps, **4 FAILS de 10** por límites de scaffold (>50 images, content filter)
- min_steps=30 → todavía corriendo

**Implicación crítica**: forzar más steps revela **bugs del scaffold** (acumulación de imágenes en contexto). Hay que fixearlo (ver issue "Scaffold: clear context").

### 1.4 Estratificación por tier de dificultad

**Por qué**: agregado de "distancia promedio" puede ocultar diferencias importantes. Un modelo puede ser mucho mejor en fotos fáciles y igual en difíciles, o viceversa.

**Implementación**: pre-clasificar el corpus con el atacante GPT-4o-sin-tools (`scripts/run_attacker_filter.py`):
- **Tier 1 (fácil)**: atacante resuelve directamente (distancia < 100 km)
- **Tier 2 (medio)**: atacante falla pero tiene hipótesis razonable (100 km < dist < 1000 km)
- **Tier 3 (difícil)**: atacante completamente perdido (dist > 1000 km o sin hipótesis clara)

**Métricas**: distancia promedio por tier, no solo agregado.

---

## 2. Ejes secundarios (refuerzan el paper)

### 2.1 Blur (anti-shortcut textual)

**Por qué**: detectamos en E011 que **45% del corpus tiene texto archivístico** (captions, sellos, watermarks). Sin blur, el modelo lee el cartel → googlea → resuelve = no es investigación.

**Implementación**: pipeline E011 con Sonnet, blur gaussiano radius=20 sobre regiones clasificadas `archive_overlay`.

**Hallazgos preliminares** (E010 × 5 fotos, ablation chiquita):
- Cáucaso: 232km → 28km (-204km) ✅ blur funciona donde el shortcut es OCR puro
- Lisboa: 274km → 273km (sin cambio) — lock-in semántico, no textual
- Volga: 496km → 611km (+116km) — texto era pista contextual real
- Bogotá: 3176km → 17321km (+14146km) — empeoró brutal
- Cracovia: FAIL — content filter de Azure rechazó imagen blurreada

**Decisión**: blur agresivo es correcto para benchmark de razonamiento (no de OCR). Aceptar que algunas fotos quedan más difíciles sin texto archivístico — eso es justamente lo que medimos.

**Ablation pendiente a escala**: corpus completo (185) × N modelos × {blur on, blur off}.

### 2.2 Tool ablations

**Por qué**: ¿qué tools realmente aportan? Si quitamos `street_view` y el ranking cambia poco, esa tool es decoración (mide overhead, no capacidad).

**Implementación**: para 1 modelo de referencia (gpt-5.4-mini), correr el corpus completo con cada tool individualmente removida del schema:
- Sin `web_search` (¿cuán importante es googlear?)
- Sin `street_view` (¿la verificación visual hoy aporta?)
- Sin `historical_query` (¿realmente usa OHM?)
- Sin `crop_image` (¿ver detalles a alta resolución ayuda?)
- Sin `static_map` (¿ver mapas externos ayuda?)

**Output esperado**: ranking de "valor marginal" de cada tool en la performance promedio.

### 2.3 System prompt variants

**Por qué**: en E010 vimos lock-in en 3/5 fotos. ¿Un prompt mejor lo previene?

**Variantes a A/B testear**:
- **v3_canon**: actual (descriptivo de tools, sin sesgar uso)
- **v4_anti_lockin**: agrega "considerá siempre ≥2 hipótesis vivas hasta tener evidencia decisiva"
- **v5_verification_required**: agrega "antes de submit hacé ≥1 street_view de tu hipótesis principal Y ≥1 alternativa"
- **v6_short_queries**: agrega "queries cortas y diagnósticas (≤8 palabras), no descripciones"

**Implementación**: 1 modelo × corpus subset (20-30 fotos) × 4 variantes. Probar si alguna mueve el needle.

---

## 3. Métricas de evaluación

### 3.1 Outcome metrics (lo que YA medimos vs lo que falta)

**Hoy medimos**:
- `distance_km` — distancia geodésica predicho ↔ real
- `submit_called` — % de fotos donde el agente llegó a respuesta válida
- `steps_used`
- counts de tools usadas
- `elapsed_seconds`

**Falta medir** (pedimos en `submit_answer` pero ignoramos):
- **Year error**: `|year_pred - year_truth|`. Aceptar rangos ("1960-1970" → punto medio).
- **Year accuracy buckets**: ± 5, ± 10, ± 20 años.
- **Distance accuracy buckets**: % aciertos dentro de 1, 5, 25, 100, 500, 1000 km.
- **Calibration**: corr(confidence reportada, distancia). ¿Confianza alta → cerca? ¿Confianza baja → reconoce que no sabe?
- **Verification quality**: ¿hizo al menos 1 verificación visual antes de submit? (binario)

### 3.2 Process metrics (segunda capa — `process_eval_design.md`)

**Annotator CORRAL-adapted** (ver `src/geodetective/judge/`):
- Epistemic graph density (cuántos H/T/E/J/U/C únicos + edges)
- Evidence-led hypothesis ratio (% de H precedidas por E)
- Contradiction-without-repair (penalty) — el caso Bogotá E010 ejemplifica esto
- Visual verification before submit (binario)
- Hypothesis competition (¿consideró ≥2 hipótesis?)

**Patrones productivos** (9 motifs) y **breakdowns** (8) — ya implementados, falta correr a escala.

---

## 4. Plan factorial (matriz de experimentos)

**Principal × ablations**:

| Experimento | Modelos | Fotos | N runs | min_steps | Blur | Costo aprox |
|---|---|---|---|---|---|---|
| **Main run** | 6 modelos | 100 (stratified) | 3 | 50 (libre) | on | $$$$ |
| **Main no-blur baseline** | 6 modelos | 100 | 3 | 50 | off | $$$$ |
| **min_steps ablation** | 1 (gpt-5.4-mini) | 20 | 3 | {0, 15, 30} | on | $$ |
| **Tool ablation** | 1 (gpt-5.4-mini) | 20 | 3 | 50 | on | $$ (×5 tools) |
| **Prompt variants** | 1 (gpt-5.4-mini) | 20 | 3 | 50 | on | $$ (×4 variants) |

**Cifras totales aprox**: ~6000-8000 agent calls. Con paralelismo entre modelos: ~10-15 horas wall time. Costo: depende del mix de modelos (Claude opus es ~5× gpt-5.4-mini).

---

## 5. Pendientes para que esto se ejecute

1. **Bug scaffold** (>50 imágenes en contexto) — bloquea `min_steps` y corridas largas. Issue dedicada.
2. **Métricas year + calibration** — implementar en analysis script, no toca el agente.
3. **Atacante sobre las 185** — generar tiers de dificultad.
4. **Tool ablations** — agregar flag `--disabled-tools` al agente para skip dinámico.
5. **Prompt variants** — separar prompts en archivos versionados.

Ver issues en [Project v2](https://github.com/users/lucaspecina/projects/6).
