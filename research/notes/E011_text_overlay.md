# E011 — Text overlay detection + blur (anti-shortcut Paso 0.5)

> **Objetivo**: detectar texto archivístico (captions, sellos, watermarks) en las fotos del corpus y blurrearlo, para evitar shortcut "leer cartel → googlear topónimo → resolver".
>
> **Dónde**: `experiments/E011_text_overlay_detection/`.
>
> **Script**: `scripts/detect_text_overlays.py` (VLM-based detector con tool calling) + blur gaussiano sobre regiones clasificadas `archive_overlay`.

---

## Diseño

VLM clasifica cada región con texto en una de:
- **`in_scene`**: texto en la realidad fotografiada (cartel de tienda, marquesina, póster, vehículo). KEEP.
- **`archive_overlay`**: texto agregado posterior (caption manuscrita, número de catálogo, watermark digital, sello). BLUR.
- **`uncertain`**: caso borde, default keep.

Output: bbox + classification + confidence + reasoning + text_snippet.

Después: `blur_overlays()` aplica `ImageFilter.GaussianBlur(radius=20)` con padding 6px sobre regiones `archive_overlay` (opcionalmente sobre `uncertain` con flag).

---

## Comparación de modelos (mismo seed=42 sobre 30 fotos del corpus)

| Modelo | Tiempo | Fotos con overlay | Comportamiento |
|---|---|---|---|
| gpt-5.4 | 278s | 13/30 | Conservador |
| **gpt-4o** | **249s** ⚡ | 13/30 | Conservador (más rápido) |
| **claude-sonnet-4-6** | 592s | 14/30 | Intermedio, usa `uncertain` más |
| claude-opus-4-6 | 619s | 13/30 | Más exhaustivo en regions totales |

Los 4 detectan **las mismas ~13 fotos** como teniendo overlay (consistencia). La diferencia es **precisión de bboxes individuales** — los VLMs generales no son pixel-perfect en grounding.

**Decisión**: usar **claude-sonnet-4-6** como sweet spot precio/calidad. ~$3-4 por 185 fotos vs $15 con Opus.

---

## Scaleup sobre las 185 fotos (Sonnet)

Tiempo: 644s (10.7 min, workers=5).

| Métrica | Valor |
|---|---|
| Total | 185 |
| Sin texto detectado | 49 (26%) |
| Con ≥1 `archive_overlay` | **84 (45%)** ← críticas para blur |
| Regions `in_scene` totales | 288 (signage real, KEEP) |
| Regions `archive_overlay` totales | 140 (BLUR) |
| Regions `uncertain` | 62 |

**Conclusión jugosa**: **45% del corpus tiene shortcut textual archivístico**. Sin blur, casi la mitad del benchmark es resoluble via OCR + Google. Confirma que el clean es necesario para que sea benchmark de razonamiento.

Output: `experiments/E011_text_overlay_detection/sample185_sonnet/blurred/{cid}.jpg` (185 fotos, las 49 sin overlay son pass-through idéntico).

---

## Ablation E010 (5 fotos × {original, blurred})

Re-corrimos gpt-5.4-mini sobre las 5 fotos del E010 con las versiones blurreadas:

| cid | Zona | Sin blur | Con blur | Delta | Interpretación |
|---|---|---|---|---|---|
| 2165013 | Lisboa | 274 km | 273 km | -1 | Sin cambio. Lock-in semántico (Porto), no textual |
| 1248470 | **Cáucaso** | 232 | **28** | **-204** ✅ | Blur funcionó. Sin sello cirílico, razonó por arquitectura |
| 2086652 | Cracovia | 255 | FAIL | NA | Content filter de Azure rechazó imagen blurreada |
| 1560610 | Volga | 496 | 611 | +116 | Empeoró. Sin "-ово" perdió señal de región |
| 2000504 | Bogotá | 3176 | **17321** | **+14146** 🚨 | Catastrófico. Sin caption se fue a Manila/Filipinas |

---

## Hallazgos importantes

### 1. Blur funciona cuando el shortcut es OCR puro

**Cáucaso**: el sello cirílico era el shortcut. Sin él, el modelo razonó por arquitectura + relieve. ✅

### 2. Lock-in semántico NO se arregla con blur

**Lisboa**: distancia no cambió. El bias era visual ("tranvías + ibérico → Porto"), no textual. Necesita otra intervención (system prompt, hipótesis competitivas).

### 3. ⚠️ Blur indiscriminado puede DEGRADAR

**Volga**: el sufijo "-ово" era provenance contextual real (te dice "es ruso"), no shortcut completo. Removerlo empeoró.

**Bogotá**: caption pequeña en margen tenía señal contextual. Sin ella, el modelo fue a Manila (otra capital colonial española).

**Implicación**: la distinción `archive_overlay` no es binaria. Algunos "overlays" tienen valor semántico legítimo.

### 4. Content filters introducen FAILs nuevos

**Cracovia**: blur agregó artefactos que dispararon safety filter de Azure sobre la imagen del gueto. Hay que documentarlo como limitación del scaffold.

---

## Decisión de diseño

Para benchmark de **razonamiento geo-investigativo** (no de OCR), **blur agresivo es correcto**:

> "El modelo NO puede leer el topónimo del archivo. Si no puede sin la trampa textual, eso es lo que mide el benchmark."

Aceptamos que algunas fotos quedan "muy difíciles" sin texto archivístico — es feature, no bug. Refleja la dificultad real de geolocalizar por evidencia visual pura.

**Pendiente**: documentar honestamente en el paper que ~45% del corpus tiene texto archivístico, y que sin blur el benchmark sería resoluble por OCR shortcut.

---

## Conclusión y next steps

- ✅ Pipeline detector + blur funciona end-to-end sobre 185 fotos
- ✅ Decisión de modelo: claude-sonnet-4-6 (sweet spot)
- ⏳ Integrar como **Paso 0.5** del pipeline corpus (después de `clean_image.py`, antes de `blacklist.py`)
- ⏳ Bump `CLEAN_VERSION=2` para invalidar caches y reflejar el nuevo step
- ⏳ Re-correr E009 cross-model sobre 185 con blur — esto es la corrida principal del paper

---

## Refs

- Script: `scripts/detect_text_overlays.py`
- Viewer comparativo modelos: `experiments/E011_text_overlay_detection/compare_3models.html`
- Output 185: `experiments/E011_text_overlay_detection/sample185_sonnet/`
- Ablation E010: `experiments/E010_iteration_pilot/results_gpt-5_4-mini_blurred.json`
