# GeoDetective Envs — Visión del Proyecto

> **Norte filosófico.** Define qué es, por qué existe, qué fuerza, e invariantes que no pueden romperse. No describe implementación ni estado actual.
>
> Estado actual: `CURRENT_STATE.md` · Trabajo pendiente: GitHub Issues · Implementación detallada: `ARCHITECTURE.md` (cuando exista).

---

## ⚠️ Framing actual (mayo 2026): BENCHMARK primario, env como deuda futura

**Foco actual = benchmark de evaluación de agentes geo-investigativos.** El sistema no entrena policies — las **mide**. Un agente / modelo se conecta, se le presentan fotos del corpus, llama tools, y el sistema score su capacidad investigativa.

La idea original de exponer esto como **environment de RL** (consumible por Verifiers / TRL / OpenEnv para training) queda como **deuda futura** — válida, pero no es lo que construimos primero.

**Por qué el shift**: la evaluación de viabilidad (`research/synthesis/viability_assessment.md`, mayo 2026) confirmó que (a) el TOS de Google Maps prohíbe explícitamente usar Maps Content para training/validating ML, (b) el reverse image search web-scale para filtrado adversarial no tiene solución a costo razonable a escala de 1M+ fotos, (c) el cost de una corrida de RL serio con tools comerciales es $30K-$80K USD. Estos bloqueadores son críticos para la versión env, **no** para la versión benchmark (1K-10K fotos, costo trivial, ToS para inference es zona aceptable).

El nombre "GeoDetective **Envs**" refleja la idea original. Cambio de naming a "GeoDetective Benchmark" o similar es deuda explícita.

Las secciones que siguen (Misión, Invariantes, etc.) siguen redactadas en el lenguaje original ("environment", "policy entrenada", "RL"). **Lectura del documento**: donde dice "environment" / "training", interpretar como benchmark a menos que se indique explícitamente lo contrario. Iteración posterior reescribirá las secciones para reflejar el framing benchmark de forma nativa.

---

## Misión

Construir un **environment de RL** donde un agente recibe una fotografía —especialmente fotos antiguas— y tiene que **descubrir dónde fue tomada investigando activamente con tools**: mapas, satelital, Street View, archivos históricos, búsqueda web.

El agente piensa, formula hipótesis, consulta tools, descarta, refina. Como Tom Davies en *Geo Detective*, pero entrenable.

```
GeoDetective Envs provee:   environment + tools tipadas + reward signal
Otros traen:                 policy + framework de RL + loop de entrenamiento
```

**Criterio de éxito**: una policy entrenada con este environment demuestra mejor capacidad de geolocalización investigativa sobre fotos históricas no contaminadas que la misma policy sin entrenar — y razona genuinamente, no toma shortcuts.

---

## Por qué fotos antiguas

Las fotos modernas se resuelven cada vez más con lookup directo (reverse image search, matching contra Street View). Las fotos antiguas no:

- Los edificios cambiaron o desaparecieron.
- Las calles se reconfiguraron.
- Los modelos VLM vieron pocas en pretraining.
- Hay que **datar la foto en paralelo con ubicarla**.

Eso fuerza razonamiento genuino y es donde el problema deja de ser trivial. Es también un hueco real: los proyectos académicos actuales (GeoVista, GeoAgent, GeoRC, LocationAgent) trabajan con Street View moderno o Flickr contemporáneo. Foto histórica está casi vacío.

---

## Lo que GeoDetective Envs quiere lograr

El objetivo no es producir un agente que adivine coordenadas con baja distancia geodésica. Es construir un environment donde **la estrategia ganadora sea investigar como un geo-detective real**.

Para resolver bien un caso, el agente debería tener que:

- interpretar evidencia visual parcial (arquitectura, vegetación, iluminación, vestimenta, vehículos, idioma de carteles),
- **datar la foto** en paralelo con ubicarla (estilos, tecnología visible, contexto histórico),
- generar hipótesis geográficas y temporales como rivales genuinas,
- decidir qué tool usar cuándo (zoom satelital, Street View, web search histórica, archivos),
- razonar bajo restricciones (presupuesto de tool calls, ambigüedad, evidencia conflictiva),
- responder con fundamento en la evidencia visible + lo descubierto vía tools, no en memoria del pretraining.

> **La vara conceptual:** si el agente no tuvo que investigar como un geo-detective real para llegar a la coordenada, el environment falló — aunque la distancia geodésica final sea baja.

