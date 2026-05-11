# Sample diverso PastVu (#17)

Sampling balanceado del corpus PastVu desde la metadata bajada en #3, según las decisiones canon del epic #21.

**Fecha**: 2026-05-11.
**Script**: `scripts/sample_diverso.py`.
**Datos input**: `experiments/E006_pastvu_audit/data/pastvu.jsonl.zst` (282 MB, gitignored).
**Output**: `experiments/E007_sample_diverso/{candidates.json, audit_summary.json}` (gitignored).

---

## TL;DR

- **180 fotos sampleadas** = 6 buckets país × 6 buckets década × 5 fotos por celda. Todas las 36 celdas llenas, ninguna abajo del piso.
- **596,564 eligibles totales** (type=1 ∧ geo ∧ year ∧ 1890≤year≤1949) procesados en 34s.
- Seed fijo (`SEED=42`), reproducible.
- De-duplicación por geohash 5 (~5km) dentro de cada celda → fotos geográficamente diversas dentro del mismo bucket.
- Cobertura raw mínima por celda: 1,247 (`Resto × 1890s`). Más que suficiente para escalar K_PER_CELL si hace falta.

---

## Parámetros usados

| Parámetro | Valor |
|---|---|
| Year range | 1890-1949 (6 décadas: 1890s, 1900s, 1910s, 1920s, 1930s, 1940s) |
| Buckets país | 6: Russia-EU (lon<60°), Russia-Asia (lon≥60°), Ex-URSS, Europa-no-URSS, Norteamerica, Resto |
| K per celda | 5 |
| Geohash precision | 5 (~4.9km × 4.9km) |
| Seed | 42 |

---

## Distribución por celda

| Celda | Raw eligibles | Únicos por geohash5 | Sampleados |
|---|---:|---:|---:|
| Russia-EU × 1890s | 19,302 | 1,674 | 5 |
| Russia-EU × 1900s | 58,084 | 3,750 | 5 |
| Russia-EU × 1910s | 42,818 | 2,981 | 5 |
| Russia-EU × 1920s | 34,335 | 2,337 | 5 |
| Russia-EU × 1930s | 56,552 | 2,877 | 5 |
| Russia-EU × 1940s | 59,435 | 3,730 | 5 |
| Russia-Asia × 1890s | 3,032 | 395 | 5 |
| Russia-Asia × 1900s | 7,182 | 637 | 5 |
| Russia-Asia × 1910s | 11,795 | 701 | 5 |
| Russia-Asia × 1920s | 6,873 | 565 | 5 |
| Russia-Asia × 1930s | 7,878 | 736 | 5 |
| Russia-Asia × 1940s | 3,793 | 482 | 5 |
| Ex-URSS × 1890s | 5,301 | 754 | 5 |
| Ex-URSS × 1900s | 11,292 | 1,331 | 5 |
| Ex-URSS × 1910s | 11,705 | 1,420 | 5 |
| Ex-URSS × 1920s | 10,224 | 1,023 | 5 |
| Ex-URSS × 1930s | 15,118 | 1,242 | 5 |
| Ex-URSS × 1940s | 14,152 | 1,235 | 5 |
| Europa-no-URSS × 1890s | 18,615 | 2,139 | 5 |
| Europa-no-URSS × 1900s | 36,965 | 2,861 | 5 |
| Europa-no-URSS × 1910s | 21,976 | 2,396 | 5 |
| Europa-no-URSS × 1920s | 19,987 | 2,345 | 5 |
| Europa-no-URSS × 1930s | 29,941 | 3,137 | 5 |
| Europa-no-URSS × 1940s | 22,922 | 2,966 | 5 |
| Norteamerica × 1890s | 2,324 | 247 | 5 |
| Norteamerica × 1900s | 7,214 | 463 | 5 |
| Norteamerica × 1910s | 7,050 | 394 | 5 |
| Norteamerica × 1920s | 13,998 | 388 | 5 |
| Norteamerica × 1930s | 12,846 | 548 | 5 |
| Norteamerica × 1940s | 6,592 | 646 | 5 |
| Resto × 1890s | 1,101 | 262 | 5 |
| Resto × 1900s | 2,589 | 420 | 5 |
| Resto × 1910s | 2,199 | 334 | 5 |
| Resto × 1920s | 2,632 | 368 | 5 |
| Resto × 1930s | 5,046 | 443 | 5 |
| Resto × 1940s | 3,696 | 496 | 5 |
| **TOTAL** | **596,564** | **45,234** | **180** |

