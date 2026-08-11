# Discusión 2026-08-11 — actualización de creencias, acciones y vicios investigativos

> **Estado: EXPLORATORIO.** Esta nota conserva una conversación y sus hipótesis para retomarlas en otra sesión. No redefine el paper, no reemplaza el pivote de julio y no registra decisiones cerradas.
>
> **Pregunta que motivó la discusión:** dado que GeoDetective conoce la verdad, elicita distribuciones de creencia durante la investigación y observa todas las acciones, ¿podemos estudiar no solo qué vicios aparecen sino dónde se rompe la investigación y qué intervención mínima habría cambiado su trayectoria?

## 1. Intuición central que apareció

GeoDetective observa una cadena que pocos benchmarks observan completa:

```text
evidencia disponible
    → evidencia buscada/observada
    → creencia reportada
    → siguiente acción o verificación
    → decisión de continuar/parar
    → respuesta final y citas
```

La idea no es abandonar el **censo de vicios**. Es organizarlo mejor:

- Los vicios son los patrones de falla que vemos en las trazas.
- La posición de la ruptura en esta cadena ayuda a describir el mecanismo.
- Una intervención controlada puede mostrar si esa ruptura causó el curso posterior.

Ejemplo: “se aferró a la hipótesis equivocada” puede esconder fallas diferentes:

1. La hipótesis correcta nunca entró en su repertorio.
2. No buscó la evidencia que podía discriminarla.
3. Encontró la evidencia, pero la creencia reportada no cambió.
4. La creencia cambió, pero la siguiente acción no la acompañó.
5. Cambió de curso, pero paró antes de verificar.

Las trazas naturales permiten descubrir estas firmas. Por sí solas no siempre prueban el “por qué”; los forks/intervenciones sirven para identificarlo mejor.

## 2. El antecedente que más resonó: *Broken Links*

