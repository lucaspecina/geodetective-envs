# Pivote 2026-07 — Benchmark + creencias + presentación de evidencia → censo de vicios investigativos

> **Status**: DECISIÓN DE DIRECCIÓN (Lucas, 2026-07-13), post sesión de diseño adversarial con Codex (3 rondas, sesión `019f5bca-bdd0-7513-92b3-6bdc63874cfc`).
>
> Reemplaza como norte del paper a: (a) el framing "benchmark puro v1", (b) los claims teóricos del pivote belief-state de junio (`belief_state_redesign.md` — la MAQUINARIA sigue; los claims de incentive-compatibility y "medir bayesianidad" se retiran), y (c) EpistemicFork como paper de método standalone (queda documentado como evolución futura, §6).
>
> **Docs hermanos**: `paper_outline.md` (a re-centrar), `E016_belief_pilot_findings.md` (los datos que motivan esto), transcripts Codex en los task outputs de la sesión 2026-07-13.

---

## 1. La formulación (de Lucas, textual en espíritu)

El proyecto es:

> **Benchmark (geo+temporal detective) + estados de creencia cada ciertos pasos + presentación inteligente de evidencia (influenciar / dar pistas / meter evidencia falsa) → análisis de resultados que reporta no solo scores sino FAILURE MODES / VICIOS de investigación — los conocidos y los que encontremos — y qué modelos se comportan mejor frente a cada uno.**

### El DOBLE MOTOR (decisión Lucas, 2026-07-13 — no negociable)

El paper corre sobre dos motores complementarios que se retroalimentan. **Ninguno de los dos solo alcanza.**

| Motor | Qué hace | Rigor | Contribución |
|---|---|---|---|
| **Confirmatorio — probes diseñadas** | Miden a escala, mecánicamente, los vicios YA especificados (batería congelada, §7b). Chequeo humano/AI liviano solo para validar que los detectores no disparan mal. | Alto (preregistrado, mecánico) | Tasas defendibles modelo × vicio |
| **Exploratorio — ojo humano+AI sobre MUCHOS casos** | Busca los vicios que TODAVÍA NO nombramos. No 300 dobles-anotadas formales, pero sí muchas trazas miradas con criterio para descubrir patrones de falla nuevos. | Descubrimiento (no confirmatorio) | **Vicios/patrones nuevos = aporte central del paper** |

**Por qué las dos**: los vicios que ya enumeramos (§2) NO son los únicos posibles. Un aporte central del paper es **encontrar otros** — igual que CORRAL, que no partió de una lista cerrada sino que censó motifs/breakdowns emergentes y los cruzó con rendimiento. Las probes dan rigor sobre lo conocido; la exploración da descubrimiento sobre lo desconocido. Y se retroalimentan: lo que la exploración descubre en esta ronda se convierte en probes v2 (benchmark versionado).

**El guardrail metodológico** (de la crítica Codex, respetado): descubrir ≠ confirmar, en particiones distintas. Un vicio descubierto en modo exploratorio se reporta como **hallazgo emergente**, NO recibe p-value confirmatorio en el mismo dato; su confirmación estadística es probe v2 / trabajo futuro. El development set (E009/E010/E016) y el corpus confirmatorio nuevo no se mezclan. La revisión exploratoria da riqueza cualitativa y candidatos, no prevalencia insesgada.

Tres capas técnicas, un arco:

| Capa | Qué aporta | Origen |
|---|---|---|
| **Benchmark** (v1) | Sustrato real: fotos históricas anti-shortcut, 12 tools, outcome contra GT (dist geodésica + año) | El proyecto original — intacto |
| **Creencias por pasos** (v2) | Instrumentación del proceso: distribuciones reportadas cada N steps, scoring geodésico post-hoc, evidence chains | Pivote junio — la maquinaria queda; los claims teóricos grandiosos se retiran |
| **Presentación de evidencia** (v3-lite) | Intervención: en puntos controlados, el harness presenta evidencia diseñada (pista verdadera / influencia / evidencia falsa plausible) y mide la respuesta | Destilado de la sesión Codex (EpistemicFork), en versión acotada al servicio del censo |

**El entregable central**: el **censo de vicios investigativos** — tasas por modelo × vicio, con anclas cualitativas en trazas reales, y el ranking "qué modelo sufre qué". El score de outcome queda como ancla de validez y tabla clásica de benchmark, no como el mensaje.

## 2. La taxonomía de vicios (puente con el proyecto ADR-0141 / WAGER de Lucas)

