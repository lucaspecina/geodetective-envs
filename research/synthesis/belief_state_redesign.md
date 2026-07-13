# Belief-State Redesign — reward de proceso verificable sin judge

> **⚠️ STATUS (actualizado 2026-07-13): MAQUINARIA VIGENTE / CLAIMS TEÓRICOS RETIRADOS.**
> Este doc describe el pivote belief-state de junio 2026. Tras la sesión de diseño adversarial con Codex (2026-07-13), la dirección del proyecto cambió a **auditoría de vicios investigativos** (ver `pivot_2026-07_censo_vicios.md` + `paper_outline.md`). De este documento:
> - **SE CONSERVA (vigente)**: toda la maquinaria implementada — `report_belief`, el scorer geodésico (`eval/belief_scoring.py`) ahora entendido como **instrumento de medición proper-EN-SU-CLASE** (no como reward incentive-compatible), evidence chains, budget, viewers. Es la instrumentación del proceso que la auditoría usa.
> - **SE RETIRA (NO es la tesis del paper)**: "medir qué tan bayesiano investiga un modelo" como tesis; la incentive-compatibility como argumento sobre modelos prompteados; el reward telescópico como contribución de process supervision (los reports intermedios se cancelan — crítica Codex R1 #1); los labels normativos por-evento ("pivot productivo", "investigación muerta") sin intervención controlada. Detalle en `paper_outline.md §"Qué se RETIRÓ"`.
> - Lo interesante de "presentar evidencia para influenciar" (§ intervención) SOBREVIVIÓ y se volvió el motor confirmatorio (las probes) del nuevo framing.
>
> Leer lo que sigue como el registro histórico del pivote de junio, no como la dirección actual.
>
> **Docs hermanos**: `pivot_2026-07_censo_vicios.md` (dirección VIGENTE), `paper_outline.md` (vista paper), `process_eval_landscape.md`, `findings_so_far.md`.

---

## 0. TL;DR

Pivote del centro de gravedad del proyecto: de "benchmark que mide agentes geo-investigativos" a **"environment donde el juicio investigativo es una señal densa, mecánicamente verificable y optimizable"**. Tres mecanismos, ninguno requiere LLM-judge en el loop:

1. **Belief-state geo-forecasting**: el agente reporta distribuciones de creencia (ubicación + año) durante la investigación; se puntúan con proper scoring rules geodésicas.
2. **Reward denso por paso**: valor de cada tool call = mejora del score de creencias. Ganancia de información contra ground truth, no opinión de un judge.
3. **Cadenas de evidencia auditables**: claims del submit verificados contra el log real de tool calls (tasa de fabricación medible).

Esto resuelve la contradicción entre invariantes 2 y 4 de `PROJECT.md` (el proceso importa pero el judge no puede entrar al training loop): el proceso se vuelve optimizable **sin** judge. Ataca de frente el gap que CORRAL declara abierto ("until reasoning itself becomes a training target..."). Nadie en el espacio agéntico (GeoBrowse, Agent-X, ThinkGeo, AgentProcessBench, SeekBench) tiene reward de proceso incentive-compatible.

---

## 1. Diagnóstico — por qué el diseño actual no puede enseñar juicio

### 1.1 La contradicción estructural

- Invariante 4: "El proceso importa, no solo el outcome."
- Invariante 2: "LLM judge solo eval offline, NO entra al training loop" (reward hacking).

Resultado: el proceso se mide (annotator CORRAL) pero nunca puede optimizarse. Es la limitación de todo el campo — los frameworks de process eval son descriptivos, no entrenables.

### 1.2 Las patologías observadas que el outcome-reward no corrige

De `findings_so_far.md` (E009/E010):

| Patología observada | Por qué el reward actual no la ve |
|---|---|
| First-hypothesis lock-in (3/5 fotos E010) | La distancia final no distingue "convergió investigando" de "acertó de una y nunca dudó" |
| Confidence inflada en submit | La confidence verbal no entra al score |
| `verification_checks` ficticios | Nada chequea los claims contra lo que las tools realmente devolvieron |
| `evidence_non_uptake` (6/6 traces) | Recolectar evidencia que no mueve nada no cuesta nada |
| Tool spam sin correlación con accuracy (Kimi 154 calls / 4025 km vs Opus 91 calls / 645 km) | El penalty de spam es heurístico, no mide si el call compró información |

### 1.3 La lectura incómoda de "tools visuales infrautilizadas"

Para una foto rural URSS 1920, `street_view` y `static_map` son frecuentemente **racionalmente inútiles** (edificio demolido, sin cobertura, layout cambiado). El loop de confirmación está roto en parte del corpus — es propiedad de la tarea, no (solo) del agente. Si verificar es imposible, la política óptima degenera a web_search + prior, que es exactamente lo observado cross-model. Ver §4.3 para cómo tratamos esto SIN eliminar la incertidumbre genuina.

---

## 2. Mecanismo 1 — Belief-state geo-forecasting

### 2.1 Elicitación

Nueva tool del scaffold: **`report_belief`**. El agente la llama después de cada paso de evidencia relevante (cadencia exacta: ablation en E016, ver §6).

Schema propuesto (v1, a refinar en implementación):

```json
{
  "location_belief": [
    {"name": "Lisboa, Portugal", "lat": 38.72, "lon": -9.14, "weight": 0.55, "radius_km": 30},
    {"name": "Porto, Portugal", "lat": 41.15, "lon": -8.61, "weight": 0.25, "radius_km": 30},
    {"name": "otra ciudad ibérica", "lat": 40.4, "lon": -3.7, "weight": 0.20, "radius_km": 500}
  ],
  "year_belief": [
    {"from": 1925, "to": 1940, "weight": 0.7},
    {"from": 1910, "to": 1925, "weight": 0.3}
  ],
  "rationale": "tranvía de vía estrecha + azulejos + señalética portuguesa"
}
```

- `weight` suma ≤ 1 (el resto va a un background uniforme implícito — "no sé").
- `radius_km` expresa la incertidumbre del componente (se mapea a la concentración del kernel).
- `rationale` NO entra al score (es para el viewer y el annotator offline).

### 2.2 Scoring rule (proper, geodésica)

La creencia de ubicación se interpreta como mezcla de kernels sobre la esfera (von Mises–Fisher, o kernel gaussiano-geodésico normalizado, con κ derivado de `radius_km`) + componente uniforme de piso:

```
p(x) = Σ_k w_k · K(x; μ_k, κ_k) + (1 − Σ_k w_k + ε) · U(esfera)
S(b) = −log p(x_truth)
```

- **Log-score estrictamente proper**: la estrategia que maximiza el score esperado es reportar la creencia honesta. Sobreconfianza pierde, hedging pierde, por teorema — no por prompt ni por judge.
- El piso uniforme `ε` evita −∞ y hace que "no tengo idea" sea un reporte legítimo con score acotado.
- Año: mismo esquema en 1D (mezcla de uniformes/gaussianas por rango + piso).
- Alternativa a evaluar: CRPS geodésico (más robusto a misspecification del kernel, menos sensible a colas). Decisión en E016 con tests sintéticos.

La **calibración deja de ser una métrica post-hoc** (corr confidence-distancia, pendiente en `experiment_design.md` §3.1) y pasa a ser directamente optimizable.

### 2.3 Reward denso por paso

```
r_t = S(b_{t−1}) − S(b_t)          # mejora del score = ganancia de información verificada
Σ_t r_t = S(b_0) − S(b_T)          # telescopio: la suma es la mejora end-to-end
```

Propiedades:

- **Credit assignment mecánico**: cada tool call queda valuado por cuánto movió las creencias *hacia la verdad*. Sin judge.
- **Tool spam auto-penalizado**: con costo por call (§4.4), un call que no mueve creencias es net-negativo. El penalty heurístico de spam del invariante 2 queda obsoleto.
- **Lock-in medible**: curva de beliefs plana ante evidencia nueva = lock-in. El hallazgo cualitativo estrella de E010 se vuelve una cantidad.
- **`evidence_non_uptake` medible**: llegó evidencia (tool result), la creencia no se movió. El finding 6/6 del annotator CORRAL se replica sin LLM.
- **No hackeable vía judge**: el score se computa contra ground truth de PastVu con geopy. El vector de hackeo restante es memorización (saltar la creencia directo a la respuesta) — eso lo cubre el filtro adversarial del corpus, que ya existe y sigue siendo invariante.

### 2.4 Riesgo conocido: interferencia de la elicitación

Pedir verbalización cambió comportamiento en el pasado (v3 perdió Tomsk que v1 había acertado). Elicitar beliefs puede alterar la investigación. **E016 lo mide explícitamente** (brazo con/sin `report_belief`). Si hay interferencia, es un hallazgo en sí mismo; la mitigación candidata es cadencia más baja (cada K pasos o solo en checkpoints).

---

## 3. Mecanismos 2 y 3 — verificación contra el log

### 3.1 Claims auditables en submit

`submit_answer` pasa a exigir `evidence_chain`: lista de claims, cada uno citando el step y tool call que lo respalda:

```json
{"claim": "OHM confirma iglesia ortodoxa en esa esquina en 1900-1930", "step": 7, "tool": "historical_query"}
```

Un verificador (Python + match semántico barato) chequea cada claim contra el payload registrado de ese tool call. Output: **tasa de fabricación** por modelo. Los `verification_checks` ficticios de E010 pasan de anécdota a métrica.

### 3.2 Counterfactual ablation (eval-only, fase posterior)

Replay de la trayectoria con un item de evidencia removido → contribución causal. Caro (re-runs), queda como herramienta de análisis offline, no de reward. Documentado para el paper como extensión.

---

## 4. La estructura de la tarea — ajustes post-feedback del user

Cuatro condiciones para que la política óptima sea diseño experimental secuencial (Sherlock): (1) ninguna acción individual resuelve, (2) hipótesis intermedias testeables, (3) acciones con costo, (4) informatividad dependiente del estado. El diseño siguiente apunta a cumplirlas. **Incluye tres correcciones explícitas del user (2026-06-12).**

### 4.1 Filtro positivo: ya existe v1 (auditoría manual del user)

La auditoría manual del corpus v2 (151 fotos, mayo 2026) **ya eliminó las irresolubles** — eso ES el filtro positivo v1. Lo que sigue no es repetirlo, es formalizarlo (§4.2) para que sea defendible ante reviewers y escalable a corpus futuros.

### 4.2 Certificación retrospectiva (hindsight) — NO atada a que un modelo resuelva

**Decisión del user**: el certificado NO puede ser "al menos un modelo la resuelve" — eso pondría el techo del benchmark en los modelos actuales. El benchmark debe contener fotos que ningún modelo de hoy resuelve.

**Protocolo**: el certificador (humano, o LLM asistido) **conoce el ground truth** y verifica *hacia atrás* que existe una cadena de evidencia recorrible con el toolset:

1. Listar pistas discriminantes visibles en la foto (sin conocimiento externo, solo lo que un investigador podría notar).
2. Para cada pista, una query/tool concreta que la confirma o desambigua.
3. La cadena termina en coordenada dentro de X km del truth.

Registrado como JSON estructurado (pista → tool → evidencia esperada). Resolver hacia adelante es difícil; verificar hacia atrás conociendo el destino es barato.

**Productos derivados**:
- **Tiers de dificultad principled**: largo de la cadena mínima (2 hops, 4 hops, ...) en vez de solo "qué tan perdido quedó el atacante". Complementa (no reemplaza) los tiers del atacante.
- **Defensa ante reviewers**: "¿cómo saben que las fotos no resueltas son resolubles?" → certificado.
- **Gold traces** reutilizables para SFT cold-start (v2 RL) y para grounding del process eval (con cuidado: pueden existir múltiples caminos válidos; el certificado demuestra existencia, no unicidad).
- Fotos sin cadena demostrable: NO se borran — van a tier **frontera** (válidas para benchmark, excluidas de training futuro por ser gradiente cero).

### 4.3 Verificabilidad: metadata oculta, incertidumbre genuina preservada

**Decisión del user**: la duda "¿el edificio seguirá en pie?" es un test investigativo genuino con valor de información en ambas direcciones (está → pista fuerte; no está → también actualiza). NO se filtra el corpus por verificabilidad, NO se le sopla al agente qué tools van a funcionar.

Implementación: metadata `verifiability` por foto (¿feature persiste en OHM/OSM? ¿cobertura SV/Mapillary? ¿mapa histórico georreferenciado disponible?) **solo del lado del analista**, para estratificar análisis: "¿los modelos intentan verificar cuando es posible? ¿qué hacen cuando el edificio ya no está?". Si aun pudiendo verificar no verifican, eso es un hallazgo sobre los modelos, no sobre la tarea.

Acción complementaria: cerrar el loop de verificación *en pasado* donde se pueda — mapas históricos georreferenciados (MapWarper/NYPL, ya identificados en `viability_assessment.md` bloqueador 9) y geometría persistente (ríos, costas, trazado vial) como tools de fase 2.

### 4.4 Presupuesto económico explícito

Cada tool call tiene costo (puntos, tabla por tool), el episodio tiene budget. Acoplado al reward denso: la cantidad optimizable es **ganancia de información por unidad de costo** — la formalización del "uso estratégico de tools" que `PROJECT.md` pide como presión evolutiva. Captura con una sola métrica el over-investigating de Dealey (E009) y el contraste Opus 6 calls vs Kimi 154 calls.

### 4.5 Casos multi-artefacto (fase 2, opcional)

Expediente en vez de foto única: 2-3 fotos del mismo lugar (PastVu tiene clusters naturales por ubicación), dorso de postal, recorte. Fuerza condición (1) por construcción. No bloquea E016.

### 4.6 El dominio NO cambia

Evaluadas alternativas (fotos modernas: saturado; OSINT personas/eventos: minado ético; documentos puros: pierde el eje visual-espacial). Fotos históricas conservan tres activos: eje de datación (no googleable, lectura de evidencia pura), resistencia natural a memorización, ground truth gratis verificable (PastVu).

---

## 5. Qué se conserva / qué cambia

| Pieza | Estado |
|---|---|
| Corpus 151 + pipeline anti-shortcut (blur, phash, blacklist, atacante) | **Se conserva entero** (el filtro adversarial es ahora también la defensa anti-hackeo del belief reward) |
| 12 tools + scaffold ReAct + llm_adapter | Se conserva; se agregan `report_belief` y `evidence_chain` en submit |
| Annotator CORRAL | Se conserva como **validación convergente** offline: ¿el reward mecánico correlaciona con motifs/breakdowns del judge? (sección del paper) |
| Reward = distancia geodésica puntual | **Reemplazado** como señal principal por proper scoring rule sobre beliefs (la distancia puntual queda como métrica reportada, comparable con literatura) |
| Penalties heurísticos de spam/error (invariante 2) | Obsoletos si el reward denso + budget funcionan (E016 decide) |
| Framing "benchmark primario, env deuda futura" | Se mantiene operativamente, pero el mismo mecanismo sirve a ambos: métricas nuevas para el benchmark hoy, reward entrenable para el env mañana — sin Google en el loop de reward (scoring = geopy + ground truth, cero ToS) |
| Viewer HTML | Se extiende: **mapa de calor de creencias contrayéndose sobre el globo paso a paso** (el demo del proyecto) |

Posicionamiento del paper: *judge-free, mechanically verifiable process rewards for investigative agents*, testbed foto histórica. Los diferenciadores previos (eje histórico, anti-shortcut, IAA, toolset historiográfico — `process_eval_landscape.md` §5) pasan de contribución principal a setup. Contra PRMs: los PRMs son judges aprendidos (hackeables); esto es incentive-compatible por teorema. Contra GeoBrowse: pass@1 binario vs distribuciones + reward denso.

---

## 6. E016 — experimento de validación (primer paso ejecutable)

**Hipótesis riesgosa a validar antes de reescribir nada más**: los modelos pueden reportar beliefs útiles, y la métrica discrimina.

1. **Scaffold**: agregar `report_belief` a `react.py` (extensión chica).
2. **Scorer**: log-score geodésico sobre mezcla + piso uniforme, con tests sintéticos (casos: certeza correcta, certeza incorrecta, hedge honesto, hedge vago, "no sé"). Decidir log-score vs CRPS acá.
3. **Corridas**: 3 modelos (gpt-5.4-mini, claude-sonnet-4-6, claude-opus-4-6) × 10 fotos del corpus v2 **certificadas a mano con cadena hindsight** (§4.2 — esto mismo prototipa el protocolo de certificación) × N=3 × {belief on, belief off}.
4. **Budget**: incluido como variable del scaffold desde el día uno (costos por tool, tabla simple v1).

**Criterios de éxito**:
- Las curvas de belief discriminan modelos (donde la distancia final sola no).
- El lock-in de E010 es visible mecánicamente (curvas planas ante evidencia).
- Interferencia de elicitación medida (on vs off) y acotada o, si es grande, caracterizada.

**Si valida** → scoring formal + verificador de claims + re-run E009 con métrica nueva + actualizar `PROJECT.md`/`experiment_design.md`. **Si no valida** → se perdieron ~2 semanas; el benchmark clásico queda intacto.

---

## 7. Open questions

1. Log-score vs CRPS geodésico (decide E016 con sintéticos).
2. Cadencia de `report_belief` (cada paso vs cada K vs checkpoints) — tradeoff señal densa vs interferencia/costo de contexto.
3. ¿El belief de año va junto o separado en el reward? (propuesta v1: score conjunto aditivo con peso α a calibrar).
4. Tabla de costos por tool para el budget (¿proporcional al costo real en USD? ¿al tiempo? ¿uniforme?).
5. ¿Cómo evitar que el agente "olvide" reportar beliefs? (¿bloquear tools hasta reportar tras evidencia nueva? — riesgo de interferencia; medir primero).
6. Prior work exacto a citar contra: PRM literature (learned judges), intrinsic motivation / information gain en RL exploration, probabilistic geolocation (no agéntica), proper scoring rules en forecasting. Hacer pasada de related work antes del paper.
