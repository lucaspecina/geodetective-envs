# Cómo retomar desde otra máquina / sesión nueva

> **Última sesión**: 2026-05-20 — sesión muy productiva con rediseño de tools (Fases 1-3), prompt iteration, corpus blureado canónico, métricas eval. **Próximo paso claro**: expansión + re-balance del corpus (issue #46).
>
> Si retomás en otra máquina, leé este doc PRIMERO. Después tenés `CURRENT_STATE.md` para el panorama completo.

---

## Estado al cierre (2026-05-20)

### Sistema técnico — ya está sólido

| Capa | Estado |
|---|---|
| **Tools v2** (Fases 1-3 rediseño) | ✅ Implementadas, commiteadas, validadas: fetch_url_with_images (con captions), web_search (metadata), static_map enriquecido (POIs + elevation + multi), street_view (nearby), image_search (grilla 4×4 + pick + paginación) |
| **Cliente Google común** (`google_api.py`) | ✅ Cache compartido, error handling non-fatal |
| **historical_query_at** wrapper amigable | ✅ |
| **min_steps** parameter | ✅ Implementado en react.py |
| **Sliding-window cleanup** de imágenes (Azure 50 limit) | ✅ |
| **Corpus blureado canónico** | ✅ `corpus/photos/{cid}_clean_v1.jpg` = versiones blureadas (post issue #33) |
| **Métricas eval module** | ✅ year + calibration + buckets en `src/geodetective/eval/metrics.py` |
| **SYSTEM_PROMPT actualizado** | ✅ con regla "evidence-driven submit" + descripciones tools v2 |
| **Adapter cross-provider** | ✅ OpenAI + Anthropic via Foundry |
| **README orientado a usuarios** | ✅ reescrito |

### Hallazgos clave de la sesión

1. **El prompt actualizado destraba el lock-in**: Lisboa 274 km (Porto) → 2 km (Lisboa) solo cambiando el prompt para que el modelo conozca las tools.
2. **Prompt-only es insuficiente para forzar más exploración**: gpt-5.4-mini ignora "seguí investigando" del prompt. Hace falta restricción de código (min_steps).
3. **min_steps=12 funciona técnicamente** (steps suben de 7 a 12.6, distance baja 38%) pero introduce FAILs (1/10) por modelo "rindiéndose" con contexto lleno.
4. **Corpus contaminado por shortcut OCR**: corridas E010/E012/E014 anteriores usaron fotos sin blur. **Bug fixed en commit `ef4dee6`**, pero results históricos quedaron contaminados.
5. **Corpus sesgado a Rusia (33%)** — limitación grave para benchmark con pretensión de generalización.

### Issue de continuidad

**[#46 Expansión + re-balance corpus a 250 → ~100 finales](https://github.com/lucaspecina/geodetective-envs/issues/46)** — el siguiente trabajo concreto.

---

## Próximos pasos en orden

### 1. EXPANSIÓN DEL CORPUS (issue #46) — lo siguiente que hay que hacer

Plan detallado en la issue. Resumen:

```
Actual: 180 fotos → 33% Rusia, prácticamente 0% LatAm/África/Oceanía/Asia non-CN
Target: 250 candidatos sampleados → pipeline filtra → usuario selecciona → ~100 finales bien distribuidos
```

Pasos concretos:
1. **Modificar `sample_diverso.py`** para subdividir "Resto" en LatAm / Asia-non-CN / África-ME / Oceanía
2. **Re-samplear** con nuevas cuotas (ver issue #46)
3. **Pipeline completo** sobre las nuevas: download → clean → blur → atacante
4. **Selección manual del usuario** sobre las que sobrevivan (HTML grid clickeable propuesto)
5. **Re-blureado opcional** de las 180 existentes para uniformidad

### 2. Después del corpus consolidado

Una vez que tengamos ~100 fotos canónicas bien distribuidas:

- **Cross-model evaluation** (Codex priorizó): 4 modelos (gpt-4o, claude-sonnet, claude-opus, gpt-5.4-mini) × 100 fotos × N=3 runs × min_steps tuneado
- **Annotator CORRAL** sobre todas las traces para process metrics
- **Estratificación por dificultad** vía atacante
- **Baseline humano** opcional (5-10 fotos cronometradas)

---

## Cómo retomar técnicamente

### Setup nuevo (si nunca clonó)

```bash
git clone https://github.com/lucaspecina/geodetective-envs.git
cd geodetective-envs
conda create -n geodetective python=3.11 -y && conda activate geodetective
pip install openai httpx pillow imagehash beautifulsoup4 lxml geopy pydantic ddgs zstandard huggingface_hub pygeohash
```

`.env` con:
```
AZURE_INFERENCE_CREDENTIAL=...
AZURE_FOUNDRY_BASE_URL=https://your-resource.openai.azure.com/openai/v1
AZURE_MODEL=gpt-5.4
GOOGLE_MAPS_API_KEY=...
```

### Regenerar corpus (si arrancás en máquina nueva)

```bash
# 1. Dump PastVu (282 MB, una vez)
python scripts/download_pastvu_dump.py

# 2. Re-samplear 180 (estado actual) o 250 (target post-#46)
python scripts/sample_diverso.py
# Output: experiments/E007_sample_diverso/candidates.json

# 3. Bajar las fotos
python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates.json

# 4. Blureado (anti-shortcut OCR) — IMPORTANTE
python scripts/detect_text_overlays.py --photos-dir corpus/photos --out-dir experiments/E011_text_overlay_detection/sample185_sonnet --model claude-sonnet-4-6 --workers 5

# 5. Sobreescribir corpus con blureadas
for blur in experiments/E011_text_overlay_detection/sample185_sonnet/blurred/*.jpg; do
    cid=$(basename "$blur" .jpg)
    cp "$blur" "corpus/photos/${cid}_clean_v1.jpg"
done
```

### Comandos típicos

```bash
# Correr agente sobre fotos específicas
MODEL=gpt-5.4-mini MAX_STEPS=20 MIN_STEPS=12 CIDS="2165013" python scripts/run_e010_iteration.py

# Métricas post-hoc
python scripts/compute_metrics.py experiments/E010_iteration_pilot/results_*.json

# Viewer step-by-step (con sidebar navigation)
python scripts/build_iteration_viewer.py path/to/results.json --photos-dir corpus/photos
```

---

## Documentos para orientarse al volver

Orden recomendado:

1. **`SESSION_RESUME.md`** (este doc) — estado al cierre + próximos pasos
2. **Issue [#46](https://github.com/lucaspecina/geodetective-envs/issues/46)** — el siguiente trabajo concreto
3. **`CURRENT_STATE.md`** — panorama actual del proyecto
4. **`research/synthesis/tools_redesign.md`** — qué se cambió en tools (referencia)
5. **`research/synthesis/findings_so_far.md`** — hallazgos cross-experimento
6. **`research/synthesis/experiment_design.md`** — ejes a medir en el paper
7. **GitHub issues abiertas** — siguiente trabajo
8. **`CLAUDE.md`** — convenciones del repo

---

## Commits importantes de esta sesión

```
9557064 data: E014 diverse10 results (evidence + blurred+minsteps)
ef4dee6 fix: corpus canónico ahora usa fotos blureadas (cierra #33)
a883d76 feat: regla evidence-driven submit + viewer nav sidebar
1b98ae9 chore: limpieza experiments (235MB → 49MB)
38a05ea feat: prompt v3 image_search semántico
8f64def feat: SYSTEM_PROMPT actualizado + historical_query_at
7567e69 docs: README reescrito para usuarios
29444e2 feat: image_search paginación
ebad6b5 feat: eval module (year + calibration + buckets)
fc0193f feat: Fase 3 image_search grilla
4186867 feat: Fase 2 google_api + static_map + street_view
b7992ba feat: Fase 1.2 + 1.3 web_search + street_view
255b8b4 feat: fetch_url_with_images v2 con captions
43e0f0b docs: tools redesign plan + audit
```

---

## Notas importantes / gotchas

- **Corpus blureado** es ahora canónico. Si re-descargás fotos, hay que aplicar el blur otra vez.
- **`corpus/photos_pre_blur/`** existe como backup local de las fotos sin blur (gitignored).
- **Results históricos contaminados**: E010, E012, E014 (excepto blurred_minsteps), E009 corrieron sobre fotos sin blur. **No usar como baseline canónico** del paper — sí como "pre anti-shortcut comparison".
- **Issue [#33 cerrada](https://github.com/lucaspecina/geodetective-envs/issues/33)** — pipeline corpus Paso 0.5 ya aplicado.
- **Issues abiertas relevantes**: #46 (corpus expansion), #34 (main run), #35 (estratificación), #39 (annotator E009/E010), #43 (ablations), #44 (validación E010).

---

## Comando sugerido al retomar mañana

```powershell
cd C:\Users\YT40432\Desktop\lp\research\lucaspecina\geodetective-envs
git pull
# Leer SESSION_RESUME.md y issue #46
gh issue view 46
```

Y arrancar con #46 — modificar `sample_diverso.py` para los buckets nuevos.
