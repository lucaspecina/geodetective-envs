# Paper outline — auditoría comportamental de vicios investigativos

> **Status**: REESCRITO 2026-07-13 tras la sesión de diseño adversarial con Codex (4 rondas) y la decisión de dirección de Lucas. Reemplaza por completo la versión anterior (belief-state con claims C1-C8), que quedó **RETIRADA** — ver §"Qué se retiró" y `pivot_2026-07_censo_vicios.md`.
>
> **Doc canónico de la dirección**: `research/synthesis/pivot_2026-07_censo_vicios.md` (decisión + matriz de probes + estándares + veredictos Codex). Este outline es la vista "paper".

---

## Working title (a iterar)

**"Correct Answers, Bad Investigations? A Behavioral Audit of Multimodal Historical Geolocation Agents"**

(alt: "GeoDetective: Auditing Belief, Evidence, and Provenance in Tool-Using Multimodal Agents")

## Tesis central (la oración que el paper defiende)

> **La accuracy final esconde sistemáticamente fallas distintas de regulación de creencias, de parada, y de procedencia de la evidencia; con estados de creencia explícitos, logs auditables y escenarios diseñados, revelamos qué modelos llegan a la respuesta correcta por razones defendibles y cuáles reconstruyen la justificación después — y descubrimos vicios investigativos que la literatura no había nombrado.**

Frase de una línea para abstract: *outcome correcto y proceso investigativo auditable son dimensiones distintas, y las medimos sin depender de un LLM-judge.*

## Posicionamiento

Precedente que valida el género: **CORRAL** (censo de patrones epistémicos en 25K runs con LLM-judge; "68% ignora evidencia"; cierra pidiendo que el razonamiento sea training target). Nuestros diferenciales reales (rankeados por valor, Codex R3):
1. **Disociación outcome–procedencia**: una respuesta exacta puede tener cadena de evidencia inexistente/insostenible. El diferencial #1 si se verifica semánticamente.
2. **Trayectorias probabilísticas contra GT continuo**: entrenchment, abandono de lo correcto, recuperación, deterioro, calibración — sin interpretar cada evento.
3. **Doble eje ubicación–fecha**: spillover perjudicial entre dos creencias explícitas (vicio nuevo: narrative bundling).
4. **Investigación multimodal open-web real** (no simulaciones): validez ecológica.
5. **Escenarios diseñados (probes)**: convierten en mecánicos vicios que en trazas naturales exigirían juez humano.

Contra el riesgo "CORRAL ya lo hizo": menos categorías, observables explícitos, validación semántica, intervenciones que identifican lo que CORRAL solo podía anotar, y descubrimiento de vicios nuevos.

## Venue

Codex R4 (con el diseño corregido): **7/10 en NeurIPS D&B, ACL/EMNLP main, e ICLR main**; 8/10 si las probes predicen fallos en siblings naturales Y hay provenance failure entre outcomes correctos. Decisión de venue según el titular final (artifact→D&B; taxonomía/provenance→ACL/EMNLP; método de probes→ICLR). Decidir con resultados.

---

## El doble motor (la estructura del paper)

**Confirmatorio (rigor sobre lo conocido)** + **Exploratorio (descubrimiento de lo desconocido)**. Detalle y guardrails en `pivot_2026-07_censo_vicios.md §1`. Descubrir ≠ confirmar, en particiones distintas.

## Contribuciones (claims que el paper defiende)

### K1 — Disociación outcome ↔ proceso (la headline)
Modelos que resuelven la tarea (opus mediana ~0-1 km) igual exhiben fallas de proceso: citas sin sustento incluso acertando (pilot: run a 0.4 km con 0/5 citas válidas). **Evidencia**: benchmark outcome + tasas de procedencia. **Estado**: núcleo; requiere verificación semántica (probe P3 + puente natural).

### K2 — Batería de probes: medición mecánica de vicios sin LLM-judge
Escenarios diseñados donde diagnosticidad/veracidad/dominancia se conocen por construcción → el label es mecánico. Familias: contradicción (P1), parada (P2), procedencia sembrada (P3), verificación (P4), spillover cross-eje (P5). **Principio no negociable** (Codex R4): la probe formaliza qué sabe EL AGENTE y qué decisión está dominada — "nosotros sabemos que era falso" no alcanza. **Estado**: diseñada, a implementar (spec en pivot doc §7b).

### K3 — Regulación de creencias como par bipolar (el eje central de Lucas, operacionalizado)
wrong entrenchment ↔ correct abandonment + recovery, medido por first-passage/survival sobre trayectorias probabilísticas y por P1. No "terquedad/credulidad" (intención no identificada) sino firmas conductuales. **Estado**: mecánico observacional + probe.

### K4 — Integridad de procedencia (el diferencial #1)
Coverage / citation fidelity / hallucinated pointer / correct-outcome provenance. Mecánico exhaustivo en evidencia natural (estructural) + semántico exacto en evidencia sembrada (P3) + puente humano de ~200 pares claim-fuente naturales. **Estado**: estructural hecho (pilot); semántico por construir.

