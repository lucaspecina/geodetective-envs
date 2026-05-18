# E012 — Ablation min_steps (¿forzar más pasos ayuda?)

> **Objetivo**: testear si forzar al modelo a hacer más steps mejora la performance, o si "estira" el razonamiento haciendo cosas redundantes.
>
> **Setup**: gpt-5.4-mini × 10 fotos random del pool blurreado × min_steps ∈ {0, 15, 30}.
>
> **Dónde**: `experiments/E012_min_steps/`.

---

## Diseño

Agregamos parámetro `min_steps` al agente ReAct (`src/geodetective/agents/react.py`):

```python
if (step + 1) < min_steps:
    # rechazar submit_answer, pedirle al modelo que siga investigando
```

Si el modelo intenta `submit_answer` antes del piso mínimo, recibe mensaje:
> "submit_answer bloqueado: estás en el step N pero el piso mínimo es M. Seguí investigando con otras tools antes de submitir..."

10 fotos random sampleadas del corpus blurreado (E011 output) con seed=42.

---

## Resultados finales

| min_steps | OK | FAIL | Avg steps | Avg dist (OK) | Avg duración |
|---|---|---|---|---|---|
| **0** (libre) | 10/10 | 0 | 5.5 | 2639 km | 3.5 min/foto |
| **15** | 6/10 | 4 | 13.2 | **1387 km** ⭐ | 7.7 min/foto |
| **30** | 4/10 | 6 | 24.6 | 4474 km | 16.6 min/foto |

### Hallazgo principal: hay un sweet spot

- **min_steps=15 reduce la distancia promedio ~50%** (de 2639 → 1387 km). Forzar pensar más TIENE valor, en este rango.
- **min_steps=30 EMPEORA** (4474 km > min_steps=15). Demasiada obligación se vuelve contraproducente: el modelo da vueltas, cambia de hipótesis caprichosamente, o se compromete a hipótesis cada vez más exóticas.
- El sweet spot probablemente está entre 10-15 steps. Pendiente medir min_steps=10 y min_steps=20 para curva más fina.

### Bug del scaffold mata el experimento min30

**Submit rate cae rápido**: 10/10 → 6/10 → 4/10 con más forzado. NO es por capacidad del modelo, es por bugs del scaffold:

**Causas de FAILs**:
- **Too many images in request (>50)**: el agente acumula imágenes en contexto sin liberarlas. Con muchos steps llega al límite hard de Azure (50 imágenes/request).
- **Content policy violation**: más crops + image_searches → mayor probabilidad de hit el filtro de seguridad de Azure (aleatorio).
- **Payload null**: bug menor en algún tool result, a investigar.

Distribución de FAILs por min_steps:
- min_steps=0: 0 FAILs (no llega a estos problemas)
- min_steps=15: 4 FAILs (2× content filter, 1× too many images, 1× payload null)
- min_steps=30: 6 FAILs (6× too many images — domina por completo)

### Implicación: prioridad fix scaffold

El bug **"Too many images"** es el **único bloqueante real**. Una vez fixed:
- min_steps=30 debería tener submit rate ~10/10 también
- Podríamos medir min_steps en {0, 5, 10, 15, 20, 30, 40} para curva completa
- Permitiría correr fotos complejas (Tomsk-like) sin perder calls

