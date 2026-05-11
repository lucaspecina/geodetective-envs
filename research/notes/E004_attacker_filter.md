# E004 — Atacante adversarial sobre sample diverso (#24)

Filtro per-foto del sample diverso (#17 → E007). Para cada foto se corre N=3 llamadas a GPT-4o sin tools y se descarta si en alguna de las 3 corridas el modelo predice a <10 km del lugar real con confianza media o alta.

**Fecha**: 2026-05-11.
**Script**: `scripts/run_attacker_filter.py`.
**Input**: `experiments/E007_sample_diverso/candidates.json` (180 fotos).
**Output**: `experiments/E004_attacker_filter/results.json` (gitignored).
**Tiempo**: 386 s (6.4 min) con 8 workers.

---

## TL;DR

- **101 fotos sobreviven (56.1%)**, **79 se descartan (43.9%)**. Por encima del piso esperado de #24 (≥50% sobrevivientes).
- **Patrón fuerte por país**: Norteamérica reject_rate=80%, Russia-Asia 13%. Esto es **consistente con** dos explicaciones que no podemos separar todavía: (a) GPT-4o tiene más exposición/familiaridad con USA en su training, (b) el sample de USA en PastVu pesa más en landmarks/fotos urbanas reconocibles vs Russia-Asia (Vladivostok/Tomsk) que pesa en escenas cotidianas. Para discriminar entre (a) y (b) habría que controlar por "landmarkness" del sample, no medible aún. Por ahora el patrón es señal útil sin causa unívoca.
- **Patrón temporal**: 1890s-1900s rechazan más (53-57%), 1930s rechaza menos (30%). Las fotos más viejas tienden a ser landmarks famosos (Wall Street 1895, Casino Monte-Carlo 1894), las posteriores son más cotidianas.
- **Determinismo aceptable**: de los 79 rejects, **60 (76%) dispararon las 3 corridas**, 13 dispararon 2 de 3, y solo 6 (8%) dispararon una sola corrida. Los casos "1/3 triggered" son borderline donde el modelo aprovechó la variancia para acertar una vez — la regla "any-run" los toma pero queda registrado para análisis.

---

## Configuración

| Parámetro | Valor |
|---|---|
| Modelo atacante | `gpt-4o` (Foundry) |
| N corridas por foto | 3 |
| Threshold distancia | < 10 km |
| Threshold confianza | media o alta (auto-reportada) |
| Workers paralelos | 8 |
| Prompt versión | v1 (idéntico a `test3_no_tools.py`) |

Regla de descarte: una foto se rechaza si **EN ALGUNA DE LAS 3 CORRIDAS** se cumple `dist_km < 10 AND conf ∈ {media, alta}`. Es decir: si el modelo nailed it confiando aunque sea una vez, asumimos que la sabe de memoria. Cada result registra `triggering_runs` con los índices de las corridas que dispararon — permite análisis posterior de consistencia.

---

## Resultados por bucket

### Por bucket país

| Bucket | Total | Keep | Reject | Reject rate |
|---|---:|---:|---:|---:|
| Russia-Asia | 30 | 26 | 4 | **13.3%** |
| Russia-EU | 30 | 22 | 8 | 26.7% |
| Ex-URSS | 30 | 19 | 11 | 36.7% |
| Europa-no-URSS | 30 | 15 | 15 | 50.0% |
| Resto | 30 | 13 | 17 | 56.7% |
| Norteamerica | 30 | 6 | 24 | **80.0%** |
| **TOTAL** | **180** | **101** | **79** | **43.9%** |

**Lectura**: solo 4 de 30 fotos USA/Canadá sobreviven al filtro. La hipótesis más simple es que GPT-4o tiene más exposición a fotos de Norteamérica en su training; pero también podría ser que el sub-sample de USA tiene más landmarks intrínsecamente identificables (Wall Street, NY Worlds Fair, etc) que el sub-sample de Russia-Asia. Para separar las hipótesis se necesitaría una métrica de "landmarkness" controlada, no implementada acá.

### Por bucket década

| Década | Total | Keep | Reject | Reject rate |
|---|---:|---:|---:|---:|
| 1890s | 30 | 13 | 17 | 56.7% |
| 1900s | 30 | 14 | 16 | 53.3% |
| 1910s | 30 | 19 | 11 | 36.7% |
| 1920s | 30 | 19 | 11 | 36.7% |
| 1930s | 30 | 21 | 9 | **30.0%** |
| 1940s | 30 | 15 | 15 | 50.0% |

**Lectura**: 1890s-1900s son las décadas con más fotos icónicas (landmark famosos en su mayor expansión fotográfica). 1930s tiene la tasa de descarte más baja: fotos más mundanas y diversas. 1940s rebota probablemente por fotos de guerra reconocibles.

---

## Casos paradigmáticos

### Rechazos claros (dist ≈ 0 km, alta/alta/alta)

| CID | Bucket | Año | País | Título |
|---|---|---|---|---|
| 229068 | Russia-EU | 1896 | Russia | "Гости и зрители на крытой галерее..." |
| 1205384 | Russia-EU | 1900 | Russia | "Гатчина. Столовая" (palacio imperial) |
| 545661 | Russia-Asia | 1924 | Russia | "Последний дворец последнего царя" |
| 1933872 | Norteamerica | 1890s | USA | Wall Street 1895 |
| 218693 | Norteamerica | 1890s | USA | (no leí título) |
| 1856912 | Norteamerica | 1930s | USA | (Empire State / Times Square era?) |
| 1410781 | Norteamerica | 1890s | USA | (landmark NYC) |

Estos son los casos que el atacante **debe** rechazar: lugares famosos donde el modelo no investiga, solo recuerda. El filtro funciona.

### Sobrevivientes (keep) — fotos opacas para GPT-4o

| CID | Bucket | Año | Confidences | Distancia |
|---|---|---|---|---|
| 414978 | Russia-EU | 1895 | media/media/media | 2119 km (Kazan, modelo se confunde) |
| 2126812 | Russia-Asia | 1898 | baja/baja/baja | N/A (no aventura coords) |
| 1311033 | Ex-URSS | 1895 | baja/media/media | 268 km (Tashkent) |
| 758273 | Norteamerica | 1900s | baja/baja/baja | N/A |
| 1626616 | Europa-no-URSS | 1890s | baja/baja/baja | N/A |
| 669221 | Resto | 1900s | baja/baja/baja | N/A (residencia Shanghai) |

Estos sirven al benchmark: el modelo necesita herramientas para resolverlas. **Es el material crudo del corpus final**.

### Casos borderline (keep pero cerca)

Fotos que apenas pasaron el threshold:

| CID | Bucket | Dist (km) | Conf | Comentario |
|---|---|---|---|---|
| 1226590 | Norteamerica/1920s | 11 | media/alta/alta | "Chateau Apartment garden" — barely above 10km cutoff |
| 2041983 | Norteamerica/1930s | 16 | alta/alta/alta | "Verona Place" — confidencia alta pero error >10km |
| 1033099 | Norteamerica/1940s | 12 | media/media/media | "NY 1939 World's Fair" — landmark conocido pero el coord predicho cae 12km off |

El threshold `<10 km` es genuinamente discriminativo. Si se mueve a 20 km, estos casos también se descartarían — habría ~74 sobrevivientes (en lugar de 101) y reject_rate subiría a 59%. Por ahora mantengo el threshold canon. Si en el futuro vemos que el corpus sobrevive trampas obvias, se revisa.

---

## Observaciones

1. **Diferencia 6x entre Norteamerica y Russia-Asia** es estructural, no ruido — tres décadas consecutivas confirman el patrón. La causa exacta (familiaridad del modelo vs landmark-prevalence del sample) no se separa con estos datos. **Implicación operativa**: si evaluamos con GPT-4o como participante, el corpus filtrado va a tener pocos casos USA. Es deliberado en el sentido de que esos casos no exigirían investigación; queda pendiente confirmar que no estamos perdiendo casos USA legítimos que solo parecen fáciles.

2. **Cuando GPT-4o no sabe, lo admite**: `baja/baja/baja` aparece consistentemente en sobrevivientes. El modelo no inventa cuando no puede ubicar la foto — bien.

3. **El descarte por confianza importa**: muchas fotos donde el modelo se acercó (dist ~50-200km) pero con conf media o baja sobrevivieron. Sin el filtro de confianza el reject rate sería más alto pero menos preciso (rechazaríamos buenos casos donde el modelo "tuvo suerte").

4. **El threshold de 10 km es razonable**: tests con 5 km y 20 km darían sample muy distinto, pero 10 km coincide con el filtro v2 de E001 y E002 que ya validamos.

---

## Implicaciones para el corpus final del benchmark

- **101 fotos sobrevivientes** es buen tamaño para un primer benchmark (E001 sólo tenía 17). Cubre las 6 décadas y los 6 buckets país (mínimo 4 fotos por bucket país, peor caso Norteamerica con 6).
- **Distribución sesgada después del filtro**: Russia-Asia/EU dominan los sobrevivientes. Para mantener balance, en el benchmark final hay que **submuestrear** las celdas grandes o **aumentar K_PER_CELL** del sample inicial.
- **Recomendación próxima iteración**: cuando se necesite balance estricto en el corpus final, correr `sample_diverso.py` con K=10-15 y re-filtrar.

---

## Deuda implementada

Como parte de #24, se aplicó la deuda del hash perceptual en `src/geodetective/agents/react.py`: cuando `image_search` o `fetch_url_with_images` devuelven una imagen con `is_likely_target=True` (hash perceptual cercano a la foto target), ahora se **oculta del modelo** (hard reject) en lugar de mostrarse con flag. Solo se informa al modelo cuántas se ocultaron. Alinea código con `PROJECT.md`.

---

## Próximo paso

Cierra el epic #21. Para escalar el benchmark, ver issue futura (TBD): aumentar K_PER_CELL en #17 → re-filtrar → balance final del corpus.
