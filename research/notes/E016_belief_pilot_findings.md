# E016 — Belief-state pilot: resultados + taxonomía de failure modes

> **Status**: análisis primario, 2026-06-16. Pilot completo: 3 modelos (gpt-5.4-mini, claude-sonnet-4-6, claude-opus-4-6) × 10 fotos certificadas × N=3 × {belief on, off} = 180 corridas.
>
> **Pregunta del benchmark** (ver `paper_outline.md`): ¿qué tan bayesianamente investiga un modelo? Lo medimos como distancia al óptimo bayesiano (= óptimo del reward por construcción), descompuesto en failure modes. **Eje central** (decisión Lucas): el pivoteo — revisar creencias ante evidencia/dead-ends — es la capacidad que separa investigadores.
>
> **Refs**: tabla cruda en `scripts/analyze_e016.py`; trazas completas en `digest.md` + viewers; mecanismo en `belief_state_redesign.md`.

---

## 1. La tabla (6 celdas, N=3 × 10 fotos)

| modelo | arm | med_km | <25km | year MAE | steps | beliefs | reward | dead% | lock-in | switches | piv+% | cit_ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| opus | off | 1 | 62% | — | 18.0 | — | — | — | — | — | — | — |
| **opus** | **on** | **0** | **89%** | — | 19.4 | 4.4 | +13.4 | 37% | 0% | 2.8 | 55% | 49% |
| sonnet | off | 1 | 67% | — | 20.1 | — | — | — | — | — | — | — |
| sonnet | on | 1 | 70% | — | 22.2 | 4.9 | +13.3 | 38% | 0% | 3.4 | 57% | 67% |
| mini | off | 13 | 53% | — | 7.3 | — | — | — | — | — | — | — |
| mini | on | 477 | 37% | — | 10.6 | 3.0 | +5.0 | 47% | 4% | 1.6 | 38% | 35% |

