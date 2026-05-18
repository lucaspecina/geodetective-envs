# Cómo retomar desde otra máquina / sesión nueva

> **Última sesión**: 2026-05-18.
>
> Este doc es un pointer rápido al estado exacto cuando termines una sesión. Si retomás en otra máquina, leelo PRIMERO. Después puede ir a `CURRENT_STATE.md` para el panorama completo.

---

## Estado al cierre (2026-05-18)

### Avances de esta sesión

1. **Corpus canónico funcional**: `corpus/photos/` con 185 fotos balanceadas (descargadas de PastVu vía dump HF). Pipeline reproducible: `scripts/download_pastvu_dump.py` → `sample_diverso.py` → `download_corpus_photos.py`.

2. **E011 Detector de overlays textuales**: VLM (claude-sonnet-4-6) detecta texto archivístico en 84/185 fotos (45%). Blur gaussiano sobre regiones detectadas. Output canónico en `experiments/E011_text_overlay_detection/sample185_sonnet/blurred/`.

3. **E012 Ablation min_steps {0, 15, 30}** con gpt-5.4-mini × 10 fotos:
   - **Hallazgo principal**: hay sweet spot en min_steps. Libre da 2639km avg, min15 da 1387km avg (mejora 50%), min30 da 4474km avg (empeora). Confirma que "pensar más tiempo" ayuda hasta un punto y después es contraproducente.
   - **Bugs scaffold descubiertos**:
     - `content: null` cuando modelo devuelve content="" sin tool_calls
     - "Too many images: 51/50" — Azure rechaza si historial acumula >50 imágenes
   - **2 fixes aplicados** (commit `34414ce` + cambios staged sin commit aún) — ver "Trabajo no commiteado" abajo.

4. **Docs actualizados extensivamente**:
   - `CLAUDE.md`, `CURRENT_STATE.md` — tech stack post-Tavily (Azure Bing Grounding + DDG), estructura actual del repo
   - `research/synthesis/experiment_design.md` (NUEVO) — ejes canónicos del benchmark (modelos, N runs, min_steps, dificultad, blur, tools)
   - `research/synthesis/findings_so_far.md` — hallazgos post-E009 sumados
   - `research/notes/E010_iteration_findings.md` (NUEVO) — 5 patrones de gpt-5.4-mini
   - `research/notes/E011_text_overlay.md` (NUEVO) — detector + ablation
   - `research/notes/E012_min_steps.md` (NUEVO + update con fixes) — sweet spot + bugs scaffold