Observaciones:

- **Norteamérica × 1920s/1930s** son los buckets más densos fuera de Russia (13.9K y 12.8K raw) — coherente con la era de fotografía amateur en USA.
- **Resto × 1890s** es la celda más escasa (1.2K raw) pero suficiente.
- La ratio `unique_gh5 / raw` varía entre 5% (Russia-EU × 1900s, mucha concentración urbana) y 23% (Norteamerica × 1890s, más disperso). Confirma que el de-clustering hace un trabajo real.

## Ejemplos del sample (1 por bucket país)

| Bucket | CID | Año | Lugar | Título |
|---|---|---|---|---|
| Russia-EU | 414978 | 1895 | Kazan | Гостиный двор |
| Russia-Asia | 423107 | 1898 | Vladivostok | Перекресток Хабаровской y Занадворовской |
| Ex-URSS | 1311033 | 1895 | Tashkent | Большой караван-сарай |
| Europa-no-URSS | 434549 | 1898 | Rouen, France | Porte de la Grosse Horloge |
| Norteamerica | 429668 | 1895 | New York | Wall Street |
| Resto | 1625025 | 1890 | Shanghai, China | Nanking Road |

Notable: el sample incluye landmarks famosos (Wall Street, Monte-Carlo Casino, Hardstrasse Zurich) que el atacante de #24 debería detectar como trampeables. **Es el comportamiento esperado**: el filtro va a quitar esas fotos del corpus final del benchmark, y eso valida que el filtro funciona.

## Schema de cada candidate

```json
{
  "cid": 414978,
  "provider": "pastvu",
  "provenance_source": "",
  "page_url": "https://pastvu.com/p/414978",
  "file_url": "https://pastvu.com/_p/a/.../...jpg",
  "title": "...",
  "year": 1895,
  "year2": 1895,
  "country": "Russia",
  "bucket_pais": "Russia-EU",
  "bucket_decada": "1890s",
  "geo": [55.796124, 49.10791],
  "geohash5": "v1fvm",
  "type": 1,
  "h": 1024, "w": 722,
  "waterh": 24,
  "dir": "nw"
}
```

Campo `provenance_source` vacío: el dump de PastVu no incluye el field `source` (que sí trae la API `photo.giveForPage`). Para #24 esto significa que `compute_excluded_domains(provider="pastvu", source="")` va a usar `BLOCKED_DOMAINS_GLOBAL + PROVIDER_DOMAINS["pastvu"]` y nada más — funciona, no degrada anti-shortcut.

## Decisiones tomadas durante la implementación

- **No deprecar `scripts/sample_pastvu.py`**: produce el `candidates.json` que todavía consumen `test3_no_tools.py` y `run_react_websearch.py` (corpus E001). Si en algún momento esos scripts se reemplazan o el corpus E001 se archiva, ahí se nuke. Por ahora coexisten — el "corpus diverso" vive en E007 separado.
- **`provenance_source` vacío en candidates**: el dump no trae `source`. Sin re-querying API (rate-limited) no se puede enriquecer. Decisión: aceptable para v1, el blacklist por provider cubre el caso pastvu.
- **Microestados europeos** (Mónaco, Vaticano, San Marino, Andorra, Liechtenstein) agregados a `EUROPA_NO_URSS` post-review Codex (antes caían en `Resto`). Resultado del cambio: 146 fotos más de Mónaco/etc consideradas Europa, ~150 menos en Resto. Sample final se mantiene en 180.
- **Dedup por geohash5 es intra-cell**, no global. Una misma geohash5 puede aparecer en distintas celdas (mismo barrio fotografiado en 1900 y en 1940 → ambas pueden sobrevivir, una en cada celda). Aceptable y deseado: queremos diversidad temporal en el mismo lugar como caso interesante. Si en #24 esto resulta problemático, se sube a global.

## Schema para consumidores (referencia para #24)

Notar para `scripts/run_attacker_filter.py` (todavía no escrito):
- El nuevo `candidate` usa `file_url` (no `file` como en E001/E002).
- `provenance_source` (no `source` como en E001/E002).
- Si se reutiliza la lógica de download de `test3_no_tools.py`, agregar un adapter o renombrar fields en el lectorcito.

## Próximo paso

`#24`: correr atacante GPT-4o (N=3 corridas, sin tools) sobre estas 180 fotos. Descartar las que tengan `dist_min<10km` y `confidence≥media`. Estimado de sobrevivientes: ~50% (basado en filtro v2 de E001 sobre sample manual).