---

## Lo que NO es

- **No es un benchmark fijo**. El corpus crece y rota; cada foto puede ser nueva.
- **No entrena policies**. Provee environment + reward.
- **No prescribe el loop de razonamiento**. Da tools y reward; el agente decide cómo proceder.
- **No es geolocalización de fotos modernas**. Eso lo resuelven Pigeon, GeoVista et al.
- **No es un wrapper de reverse image search**. Las tools que disfrazan lookup están explícitamente bloqueadas.

---

## LA PREGUNTA (filtro diagnóstico)

Cada decisión y cada componente pasa por estas dos preguntas:

> **1. ¿Por qué este caso todavía no es una investigación geo-detectivesca real? ¿Qué le falta?**
>
> **2. ¿Por qué un modelo entrenado con RL sobre este environment todavía no aprendería buen juicio investigativo geo-espacial?** ¿Qué le falta al sistema para enseñar: lectura de evidencia visual, datación, generación de hipótesis geográficas/temporales, uso estratégico de tools, distinguir cuándo una conclusión es prematura vs bien fundada?

---

## Presiones evolutivas (criterio de diseño)

El environment **debe estar diseñado para que las presiones evolutivas del entrenamiento fuercen** que los agentes bien puntuados tengan estas propiedades — porque NO tenerlas produce, en promedio, scores más bajos.

**Test de diseño operativo**: para cada componente, ¿un agente SIN la propiedad X obtiene un score más bajo? Si no, hay que rediseñar.

Lista de propiedades:

- **Lectura de evidencia visual**: identificar pistas no obvias (arquitectura regional, vegetación bioma-específica, vehículos por época, idioma de carteles).
- **Datación**: triangular fecha desde estilos, tecnología, modas, contexto histórico — no asumir presente.
- **Hipótesis**: generar hipótesis geográficas rivales, testeables, que discriminen entre regiones plausibles.
- **Uso estratégico de tools**: elegir qué tool usar cuándo. Static Maps para verificar layout, Street View para confirmar, web search para contexto histórico, archivos para fotos similares.
- **Eficiencia**: no spammear tool calls. Cada query tiene costo conceptual (presupuesto explícito o implícito).
- **Robustez ante shortcuts**: NO depender de reverse image search disfrazado, NO memorizar pares foto→coord del pretraining.
- **Calibración de incertidumbre**: saber cuándo la evidencia alcanza para comprometerse a una región/coordenada y cuándo seguir investigando.
- **Pivoteo**: cambiar de hipótesis cuando la evidencia contradice; no obsesionarse con la primera intuición.

Si el environment no puede crear estas presiones, no cumple su propósito.

---

## Invariantes (NO negociables)

1. **Filtrado adversarial del corpus completo.** Antes de aceptar una foto al dataset, debe resistir tres tests: (a) reverse image search en Google Lens / Yandex / TinEye no la resuelve, (b) una descripción textual generada por VLM no la encuentra googleando, (c) VLMs grandes no la ubican sin tools. Sobreviven solo fotos que ya demostraron forzar investigación. **El filtrado aplica al corpus entero, training incluido** — no solo al held-out. Razón: si una foto está indexada o estaba en el pretraining del modelo base, entrenar con ella enseña memorización en lugar de investigación.

2. **El reward principal optimizable es continuo y geodésico.** Distancia al ground truth en kilómetros (estilo GeoGuessr), no binario. Permite gradiente de aprendizaje. **Componentes adicionales del reward** (penalizadores de proceso, no señales optimizables directamente):
   - **Tool spam penalty**: penalizar trayectorias con muchos tool calls sin resultados útiles (insight de GeoBrowse: "coherent plans > more tool calls").
   - **Tool error penalty**: penalizar calls que fallan por mal uso, discriminando hipótesis genuinas de spam.
   - **LLM judge / rúbrica investigativa**: SOLO para eval offline. **NO entra al training loop** — meterlo como señal optimizable expone al sistema a reward hacking (el agente aprende a satisfacer al judge, no a investigar).

3. **Las tools NO pueden ser shortcuts disfrazados.** Filtros en runtime bloquean dominios de origen del dataset (pastvu.com, smapshot.ch, etc.) y un hash perceptual descarta resultados que contengan la imagen objetivo. Si un agente llega vía reverse image search, el filtro falló — corregirlo.

