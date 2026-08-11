# E018 — análisis temporal descriptivo de creencias

> **Alcance:** este informe describe reportes elicitados, cambios observados y la acción posterior. No estima fuerza normativa de evidencia web, corrección bayesiana de una actualización ni efectos causales.

Generado determinísticamente por `python scripts/analyze_temporal_beliefs.py` a partir de los slim de E016.

## Inventario

Estado material: **179 corridas**, 89 belief-on, 90 belief-off, 371 reportes aceptados y 2 intentos rechazados.

| Modelo | Arm | Runs | Steps rango / media | Reportes | Reportes/run rango / media |
|---|---:|---:|---:|---:|---:|
| claude-opus-4-6 | off | 30 | 3–28 / 18.27 | 0 | 0–0 / 0.00 |
| claude-opus-4-6 | on | 29 | 3–30 / 20.24 | 134 | 1–7 / 4.62 |
| claude-sonnet-4-6 | off | 30 | 6–30 / 20.07 | 0 | 0–0 / 0.00 |
| claude-sonnet-4-6 | on | 30 | 6–30 / 22.20 | 146 | 1–7 / 4.87 |
| gpt-5.4-mini | off | 30 | 5–15 / 7.27 | 0 | 0–0 / 0.00 |
| gpt-5.4-mini | on | 30 | 4–17 / 10.60 | 91 | 1–6 / 3.03 |

Celdas faltantes contra la grilla observada: `[{"model": "claude-opus-4-6", "arm": "on", "cid": 963644, "run_idx": 1}]`.

## Timing de los reportes

Los checkpoints no son fijos. El agente puede reportar voluntariamente y el nudge se activa después de tres turns sin reporte.

- Separación agregada entre reportes: `{"2": 21, "3": 15, "4": 226, "5": 11, "6": 3, "7": 6}`.
- Submit menos último reporte: `{"0": 1, "1": 36, "2": 20, "3": 28, "4": 4}`.
- Reportes con una tool sustantiva coemitida en el mismo turn: **179**. Esa tool no se considera evidencia previa al reporte.

## Temprano / medio / tardío

Fases: early `step/steps_used ≤ 1/3`; middle `≤ 2/3`; late `> 2/3`. Cada métrica se promedia primero dentro de la corrida-fase. Top weight, entropía, masa regional y masa temporal muestran la media entre corridas; distancia muestra la mediana de las medias por corrida.
Si se excluyera el turn de submit del denominador, cambiarían de fase **21**/371 reportes: `{"early->middle": 3, "middle->late": 18}`.

| Modelo | Fase | Runs | Reports | Top weight | H loc. fija | Masa ≤500 km | Dist. top mediana | Masa fecha verdadera |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-4-6 | early | 24 | 33 | 0.638 | 0.438 | 0.685 | 1.3 km | 0.617 |
| claude-opus-4-6 | middle | 29 | 52 | 0.682 | 0.416 | 0.799 | 1.2 km | 0.525 |
| claude-opus-4-6 | late | 26 | 49 | 0.732 | 0.363 | 0.838 | 0.5 km | 0.584 |
| claude-sonnet-4-6 | early | 27 | 37 | 0.696 | 0.382 | 0.636 | 1.4 km | 0.648 |
| claude-sonnet-4-6 | middle | 30 | 54 | 0.697 | 0.410 | 0.720 | 1.0 km | 0.639 |
| claude-sonnet-4-6 | late | 29 | 55 | 0.758 | 0.347 | 0.740 | 0.6 km | 0.586 |
| gpt-5.4-mini | early | 28 | 35 | 0.398 | 0.749 | 0.271 | 1229.2 km | 0.435 |
| gpt-5.4-mini | middle | 25 | 30 | 0.552 | 0.661 | 0.446 | 447.6 km | 0.322 |
| gpt-5.4-mini | late | 23 | 26 | 0.605 | 0.608 | 0.401 | 630.0 km | 0.283 |

La entropía primaria es Shannon sobre candidatos explícitos más un único bin residual, dividida por `log(6)` —soporte máximo fijo: cinco candidatos más fondo—. No es entropía espacial y no incorpora radios. El JSON conserva además nats y la normalización exploratoria por soporte actual; esta última no se usa para firmar cambios porque K varía entre reportes.

## Contraste pareado early → late