### K5 — Verificación de paja (contribución conceptual)
Distinguir `dominated test choice` (adquisición incompetente) de `straw verification` (declarar "verified" tras resultado no-diagnóstico — el vicio real). Probe P4 con dominancia formal + output estructurado. **Estado**: por construir; es el vicio que más pierde al pasar a probe → acompañar con observacional natural.

### K6 — Vicios NUEVOS descubiertos (contribución tipo-CORRAL, el aporte del motor exploratorio)
narrative bundling / cross-axis binding failure (P5 diff-in-diff), provenance reconstruction (cita reconstruida), single-cue dominance — MÁS los que la revisión exploratoria a escala descubra. **Estado**: 3 candidatos del development; lista abierta por diseño.

### K7 — Perfiles por modelo + validez ecológica
Qué modelo sufre qué vicio (el "consumer report" epistémico) + diseño sibling (¿la susceptibilidad en probe predice recovery/abandono/stopping/outcome en la rama natural del mismo prefijo?). **Estado**: por correr.

## Qué se RETIRÓ (para que no reaparezca disfrazado de nuevo)

De la versión belief-state de junio, RETIRADO por la crítica Codex R1 (aceptada):
- "El óptimo del reward es el investigador bayesiano por construcción" / "medimos bayesianidad" como TESIS. (La geolocalización bayesiana queda como inspiración, no como claim.)
- Incentive compatibility como argumento sobre modelos prompteados.
- Reward telescópico como contribución de process supervision (los intermedios se cancelan).
- Labels normativos por-evento sin intervención ("este pivot fue productivo", "esta búsqueda fue investigación muerta"): pasan a tasas poblacionales / probes / anclas cualitativas.
- Switches count y "pivot productivo = reward>0" como métrica (matemáticamente acoplada al outcome).
- Evidence-chain estructural como prueba de "fabricación" (es fallo de procedencia, no fabricación).
- H1/H2/H3 como leyes causales de capacidad (quedan como observaciones + contrastes intra-familia).
- Año como eje co-primario (secundario, resolución decadal).
- Best-of-N / training demo (otro paper).

Lo que SE CONSERVA de junio: la MAQUINARIA (report_belief, scorer geodésico como instrumento de medición proper-en-la-clase, evidence chains, viewers, budget, annotator CORRAL para labels semánticos). Ver `belief_state_redesign.md` (marcado como maquinaria-vigente / claims-retirados).

## Escala y método (Codex R3/R4)

- **Corpus**: audit split 80 (representativo, para prevalencia) + challenge split 40 (difícil, para benchmark no-saturado). 120 fuerte, 80 floor. Las 10 fotos actuales = development.
- **Modelos**: 6, ≥3 familias, ≥1 open-weight, escaleras intra-familia; N=3; intercalados temporalmente; tool outputs cacheados/versionados.
- **Humano**: NO 300 dobles-anotadas. Sí: revisión de templates por 2 personas; spot-checks (30-100 por probe); ~200 pares claim-fuente naturales; "muchas" trazas para descubrimiento exploratorio; 12-30 case studies.
- **Stats**: efectos mixtos por foto, survival/hazard para switches/parada, offset por tool-calls en conteos, leave-photo-out incremental, FDR por familia de vicios, split-half reliability de perfiles. Nada causal sin intervención.
- **Artifact**: probes + payloads sembrados + prefijos congelados = redistribuible (la parte sintética resuelve el problema de licencias que la web viva no).

## Riesgos (firmados por Codex, a mitigar)

- **#1**: que "vicio" sea interpretación post-hoc de proxies (confundir persistencia con terquedad, cambio con credulidad, actividad con verificación, falta de soporte con fabricación). → nombres conductuales, observables explícitos, validación semántica.
- **#2**: overlap CORRAL. → disociación como tesis, intervenciones, vicios nuevos.
- Detección de la inyección / demand effects en las probes. → placebos mismo-formato, tools documentadas desde el inicio, manipulation check de indistinguibilidad.
- Saturación. → challenge split.
- Base rates: pocos checkpoints elegibles por saturación de opus. → cuotas de elegibilidad, sampling adaptativo, no publicar rate de celda <30.

## Plan de ejecución (orden)

1. **Codebook v1**: spec por vicio (definición, inclusión/exclusión, contraejemplo, observable, nivel M/H/X) + spec de cada probe (contrato de información del agente, dominancia, controles). Congelar antes del confirmatorio. Usa E009/E010/E016 como development.
2. **Implementar la batería de probes** en el scaffold + smoke test 1 modelo.
3. **Motor exploratorio v1**: pasada humana+AI sobre el development set → refinar codebook + candidatos a vicios nuevos.
4. **Corpus**: audit split + challenge split (certificación hindsight).
5. **Main run** (natural + probes) + análisis + case studies + puente de procedencia.
6. Redacción por venue.

Docs vivos: este outline + `pivot_2026-07_censo_vicios.md` (canónico). Al cambiar la dirección otra vez, actualizar AMBOS y marcar lo superseded.