Estructura heredada del otro proyecto de Lucas: **pares bipolares** + ejes (Competencia / Integridad / Operación). Mapeo empírico contra los datos GeoDetective existentes (E009/E010/E016):

| Vicio (taxonomía Lucas) | Evidencia GeoDetective ya observada | Medición |
|---|---|---|
| 1. No cambiar de idea ↔ dejarse influenciar | Lock-in Túnez (w 0.35→0.85, dist clavada 1694 km); first-hypothesis lock-in 3/5 (E010). El polo "influenciable" requiere intervención (capa 3) | Observacional (polo terco) + intervención (polo crédulo) |
| 2. Calibración de parada (overstay ↔ cierre prematuro) | AMBOS polos: submit prematuro con confidence alta (E010); over-investigating empeora (E009 Dealey). Nota: en agéntico-con-tools el overstay está VIVO (contra el estado "muerto en frontier" de la tabla original) | Observacional |
| 3. No verificar / inflar / fabricar | Citas de evidence_chain inválidas: mini 65% / opus 51% / sonnet 33% — incluso ACERTANDO (run 0.4 km con 0/5 citas válidas) | Mecánica (estructural) + judge validado (semántica) |
| 5. Perder el hilo | Señales en corridas largas (pruning >45 imágenes); cuantificar como drift de creencias sin evidencia nueva | Observacional (pendiente operacionalizar) |
| 6. Adivinar en vez de preguntar | mini submitea en 5-7 steps; el filtro adversarial existe porque los modelos adivinan de memoria | Observacional + tier de contaminación |
| 9. Verificación de paja | street_view post-decisión solo confirmatorio (E010); claims de verificación citando tools que no verifican | Mixta (mecánica + judge) |
| 4 y 7 (estructura escondida; correlación/causa) | No aplican naturalmente al dominio geo | Fuera de alcance |

**Vicios candidatos NUEVOS aportados por GeoDetective** (no están en la taxonomía original — y encontrar MÁS es objetivo explícito del motor exploratorio):

- **(a) Narrative bundling / contagio cross-eje**: al adoptar una narrativa recuperada se importan TODOS sus atributos correlacionados — Estocolmo: la evidencia de demoliciones arregla ubicación Y arrastra la fecha 40 años (year-belief truth-weight 0.35→0.08, replicado N=2). No es terquedad ni credulidad: es comprar el paquete.
- **(b) La cita reconstruida**: fabricación de la *procedencia* (punteros al propio log inventados) aun con la respuesta correcta. Distinta de fabricar contenido. Medible mecánicamente a escala.
- **(c) Anclaje a pista saliente**: una pista textual legible y temprana captura la investigación entera (OSPEDALE ITALIANO → Estambul, ignorando el minarete octogonal).

Estos 3 salieron del motor EXPLORATORIO sobre el development set (autopsias del pilot). La expectativa es que la revisión exploratoria a escala descubra más. La lista NO está cerrada — cerrarla sería traicionar el aporte principal.

## 3. Qué se conserva, qué se retira (lecciones de la sesión Codex)

**Se conserva**: environment completo (12 tools + scaffold + anti-shortcut + budget), corpus y pipeline de certificación hindsight, `report_belief` + scoring geodésico (como INSTRUMENTO de medición, proper-en-su-clase), evidence chains, viewers, annotator CORRAL (para vicios semánticos, con validación humana + IAA), todo el análisis descriptivo del pilot E016.

**Se retira** (críticas fatales aceptadas — detalle en transcripts Codex R1):
- "Incentive compatibility" como argumento sobre modelos prompteados.
- "El óptimo del reward es el investigador bayesiano" / "medimos bayesianidad" como tesis.
- El reward telescópico como contribución de process supervision (los intermedios se cancelan; si se usa para training futuro: descuento o área-bajo-la-curva).
- **Labels normativos por-evento** ("este pivot fue productivo", "esta búsqueda fue investigación muerta"): pasan a (i) tasas poblacionales comparadas entre modelos bajo evidencia compartida, (ii) veredictos identificados SOLO donde hay intervención (capa 3), (iii) anclas cualitativas sin pretensión estadística.
- El eje año como co-primario (queda secundario; resolución honesta ~década).
- H1 "metacognición ∝ capacidad" como ley causal (queda como observación + contrastes intra-familia).

## 4. La capa de intervención (versión acotada, al servicio del censo)