Sólo entran corridas con al menos un reporte en ambas fases. Para cada corrida se calcula `media(late) − media(early)` y después se resumen esos deltas. Es una comparación descriptiva sobre una muestra seleccionada; con estos N no se hace inferencia estadística.

| Modelo | Pares | Δ top weight media / mediana | Δ masa ≤500 km | Δ masa fecha verdad | Δ H fija |
|---|---:|---:|---:|---:|---:|
| claude-opus-4-6 | 24 | 0.0797 / 0.0800 | 0.1471 / 0.0750 | -0.0191 / 0.0000 | -0.0592 / -0.0854 |
| claude-sonnet-4-6 | 27 | 0.0473 / 0.0200 | 0.0877 / 0.0550 | -0.0528 / 0.0000 | -0.0164 / 0.0102 |
| gpt-5.4-mini | 22 | 0.2002 / 0.1750 | 0.1052 / 0.0000 | -0.1711 / -0.1250 | -0.1459 / -0.1354 |

## Magnitud de cambios entre reportes

| Modelo | Transiciones | Salto top mediano | >100 km | mediana abs(Δ top weight) | mediana abs(ΔH) | Confianza sube | Entropía baja |
|---|---:|---:|---:|---:|---:|---:|---:|
| claude-opus-4-6 | 105 | 0.1 km | 15.2% | 0.070 | 0.072 | 51.4% | 52.4% |
| claude-sonnet-4-6 | 116 | 0.1 km | 13.8% | 0.050 | 0.055 | 49.1% | 49.1% |
| gpt-5.4-mini | 61 | 1.4 km | 31.1% | 0.100 | 0.083 | 80.3% | 75.4% |

## Generación y abandono de la región correcta

Definición principal: masa explícita positiva en un candidato cuyo centro está a ≤500 km del ground truth. `Ausente en último reporte` exige que apareciera antes y terminara con masa cero; es un proxy de abandono, no la creencia exacta al submit.

| Modelo | Runs | Alguna vez | Ya en primer reporte | Introducida después | Nunca | Ausente en último reporte |
|---|---:|---:|---:|---:|---:|---:|
| claude-opus-4-6 | 29 | 29 | 28 | 1 | 0 | 1/29 |
| claude-sonnet-4-6 | 30 | 28 | 26 | 2 | 2 | 2/28 |
| gpt-5.4-mini | 30 | 23 | 20 | 3 | 7 | 6/23 |

`Nunca` significa que la región no apareció en los checkpoints elicitados; no prueba que el modelo jamás la haya pensado. Los índices/steps de primera aparición y los casos introducidos tarde están en `analysis.json`.

Sensibilidad por umbral (`alguna vez / ausente en último reporte`):

- **claude-opus-4-6:** 25 km: 25/1; 100 km: 27/3; 250 km: 29/2; 500 km: 29/1; 1000 km: 29/0.
- **claude-sonnet-4-6:** 25 km: 25/4; 100 km: 27/3; 250 km: 28/4; 500 km: 28/2; 1000 km: 30/0.
- **gpt-5.4-mini:** 25 km: 17/7; 100 km: 17/7; 250 km: 22/8; 500 km: 23/6; 1000 km: 23/4.

## Acoplamiento con la siguiente acción

Se toma el set completo de acciones del primer turn sustantivo estrictamente posterior. Las columnas son multi-label: un mismo turn puede contener varias tool calls paralelas. `visual` incluye image search/pick/crops; `map_history` incluye geocode, mapas, Street View e historical query.

La separación crítica es temporal: en un checkpoint `report-only` no hay tool informativa/de investigación coemitida —submit no cuenta—; en `coemitted-tool`, el resultado de esa tool llega después del belief pero antes del siguiente turn. Sólo el primer estrato admite una lectura directa belief→acción; el segundo se conserva descriptivamente como belief→evidencia intermedia→acción.

| Estrato | Modelo | Reports | Web | Visual | Map/history | Submit | Sin acción |
|---|---|---:|---:|---:|---:|---:|---:|
| report_only | claude-opus-4-6 | 76 | 43 | 28 | 24 | 10 | 1 |
| report_only | claude-sonnet-4-6 | 27 | 15 | 7 | 9 | 8 | 0 |
| report_only | gpt-5.4-mini | 89 | 54 | 21 | 17 | 10 | 0 |
| coemitted_tool | claude-opus-4-6 | 58 | 33 | 23 | 20 | 3 | 0 |
| coemitted_tool | claude-sonnet-4-6 | 119 | 82 | 35 | 39 | 5 | 0 |
| coemitted_tool | gpt-5.4-mini | 2 | 2 | 0 | 1 | 0 | 0 |

