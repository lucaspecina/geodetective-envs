# E010 — Iteration pilot (gpt-5.4-mini × 5 fotos)

> **Objetivo**: para iterar/debuggear el comportamiento de UN modelo rápido sobre fotos nuevas. Output con `payload_to_model` completo guardado por tool event para análisis de qué recibe el modelo en cada paso.
>
> **Dónde**: `experiments/E010_iteration_pilot/results_gpt-5_4-mini.json` + viewer `viewer_gpt-5_4-mini.html`.
>
> **Fotos**: cid 1248470 Cáucaso 1960, cid 1560610 Volga 1915, cid 2165013 Lisboa 1947, cid 2086652 Cracovia 1943, cid 2000504 Bogotá 1930.

---

## Resumen cuantitativo

| cid | Zona | Año | Truth | Predicho | Confianza | Distancia |
|---|---|---|---|---|---|---|
| 1248470 | Cáucaso rural | 1960 | (42.47, 44.93) | (41.65, 42.35) | media | **232 km** |
| 1560610 | Volga rural | 1915 | (55.47, 39.65) | (54.7, 32.0) | baja | **496 km** |
| 2165013 | Lisboa | 1947 | (38.72, -9.14) | (41.15, -8.61) "Porto" | media | **274 km** |
| 2086652 | Cracovia | 1943 | (50.04, 19.96) | (52.24, 20.99) "Warsaw" | alta | **255 km** |
| 2000504 | Bogotá | 1930 | (4.60, -74.08) | (19.43, -99.13) "CDMX" | media | **3176 km** |

**Submit rate**: 5/5 (100%). **Steps usados**: 4-7 (media 5.4 sobre budget 50). **Tiempo**: ~80s/foto avg.

---

## Hallazgos cualitativos (5 patrones)

### Patrón 1 — First-hypothesis lock-in (3/5 fotos)

El modelo se enamora de su PRIMERA hipótesis en el step 1 y nunca la abandona seriamente:

- **Lisboa → Porto**: en step 1 dice *"probaría Porto o alguna ciudad ibérica similar"*. Las 9 búsquedas siguientes incluyen literal **"Porto"** en TODAS las queries. Nunca buscó "Lisboa". El sistema le devolvió "Praça da Liberdade" como matching Porto porque LE PIDIÓ Porto. Sesgo confirmatorio puro.
- **Bogotá → México**: step 1 search ya retorna "Ciudad de México" en top. Step 5 admite **"la foto target no coincide con esta plaza"** pero igual submite CDMX. Vio evidencia contraria y la ignoró.
- **Cracovia → Varsovia**: el PRIMER search en fotopolska devuelve snippet sobre "Nowolipie/Zamenhofa" del gueto de Varsovia. El modelo nunca consideró que Kraków también tuvo gueto. La query del step 1 ya estaba sesgada a Varsovia.

### Patrón 2 — Queries demasiado largas y descriptivas

Ejemplos reales:
- `Porto plaza tram construction black and white photo "A Cidade"`
- `vista aérea centro histórico ciudad de méxico palacio nacional catedral edificio neoclásico esquina torre domo historia`

Bing/Tavily responden con lo más cercano a esos tokens, no con lo más útil. Genera "alucinaciones por matching parcial".

### Patrón 3 — Tools visuales infrautilizadas

- Cáucaso: 0 street_view, 0 static_map. **Una sola** foto Street View de un valle georgiano se daría cuenta si era o no.
- Lisboa: 0 street_view de Praça da Liberdade Porto vs Lisboa Baixa. Cualquiera de las dos descartaba la otra.
- Bogotá: 1 street_view pero confirmó el Zócalo, no exploró Bogotá.

### Patrón 4 — Submit prematuro con confidence inflada

- Cracovia: confidence=**alta**, está 255 km mal.
- Lisboa: confidence=**media**, está 274 km mal.
- Solo Volga (confidence=**baja**) refleja honestamente la incertidumbre.

### Patrón 5 — `verification_checks` ficticio

Cracovia listó como verification: *"USHMM menciona Nowolipie"*. Pero NUNCA verificó que la foto target específica matcheara — usó texto sobre OTRA foto del gueto. Falsa verificación.

---

## Diagnóstico

El modelo opera en modo **"text-first reasoning"**: lee la foto, forma hipótesis textual, hace queries para confirmarla, y submite cuando los snippets repiten su hipótesis. Las herramientas visuales (que serían el árbitro real) se subutilizan. La foto vuelve a "verse" solo en crops, no se compara con candidatos visuales.

---

## Cambios sugeridos (propuestas para iterar)

1. **System prompt**: agregar **"considerá ≥2 hipótesis competidoras EXPLÍCITAS en el primer thinking y mantenélas vivas hasta tener evidencia que descarte alguna"**.
2. **System prompt**: **"queries cortas y diagnósticas, no descriptivas"** (ej: `"Bogotá plaza Bolívar 1930"` no `"plaza catedral dos torres edificio neoclásico vista aérea centro histórico latinoamericana"`).
3. **System prompt**: **"antes de submit, hacé ≥1 street_view o static_map de tu hipótesis principal Y de al menos 1 alternativa, y compará visualmente con la foto target"**.
4. **`submit_answer` schema**: hacer `verification_checks` obligatorio con ≥1 chequeo visual (no solo textual).
5. **Anti-anchor mechanism** (más invasivo): forzar que en el step 2 el modelo emita una hipótesis ALTERNATIVA distinta a la del step 1.

---

## Ablation con blur (E011 → E010 blurred)

Ver `E011_text_overlay.md`. Resultados sobre las mismas 5 fotos con `archive_overlay` blureado:

- Cáucaso: 232 → 28 km (-204, mejoró drástico). El sello cirílico ERA el shortcut.
- Lisboa: 274 → 273 km (sin cambio). El sesgo era semántico, no textual.
- Volga: 496 → 611 km (+116, empeoró). El texto "-ovo" era pista contextual real.
- Bogotá: 3176 → 17321 km (+14146, empeoró brutal). Caption pequeña tenía señal contextual.
- Cracovia: FAIL — content filter rechazó imagen blurreada.

**Implicación**: blur funciona donde el shortcut es OCR puro, no resuelve lock-in semántico, y puede degradar fairness cuando "overlay" tiene señal contextual legítima.