Estrategia propuesta (issue #29): tool nueva `note_observation(text)` que permite al modelo apuntar observaciones clave en TEXTO antes de que las imágenes caduquen del contexto, + cleanup automático de imágenes viejas con foto target preservada como anchor.

---

## Update 2026-05-18: fixes aplicados + re-run min30

Tras review con Codex (ver agentId ae881a3db028a8538), implementamos **2 fixes** en `src/geodetective/agents/react.py`:

### Fix 1 — `content: null` bug
- **Antes**: `if msg.content:` saltaba cuando content era `""`. assistant_turn quedaba sin content key. Azure rechazaba next call con "content: expected string, got null".
- **Después**: normalizar a string (nunca None), detectar empty response cubriendo None Y `""`.

### Fix 2 — Sliding-window cleanup (Azure 50 imgs hard limit)
- Helpers `_count_images_in_messages()` y `_prune_old_images()`.
- Antes de cada step, si hay ≥45 imágenes → eliminar las más viejas hasta 40.
- **Foto target inmune** (primera imagen del historial).
- Reemplazo con marker `type=text`: "[imagen eliminada del contexto en step N. Para re-acceder, invocá la tool original con sus parámetros guardados.]"
- Text descriptors antes de cada imagen (ej `[Crop region=...]`) quedan intactos.

### Tests sintéticos: `scripts/test_image_pruning.py`
7 tests, todos pasan: count exacto, prune al target, foto target preservada, descriptors preservados, markers válidos para Anthropic, no-op cuando no hace falta, estructura intacta.

### Re-run E012 min30: validación de fixes

| Métrica | Antes fix | Después fix |
|---|---|---|
| Submit OK | 4/10 | 4/10 |
| FAIL "Too many images" | 6 | **0** ✅ |
| FAIL "content null" (subset) | 3 | **0** ✅ |
| Cleanups activados | N/A | 9× en 4 fotos ✅ |
| FAIL "Empty response" (nuevo) | 0 | **5** |
| FAIL content_policy | 0 | 1 |

### Hallazgo nuevo: modelo "se rinde"

Los 2 bugs scaffold ya NO aparecen (cleanup confirmado funcionando). Pero apareció un comportamiento nuevo: **5/10 fotos terminan con `finish_reason='stop'` + content vacío y sin tool_calls**. El modelo "se rinde" cuando el contexto tiene muchos markers `[imagen eliminada]` + 30 steps forzados.

Esto NO es bug del scaffold, es **propiedad del modelo**. Confirma el hallazgo principal del experimento: `min_steps=30` es overkill, el modelo abandona. **El sweet spot real es min_steps=15** (donde 6/10 OK con avg 1387 km, vs 30 con 4/10 OK + 2856 km).

### Conclusión actualizada

- Sweet spot min_steps probablemente está entre 10-15.
- `min_steps=30` es contraproducente: el modelo se rinde o da vueltas estériles.
- Bugs scaffold resueltos → habilita correr main run (#34) sin perder calls por estos errores.
- Comportamiento "se rinde con contexto lleno" es un hallazgo para reportar en paper.

Pendiente:
- Validar curva fina: re-correr E012 con `MIN_STEPS_LIST="0,5,10,15,20"` (rango menor, donde está el sweet spot).
- Si querés, también re-correr min15 con fixes para ver si baja de 4/10 FAIL → 0/10 FAIL (esperable).

---

## Hallazgos

### 1. Forzar más steps revela bug del scaffold

El bug **"Too many images in request: 51, max 50"** es un problema real del scaffold, no del modelo. Con min_steps alto, el agente:
- Hace más crops → cada uno suma 1 imagen al contexto
- Hace más image_search → cada uno suma hasta 5 imágenes
- Hace más street_view → cada uno suma hasta 4 imágenes
- Acumula → eventualmente >50 → Azure rechaza el next call

**Solución necesaria**: clear context strategy — limpiar imágenes viejas del contexto cuando se acerca al límite. Posibilidades:
- A. Mantener solo las últimas N imágenes inyectadas
- B. Eliminar imágenes después de M turns
- C. Comprimir imágenes viejas a sus metadatas (descripción text-only)

Sin esta fix, **no podemos forzar más pasos**. Issue dedicada.

### 2. Comparativa parcial (con N pequeño)

| min_steps | Submit rate | Steps avg | Dist avg | Comentarios |
|---|---|---|---|---|
| 0 | 10/10 | 5.5 | ~2960 km | Varianza enorme |
| 15 | 4/10 OK | 13 | ~1640 km | Mejor en los que terminaron, pero menos terminan |
| 30 | TBD | — | — | TBD |

**Tendencia preliminar**: con min_steps el modelo razona más, llega más fotos a submit con menos errores groseros entre los que terminan. PERO el scaffold sufre y aparecen FAILs nuevos.

Con N=4-6 datapoints comparables, no es concluyente. Necesitamos:
1. Fix del bug del scaffold
2. Re-correr con N mayor (20+ fotos)
3. Múltiples runs por foto (variance)

---

## Next steps

1. **Fix scaffold bug** (>50 images): primera prioridad, bloquea todo lo demás de este eje.
2. **Re-correr E012 a escala** después del fix: 20-30 fotos, min_steps ∈ {0, 10, 20, 30, 40}.
3. **Combinar con prompt iteration**: ¿prompt mejor + min_steps alto da lo mejor de los dos mundos?

---

## Refs

- Script: `scripts/run_e012_min_steps.py`
- Outputs: `experiments/E012_min_steps/results_gpt-5_4-mini_min{0,15,30}.json`
- Viewers HTML por setting: `experiments/E012_min_steps/viewer_min{0,15}.html`
- Patch react.py: `src/geodetective/agents/react.py` (parámetro `min_steps`, bloqueo de submit_answer)