### Parada tardía, estratificada

Cada celda es `submit en siguiente turn / checkpoints con siguiente acción`. No se combinan modelos; las celdas pequeñas —por ejemplo 1/1— no sostienen inferencia.

| Estrato | Modelo | Top weight ≥.8 | Top weight <.8 | Masa500 positiva | Masa500 cero |
|---|---|---:|---:|---:|---:|
| report_only | claude-opus-4-6 | 7/15 (46.7%) | 3/17 (17.6%) | 9/31 (29.0%) | 1/1 (100.0%) |
| report_only | claude-sonnet-4-6 | 6/12 (50.0%) | 2/5 (40.0%) | 8/16 (50.0%) | 0/1 (0.0%) |
| report_only | gpt-5.4-mini | 4/5 (80.0%) | 6/20 (30.0%) | 6/12 (50.0%) | 4/13 (30.8%) |
| coemitted_tool | claude-opus-4-6 | 1/6 (16.7%) | 0/10 (0.0%) | 1/16 (6.2%) | 0/0 (—) |
| coemitted_tool | claude-sonnet-4-6 | 3/11 (27.3%) | 2/27 (7.4%) | 4/31 (12.9%) | 1/7 (14.3%) |
| coemitted_tool | gpt-5.4-mini | 0/0 (—) | 0/1 (0.0%) | 0/1 (0.0%) | 0/0 (—) |

Hay 192 checkpoints report-only y 179 coemitted-tool. En sus siguientes turns, respectivamente, 113 y 130 contienen múltiples acciones; 54 y 64 mezclan categorías.
Acciones map/history con coordenadas tras report-only: 50 eventos en 36 reportes; tras coemitted-tool: 35 eventos en 31 reportes.

Incluso en report-only, estas tasas son asociaciones descriptivas: el tipo de checkpoint, la fase y la parada son decisiones endógenas del agente. No atribuyen fuerza a la evidencia ni efectos causales.

## Limitaciones

- E016 contiene sólo diez fotos y tres réplicas por celda; reportes y transiciones de una misma corrida no son observaciones independientes.
- Los checkpoints son autoelegidos y los modelos tienen distinta longitud de corrida; early/middle/late normaliza por steps_used, pero no iguala exposición a evidencia.
- La fase usa la duración final de una corrida endógena a la decisión de parar e incluye el turn de submit; se reporta cuántos reportes cambiarían al excluir ese turn.
- El contraste early-late está condicionado a corridas que tienen checkpoints en ambas fases. Es pareado y descriptivo, pero no representa todas las corridas ni autoriza inferencia con estos tamaños muestrales.
- El nudge para reportar creencias es una intervención. El brazo off no contiene una trayectoria latente comparable.
- La entropía discreta ignora radios geográficos y trata la masa no asignada como un único bin. La serie primaria usa Shannon en nats y normalización de soporte fijo; la normalización por soporte no nulo se conserva sólo como diagnóstico porque K cambia.
- La masa regional suma candidatos por distancia de su centro; 500 km es un umbral operativo arbitrario, por eso se reporta sensibilidad entre 25 y 1000 km.
- La masa temporal cuenta intervalos que solapan la verdad y por lo tanto favorece intervalos amplios; no es una densidad temporal ni una proper scoring rule.
- El último reporte no coincide con la creencia al submit en 88/89 corridas y una tool coemitida en el mismo turn todavía no había devuelto su resultado al agente. Por eso 'ausente al final' significa ausente en el último checkpoint observado.
- En checkpoints coemitidos, el resultado de la tool media entre belief y siguiente turn; no se interpreta como acoplamiento directo. En report-only la adyacencia es más limpia, pero sigue siendo observacional y no prueba causalidad ni valor informativo.
- Los slim preservan texto y metadata, pero no los píxeles base64 devueltos por crops, mapas y Street View; esos estímulos no pueden reauditarse bit a bit aquí.
- Las certificaciones de las diez fotos del piloto siguen en estado draft.
- Este análisis no modela likelihoods ni la fuerza normativa de evidencia web; no califica una actualización como correcta o incorrecta dado lo observado.

## Reproducción

```bash
python scripts/analyze_temporal_beliefs.py
```

Los hashes SHA-256 exactos de los seis inputs están en `analysis.json`.
