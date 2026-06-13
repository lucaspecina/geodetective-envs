# Paper outline — claims, evidencia y gaps

> **Status**: working draft, junio 2026. Esqueleto orientado a claims: cada afirmación del paper mapeada a la evidencia que la respalda y a lo que falta. Se actualiza a medida que E016 produce datos.
>
> **Refs**: `belief_state_redesign.md` (mecanismo), `process_eval_landscape.md` (related work), `harness_review_post_belief.md` (fixes), `findings_so_far.md` (E001-E012).

---

## Working title

**"Belief-State Geo-Forecasting: Judge-Free, Mechanically Verifiable Process Rewards for Investigative Agents"**

(alt: "Measuring Investigative Judgment Without a Judge: Proper Scoring Rules for Tool-Using Agents")

## Posicionamiento (1 párrafo)

El process eval de agentes está fragmentado y es descriptivo: CORRAL/AgentProcessBench/SeekBench anotan trazas con LLM-judges (costosos, hackeables si entran al training loop). CORRAL cierra: *"until reasoning itself becomes a training target..."*. Nosotros convertimos el juicio investigativo en señal **densa, mecánica e incentive-compatible**: el agente reporta distribuciones de creencia durante la investigación, puntuadas con proper scoring rules geodésicas contra ground truth. Sin judge. Testbed: geolocalización + datación de fotos históricas (dominio con anti-shortcut riguroso y eje temporal que nadie cubre).

## Venue target

NeurIPS Datasets & Benchmarks o ICLR (benchmark + method). Decidir con resultados en mano.

---

## Claims → evidencia → estado

### C1 — Las proper scoring rules geodésicas hacen optimizable la calibración investigativa (el mecanismo)
- **Evidencia**: teoría (log-score estrictamente proper, telescopía del reward denso) + tests sintéticos (ordenamiento canónico, properness por Monte Carlo, divergencia log vs energy score ante el confiado-equivocado).
- **Estado**: ✅ listo (commits `c86a8fd`). Sección Methods escribible hoy.

### C2 — Los modelos comerciales PUEDEN reportar creencias útiles sin colapsar (viabilidad de la elicitación)
- **Evidencia**: smokes + pilot: report_belief espontáneo en step 1, hedging con masa "no sé", radios sensatos, 0 rechazos de validación estructural en N corridas.
- **Estado**: 🟡 confirmado cualitativamente; cuantificar con pilot completo (180 runs).

### C3 — La trayectoria de creencias revela lo que el outcome oculta (el argumento central)
- **Sub-claims con evidencia ya observada (N chico, pendiente pilot completo)**:
  - (a) **Lock-in narrativo cross-eje**: la misma evidencia web que arregla ubicación contamina datación (Estocolmo ×2: year belief w_truth 0.35 → 0.08 mientras location converge a 1.5 km). Outcome-only lo llama éxito.
  - (b) **Investigación muerta medible**: % de belief reports con reward ≤ 0 (≈48% en datos parciales de mini).
  - (c) **Percepción >> búsqueda en información ganada**: el salto de nats del step 1 (pura percepción) domina la curva (+11.7 de +12.6 en Estocolmo; +12.7 de +20.5 en Montevideo).
- **Estado**: 🟡 pilot completo + análisis. ESTE es el claim que el análisis cualitativo debe poblar con taxonomía de failure modes.

### C4 — El benchmark discrimina modelos en dimensiones que la distancia no ve
- **Evidencia esperada**: tabla cross-model (mini/sonnet/opus × on/off × N=3): lock-in rate, dead-report rate, calibración (reward total), switches, citas válidas — vs ranking por distancia.
- **Estado**: 🔴 esperando pilot. Si los rankings por proceso ≠ rankings por distancia → claim fuerte. Réplica del hallazgo E009 ("tier comercial no predice") con la métrica nueva.

### C5 — La fabricación/mis-citación de evidencia es medible mecánicamente y varía por modelo
- **Evidencia**: evidence_chain con citas (step, tool) verificadas contra el log. Datos parciales: solo ~30% de citas estructuralmente válidas (mini). Verificador semántico (claim vs payload real) pendiente.
- **Estado**: 🟡 estructural listo; semántico por construir (LLM compara claim vs payload registrado — es verificación contra log, no judge libre).

