# GeoDetective Envs — Arquitectura

> **Status**: CANON (creado 2026-05-14). Documenta contratos entre módulos + principio de storage (canon vs derived).
>
> Visión y por qué: `PROJECT.md`. Estado actual qué corre: `CURRENT_STATE.md`. Historial: `CHANGELOG.md`.

---

## Principio central: storage-as-canon, reports-as-derived

Toda ejecución (corrida del agente, anotación, smoke test) guarda **un JSON estructurado** con toda la información del run. Los reportes HTML son **vistas derivadas, regenerables**, que leen esos JSONs.

```
EJECUCIÓN                          STORAGE (canon)                       VISTAS (derivadas)
─────────                          ──────────────                        ─────────────────
scripts/run_multimodel_pilot.py    experiments/E009_multimodel/          scripts/build_multimodel_report.py
  ↓                                  results_{model}.json (×N)             → report_multimodel.html
                                     agentic_probe.json                  scripts/build_multimodel_full_report.py
                                                                           → report_multimodel_full.html

scripts/run_annotator.py           experiments/E005_react_pilot/         (futuro: scripts/build_annotator_report.py)
  ↓                                  annotated_{prompt}.json               → report_annotated.html
```

**Invariante**: el JSON contiene **toda la información** necesaria para reconstruir cualquier reporte. Borrar reports y regenerar = mismo output. Reports nunca son la fuente de verdad.

**Implicación**:
- Agregar un reporte nuevo = leer los JSONs existentes. NO requiere re-correr el agente.
- Múltiples reportes pueden coexistir sobre los mismos datos.
- Resume support: si `results_{model}.json` ya tiene fotos hechas, el pilot script saltea.

---

## Módulos y contratos

### `src/geodetective/corpus/`

Pipeline de preparación del corpus, anti-shortcut.

| Módulo | Input | Output | Invariante |
|---|---|---|---|
| `clean_image.py` | foto raw + provider_meta | `experiments/.../photos/{cid}_clean_v{N}.jpg` + `CleanResult` (action, crop_px, notes) | Strip EXIF + crop watermark + RGBA→RGB. Versionado por `CLEAN_VERSION`. |
| `blacklist.py` | provider + provenance_source | `excluded_domains: set[str]` | Per-photo runtime, no global. Combina GLOBAL minimal + PROVIDER_DOMAINS + extracción de hosts del source. |

### `src/geodetective/tools/` (12 tools)

Cada tool es una función pura con TOOL_SCHEMA (OpenAI function-calling format) + impl + dataclass de resultado.

| Tool | Backend | Resultado |
|---|---|---|
| `web_search` | Azure Responses API + Bing Grounding | `WebSearchResult(results, blocked_count, total_raw)` |
| `fetch_url` / `fetch_url_with_images` | httpx + bs4 + imagehash | `FetchResult(title, text, images[], status_code)` |
| `image_search` | DuckDuckGo (ddgs) + imagehash | `ImageSearchResult(images[], target_match_count, blocked_domain_count)` |
| `geocode` / `reverse_geocode` | Nominatim OSM | `GeocodeResult(lat, lon, display_name, type)` |
| `historical_query` | OpenHistoricalMap Overpass | `HistoricalQueryResult(features[], n_features)` |
| `crop_image` / `crop_image_relative` | PIL local | `CropResult(width, height, region, base64_jpeg)` |
| `static_map` | Google Maps Static | `StaticMapResult(lat, lon, zoom, type, base64_jpeg)` |
| `street_view` | Google Street View Static | `StreetViewResult(images[], panorama_id, pano_date)` |

**Contrato clave**: cada tool acepta `excluded_domains` y rechequea URLs post-redirect. Imágenes con `is_likely_target=True` (hash perceptual match con foto target) son **hard reject** — ni bytes ni URL al modelo.

### `src/geodetective/llm_adapter.py`

Ruteo OpenAI vs Anthropic vía MODEL_SPECS registry.

| Componente | Contrato |
|---|---|
| `MODEL_SPECS` | dict `{model: {provider, vision, tools}}`. 21 modelos hoy. Default conservador si no está en registry. |
| `complete(model, messages, tools, **kwargs)` | Una sola entry point. OpenAI = passthrough cliente openai (no regresión). Anthropic = httpx POST a `/anthropic/v1/messages` con format translation. |
| `to_anthropic_messages` | OpenAI format → Anthropic. Fusiona consecutivos same-role (strict alternation), traduce image_url → image base64 source, tool calls → content blocks, tool messages → user con tool_result blocks. |
| `parse_anthropic_response` | Anthropic content array → AdapterResponse con shape OpenAI-compatible (`.choices[0].message.{content, tool_calls, thinking_blocks}`). |

