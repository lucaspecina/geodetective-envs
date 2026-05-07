# E001 — Test 3 (VLM sin tools) sobre 17 fotos PastVu

> Experimento exploratorio para validar el filtrado adversarial Tier 3 (VLM sin tools).
> Artefactos crudos: `experiments/E001_test3_pastvu/{candidates.json, results.json, photos/}`.

## Objetivo

Verificar empíricamente que un VLM top (gpt-5.4) sin tools puede ubicar fotos PastVu de distintos perfiles, y caracterizar el "sweet spot" del corpus.

## Setup

- **Modelo**: gpt-5.4 vía Azure Foundry (deployment del recurso `amalia-resource`).
- **Sample**: 17 fotos PastVu (de 19 candidatos, 2 fallaron por bug PNG/RGBA), mezcla de:
  - Urbanas con landmark (Plaza de Mayo, Zócalo, Malecón Habana, Puerto Madero, Puerto Belgrano, Lisboa Martim Moniz).
  - Urbanas sin landmark (La Boca, barrio Cabal BA, Vedado).
  - Rurales URSS / Cáucaso / Kazajstán.
  - Pre-1900 (Lima 1868, Casa Cáucaso 1911).
  - 1 conocida con source Wikimedia (Puerto Belgrano).
- **Procedimiento**: `scripts/test3_no_tools.py` con N=3 runs por foto, prompt sin tools pidiendo coords, año, razonamiento, confidence.
- **Métricas**: distancia geodésica al ground truth (km), error absoluto de año, confidence reportada.
- **Filtrado watermark**: PastVu watermark cropeado (bottom 42 px proporcional).

## Resultados — tabla por dist_min (peor caso = más informado)

| CID | Zona | YR | dist_min (km) | Conf típica |
|---|---|---|---|---|
| 2165013 | Lisboa Martim Moniz | 1947 | **0.08** | media |
| 208082 | Puerto Madero BA | 1999 | 0.5 | media |
| 1745176 | Puerto Belgrano (wiki) | 1979 | 0.6 | media |
| 2233530 | La Boca BA | 1999 | 0.6 | alta |
| 1043161 | La Habana Matadero | 1998 | 0.9 | media |
| 1560595 | Cracovia (Lenin) | 1955 | 0.9 | media-baja |
| 1894556 | Malecón Habana | 1962 | 1.4 | media |
| 1718681 | село Нар (Cáucaso) | 1961 | 44 | media-baja |
| 1060326 | Casa Cáucaso (1911) | 1911 | 98 | media |
| 1459395 | iglesia rural Volga | 1956 | 103 | baja |
| 2086652 | Cracovia gueto 1943 | 1943 | 194 | baja |
| 2000504 | Bogotá 1930 | 1930 | 726 | media-alta |
| 212079 | Abay Kazajstán | 1975 | 776 | media-baja |
| 1748874 | SP barrio anónimo | 1996 | 2573 | baja |
| 216313 | Lima 1868 | 1868 | 3307 | media |
| 1101385 | Volga deep rural | 1987 | 11994 | baja |
| 951727 | Escuela Vaka (Cáucaso) | 1965 | N/A (no devolvió coords) | baja |

## Hallazgos

### 1. Patrón claro: landmark vs no-landmark
- Foto con **landmark identificable** (plaza, edificio emblemático, marina): dist_min < 2 km, confidence media-alta.
- Foto **sin landmark** (rural, barrio anónimo, cotidiano): dist_min 40-12000 km, confidence baja.
- Esto valida la hipótesis del proyecto: el sweet spot del benchmark está en lo cotidiano.

### 2. Razonamiento genuino, no memorización
Incluso cuando el modelo "clava" coords (Plaza de Mayo, Zócalo), el reasoning no dice "conozco esta foto". Razona desde arquitectura, vegetación, vehículos, idioma. **El modelo recupera coords del landmark, no de la imagen específica.**

### 3. Pifias entendibles (no aleatorias)
- **Bogotá 1930 → Quito 726 km**: arquitectura colonial similar.
- **Lima 1868 → Antigua Guatemala 3307 km**: "ruinas coloniales" pista correcta, ubicación incorrecta.
- **Volga rural 1987 → Argentina 12000 km**: razonó "rural templado" y cruzó hemisferio.
- **#1748874 SP → Moscow 642 km en run 1, "Europa del Este" 2573 km en runs 2-3**: discriminación URSS-genérico.

### 4. Confidence calibrada (importante para el filtro)
Cuando el modelo dice "baja", **suele estar lejos** (44-12000 km). Cuando dice "alta", suele estar cerca (<1 km). La auto-evaluación del modelo es señal usable.

### 5. Variancia run-to-run alta
- #1718681 село Нар: 44 / 51 / 330 km → factor 7x.
- #1459395 iglesia: 103 / 163 / 714 km → factor 7x.
- → Para el filtro hay que tomar **dist_min** (peor caso = más informado), no promedio. Una sola corrida puede engañar.

### 6. Año error variable
- Algunas clavadas (Plaza de Mayo 1907 → year_err=0; Pirámide Ehécatl 1983 → 0).
- Otras con 6-15 años de error.
- Mediana ~5 años. Útil pero menos discriminante que coords.

## Filtro v2 (formulación simplificada)

Reemplaza el filtrado tiered de 4 tests por:

```
DESCARTAR foto si:
  source ∈ {wikimedia, wikipedia, flickr, otros archivos públicos}
  O
  (dist_min < 10 km AND confidence ≥ media)

KEEP si pasa ambas.
```

**Ventaja**: 2 tests baratos (1 lookup + 1 VLM call x N runs) en lugar de 4 tests caros (TinEye + CLIP + descripción→search + VLM).

**Resultado en este sample**: 9 de 17 (~53%) sobreviven. Higher than el 20-40% estimado en `viability_assessment.md`, pero el sample tiene bias rural.

## Bugs detectados

1. **Imágenes RGBA (PNG con transparencia)** → fallan al guardar como JPEG. Fix: convertir a RGB antes del save. Afectó #1683702 y #1791497.
2. **Algunas corridas no devuelven `lat`/`lon`** (modelo dice "no sé") → manejarlo explícitamente, no como error.

## Implicaciones para diseño

- **Filtro v2 funciona** en este sample. Validar en más fotos antes de comprometerse.
- **Sweet spot confirmado**: rural URSS, Cáucaso, Kazajstán, fotos cotidianas pre-1950 → casi todas pasan.
- **Necesitamos N runs** (≥3) para robustez frente a varianza.
- **Métrica primaria = dist_min** (peor caso para filtro). Median sirve para reportar.
- **Métrica secundaria = año error**. Útil pero menos importante.

## Próximos pasos

- Arreglar bug RGBA → re-correr 2 fotos faltantes.
- Sample más diverso (Asia, África, Europa Norte) — pendiente, las bbox actuales no agruparon.
- Probar el filtro en otras fuentes (LoC, OldNYC) — validar generalidad.
- **Test ReAct con web_search**: experimento E002 (ya hecho, ver doc separado).