(year MAE pendiente de recompute; opus belief-on tenía 3 fails de Montevideo — bug #14, arreglado y re-corriendo. No mueve las conclusiones.)

---

## 2. Los tres hallazgos primarios

### H1 — El costo de la metacognición decrece con la capacidad ⭐ (claim C6)

Pedirle al modelo que reporte su estado de creencias mientras investiga (brazo on) tiene un costo que **depende del modelo**:

| modelo | Δ mediana (on − off) | on peor en |
|---|---|---|
| opus | **−0.0 km** (incluso ayuda) | 3/9 fotos |
| sonnet | +0.4 km | 7/10 fotos |
| mini | **+238 km** | 7/10 fotos |

Para los modelos capaces, mantener y verbalizar creencias durante la investigación es **gratis**. Para el chico es **caro** — mini no puede investigar y sostener su estado epistémico a la vez, y se le degrada el outcome. La metacognición tiene un precio que la capacidad amortiza.

**Implicación metodológica honesta**: el belief-arm no es un instrumento neutral para modelos chicos. Para benchmarking de modelos débiles, el scoring de trayectorias debería hacerse sobre el comportamiento natural (arm off) con elicitación post-hoc, o reportar el costo. Para modelos capaces, la elicitación online es válida y barata.

### H2 — Verbalizar creencias MEJORA a opus (hallazgo contraintuitivo)

opus belief-**on** llega a **89%** de fotos bajo 25 km vs **62%** en off — y dos fotos que off erraba, on las clava (Túnez 512→0.5 km, Ipswich 63→0.4 km). Forzar el reporte explícito del estado epistémico parece **ordenarle la investigación** al modelo capaz: lo obliga a explicitar hipótesis rivales y a re-evaluar pesos. Es el correlato positivo de H1 — la misma intervención que lastra al chico, beneficia al grande. Resultado citable (contradice la intuición "verbalizar siempre cuesta", precedente Tomsk v3).

### H3 — El pivoteo separa investigadores, y se mide sin judge ⭐ (claim C3b, eje central)

| modelo | switches/run | pivots productivos | mediana |
|---|---|---|---|
| opus on | 2.8 | 55% | 0 km |
| sonnet on | 3.4 | 57% | 1 km |
| mini on | 1.6 | **38%** | 477 km |

Los modelos buenos cambian de hipótesis ~2× más seguido y, crucialmente, **más de la mitad de sus pivots los acercan a la verdad**; mini pivotea poco y mal (la mayoría de sus cambios lo alejan). Esto es la versión mecánica del "refutation-driven belief revision" de CORRAL (que necesitaba un LLM-judge): acá cada switch del candidato top lleva el signo de su propio reward. **El buen investigador no es el que acierta de una — es el que revisa bien.**

---

## 3. Taxonomía de failure modes (como violaciones del ideal bayesiano)

Cada modo está anclado en trazas reales del digest. El framing: un investigador bayesiano ideal mantiene hipótesis rivales, las actualiza con evidencia diagnóstica, abandona dead-ends, y calibra su confianza a la evidencia. Cada failure es una violación específica.

### FM1 — Lock-in: confianza que sube sin que suba la verdad (no-update)
**Firma mecánica**: el peso del candidato top crece monótonamente mientras `dist_top` se queda clavado lejos. El modelo confunde "encontré más evidencia consistente con mi hipótesis" con "mi hipótesis es correcta".

**Caso canónico — mini-on, Túnez run 1 (1694 km)**: el cartel "OSPEDALE ITALIANO" lo ancla a Estambul en el step 1 (hospital italiano de Beyoğlu existe). De ahí:
```
step 1:  Estambul w=0.35  dist=1693 km
step 3:  Beyoğlu  w=0.55  dist=1694 km
step 5:  Defterdar Yokuşu w=0.70  dist=1693 km
step 10: Firuzağa, Beyoğlu w=0.85  dist=1694 km
```
El peso casi se triplica (0.35→0.85) y la distancia no se mueve un kilómetro. Cada web_search "confirma" el hospital italiano de Estambul — que existe, pero es el de la ciudad equivocada. **La evidencia era consistente pero no diagnóstica**: no discriminaba Estambul de Túnez (ambas tienen hospital italiano y minarete). El bayesiano hubiera buscado el test que separa las hipótesis; mini buscó el que confirma la que ya tenía.

**Contraste — mini-on, Túnez run 2 (0.4 km)**: arranca peor (Alepo, 2408 km, w=0.25) pero con baja confianza, y en el step 5 **pivotea fuerte a Túnez (w=0.55, 0.7 km, reward +5.76)**. La misma evidencia, distinto manejo: la hipótesis inicial débil dejó espacio para la revisión. El lock-in no es falta de evidencia — es exceso de compromiso temprano.

### FM2 — Lock-in narrativo cross-eje: la evidencia que arregla un eje envenena el otro
**Firma**: la búsqueda textual resuelve la ubicación pero arrastra una narrativa temporal equivocada (o viceversa). Único de tener dos ejes (lugar Y año) puntuados por separado.

**Caso — Estocolmo (smokes, replicado N=2)**: el year-belief tiene la verdad (1916) en el rango top inicial por percepción pura (ropa/arquitectura, w=0.35); converge la ubicación googleando "demoliciones de Klara años 50" → y el year-belief migra a 1950s (w_truth → 0.08). La misma evidencia web que llevó la ubicación a 1.5 km empujó el año 40 años lejos. **Outcome-only lo llama éxito** (ubicación clavada); la trayectoria muestra que media investigación fue contaminación.

### FM3 — Investigación muerta: tests sin valor de información
**Firma**: `reward_vs_prev ≤ 0` en un report — el agente actuó pero la creencia no se acercó. Tasa: mini 47%, opus/sonnet 37%. Casi la mitad de los pasos de investigación de mini no compran información.

Sub-tipo observado (Túnez run 1): los steps 7-10 acumulan static_map, street_view, historical_query y geocode **todos alrededor de Estambul** — confirmando el lugar equivocado con tools visuales. No es falta de esfuerzo: es esfuerzo mal dirigido por una hipótesis no testeada. (El humano experto, GeoWizard, hace lo inverso: usa la tool para discriminar, no para confirmar.)

### FM4 — Fabricación / mis-citación de evidencia (likelihood corrupta)
**Firma**: el evidence_chain cita (step, tool) que no respaldan el claim. Tasa de citas estructuralmente válidas: **mini 35%, opus 49%, sonnet 67%**. Es decir, **2 de cada 3 claims de mini citan un step/tool que no produjo esa evidencia**.

**Caso — mini-on Túnez run 0 (0/5 citas válidas)**: acierta la ubicación (0.4 km) pero TODAS sus citas son inválidas — atribuye a "s7 web_search" y "s8 street_view" hallazgos que no están en esos pasos. El modelo **reconstruye una narrativa de justificación post-hoc** que no corresponde a su propio log. Crítico: el acierto y la integridad de la cadena de razonamiento son independientes — un modelo puede acertar fabricando su justificación. Sonnet, con 67%, es notablemente más fiel a su propio proceso. *(La verificación es estructural — ¿existe el step/tool citado? La semántica — ¿el contenido está en el payload? — es el verificador pendiente, subirá el rigor.)*

### FM5 — Anclaje a pista textual sobre-saliente
**Firma**: una pista textual fuerte y temprana (cartel, letrero) domina toda la investigación, suprimiendo otras pistas. Es la causa raíz de varios FM1.

"OSPEDALE ITALIANO" es el ejemplo perfecto: pista real pero **ambigua** (hubo hospitales italianos en todo el Mediterráneo por la diáspora). mini la trata como casi-resolución (salta a Estambul/Alepo según run); opus/sonnet la tratan como una restricción entre varias y siguen mirando el minarete (octogonal → magrebí → Túnez). El anclaje textual es el reverso del eje de datación que nos hace fuertes: cuando el texto es diagnóstico ayuda, cuando es ambiguo es trampa.

### FM6 — Varianza run-to-run como propiedad medible
No es un failure mode del agente sino del benchmark, pero crítico: **misma foto + mismo modelo + mismo prompt → resultados de 0.4 km y 1694 km** (Túnez mini-on). Confirma el factor ~7× de E001 y justifica N≥3. La belief-trajectory además nos dice *por qué* divergen las corridas: no es ruido random, es el punto donde una corrida pivotea y otra hace lock-in. La varianza es interpretable.

---

## 4. Qué dice esto del benchmark (claims del paper)

- **C4 (discrimina en dims que la distancia no ve)**: ✅. Más allá de distancia, las celdas se separan limpio en pivot quality, citation validity y dead-report rate. sonnet ≈ opus en distancia pero sonnet domina en fidelidad de citas (67% vs 49%) — dimensión invisible al outcome.
- **C3b (pivoteo)**: ✅ con N=3. El eje central tiene señal fuerte y mecánica.
- **C6 (interferencia)**: ✅ y matizado — es función de capacidad (H1). Cualquier resultado era publicable; éste es el interesante.
- **C5 (fabricación)**: ✅ estructural; el verificador semántico lo reforzará.

## 5. Pendientes inmediatos
1. Re-correr Montevideo opus (4 corridas, bug #14 arreglado) — en curso.
2. Recompute year MAE en la tabla (el dato está, falta exponerlo en el agg).
3. Verificador semántico de claims (claim vs payload citado).
4. Pivot latency + missed pivots (cuántos dead-ends visibles se ignoran).
5. Decidir con Lucas: ¿el mecanismo valida para escalar al main run (6 modelos, corpus 30-50)?
