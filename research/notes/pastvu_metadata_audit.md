# PastVu metadata audit (#3)

Auditoría del dump completo de metadata de PastVu (`pastvu.jsonl.zst`, HF dataset `nyuuzyou/pastvu`).

**Fecha**: 2026-05-11.
**Comando**: `python scripts/audit_pastvu_metadata.py`.
**Datos**: `experiments/E006_pastvu_audit/data/pastvu.jsonl.zst` (282.5 MB, gitignored).
**Output crudo**: `experiments/E006_pastvu_audit/results.json` (gitignored).

---

## TL;DR

- **2.08M records** confirmados (genesis-intro decía "2M", correcto).
- **98% son fotos** (`type==1`), 2% otros tipos (`type==2`, probablemente grabados/pinturas).
- **Completitud altísima**: 97% tiene `geo`, 99.95% tiene `year`, 100% tiene `regions[0].country`.
- **Sesgo Rusia: 62%** del total (no 70-95% como afirmaba genesis-intro). Si ampliamos a ex-URSS: 74%. Confirmado pero menos extremo de lo esperado.
- **100% de las fotos tienen watermark** (`waterh > 0`). El módulo `clean_image` no es opcional, es obligatorio.
- **676,667 fotos elegibles** (`type==1` ∧ `has_geo` ∧ `has_year` ∧ 1850 ≤ year ≤ 1950). 32.5% del total. Más que suficiente para muestrear ≥80 fotos diversas.
- **Rango temporal real**: 1700-2000 (no 1860-2000 como decía la README). Pre-1850 son ~12K records, probablemente reproducciones de pinturas. Para fotografía propiamente dicha: 1850 en adelante.
- **No hay field directo urbano/rural** — decisión 2026-05-11 (user): NO derivarlo con heurísticas. Se suelta como dimensión de balance. País × década alcanza para v1.
- **Shards**: 2094 .tar shards confirmados (HF tiene 2097 archivos = 3 metadata + 2094 shards). Coincide con la README. La contradicción "47 shards / 14.7 GB" mencionada en `pastvu_deep_dive.md` debe referirse a otra snapshot o estaba mal.

---

## Volumen y tipos

| Métrica | Valor |
|---|---|
| Total records | 2,081,902 |
| `type==1` (foto) | 2,040,894 (98.0%) |
| `type==2` (otro) | 41,008 (2.0%) |

**Decisión**: filtrar `type==1` para el corpus.

## Completitud de campos clave

| Campo | Records | % |
|---|---|---|
| `geo` (lat, lon válidos) | 2,020,705 | 97.06% |
| `year` (1700-2030) | 2,080,770 | 99.95% |
| `regions[0].title_en` (país) | 2,081,902 | 100.00% |

**Decisión**: filtros base son baratos (97% sobrevive el filtro completo).

## Distribución temporal (todos los records)

| Década | Count |
|---|---|
| 1700s | 249 |
| 1710s-1840s | < 3K cada una (total ~8K) |
| 1850s | 5,205 |
| 1860s | 9,947 |
| 1870s | 11,983 |
| 1880s | 21,148 |
| 1890s | 53,487 |
| **1900s** | **129,335** |
| 1910s | 102,240 |
| 1920s | 93,083 |
| **1930s** | **133,547** |
| 1940s | 117,673 |
| 1950s | 218,630 |
| 1960s | 310,795 |
| 1970s | 364,830 |
| 1980s | 318,097 |
| 1990s | 165,597 |
| 2000s | 14,491 |

**Decisión para #17**: usar buckets `1890s / 1900s / 1910s / 1920s / 1930s / 1940s`. Pre-1890 es demasiado escaso para balancear (excepto curiosidad). 1950s en adelante queda fuera del foco del benchmark per `PROJECT.md` (queremos pre-fotografía-color masiva, pre-Instagram, pre-Google Street View ≈ 1950 corte natural).

## Distribución por país (top 20)