Paper: [Why Do LLMs Struggle in Strategic Play? Broken Links Between Observations, Beliefs, and Actions](https://arxiv.org/abs/2605.00226) (Sobotka, Karabag y Topcu, 2026).

### Qué encuentra

En interacciones estratégicas simples, los modelos empiezan actualizando sus creencias de manera razonable, pero incorporan progresivamente menos la evidencia nueva.

El caso más limpio es un juego repetido con dos tipos posibles de oponente. Cada tipo tiene una política fija y conocida sobre dos acciones. Como se conoce `P(acción | tipo)`, para cada observación se conoce exactamente el cambio bayesiano esperado:

```text
cambio esperado en log-odds = log P(observación | A) / P(observación | B)
```

Ejemplo intuitivo: si “rojo” ocurre con probabilidad 0.8 bajo A y 0.2 bajo B, observar rojo debería multiplicar por cuatro las odds a favor de A.

El paper mide la distribución antes y después de cada observación de dos maneras:

- **Creencia verbal:** le pide al modelo una distribución explícita.
- **“Creencia interna”:** entrena un probe lineal sobre activaciones de modelos open-weight. Es un sensor aprendido, no acceso literal a una creencia mental.

Luego compara el cambio observado con el esperado:

- **BCC:** correlación entre ambos; mide si las actualizaciones siguen la dirección/patrón bayesiano.
- **Pendiente:** mide magnitud. `1` sería actualización proporcional; una pendiente baja indica subactualización.

En el ejemplo principal de Llama 3.1 70B, la pendiente pasa aproximadamente de `1.07` en la ronda 1 a `0.28` en la ronda 10; el BCC cae de `0.85` a `0.38`. Las historias llegan hasta 30 rondas, aunque el análisis más explícito usa rondas 1–5 y 10. Poker tiene hasta 3 rondas de apuestas y Chameleon hasta 4 pistas.

### Qué tan “clean” es realmente

- **Muy limpio en el juego repetido:** dos hipótesis, política generadora conocida, tipo aleatorizado y observaciones simples.
- **Menos limpio en Poker y Chameleon:** la fuerza esperada de la evidencia se estima usando las probabilidades contrafactuales del propio LLM oponente.
- El paper dice que el deterioro aparece con contexto corto, pero no reporta un conteo exacto de tokens.
- No separa causalmente si el deterioro viene de cantidad de turnos, volumen de contexto, acumulación de compromisos, confianza previa o memoria/posición.

Ese último punto parece una oportunidad fuerte para GeoDetective.

## 3. Qué podríamos medir nosotros

### A. Modo natural: dejar investigar

El agente elige qué buscar, qué herramienta usar, cómo actualizar y cuándo parar. Esto conserva la realidad ecológica del benchmark y permite:

- Descubrir vicios no anticipados.
- Medir si alguna vez consideró la región/época correcta.
- Localizar firmas de ruptura en la cadena evidencia → creencia → acción → parada.
- Preguntar si la receptividad aparente a evidencia disminuye entre etapas tempranas, medias y tardías.
- Relacionar esas firmas con recuperación, abandono de una hipótesis correcta y resultado final.

Limitación: en web abierta normalmente **no conocemos cuánto debería mover una fuente concreta**. Conocer la verdad ex post no alcanza para asignarle una fuerza normativa a la evidencia. Las fuentes están seleccionadas por el propio agente, pueden estar correlacionadas y tienen confiabilidad incierta. Acá corresponde hablar de asociación, dirección o responsividad, no de actualización bayesiana exacta.

### B. Modo intervenido: medir limpio y después soltar

Congelar prefijos de investigaciones reales e introducir una señal cuya confiabilidad y mecanismo generador sean conocidos. Elicitar creencia justo antes y después; luego dejar que el agente continúe libremente.

Medir cuatro eslabones:

1. **Creencia:** cuánto incorpora de la actualización esperada.
2. **Acción:** si la próxima búsqueda/verificación es coherente con la nueva distribución.
3. **Parada:** si la evidencia cambia apropiadamente continuar vs entregar.
4. **Consecuencia:** si corrige, se recupera o empeora el resultado final.

La intervención es un instrumento de diagnóstico dentro de una investigación, no un reemplazo de la conducta libre.

### Intervención temporal que parece especialmente prometedora

Dar una señal de **igual fuerza conocida** en puntos tempranos, medios y tardíos. Pregunta:

> ¿El agente se vuelve menos sensible a la misma evidencia a medida que avanza una investigación real?

Para distinguir explicaciones, idealmente variar por separado:

- Número de pasos, manteniendo el contexto compacto mediante un resumen controlado.
- Volumen de tokens/contexto, manteniendo similar el número de decisiones.
- Cantidad de reportes/compromisos previos con una hipótesis.
- Confianza previa, manteniendo fija la fuerza de la nueva señal.

Esto podría separar “contexto largo” de “profundidad temporal/compromiso”. *Broken Links* muestra la degradación, pero no resuelve esa causa.

### Forma mínima posible

- Reducir el checkpoint a dos candidatos explícitos A/B.
- Declarar al agente la confiabilidad del canal (si no la conoce, no existe una actualización normativa exigible).
- Usar señales equivalentes en formato y saliencia:
  - diagnóstica a favor de A;
  - diagnóstica a favor de B;
  - placebo con likelihood ratio 1;
  - opcionalmente señal repetida para medir double-counting.
- Comparar el cambio en log-odds con el `log likelihood ratio` conocido.
- Repetir la misma familia de señales temprano/medio/tarde.
- Después del reporte, permitir nuevamente tool use y parada libres.

El probe P1(ii) existente, con canal declarado de 55% y `LR` conocido, parece un punto de partida reutilizable; todavía no se decidió si será el diseño final.

## 4. “¿Qué intervención mínima habría cambiado la trayectoria?”

Esta pregunta puede operacionalizarse con forks desde un mismo prefijo:

- Rama natural: continúa sin intervención.
- Rama evidencia: recibe una pieza diagnóstica mínima.
- Rama placebo: recibe una pieza igual de saliente pero no informativa.
- Opcionalmente, rama de acción: se le ofrece/ejecuta una herramienta que no eligió y luego vuelve a actuar libremente.

Se busca la intervención más pequeña que cambie un resultado relevante: generar la hipótesis correcta, mover la creencia, elegir una verificación discriminante, evitar parar o corregir la respuesta.

No conviene llamar automáticamente a esto “mundo gemelo”. Dos forks con evidencia fabricada pueden medir obediencia a una inyección. Para el claim más fuerte harían falta pares de casos reales homologados con evidencia auténtica que lleve a conclusiones opuestas. Si se usan forks, describirlos honestamente como **evidence forks**.

## 5. Cómo encaja con el censo de vicios

La dirección tentativa sería conservar dos motores:

- **Exploratorio/natural:** descubre vicios y muestra cómo se ven en investigaciones reales.
- **Confirmatorio/intervenido:** toma unas pocas firmas importantes y prueba su mecanismo en datos separados.

Una organización posible de los vicios por eslabón:

| Eslabón | Ejemplos de firma de falla |
|---|---|
| Generación de hipótesis | La región correcta nunca aparece |
| Adquisición | No busca la observación que discrimina candidatos |
| Interpretación/actualización | Ignora falsificación, sobrerreacciona a confirmación, se mueve ante placebo |
| Creencia → acción | Reporta cambio pero continúa con la misma estrategia |
| Parada | Cierra antes de resolver incertidumbre o sigue hasta deteriorar una respuesta correcta |
| Evidencia → afirmación/cita | La fuente no sustenta lo afirmado o la procedencia es reconstruida |

Esto mantiene la impronta original —entender por qué fallan— pero evita que “vicio” sea solo una etiqueta retrospectiva. Una formulación útil:

> Los vicios son los síntomas observables; el eslabón roto localiza la falla; la intervención prueba el mecanismo.

Advertencia: un patrón natural explica causalmente el fracaso solo cuando el diseño permite descartar alternativas. Sin intervención, debe describirse como firma o candidato a mecanismo.

## 6. Posible tesis del paper — todavía hipotética

Pregunta compacta:

> **¿Los agentes de investigación convierten evidencia en creencias, y creencias en acciones, de forma estable durante investigaciones largas?**

Resultado fuerte posible, solo si los datos lo confirman:

> A medida que avanza una investigación, los agentes se vuelven menos sensibles a evidencia nueva de igual fuerza; esa rigidez se propaga desde sus creencias reportadas hacia las búsquedas y decisiones de parada, y ayuda a explicar vicios observados en trazas naturales.

La diferencia frente a estudiar solamente juegos sería:

- Investigación multimodal y web abierta.
- Elección real de herramientas y evidencia.
- Distribución conjunta sobre lugar y fecha.
- Trayectorias largas.
- Parada y procedencia/citas observables.
- Puente explícito entre probes controladas y fallos naturales held-out.

La condición importante de publicabilidad sería que la respuesta en las probes controladas **prediga o explique comportamiento natural posterior**. Si no cruza ese puente, puede parecer un test bayesiano sintético pegado al benchmark.

## 7. Alertas de novedad y lenguaje

El espacio ya está ocupado por trabajos sobre outcome ≠ process, citas incorrectas, evidencia engañosa, belief trajectories, replay causal y stopping. Referencias surgidas en la discusión para revisar/posicionar con cuidado:

- *Broken Links Between Observations, Beliefs, and Actions*.
- BayesBench / trabajos de actualización bayesiana multi-turn.
- Causal Agent Replay y trabajos de prefix branching.
- *Calibration Is Not Control*.
- *Scores Are Not Decisions* / *Don't Stop Early*.
- CUE-R (`REMOVE/REPLACE/DUPLICATE` de evidencia).
- ProvenAI y el “citation-influence gap”.
- DRNoise y MisKnow-Agent sobre evidencia engañosa.

Por eso no parecen suficientes, aisladamente, estos titulares:

- “Outcome no refleja proceso”.
- “Los agentes citan mal”.
- “Intervenimos evidencia”.
- “Medimos belief trajectories”.
- “Los agentes paran mal”.

El hueco potencial está en integrar secuencialmente **evidencia → creencia → acción → parada → respuesta/procedencia** dentro de investigación multimodal abierta, y demostrar una relación causal o predictiva que otros trabajos no muestran.

También hay que llamar a nuestras distribuciones **reportes de creencia elicitados**, salvo validación adicional. GeoDetective no observa activaciones internas de modelos cerrados. Conviene probar si el reporte predice la acción y si pedirlo altera la trayectoria mediante shadow branches.

## 8. Conexión con WAGER

*Broken Links* también parece relevante para `research-worlds-envs`:

- WAGER conoce el mundo generador y puede conocer likelihoods exactos; podría adoptar una métrica tipo BCC más directamente que GeoDetective.
- Puede localizar un knowledge/belief → action gap bajo recompensas matemáticas.
- Su advertencia sobre incentivos sigue siendo crucial: antes de llamar “vicio” a una conducta, medir cuánto paga realmente la conducta correcta y si esa consecuencia es visible para el agente.

Para GeoDetective, esto afecta especialmente al hallazgo de citas: si el score solo premia distancia y año, citar mal puede ser una conducta no incentivada, no evidencia suficiente de mal juicio. Una manipulación explícita de incentivos permitiría separar sensibilidad al objetivo de incapacidad.

## 9. Próximos chequeos baratos sugeridos — no aprobados todavía

1. En corridas existentes, dividir transiciones de creencia en temprano/medio/tarde y buscar degradación descriptiva.
2. Medir si la región correcta apareció alguna vez: “nunca la generó” vs “la consideró y la perdió”.
3. Auditar cuánto recompensa el entorno cada conducta que hoy llamamos vicio.
4. Repetir una versión pequeña de P1(ii) con la misma señal calibrada en distintos checkpoints.
5. Medir no solo actualización de creencia sino alineación de la siguiente acción y cambio de parada.
6. Probar contexto completo vs resumen controlado para separar tokens de cantidad de decisiones/compromisos.
7. Incluir una rama sin reporte de creencia para estimar si la propia elicitación cambia la política.

## 10. Primer chequeo empírico de esta sesión

Se reutilizaron las 179 corridas de E016 y se dejó un análisis reproducible en
`experiments/E018_temporal_belief_pilot/`. Los resultados siguen siendo
exploratorios; sirven para decidir qué vale la pena probar de forma causal.

### Lo que apareció en las trazas naturales

- Opus y Sonnet normalmente ya incluían la región correcta en el primer reporte
  y luego convergían: el problema dominante no parece ser “descubrimiento tardío”.
- En los promedios por fase, GPT-5.4-mini parecía concentrarse sin mejorar. El
  contraste correcto, pareando sólo las 22 corridas con reportes early y late,
  cambió la lectura: su top weight sube 0.20, la entropía baja 0.15 y la masa de
  ubicación correcta **mejora** 0.11, pero la masa sobre la fecha verdadera cae
  0.17. La firma más interesante es aprendizaje asimétrico entre las dos
  dimensiones: converge geográficamente mientras pierde la fecha.
- Hay una asociación entre reporte y acción: las 85 acciones de mapa/historia
  con coordenadas quedaron a menos de 100 km del top declarado. Pero sólo 50
  siguen a checkpoints report-only; en los otros 35 hay evidencia intermedia y
  no se identifica un vínculo directo creencia→acción.
- En checkpoints tardíos report-only, mayor concentración precede más submit en
  los tres modelos (Opus 46.7% vs 17.6%; Sonnet 50% vs 40%; mini 80% vs 30%).
  Son asociaciones con celdas pequeñas; no prueban todavía un mecanismo de parada.
- Hay una limitación de instrumentación importante: 179/371 reportes se
  coemitieron con otra tool, cuyo resultado todavía no existía al formular el
  reporte. Además, el último reporte no coincide con el momento de submit en
  88/89 corridas.

### Smokes con señal calibrada

P1(ii) declara un canal 55/45 y por lo tanto permite calcular el cambio esperado.
En una foto de Auckland:

- GPT-5.4-mini: contradicción 0.90→0.80 (elasticidad 4.04) y placebo 0.92→0.92.
- Sonnet, dos corridas: 0.88→0.52 y 0.85→0.45 (elasticidades 9.53 y 9.64).
- Un smoke temporal de GPT dio 5.21 temprano y 2.13 tarde, con placebos casi
  inmóviles.

La reacción observada fue mucho mayor que la actualización normativa de la señal
débil: el primer fenómeno a estudiar podría ser **sobrerreacción**, no simple
subactualización. El valor tardío de GPT es especialmente ruidoso: con un prior
de 0.96, redondear el weight sólo 0.02 ya produce elasticidad >2.

Se hizo además un primer fork de Sonnet desde tres prefijos exactamente idénticos
(steps 8, 16 y 20 de la misma trayectoria), siempre con report-only, protocolo
cumplido, masas fuera de frontera y placebo source-matched:

- placebo: Δlogit 0 en los tres checkpoints;
- contradicción: elasticidad ajustada 9.95, 4.97 y 9.09;
- ninguna rama intentó parar inmediatamente; las seis eligieron investigar.

Este N=1 **no muestra una degradación monotónica**: la respuesta baja en el punto
medio y vuelve a ser enorme tarde. Sí demuestra que el diseño same-prefix es
viable y refuerza la hipótesis de sobrerreacción a una señal débil declarada. La
trayectoria base incluía documentación de boletines y las acciones siguientes
sólo se muestrearon, no se ejecutaron. Hace falta replicar entre fotos/modelos y
usar varias fortalezas de canal para modelar redondeo y fronteras.

El mismo fork sobre GPT-5.4-mini produjo una firma distinta y potencialmente más
interesante. En el par válido del step 7, la contradicción hizo subir la masa del
disco refutado de 0.45→0.50; el placebo la llevó a 0.48, de modo que el efecto
ajustado quedó levemente en la dirección incorrecta. El reporte textual decía que
la señal “debilita” Auckland, pero repartió la masa entre dos candidatos nuevos
dentro del mismo disco de 25 km. En el step 10 volvió a subir 0.82→0.88 y la
siguiente acción fue submitir dentro del disco; el placebo de ese checkpoint no
cumplió el protocolo, así que esa comparación es sólo cualitativa.

Nombre provisional para esta firma: **actualización performativa** o **lavado de
hipótesis**. El agente reconoce verbalmente la evidencia y renombra/fragmenta la
hipótesis, pero la masa sobre el evento refutado no baja y la acción continúa como
si nada. GeoDetective puede detectarlo precisamente porque identifica hipótesis
por cluster espacial, no por string.

Una réplica GPT sobre Copenhague **no** repitió el lavado. En el único par
completo, la contradicción bajó la masa 0.45→0.18 y el placebo quedó 0.45→0.46
(elasticidad ajustada 6.76): sobrerreacción clara. En dos checkpoints posteriores
GPT cumplió el reporte ante contradicción pero omitió `report_belief` ante placebo,
por lo que esos pares quedaron excluidos. El patrón no es “GPT siempre lava la
hipótesis”; depende del caso/estado. La omisión selectiva del reporte placebo es
además una señal de que conviene separar cumplimiento espontáneo de medición
forzada de la distribución.

### Experimento candidato: dosis mínima que cambia la trayectoria

La versión confirmatoria más limpia empezaría con un top **naturalmente
equivocado** y un certificado vinculante verdadero que refuta el disco, frente a
un certificado placebo source-matched. El reporte inmediato usaría tres bins
fijos y exhaustivos (`≤25 km`, `25–100 km`, `>100 km`) en basis points, además de
los candidatos libres. Luego se ejecutarían 3–5 acciones por rama. Eso permite
separar:

- no baja la masa: resistencia a evidencia;
- baja la masa pero sigue actuando/entrega allí: actualización performativa;
- baja la masa y cambia la conducta: actualización efectiva;
- baja el bin fijo pero reaparece masa equivalente en candidatos: lavado
  representacional o inconsistencia del reporte.

Un smoke inicial de esta variante **no es evidencia utilizable**: el top era
“Australia” con `radius_km=1200`, mientras el certificado sólo refutaba un disco
de 25 km alrededor de su centro. El modelo bajó 0.28→0.02, pero no era la misma
proposición. Esto reveló un bug de elegibilidad y se corrigió: las probes de
ubicación ya no disparan si el radio del top excede el disco intervenido.

Como extensión, desde el mismo prefijo se puede variar la fuerza declarada de un canal contradictorio
(por ejemplo 51/49, 55/45, 65/35, 80/20 y certificado), siempre con placebo.
Para cada dosis medir:

1. cambio normativo y observado de la masa del **mismo conjunto geográfico**;
2. fragmentación o renombrado de candidatos dentro de ese conjunto;
3. consistencia entre lo que el rationale dice (“sube/baja”) y los números;
4. cambio de la próxima acción y de la decisión de parar;
5. recuperación o resultado si se ejecuta el resto de la rama.

Esto operacionaliza literalmente “¿qué intervención mínima habría cambiado la
trayectoria?”: el umbral mínimo de evidencia que produce una actualización con
signo correcto y/o cambia la política de investigación. Un control adicional
debe pedir primero la probabilidad del evento binario fijo (dentro/fuera del
disco) y después permitir candidatos libres, para distinguir incapacidad de
actualizar de artefactos de partición.

### Posible vuelta de tuerca teórica: persistencia por repartición semántica

La búsqueda de literatura no encontró el mecanismo completo ya estudiado. La
contribución no sería “los LLM actualizan mal”, sino:

> Cuando el agente escribe su propio espacio de hipótesis, puede aparentar que
> incorporó contraevidencia cambiando la partición semántica, mientras preserva
> la masa y la política sobre el mismo evento.

Esto conecta con *support theory* y el efecto de unpacking en humanos. Los trabajos
más cercanos sobre contraevidencia, actualización bayesiana y evolución de
hipótesis usan en general estados/proposiciones fijas o no re-agregan hijos y
aliases al conjunto refutado. El control causal decisivo sería cruzar:

- hipótesis fijas vs candidatos libres;
- el mismo evento empaquetado como una región vs desempaquetado como ciudades;
- evidencia/contraevidencia idéntica;
- masa agregada externamente, relato verbal y siguiente acción.

Frase provisional: **el agente no cambió de idea; cambió el vocabulario en el que
su idea sobrevivió**. En inglés, términos menos cargados que “semantic laundering”
(ya usado con otro sentido) serían *semantic repartitioning under counterevidence*
o *partition-shifted belief persistence*.

Referencias cercanas para posicionar:

- [Ask WhAI](https://arxiv.org/abs/2511.14780): replay e inyección de contraevidencia.
- [Hypothesis Evolution Protocol](https://arxiv.org/abs/2607.09195): creación,
  refinamiento y fusión de hipótesis con linaje.
- [Reducing Belief Deviation / T³](https://arxiv.org/abs/2510.12264): desviación
  bayesiana y acciones, con estados enumerables.
- [Empirical Characterization of Elicited Probability Transformations](https://arxiv.org/abs/2603.19262):
  amplificación/atenuación de updates bajo hipótesis fijas.
- [Support Theory](https://doi.org/10.1037/0033-295X.101.4.547): antecedente de
  dependencia de partición/unpacking.

### Auditoría de incentivos

El runtime pide una `evidence_chain` auditable y advierte que será verificada,
pero el campo no es obligatorio y las métricas actuales no puntúan su integridad.
Sí puntúan ubicación, año, confianza y presencia de verificación visual. Por lo
tanto, el hallazgo de citas inválidas todavía tiene un **desajuste de incentivo**
que debe manipularse explícitamente antes de llamarlo incapacidad o vicio estable.

## 11. E019 — fork de evento fijo con continuación real (exploratorio)

Se implementó un runner que congela un evento geográfico concreto —estar dentro
de 25 km del centro de la hipótesis del agente— y pide tres probabilidades fijas
que suman 10.000 (`≤25`, `25–100`, `>100 km`). Desde el mismo historial abre dos
copias: una recibe una señal `OUTSIDE` de un canal 70/30 y la otra un placebo con
LR=1. Después del reporte inmediato, ambas vuelven al loop real hasta cinco
turnos. El cambio esperado ante `OUTSIDE` es conocido:
`Δlogit = log(.30/.70) = -0.8473`.

Las mediciones son gratuitas y no adelantan el reloj natural. El checkpoint se
captura después de que terminaron todas las tools y sus resultados; por eso una
tool coemitida no queda entre el pre y el post. Base y ramas usan temperatura 0,
el cache mutable de `image_search` se restaura por rama y las corridas nuevas
guardan una copia auditable del prefijo común sin binarios.

Corridas hechas hasta ahora:

- **GPT-mini / Auckland (`1425423`) — válido y foto limpia**. El agente se cerró
  equivocadamente sobre Melbourne. Pre fijo `.85`; contradicción `.72`
  (`Δlogit=-.790`, 93% del update normativo); placebo `.85`. Las dos ramas
  submitieron Melbourne inmediatamente, a 2.626 km de la verdad. Es un ejemplo
  candidato de update numérico sin cambio de decisión, no una tasa.
- **GPT-mini / Copenhague (`947961`) — válido y foto limpia**. Pre `.78`;
  contradicción `.65` (`Δlogit=-.647`, 76% del normativo); placebo `.78`. Las
  trayectorias luego divergieron: contradicción submitió a 205 m del ground truth;
  placebo siguió investigando y no submitió dentro del horizonte. Es evidencia de
  factibilidad de “intervención mínima que cambia la trayectoria”, no de que la
  contradicción siempre mejore el resultado.
- **Sonnet / Auckland — descarte correcto**. El único reporte temprano era una
  región de 2.000 km; los reportes compactos siguientes tenían `.92` y `.97`, fuera
  de la ventana prereglada `[.50,.90]`. No se abrió ningún fork.
- **Sonnet / NYC (`2063941`) — excluir del análisis principal**. El fork inmediato
  fue mecánicamente limpio (`.85→.71` vs placebo `.85`), pero la foto final todavía
  deja leer el overlay `ST. NICHOLAS AVE`. Sonnet lo explotó explícitamente. Además,
  la continuación contradictoria tuvo una respuesta vacía y recibió un prompt
  correctivo; el runner ya marca esos casos como conducta no comparable.
- **Sonnet / Copenhague** identificó Admiralgade en step 4, pero el pre fijo fue
  `.95`, fuera de la ventana `[.50,.90]`; no se abrieron ramas.
- **Sonnet / St Petersburg (`1336113`) — belief pair válido, conducta no**. Pre
  `.85`; contradicción `.7083`, prácticamente el posterior bayesiano exacto
  (`Δlogit=-.8475` vs `-.8473` esperado); placebo `.85`. La rama contradictoria
  tuvo una respuesta vacía y recibió un prompt correctivo, por lo que las acciones
  no son comparables. Después de cinco turns el bin fijo seguía `.70` vs `.85` en
  placebo, pero la masa de candidatos libres dentro del disco había subido de
  `.75` a `.80` inmediatamente tras la contradicción: inconsistencia exploratoria,
  no evidencia confirmatoria de lavado.

### Hallazgo de control de calidad del corpus

E011 no alcanza como gate automático. Detectó correctamente el overlay de NYC,
pero Gaussian blur radius 20 dejó letras grandes recuperables. También omitió por
completo el caption de Lida (`636474`), todavía legible en `clean_v1`. Para el
piloto actual se excluyen ambas y se exige revisión visual de la imagen final.

Revisión manual provisional: Copenhague `947961`, St Petersburg `1336113`, White
Tower `1134072` e Ipswich `1862569` no muestran captions archivísticos; Auckland,
Shanghai y Tunis parecen seguros después del blur, conservando sólo signage de
la escena. Esta lista es un preflight del piloto, no un QC cerrado del corpus.

Lectura honesta hasta acá: hay **dos pares completos de creencia con GPT-mini y
uno con Sonnet**. Los dos GPT tienen continuaciones comparables; la de Sonnet no,
por el prompt correctivo. Eso alcanza para demostrar que el protocolo puede medir
por separado creencia y trayectoria; no alcanza para nombrar un vicio estable ni
elegir el titular del paper.

## 12. Cosas que esta nota NO decide

- No decide reemplazar el censo de vicios.
- No decide que la degradación temporal sea el nuevo titular; primero hay que observarla.
- No afirma que las creencias naturales tengan una actualización bayesiana normativa calculable.
- No decide entre evidence forks, pares reales homologados u otro diseño.
- No convierte todas las probes en contribuciones primarias.
- No resuelve todavía cuál es el conjunto mínimo de vicios headline.
- No cambia el alcance, corpus, modelos ni presupuesto del experimento principal.
