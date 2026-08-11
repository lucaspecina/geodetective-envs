# E019 — Fixed-event belief/action forks

Piloto exploratorio. Cada fork mide primero la probabilidad de un evento fijo
(`≤25 km` de un centro congelado), entrega una señal calibrada 70/30 o un
placebo con LR=1 desde el mismo prefijo y luego ejecuta hasta cinco turns reales.

Los `event_fork_*.json` son artefactos crudos e incluyen intentos descartados y
versiones anteriores del runner. No deben agregarse contando simplemente
`pair.valid`: usar [`audit.json`](audit.json), que registra la revisión posterior
del protocolo y del control de calidad de cada foto.

Resultado de factibilidad al 2026-08-11: tres pares inmediatos de creencia
válidos (dos GPT-5.4-mini y uno Claude Sonnet). Sólo los dos GPT tienen
continuaciones conductuales comparables. No es una estimación poblacional ni un
resultado confirmatorio.