| País | Count | % del total |
|---|---|---|
| **Russia** | 1,295,206 | 62.21% |
| Ukraine | 124,202 | 5.97% |
| USA | 84,280 | 4.05% |
| Germany | 54,185 | 2.60% |
| France | 48,227 | 2.32% |
| Denmark | 43,551 | 2.09% |
| Netherlands | 37,052 | 1.78% |
| Czech Republic | 34,690 | 1.67% |
| Uzbekistan | 31,213 | 1.50% |
| Georgia | 27,600 | 1.33% |
| Italy | 25,009 | 1.20% |
| Belarus | 21,796 | 1.05% |
| UK | 21,689 | 1.04% |
| Switzerland | 21,515 | 1.03% |
| Latvia | 19,057 | 0.92% |
| Lithuania | 12,011 | 0.58% |
| Bulgaria | 11,632 | 0.56% |
| Sweden | 11,601 | 0.56% |
| Kazakhstan | 10,854 | 0.52% |
| Poland | 10,740 | 0.52% |

**Ex-URSS (Russia + Ukraine + Belarus + Georgia + Uzbekistan + Latvia + Lithuania + Kazakhstan)**: ~1.54M = 74%.

### Buckets de país/región propuestos para #17

| Bucket | Países | Aprox total |
|---|---|---|
| Russia (Europe) | Russia (filtrar por lon < 60° para excluir Siberia) | ~1.0-1.2M |
| Russia (Asia/Siberia) | Russia con lon ≥ 60° | ~100-300K |
| Ex-URSS (no Russia) | Ukraine, Belarus, Georgia, Uzbekistan, Latvia, Lithuania, Kazakhstan, Armenia, Azerbaijan, Moldova, Estonia, Tajikistan, Kyrgyzstan, Turkmenistan | ~250K |
| Europa Occidental | Germany, France, Denmark, Netherlands, Italy, UK, Switzerland, Sweden, Spain, etc. | ~280K |
| Europa Central/Este (no ex-URSS) | Czech, Poland, Hungary, Romania, Bulgaria, etc. | ~80K |
| Norteamérica | USA, Canada | ~95K |
| Resto del mundo | Asia (excl. ex-URSS), África, Sudamérica, Oceanía | < 50K |

**Decisión a tomar**: ¿bucketear con esta granularidad (7 buckets) o más simple (4: Russia / Ex-URSS / Europa / Resto)? Sugerencia: empezar con 4-5 buckets y submuestrear los grandes para que no aplasten a los chicos. Detalle en #17.

## Watermarks — CRÍTICO

| Métrica | Valor |
|---|---|
| `waterh > 0` | 2,081,900 (100.00%) |
| Heights más comunes | 14px (272K), 19px (104K), 16px (85K), 15px (75K), 18px (72K), 24px (67K), 17px (61K), 25px (61K) |