5. **GitHub issues creadas** (#29-#39) + cerradas obsoletas (#25, #27, #28). Ver [Project v2](https://github.com/users/lucaspecina/geodetective-envs/projects/6).

### Trabajo NO commiteado todavía (al momento de cerrar)

```
modified:   research/notes/E012_min_steps.md        # update con fixes + re-run
modified:   src/geodetective/agents/react.py        # 2 fixes scaffold
new:        scripts/test_image_pruning.py            # smoke tests sintéticos
new:        experiments/E012_min_steps/results_gpt-5_4-mini_min30.json  # re-run con fixes
new:        SESSION_RESUME.md                        # este doc
```

**Acción urgente al retomar**: hacer commit de esto. Comando sugerido al final de este doc.

---

## Próximos pasos (en orden de prioridad)

Ver [Project v2](https://github.com/users/lucaspecina/geodetective-envs/projects/6) para detalle de cada issue. Resumen:

### Inmediato (lo más impactante)

1. **#34 Main run cross-model con N=3 corridas** ⭐ — paper-blocker
   - Pre-requisito: #35 (estratificación) + #32 (métricas year + calibration)
   - 6 modelos × 100 fotos × N=3 = ~1800 corridas, ~10-15h con paralelismo, ~$80-300
   - Ahora SÍ es factible porque los bugs scaffold están fixed

2. **#35 Estratificación corpus por tier de dificultad** — corre en paralelo
   - GPT-4o-sin-tools sobre las 185 → 3 tiers (fácil/medio/difícil)
   - ~15-20 min, $4-6, output en `experiments/E014_corpus_stratified/`

3. **#32 Métricas year + calibration** — análisis post-hoc gratis
   - Implementar `src/geodetective/eval/metrics.py` + `scripts/compute_metrics.py`
   - Aplicar a results existentes E005, E009, E010, E012
   - ~1h trabajo, $0

### Secundario

4. **#33 Pipeline corpus Paso 0.5 blur** — integrar el detector E011 al pipeline canónico, bump CLEAN_VERSION=2
5. **#30 Tool review v1** — análisis cuantitativo + decisión qué queda/sacar (resuelve #6)
6. **#31 Prompt iteration** — 4 variantes anti-lock-in, test sobre subset
7. **#39 Annotator CORRAL sobre E009/E010** — process metrics cross-model
8. **#36-38 Nuevas tools** — wikipedia_search, terrain_elevation, compare_images

---

## Cómo retomar desde otra máquina

### Setup nuevo (si nunca clonó el repo)

```bash
git clone https://github.com/lucaspecina/geodetective-envs.git
cd geodetective-envs
conda create -n geodetective python=3.11 -y
conda activate geodetective
pip install openai httpx pillow imagehash beautifulsoup4 lxml geopy pydantic ddgs zstandard huggingface_hub pygeohash
```

Crear `.env` con credenciales (gitignored — NO está en repo):
```
AZURE_INFERENCE_CREDENTIAL=...
AZURE_FOUNDRY_BASE_URL=https://amalia-resource.openai.azure.com/openai/v1
AZURE_MODEL=gpt-5.4
GOOGLE_MAPS_API_KEY=...
```

### Si solo querés sincronizar trabajo

```bash
cd geodetective-envs
git pull
conda activate geodetective
```

### Regenerar el corpus (las 185 fotos están gitignored)

```bash
# 1. Bajar dump PastVu 282MB
python scripts/download_pastvu_dump.py

# 2. Samplear 180 fotos balanceadas (ya hay candidates.json commiteado en E007)
# Si no querés re-samplear, salteá este paso

# 3. Descargar las fotos (~80s, paralelo)
python scripts/download_corpus_photos.py experiments/E007_sample_diverso/candidates.json
```

Eso genera `corpus/photos/{cid}_raw.jpg` + `{cid}_clean_v1.jpg` para las 185.

### Para regenerar el corpus con BLUR (Paso 0.5)

Pendiente integrar (#33). Por ahora manual:

```bash
python scripts/detect_text_overlays.py \
  --photos-dir corpus/photos \
  --out-dir experiments/E011_text_overlay_detection/sample185_sonnet \
  --model claude-sonnet-4-6 \
  --pattern "*_clean_v1.jpg" \
  --workers 5
```

Las fotos blurreadas quedan en `experiments/E011_text_overlay_detection/sample185_sonnet/blurred/{cid}.jpg`. ~$3-4 + 10-15 min.

### Documentos para orientarse al volver

En orden recomendado para retomar contexto:

1. **`SESSION_RESUME.md`** (este doc) — estado al cierre, qué falta commitear
2. **`CURRENT_STATE.md`** — panorama actual del proyecto
3. **`research/synthesis/experiment_design.md`** — ejes experimentales que estamos midiendo
4. **`research/synthesis/findings_so_far.md`** — hallazgos cross-experimento
5. **`research/notes/E012_min_steps.md`** — lo último que tocamos (fixes scaffold)
6. **`CLAUDE.md`** — convenciones del repo + tech stack
7. **GitHub issues** abiertas — siguiente trabajo concreto

---

## Comando sugerido al retomar para commit del trabajo pendiente

```powershell
cd C:\Users\YT40432\Desktop\lp\research\lucaspecina\geodetective-envs
git add src/geodetective/agents/react.py scripts/test_image_pruning.py research/notes/E012_min_steps.md experiments/E012_min_steps/results_gpt-5_4-mini_min30.json SESSION_RESUME.md
git commit -m "fix: scaffold bugs descubiertos en E012 (content null + 50-imgs limit)

Dos fixes en src/geodetective/agents/react.py:
1. content: null cuando msg.content='' y no hay tool_calls. Antes saltaba la asignación content del assistant_turn, generando dict sin content key. Azure rechazaba next call.
2. Sliding-window cleanup de imágenes acumuladas. Si historial tiene ≥45 imágenes, eliminar las más viejas hasta 40, preservando foto target como anchor. Marker text descriptor compatible con Anthropic.

Tests sintéticos en scripts/test_image_pruning.py (7 escenarios, todos pasan).

Re-run E012 min30 con fixes: NO más errores 'Too many images' ni 'content null'. Aparece nuevo terminal_state legítimo del modelo: 'Empty response' con finish_reason='stop' (el modelo 'se rinde' con contexto lleno + steps forzados).

Conclusión actualizada: sweet spot min_steps probablemente entre 10-15. min_steps=30 confirma overkill.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
git push origin main
```

Después, opcionalmente, lanzar #35 (estratificación) en background mientras hacés otra cosa:

```powershell
# (cuando esté implementado / adaptado el atacante para las 185)
python scripts/run_attacker_filter.py --photos-dir corpus/photos --out experiments/E014_corpus_stratified
```