**Invariante**: response.choices[0].message.content / .tool_calls / .tool_calls[i].id / .function.name / .function.arguments funciona idéntico para ambos providers. react.py no diferencia.

### `src/geodetective/agents/react.py`

ReAct loop multi-paso. Single entry: `run_react_agent(image_path, model, max_steps, ...) → ReActResult`.

**Output `ReActResult`**:
- `final_answer: dict | None` — submit_answer args si llegó
- `trace: list[dict]` — eventos por step (thinking, tool calls, tool results con metadata, submits, errors)
- counts por tool (`web_search_count`, etc.)
- `submit_called: bool`, `terminal_state: str` (`submitted` / `max_steps_no_submit` / `empty_response` / `api_error` / `invalid_submit` / `no_submit_early_text`)

**Anti-shortcut runtime**: hash perceptual hard reject implementado en handlers de `image_search` y `fetch_url_with_images`.

### `src/geodetective/judge/`

Process eval annotator (CORRAL adaptado). Off-line, no entra en runtime del agente.

| Componente | Contrato |
|---|---|
| `serialize_trace.serialize_trace(trace, ...)` | Trace ReAct → texto numerado `[MSG N]` con T y E separados. **Blind judge**: NO incluye ground_truth/final_answer/distance. |
| `prompts.STAGE1_*` | System + user para extracción de nodes H/T/E/J/U/C con grounding verbatim. |
| `prompts.STAGE2_*` | Para extracción de edges (testing/observing/informs/contradicting/competing/updating). |
| `annotator.annotate_trace(...)` | Orquesta Stage 1+2 vía llm_adapter (temperature=0) + Stage 3a deterministic. Devuelve `AnnotatorResult` con graph + patterns_structural. |
| `pattern_matcher.detect_patterns_structural(nodes, edges)` | 8 productive motifs + 8 breakdowns + 1 neutral, definidos sobre estructura del grafo. Patterns normativos (proxy_substitution, tool_channel_mismatch) deferidos a Stage 3b LLM-judge multimodal. |

---

## Schemas de storage

### `results_{model}.json` (cross-model run)

Lista de entries. Cada entry:

```jsonc
{
  // candidate metadata (del corpus filtrado)
  "cid": 2126812,
  "geo": [56.47, 84.95],
  "year": 1898,
  "country": "Russia",
  "bucket_pais": "Russia-Asia",
  "bucket_decada": "1890s",
  "title": "...",
  "provider": "pastvu",
  "provenance_source": "",
  "file_url": "https://pastvu.com/...",
  // ... otros campos del audit

  // run-specific
  "react": {
    "model": "claude-opus-4-6",
    "max_steps": 30,
    "prompt_version": "v3_thinking_visible",
    "elapsed_seconds": 220.0,
    "submit_called": true,
    "terminal_state": "submitted",
    "steps_used": 25,
    "final_answer": {
      "location": "...", "lat": ..., "lon": ..., "year": "...",
      "confidence": "...", "reasoning": "...",
      "visual_clues": [...], "external_evidence": [...],
      "rejected_alternatives": [...], "verification_checks": [...],
      "uncertainty_reason": "..."
    },
    "distance_km": 1930.5,
    "year_error": 5,
    // counts por tool
    "web_search_count": 11, "fetch_url_count": 2, "image_search_count": 3,
    "geocode_count": 4, "historical_query_count": 0,
    "crop_count": 4, "static_map_count": 0, "street_view_count": 0,
    "target_match_count": 0,
    "trace": [
      { "step": 1, "type": "thinking", "content": "..." },
      { "step": 1, "type": "crop_image_relative", "region": {...} },
      { "step": 2, "type": "web_search", "query": "...", "top_results": [...] },
      { "step": 3, "type": "image_search", "n_images": 5,
        "visible_images": [{"url": "...", "hamming_distance": ..., "base64_jpeg": "..."}] },
      { "step": 4, "type": "static_map", "lat": ..., "lon": ..., "base64_jpeg": "..." },
      { "step": 5, "type": "street_view", "n_images": 4, "images": [{"heading": ..., "base64_jpeg": "..."}] },
      { "step": 5, "type": "submit", "answer": {...} }
    ]
  }
}
```