Principio (destilado de EpistemicFork, sin el aparato completo): **los vicios de respuesta-a-evidencia solo son identificables si controlamos la evidencia**. Diseño mínimo:

- En checkpoints fijos de investigaciones reales, el harness presenta evidencia diseñada con dirección conocida (confirma/contradice la hipótesis top reportada), veracidad conocida (verdadera/falsa/ambigua) y formato indistinguible de payloads reales (templados de los miles logueados).
- Se mide la respuesta del belief siguiente: ¿se movió? ¿cuánto? ¿asimetría confirmatoria (se mueve más cuando lo adulan que cuando lo contradicen)?
- Esto instancia: polo "dejarse influenciar" del vicio 1, "ignorar evidencia nueva", susceptibilidad a evidencia falsa (relevancia safety: evidence poisoning en agentic search).
- Lo que NO entra ahora (queda en §6): canales con matriz de confusión declarada, acquisition regret formal, shadow-vs-reinserted completo, réplica en segundo dominio.

## 5. Forma del paper

- **Título de trabajo**: "Investigative Vices of Tool-Using Agents: a Behavioral Census on a Historical Geo-Temporal Benchmark" (a iterar).
- Posicionamiento vs CORRAL (el precedente que valida el género "censo epistémico"): dominio multimodal open-web real (no sims), instrumentación mecánica para varios vicios (ellos requieren judge para todo), estructura de pares bipolares, vicios nuevos (a)-(c), intervenciones para los vicios no-identificables observacionalmente, y GT continuo.
- Resultados, organizados por los dos motores:
  - **Confirmatorio**: (i) tabla clásica de benchmark (outcome), (ii) tasas modelo × vicio de la batería de probes, (iii) validación del instrumento (test-retest de reports, indistinguibilidad seeded-vs-natural, spot-check de detectores), (iv) validez ecológica sibling (¿la susceptibilidad en probe predice el fallo natural?).
  - **Exploratorio**: (v) **descubrimiento de vicios/patrones nuevos** por revisión humana+AI de muchas trazas (la contribución tipo-CORRAL), (vi) case studies cualitativos anclados como evidencia de mecanismo.
- Escala (Codex R3/R4): audit split 80 + challenge split 40 (120 fuerte; 80 floor), 6 modelos (3+ familias, 1 open-weight), N=3, batería de probes en subset con cuotas de elegibilidad. Revisión exploratoria: "muchas" trazas (orden de magnitud 100+, no 300 dobles formales) para descubrimiento, + ~200 pares claim-fuente naturales para el puente de procedencia.

## 6. Parkeado como evolución futura (NO es el paper de ahora)

- **EpistemicFork completo** (paper de método): forks contrafactuales exhaustivos, canales con likelihood declarado, update/acquisition regret, shadow arms, réplica en segundo sustrato. Diseño completo + predicciones firmadas de Codex en el transcript R2 (2026-07-13). Retomar con `codex exec resume 019f5bca-bdd0-7513-92b3-6bdc63874cfc`.
- Demo de entrenabilidad (best-of-N / RL con reward de área): explícitamente cortado de este paper.
- Réplica cross-dominio del censo.

## 7. Veredicto Codex R3 (2026-07-13) — SÍ condicionado, con estándar

**Publicable**, pero no como "censo de 9 vicios" — como **"taxonomy-guided behavioral audit"** con tesis de disociación:

> *"Final accuracy systematically hides distinct failures of belief regulation, stopping, and evidential provenance"* — título sugerido: **"Correct Answers, Bad Investigations? A Behavioral Audit of Multimodal Historical Geolocation Agents"**.

**Scores firmados** (bien ejecutado): NeurIPS D&B 7/10 weak accept, **ACL/EMNLP main 7/10 (mejor fit)**, ICLR 6/10. Mal ejecutado (48 fotos, sin shadow, llamando "fabricación" a citas estructuralmente inválidas): 4/10 reject.