### C6 — La elicitación de creencias tiene un costo medible (honestidad metodológica)
- **Evidencia**: brazo on vs off pareado por foto. Señal preliminar (N=1, harness viejo): on peor en mediana. Si se confirma: la medición perturba — se reporta como tradeoff del método con su magnitud, no se esconde.
- **Estado**: 🔴 esperando pilot. CUALQUIER resultado es publicable (interfiere → tradeoff cuantificado; no interfiere → método gratis).

### C7 — Anti-shortcut + certificación hindsight = corpus defendible
- **Evidencia**: pipeline existente (blur, phash, blacklist, atacante) + certificación retrospectiva de resolubilidad (10 fotos piloto documentadas; protocolo definido).
- **Estado**: 🟡 protocolo v1 listo; escalar post-E016. Responde al reviewer "¿cómo saben que las no resueltas son resolubles?".

### C8 (secundario) — El harness importa: bugs de tools confunden conclusiones de behavior
- **Evidencia**: harness review (13 bugs; pick muerto desde mayo, nearby jamás cableado) → la conclusión previa "tools visuales infrautilizadas" estaba parcialmente confundida. Comparación pre/post fix posible con E009 vs pilot.
- **Estado**: ✅ documentado. Candidato a sección de lecciones / apéndice — honestidad metodológica que diferencia.

---

## Estructura tentativa del paper

1. **Intro** — el gap: process eval descriptivo y judge-dependiente; nuestra propuesta. (escribible ~hoy)
2. **Related work** — landscape ya consolidado en `process_eval_landscape.md`. (escribible hoy)
3. **Method** — belief elicitation + scoring rules + reward denso + evidence chains + budget + certificación hindsight. (escribible hoy, C1)
4. **Benchmark setup** — corpus histórico, anti-shortcut, 12+2 tools, scaffold. (escribible hoy)
5. **Experiments** — E016: cross-model × on/off × N=3. (bloqueado por datos)
6. **Results quant** — C4 + C6 + C5. (bloqueado)
7. **Qualitative analysis** ⭐ — taxonomía de failure modes con las curvas como evidencia mecánica: lock-in narrativo cross-eje, investigación muerta, fabricación de citas, percepción vs búsqueda. (bloqueado; protocolo: digest + viewer + autopsias sistemáticas)
8. **Limitations** — interferencia de elicitación (C6), helper LLM en web_search (mitigado a extractivo), n=10 fotos pilot (escalar), un solo idioma de prompt, IAA pendiente si usamos annotator.
9. **Lecciones de harness** (C8, opcional/apéndice).

---

## Plan de ejecución (orden)

| # | Tarea | Bloqueado por | Quién |
|---|---|---|---|
| 1 | Pilot 180 runs | — (corriendo) | máquina |
| 2 | Tablas quant + digest (`analyze_e016.py`) | 1 | Fable |
| 3 | **Autopsias cualitativas sistemáticas** → taxonomía failure modes → `research/notes/E016_findings.md` | 2 | Fable + user (revisión) |
| 4 | Decisión: ¿el mecanismo valida? (criterios de `belief_state_redesign.md` §6) | 3 | user |
| 5 | Verificador semántico de claims (claim vs payload del log) | 2 | Fable |
| 6 | Validación user de certificaciones + escalar corpus certificado (30-50 fotos) | 4 | user + Fable |
| 7 | Main run del paper: +gpt-5.4, grok, kimi (la tabla cross-model headline) | 4, 6 | máquina |
| 8 | Secciones 1-4 del paper (no bloqueadas) | — | Fable, en paralelo |
| 9 | Results + qualitative + limitations | 7 | Fable + user |

**Riesgos del plan**: (a) si C6 da interferencia grande, el framing cambia a "post-hoc scoring de trayectorias off-arm + belief arm como instrumento" — el mecanismo sobrevive, el protocolo se ajusta; (b) cuota Street View en el main run (correr en tandas); (c) n=10 fotos es chico para C4 con significancia — el main run necesita el corpus certificado escalado (paired bootstrap, pre-registrar hipótesis primaria, ver landscape §4).