**Notas**:
- `trace` incluye base64_jpeg de imágenes visuales (crops, static_map, street_view, image_search results). Eso explica tamaños de 7-10 MB por modelo.
- Resume support en `run_multimodel_pilot.py`: si `react.final_answer` o `react.error` ya existe, salteamos.

### `annotated_{prompt}.json`

Lista de `AnnotatorResult` (uno por trace):

```jsonc
{
  "trace_id": "{cid}_{prompt_version}_{model}",
  "cid": ..., "model": ..., "prompt_version": ..., "judge_model": ...,
  "graph": {
    "nodes": [
      { "node_id": "N1", "type": "H", "modality": null, "time": 2,
        "terminal": false, "text": "...",
        "support": [{"msg_idx": 2, "quote": "..."}] }
    ],
    "edges": [
      { "src": "N1", "dst": "T1", "relation": "testing", "time": 4,
        "support": [{"msg_idx": 4, "quote": "..."}] }
    ]
  },
  "patterns_structural": {
    "productive": { "evidence_led_hypothesis": {"present": true, "nodes": [...]}, ... },
    "breakdowns": { "untested_claim": {"present": false, "nodes": []}, ... },
    "neutral": { "fixed_hypothesis_test_tuning": {...} },
    "n_nodes": 73, "n_edges": 74,
    "nodes_by_type": {"H": 5, "T": 28, ...}
  },
  "raw_stage1": {...}, "raw_stage2": {...},
  "elapsed_seconds": 224.6,
  "error": null
}
```

---

## Cómo agregar un reporte nuevo

Patrón:

```python
# scripts/build_my_new_report.py
import json, sys, os
from pathlib import Path

EXP = Path(sys.argv[1] if len(sys.argv) > 1 else "experiments/E009_multimodel")
data_by_model = {}
for p in EXP.glob("results_*.json"):
    model = p.stem.replace("results_", "")
    data_by_model[model] = json.loads(p.read_text(encoding="utf-8"))

# ... transformar data ...

out = EXP / "report_xxx.html"
out.write_text(html_str, encoding="utf-8")
```

**Convenciones**:
- Path del experimento por CLI arg `sys.argv[1]` o env var `EXP_DIR`. NO hardcode.
- Lectura/escritura SIEMPRE con `encoding="utf-8"` (Windows cp1252 rompe Cyrillic/CJK).
- Output va al mismo directorio que los datos (`EXP / "report_*.html"`).
- Imagenes embebidas como `data:image/jpeg;base64,...` — sin links externos.

---

## Versionado de schema

Hoy informal: `CLEAN_VERSION` para imágenes, `PROMPT_VERSION` en metadata del trace. **Deuda**: no hay un `SCHEMA_VERSION` formal en los JSONs. Si cambiamos el shape, reports viejos pueden romper silenciosamente.

**Convención mientras**: cuando se modifica el schema de `react.trace[]` o `final_answer`:
1. Actualizar este doc.
2. Mencionar en `CHANGELOG.md` con etiqueta `[schema]`.
3. Re-ejecutar reports sobre datos viejos para validar compatibility.

---

## Lo que NO está automatizado (deuda)

- **Auto-regen de reports** al detectar cambio de `results_*.json`. Hoy hay que correr el `build_*_report.py` a mano.
- **Schema version field** en los JSONs.
- **Index global de experimentos**: no hay un meta-report que liste E001…E009 con summary.
- **Validación post-LLM del annotator**: hoy aceptamos cualquier JSON parseable de Claude judge. Codex review flag — ver `process_eval_design.md` deudas.
- **Multimodal judge** (Stage 3b): annotator hoy es text-only, no anota patterns que requieren ver imágenes (visual_hallucination, multi_modal_cross_validation).

---

## Referencias cruzadas

- `PROJECT.md` — visión, LA PREGUNTA, invariantes (especialmente invariante 4 sobre reward vs process_score).
- `CURRENT_STATE.md` — qué corre hoy, estado de cada experimento.
- `research/synthesis/process_eval_design.md` — diseño completo del annotator y patterns CORRAL.
- `research/synthesis/findings_so_far.md` — resultados experimentales.
- `CHANGELOG.md` — historial con todas las decisiones de arquitectura.