**Núcleo de 4-5 vicios primarios** (no forzar los 9): (1) regulación bipolar de creencias — *wrong entrenchment ↔ correct abandonment* + recovery, medible MECÁNICO por first-passage/survival sobre las trayectorias; (2) regulación bipolar de parada — *early wrong commit ↔ post-correct deterioration*, mecánico; (3) **integridad de procedencia** (el diferencial #1 vs CORRAL: outcome correcto con cadena de evidencia insostenible — exige verificación SEMÁNTICA, no solo estructural); (4) verificación de paja (contribución conceptual si se operacionaliza como "verificación alegada no diagnóstica"); (5) cross-axis spillover (única nuestra). Vicios 5/6/8 secundarios; 4/7 explícitamente no instanciados. De los nuevos: **(b) cita reconstruida el más fuerte** (renombrar "provenance mismatch"); (a) bundling prometedor; (c) pista saliente es subtipo, no categoría.

**Renombres obligatorios** (no vender causalidad/intención no identificada): wrong entrenchment ≠ "terquedad"; correct abandonment ≠ "credulidad"; provenance mismatch ≠ "fabricación"; non-diagnostic verification ≠ engaño. "Vicio" de un MODELO solo con estabilidad cross-foto (split-half); evento individual = "vice-like behavioral signature". Eje Integridad → "Evidential Integrity". 0/5 citas válidas = 5 fallos de procedencia, no 5 fabricaciones (4 capas: pointer existe → corresponde → sustenta semánticamente → suficiencia).

**Matriz M/H/X por vicio** (transcript R3 completo): qué es mecánico-determinista (M), qué requiere judge validado con humanos (H), qué NO es identificable observacionalmente (X → la capa de intervención §4 es la que convierte varias X en medibles: influenciabilidad, update excesivo, causalidad del anclaje).

**Estándar de validación**: codebook congelado con E009/E010/E016 como development; judge con quotes literales verificadas mecánicamente + ciego a modelo/outcome; **300 trazas doble-anotadas** (~50/modelo) + 100 enriquecidas; Krippendorff α ≥0.80 headline / 0.67-0.80 exploratorio / <0.67 solo cualitativo; reportar trace prevalence Y event incidence (por 10 tool calls). Beliefs: reemplazar "¿son reales?" por 4 propiedades medibles (test-retest, calibración, validez predictiva, acoplamiento conductual) + **shadow arms en 20-25% de prefijos** (A: elicita y corta / B: sigue sin ver el report / C: reinserta); sin shadow, escribir siempre "prompt-elicited belief reports".

**Escala mínima**: 80 fotos floor / **120 fuerte** (80 audit split representativo + 40 challenge split difícil — resuelve saturación Y representatividad); atacante no-tools corrido con TODOS los modelos evaluados; 6 modelos (3+ familias, 1 open-weight, escaleras intra-familia); N=3; modelos intercalados temporalmente; tool outputs cacheados/versionados. Stats: efectos mixtos por foto, survival/hazard para switches/parada, leave-photo-out incremental, FDR por familia, split-half reliability de perfiles.

**Riesgo #1 firmado**: que "vicio" sea interpretación post-hoc de proxies (confundir persistencia con terquedad, cambio con credulidad, actividad con verificación, falta de soporte con fabricación). Riesgo #2: overlap CORRAL. Defensa única para ambos: pocas categorías, observables explícitos, validación semántica fuerte, tesis centrada en la disociación outcome↔proceso.

## 7b. Ronda 4 Codex — vice probes en vez de anotación masiva (2026-07-13)

Lucas rechazó las 300 trazas doble-anotadas y propuso **escenarios diseñados que eliciten vicios**. Codex FIRMA la dirección ("mejor que 300 trazas anotadas") con un principio no negociable:

> **Una probe debe formalizar qué información posee EL AGENTE y qué decisión está dominada. "Nosotros sabemos que la evidencia era verdadera/falsa" no alcanza** — el agente no ve el GT, y actualizar ante evidencia falsa-plausible de fuente aparentemente confiable puede ser RACIONAL.

**Correcciones firmadas por probe**:
- **P1 contradicción**: (i) entrenchment OK solo con canal autoritativo declarado (ej. `archive_certificate` cuyo contrato dice que es certificado); (ii) over-influence requiere confiabilidad declarada de la fuente ("no verificada, ~55% confiable") + bound normativo del swing — sin eso, renombrar a "susceptibility to conflicting observation". Controles: brazos placebo+congruente mismo formato, tool existente/documentada desde el inicio (nunca aparecida mágicamente), report en cadencia rutinaria, familias de templates + una held-out, medida continua Δlogit(q) vs placebo.
- **P2 stopping**: separar `early uncertain commit` (paró inseguro con budget) de `early overconfident wrong commit` (miscalibración); post-correct deterioration es descriptivo ("correct-to-wrong reversal"), NO "debió parar". Identificación causal opcional barata: ofrecer check gratuito y decisivo vs SUBMIT (understay), y tools que no pueden aportar nada post-certificado (overstay).
- **P3 seeded provenance (LA MEJOR PROBE)**: payloads como átomos (`fact_id/subject/predicate/object/polarity`), claims en schema compatible, distinguir direct/derived/no support; headline mecánico = "seeded semantic citation fidelity". **Puente natural barato**: 40 trazas × ~5 claims = ~200 pares claim↔payload revisados por 2 humanos → habilita el claim combinado ("los fallos de procedencia bajo evidencia controlada se extienden a un audit humano estratificado de evidencia natural, incluyendo runs con outcome correcto"). Métricas: coverage / fidelity / hallucinated pointer / correct-outcome provenance (no computar fidelity solo entre los que citaron).
- **P4 verificación**: separar `dominated test choice` (adquisición) de `straw verification` (declarar `verified` tras resultado no-diagnóstico — ESO es el vicio 9). Menú con dominancia formal (H/A exhaustivas para la microdecisión, mismo costo, semántica de outcomes conocida por descripción de tools) + output estructurado (`verification_target/test_id/result/status`). Es el vicio que MÁS pierde al pasar a probe (lo performativo se pierde) → mantener acompañantes observacionales naturales.
- **P5 bundling → diff-in-diff CAUSAL**: dos payloads idénticos salvo un año irrelevante randomizado (declarado como de OTRA entidad: `publication_year: 1952, relation_to_target_photo_date: none`). Si el year-belief sigue el distractor → **entity/narrative binding failure identificado causalmente**. El P5 observacional queda como "adverse cross-axis co-movement".

**Mínimo humano final** (reemplaza las 300 dobles): revisión por 2 personas de templates por familia; spot-checks (30-100 por probe según el caso); manipulation check de indistinguibilidad seeded-vs-natural (~60 pares); los ~200 pares claim-fuente naturales; 12-20 case studies cualitativos. Nada de anotar trazas completas.

**Cuotas de elegibilidad** (clave por saturación de opus: pocos estados finales incorrectos): ≥50 checkpoints por modelo×polaridad en P1, ≥60 en P4/P5, ≥100 citas seeded por modelo en P3; celda <30 → no publicar rate por modelo; checkpoints tempranos + sampling adaptativo; estratificar por q0/checkpoint/dificultad; forks del mismo prefijo clusterizados.

**Validez ecológica — diseño sibling** (reemplaza la correlación por modelo, que solo da 6 puntos): del mismo prefijo congelado, rama P (recibe probe) vs rama N (sigue natural); ¿la susceptibilidad en P predice recovery/abandono/stopping/outcome de N? Modelo mixto, leave-photo-out. Cientos de prefijos.

**División de trabajo confirmada**: retrospectivo (dev: E009/E010/E016) descubre vicios; prospectivo (probes congeladas, fotos nuevas) confirma; hallazgos nuevos del confirmatorio = exploratorios (probe suite v2). Las trazas naturales siguen siendo necesarias para descubrir lo no anticipado, prevalencia ecológica, y chequear que la probe no creó comportamiento artificial. Nota honesta de Codex: "las vice probes son EpistemicFork-lite" — reintrodujimos intervención controlada, y eso MEJORA el paper.

**Scores R4**: batería tal como la propuse: 5/10. Con las correcciones: **7/10 en NeurIPS D&B, ACL/EMNLP main E ICLR main** (ICLR sube de 6 a 7 por las intervenciones identificadas). **8/10** si (a) las probes predicen fallos en siblings naturales y (b) P3 muestra provenance failure entre outcomes CORRECTOS. Venue según titular: artifact→D&B; taxonomía/provenance→ACL/EMNLP; metodología de probes→ICLR.

## 8. Próximos pasos

1. ~~Cerrar R3 Codex~~ ✅ incorporado arriba.
2. Decisión de Lucas sobre el alcance R3 (120 fotos / 300 trazas anotadas / shadow arms — implicancias de costo y tiempo).
3. Re-centrar `paper_outline.md` + propagar a `PROJECT.md` (disclaimer de framing) y `CURRENT_STATE.md`.
4. **Codebook v1**: spec por vicio (definición, inclusión/exclusión, contraejemplo, observable, nivel M/H/X) usando E009/E010/E016 como development — congelar antes del confirmatorio.
5. Capa de intervención mínima (spec + smoke test 1 modelo).
6. Corpus: audit split + challenge split (las 10 actuales = development).
7. Main run + audit + validación humana.