**100% de las fotos tienen watermark.** El módulo `clean_image` (#22) es obligatorio en el pipeline, no opcional. Bien que ya esté implementado y cubra esto por provider.

## Corpus elegible para el benchmark

Criterio: `type==1` ∧ `geo válido` ∧ `year válido` ∧ `1850 ≤ year ≤ 1950`.

| Métrica | Valor |
|---|---|
| Total elegibles | **676,667** |
| % del corpus completo | 32.5% |

Más que suficiente para muestrear ≥80 fotos diversas (#17). Si filtramos también por trampeable (#24), incluso si descartamos 50% del sample, queda margen amplio.

## Cross-tab país × década (pre-1950, type=1, geo+year)

Top 5 países:

| País | 1890s | 1900s | 1910s | 1920s | 1930s | 1940s |
|---|---|---|---|---|---|---|
| Russia | 22K | 65K | 55K | 41K | 64K | 63K |
| Ukraine | 1.9K | 4.4K | 4.7K | 2.7K | 4.9K | 7.7K |
| USA | 2.2K | 7.0K | 6.9K | 13.9K | 12.7K | 6.4K |
| Germany | 3.2K | 5.8K | 3.0K | 2.1K | 3.5K | 3.3K |
| France | 3.3K | 11.1K | 4.6K | 3.2K | 2.4K | 3.3K |

Russia domina todas las décadas excepto USA 1920s/1930s. Para balance #17 hay que sub-samplear Russia o sobre-samplear el resto.

Países secundarios escasean en algunas combinaciones (ej. Switzerland 1940s = 321, Uzbekistan 1940s = 809). El balance multi-dimensional va a tener cells chicas — aceptable, se reporta abajo del piso esperado.

## Urbano vs rural — SOLTADO

PastVu metadata no incluye una clasificación urbano/rural directa. Las opciones para derivarla (profundidad de `regions[]`, proximidad a OSM urbano, regex sobre título/descripción) son todas frágiles y requerirían validación manual.

**Decisión 2026-05-11 (user)**: soltar urbano/rural como dimensión de balance. País × década alcanza para v1. Si más adelante hace falta, se reabre. Distribución de `regions` depth queda registrada abajo por si vuelve.

| `len(regions)` | Records | Lectura |
|---|---|---|
| 1 | 19,274 | 0.9% — solo país, datos pobres |
| 2 | 143,343 | 6.9% — país + región grande |
| 3 | 792,666 | 38.1% — modal-ish |
| 4 | 909,804 | 43.7% — modal |
| 5 | 175,691 | 8.4% — granularidad alta |
| 6 | 41,124 | 2.0% — granularidad máxima |

Profundidad 3-4 cubre 82% del corpus → señal urbano/rural ahí adentro sería muy ruidosa.

## Discrepancias detectadas (afirmaciones previas vs realidad)

| Afirmación previa | Realidad | Veredicto |
|---|---|---|
| 70-95% Russia (genesis-intro) | 62% Russia, 74% ex-URSS | Sesgo confirmado, pero menos extremo |
| 1.8 TB / 2094 shards (README HF) | 2094 .tar shards confirmados (2097 archivos − 3 metadata) | Confirmado |
| 47 shards / 14.7 GB (pastvu_deep_dive) | No coincide con HF actual | Snapshot vieja o error en la nota |
| ~2M records | 2.08M | Confirmado |
| Watermark "en algunas fotos" | 100% de las fotos tienen `waterh > 0` | Más severo de lo esperado |

## Campos extra auditados (round 2, post-feedback Codex)

| Campo | Cobertura | Lectura |
|---|---|---|
| `s` (status) | 100% con valor `5` | Useless para filtrar — todos los records están aprobados |
| `dir` (dirección cámara) | 92% (1.91M) | Útil para tasks futuras tipo "predict heading" |
| `title` | 100% | Disponible si querés contaminar contexto o usarlo como hint |
| `desc` | 44% | Texto descriptivo, parcial |
| `user.login` | 100% | Uploader (no fotógrafo original) |
| `year2 != year` | 41% (857K) | Rango de incertidumbre temporal, no punto. Usar `year` + `year2` para reportar bandas |
| Resolución (max(w,h)) | large ≥1600px: 51%, medium 800-1600: 43%, small 400-800: 6% | Calidad alta. No hay basura tiny |

## Decisiones para #17

1. **Pre-filtro base**: `type==1` ∧ `geo` ∧ `year` ∧ `1850 ≤ year ≤ 1950` → ~677K candidatos.
2. **Buckets primarios país/región**: 6 buckets — `Russia-Europa` (lon<60°) / `Russia-Asia` (lon≥60°) / `Ex-URSS` (Ukraine, Belarus, Georgia, Uzbekistan, Latvia, Lithuania, Kazakhstan, Armenia, Azerbaijan, Moldova, Estonia, Tajikistan, Kyrgyzstan, Turkmenistan) / `Europa no-URSS` / `Norteamérica` (USA, Canada) / `Resto`. Refinamiento Codex: USA tiene masa suficiente para bucket aparte.
3. **Buckets temporales**: 6 (1890s, 1900s, 1910s, 1920s, 1930s, 1940s). Pre-1890 fuera (escaso).
4. **Urbano/rural**: dropeado. País × década alcanza para v1.
5. **De-clustering**: geohash precisión 5 (~5km), máximo 1 foto por celda. En ciudades densas considerar geohash 6 si el balance lo necesita (Codex).
6. **Sample size objetivo**: 100-200 fotos balanceadas. Aceptable ≥80 después de de-clustering.

## Próximos pasos

- Cerrar #3.
- Arrancar #17 con las decisiones de arriba pre-cargadas. Estimado: 1 sesión.
- Después #24.