4. **El proceso importa, no solo el outcome.** El environment debe instrumentar trayectorias: qué tools llamó, qué hipótesis formuló, cómo refinó. El reward de outcome solo no alcanza para entrenar investigación; mitigar shortcuts requiere diseño adversarial del corpus + filtrado de tools + penalizadores de proceso (ver invariante 2).

5. **Foco histórico, no moderno.** Fotos modernas son trivializables y están cubiertas por la literatura. El nicho defendible y el problema interesante son las fotos antiguas (1826-2000 aprox., sweet spot 1900-1980).

6. **El environment es reusable y open source.** El artefacto final es el environment empaquetado, no un modelo entrenado. Tiene público natural en la comunidad de RL environments (Prime Intellect Hub, etc.).

7. **Compliance con TOS — distinción benchmark vs training.** El TOS de Google Maps Platform **prohíbe explícitamente** usar Maps Content para entrenar / validar / fine-tunear modelos ML. Para el framing actual (benchmark de inference), el uso es defendible bajo standard API consumption, pero hay zonas grises (caching long-term de tile outputs, machine interpretation per Map Tiles Policy). Para la versión env futura (training), Google Maps tools son **opcionales con user-supplied key + flag explícito "non-training mode"**, y el stack canónico tiene que correr completo solo con fuentes open (OSM, OpenHistoricalMap, Mapillary, open DEM, archivos públicos). Detalle en `research/synthesis/viability_assessment.md`.

---

## Jerarquía de decisión

Cuando hay conflicto entre objetivos, aplicar en este orden:

1. **Anti-shortcut > performance numérica.** Si una mejora del agente viene por un shortcut (reverse image search disfrazado, memorización del pretraining), no cuenta — es bug del environment.
2. **Investigación genuina > reward bajo.** Mejor un environment que fuerza investigación con scores modestos, que uno con scores altos por trampas.
3. **Foco histórico > cobertura amplia.** Si agregar fotos modernas dispersa el foco, no se agregan.
4. **Reusabilidad > comodidad inmediata.** Si una decisión hace el código menos reusable como artefacto open source, evaluar tradeoff.
5. **Tools libres > propietarias cuando equivalen.** OSM/Mapillary/Sentinel antes que Google Maps cuando alcanzan, por TOS y reproducibilidad.

---

## Roadmap conceptual

| Versión | Paradigma | Estado |
|---|---|---|
| **v0** | Bootstrap, diseño, filtrado inicial del corpus PastVu. | **En curso.** |
| **v1** | MVP funcional: PastVu filtrado básico + tools mínimas (Static Maps, Street View, web search) + reward geodésico + loop ReAct sobre LangGraph (clonado de GeoBenchX). Sin entrenar todavía. | Diseño. |
| **v1.5** | Filtrado adversarial completo del corpus (los 3 tests) + tool de archivos históricos (Library of Congress, OldNYC, Historypin) + Smapshot integrado. | Futuro. |
| **v2** | Entrenamiento RL real con Verifiers/TRL sobre el environment. SFT cold-start + GRPO multi-turno (receta GeoVista). | Futuro lejano. |
| **v3** | Multi-modal evaluation suite, postales escaneadas como held-out, transferencia a otros datasets históricos. | Lejano. |

Cada versión es un milestone con criterio de cierre claro, no una iteración menor.

---

## Hacia dónde va GeoDetective Envs

El destino es un environment donde un agente reciba una foto histórica que ningún sistema actual puede ubicar, tenga acceso a un set rico de tools de investigación geo + temporal, y sea forzado a investigar genuinamente. Y que esa investigación sea entrenable con RL: trayectorias instrumentadas, reward dense lo posible, filtros anti-shortcut robustos.

La dirección no es "GeoGuessr con LLMs". Es **investigación geo-detectivesca completa**: leer evidencia, datar, hipotetizar, usar tools estratégicamente, refinar, comprometerse cuando hay fundamento.

---

## Qué NO contiene este documento

- Detalles de implementación → `ARCHITECTURE.md` (cuando exista)
- Estado actual del código → `CURRENT_STATE.md`
- Backlog y prioridades → GitHub Issues / Project v2
- Bugs y deuda técnica → Issues
- Resultados experimentales → `research/notes/`
- Análisis de related work → `research/notes/` o `research/synthesis/`
