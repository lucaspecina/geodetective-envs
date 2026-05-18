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

## Resultados parciales (E012 todavía en curso al momento de escribir)

### min_steps=0 (libre, 10/10 done)

10 OK, 0 FAILs. Steps típico: 4-8 (media 5.5).

Distancias: 0, 37, 395, 666, 1421, 2360, 3024, 3195, 3413, 11877 km.

**Varianza enorme**: algunos casi exactos (cid=1056438 a 0 km), otros desastrosos (cid=888377 a 11877 km).

### min_steps=15 (8/10 done — 4 FAILs)

Causas de los FAILs:
- **2× `content_policy_violation`** (Azure content filter): cuando el modelo hace más crops y image_searches, alguna región dispara el filtro de seguridad. Aleatorio pero más probable con más operaciones.
- **1× "Too many images in request: 51, max 50"**: el agente acumula imágenes en el contexto (crops + image_searches + street_views). Con min_steps≥15 se pasa del límite de 50 imágenes que acepta Azure por request.
- **1× "Invalid value for content: expected string, got null"**: bug en algún payload de tool result. A investigar.

OK results: cid=763041 (923 km), cid=657448 (399 km), cid=2337912 (2886 km), cid=1336113 (2350 km).

### min_steps=30 (no arrancó todavía al momento de escribir)

Probable que tenga aún más FAILs por el bug de >50 imágenes.

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
