"""Smoke de la probe P1 (contradiction) end-to-end (codebook v1.1).

Corre el agente con belief_mode + ProbeInjector sobre fotos dev. El injector
dispara UN boletín en el primer checkpoint elegible; medimos la respuesta en
el primer report posterior (residual/elasticidad según polaridad).

Uso:
    python scripts/run_probe_smoke.py                     # mini × 4 fotos × {contradiction, placebo}
    MODEL=claude-sonnet-4-6 CIDS="2255098" ARMS=contradiction python scripts/run_probe_smoke.py

Output: experiments/E017_probe_smoke/results_{model}.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path("src").resolve()))
from geopy.distance import geodesic

from geodetective.agents.react import run_react_agent
from geodetective.corpus import CLEAN_VERSION
from geodetective.probes import ProbeConfig, ProbeInjector

EXP_DIR = Path("experiments/E017_probe_smoke")
PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", "corpus/photos"))
CANDIDATES_PATH = Path(os.environ.get("CANDIDATES_PATH", "experiments/E007_sample_diverso/candidates_v2_final.json"))

MODEL = os.environ.get("MODEL", "gpt-5.4-mini")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "30"))
MIN_STEPS = int(os.environ.get("MIN_STEPS", "0"))
FAMILY = os.environ.get("FAMILY", "P1")  # P1 | P5 | P4
PROBE_MIN_STEP = int(os.environ.get("PROBE_MIN_STEP", "4"))
PROBE_MAX_BUDGET_FRAC = float(os.environ.get("PROBE_MAX_BUDGET_FRAC", "0.6"))
RUN_LABEL = os.environ.get("RUN_LABEL", "").strip()
_default_arms = {"P1": "contradiction,placebo",
                 "P5": "distractor_a,distractor_b,absent",
                 "P4": "assigned"}.get(FAMILY, "contradiction,placebo")
ARMS = [a.strip() for a in os.environ.get("ARMS", _default_arms).split(",")]
# Mezcla dev: 2 fotos donde mini suele acertar (→ polaridad ii) y 2 donde suele fallar (→ i)
DEFAULT_CIDS = "1425423,947961,636474,2255098"


def _run_key(record: dict) -> tuple:
    """Identidad de una celda; incluye timing para no colisionar stages/configs."""
    return (
        record.get("cid"),
        record.get("arm"),
        str(record.get("family", "P1")).upper(),
        record.get("run_label") or None,
        int(record.get("agent_max_steps", 30)),
        int(record.get("agent_min_steps", 0)),
        int(record.get("probe_min_step", 4)),
        round(float(record.get("probe_max_budget_frac", 0.6)), 6),
    )


def _is_completed(record: dict) -> bool:
    """Errores de API/red son reanudables; nunca cuentan como celda terminada."""
    return not record.get("error") and record.get("terminal_state") != "api_error"


def main() -> None:
    cids = [int(c.strip()) for c in os.environ.get("CIDS", DEFAULT_CIDS).split(",")]
    all_c = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    cands = {c["cid"]: c for c in all_c if c["cid"] in set(cids)}

    EXP_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if FAMILY == "P1" else f"_{FAMILY.lower()}"
    if RUN_LABEL:
        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in RUN_LABEL)
        # Incluir family evita que P1/RUN_LABEL=p5 colisione con una corrida P5.
        suffix = f"_{FAMILY.lower()}_{safe_label}"
    out_path = EXP_DIR / f"results_{MODEL.replace('.', '_').replace('/', '_')}{suffix}.json"
    results = []
    if out_path.exists():
        try:
            results = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            results = []
    done = {_run_key(r) for r in results if _is_completed(r)}

    print("=" * 70)
    print(f"E017 PROBE SMOKE ({FAMILY}) — {MODEL} | arms={ARMS} | fotos={cids}")
    print(f"agent_min_steps={MIN_STEPS} | probe_window=[{PROBE_MIN_STEP}, "
          f"{PROBE_MAX_BUDGET_FRAC:.0%} del max_steps]")
    print("=" * 70)

    for cid in cids:
        cand = cands.get(cid)
        if not cand:
            print(f"[SKIP] cid={cid} sin metadata")
            continue
        img = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
        if not img.exists():
            print(f"[SKIP] cid={cid} sin foto")
            continue
        truth = cand["geo"]
        for arm in ARMS:
            run_key = (
                cid, arm, FAMILY.upper(), RUN_LABEL or None, MAX_STEPS,
                MIN_STEPS, PROBE_MIN_STEP,
                round(PROBE_MAX_BUDGET_FRAC, 6),
            )
            if run_key in done:
                print(f"[SKIP done] cid={cid} arm={arm}")
                continue
            # Si existe un intento fallido de esta misma celda, se reemplaza en
            # lugar de acumular duplicados que sesguen resúmenes posteriores.
            results = [r for r in results if _run_key(r) != run_key]
            ty = float(cand["year"]) if cand.get("year") else None
            inj = ProbeInjector(
                truth[0], truth[1],
                ProbeConfig(
                    family=FAMILY,
                    arm=arm,
                    seed=cid,
                    truth_year=ty,
                    min_step=PROBE_MIN_STEP,
                    max_budget_frac=PROBE_MAX_BUDGET_FRAC,
                ),
            )
            print(f"\n### cid={cid} arm={arm} | {cand.get('title','')[:50]}")
            t0 = time.time()
            try:
                res = run_react_agent(
                    image_path=img, model=MODEL, max_steps=MAX_STEPS,
                    min_steps=MIN_STEPS, verbose=True,
                    provider=cand.get("provider"),
                    provenance_source=cand.get("provenance_source", ""),
                    belief_mode=True, belief_nudge_after=3,
                    probe_injector=inj,
                )
            except Exception as e:
                print(f"[FAIL] {type(e).__name__}: {e}")
                results.append({
                    "cid": cid,
                    "arm": arm,
                    "model": MODEL,
                    "family": FAMILY,
                    "run_label": RUN_LABEL or None,
                    "agent_max_steps": MAX_STEPS,
                    "agent_min_steps": MIN_STEPS,
                    "probe_min_step": PROBE_MIN_STEP,
                    "probe_max_budget_frac": PROBE_MAX_BUDGET_FRAC,
                    "terminal_state": "api_error",
                    "error": str(e)[:400],
                    "traceback": traceback.format_exc()[:1500],
                })
                out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
                continue

            # Primer report posterior al fire (P1/P5) o el status reportado (P4)
            post = None
            if FAMILY == "P4":
                response = inj.score_p4()
            else:
                if inj.record.fired:
                    for rep in res.belief_reports:
                        if rep["step"] > inj.record.step:
                            post = rep["belief"]
                            break
                response = inj.score_response(post) if post else None

            dist = None
            if res.final_answer and truth:
                try:
                    dist = geodesic((truth[0], truth[1]),
                                    (float(res.final_answer["lat"]), float(res.final_answer["lon"]))).km
                except (TypeError, ValueError, KeyError):
                    pass

            rec = {
                "cid": cid, "arm": arm, "model": MODEL,
                "family": FAMILY,
                "run_label": RUN_LABEL or None,
                "agent_max_steps": MAX_STEPS,
                "agent_min_steps": MIN_STEPS,
                "probe_min_step": PROBE_MIN_STEP,
                "probe_max_budget_frac": PROBE_MAX_BUDGET_FRAC,
                "title": cand.get("title", ""),
                "probe_fired": inj.record.fired,
                "probe_step": inj.record.step,
                "polarity": inj.record.polarity,
                "pre_top": inj.record.pre_top,
                "pre_mass": inj.record.pre_mass,
                "bulletin": inj.record.bulletin,
                "post_found": post is not None,
                "response": response,
                "distance_km": round(dist, 1) if dist is not None else None,
                "steps_used": res.steps_used,
                "terminal_state": res.terminal_state,
                "belief_reports": res.belief_reports,
                "trace": res.trace,
                "elapsed_s": round(time.time() - t0, 1),
            }
            results.append(rec)
            out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

            fired_s = f"step {inj.record.step} pol={inj.record.polarity}" if inj.record.fired else "NO FIRE"
            resp_s = ""
            if response:
                if response.get("family") == "P4":
                    resp_s = f"status={response.get('status')} false_verification={response.get('false_verification')}"
                elif response.get("family") == "P5":
                    resp_s = (f"attraction={response.get('distractor_attraction')} "
                              f"loc {response['loc_pre_mass']}→{response['loc_post_mass']}")
                elif inj.record.polarity == "i":
                    resp_s = f"residual={response['residual_mass']} (pre={response['pre_mass']})"
                else:
                    resp_s = f"elasticity={response['update_elasticity']} (Δlogit={response['delta_logit']})"
            print(f"--> fire: {fired_s} | {resp_s} | dist_final={dist and round(dist,1)}km | t={rec['elapsed_s']}s")

    # Resumen
    print("\n" + "=" * 70)
    print(f"{'cid':>8} {'arm':<13} {'fired':>5} {'pol':>3} {'pre':>6} {'métrica de respuesta':<38} {'dist':>8}")
    for r in results:
        if r.get("error"):
            print(f"{r['cid']:>8} {r['arm']:<13} ERROR: {r['error'][:60]}")
            continue
        resp = r.get("response") or {}
        if not resp:
            m = "—"
        elif resp.get("family") == "P4":
            m = f"status={resp.get('status')} false_verif={resp.get('false_verification')}"
        elif resp.get("family") == "P5":
            m = f"attraction={resp.get('distractor_attraction')} loc {resp.get('loc_pre_mass')}→{resp.get('loc_post_mass')}"
        elif r.get("polarity") == "i":
            m = f"residual={resp.get('residual_mass')} ret={resp.get('retention_ratio')}"
        else:
            m = f"elasticity={resp.get('update_elasticity')} Δlogit={resp.get('delta_logit')}"
        d = f"{r['distance_km']}km" if r.get("distance_km") is not None else "NA"
        print(f"{r['cid']:>8} {r['arm']:<13} {str(r['probe_fired']):>5} {str(r.get('polarity') or '-'):>3} "
              f"{str(r.get('pre_mass') or '-'):>6} {m:<38} {d:>8}")
    if FAMILY == "P1":
        for cid in cids:
            by_arm = {
                r.get("arm"): r for r in results
                if r.get("cid") == cid and not r.get("error")
                and str(r.get("family", "P1")).upper() == "P1"
                and r.get("run_label") == (RUN_LABEL or None)
                and r.get("arm") in {"contradiction", "placebo"}
            }
            if set(by_arm) == {"contradiction", "placebo"}:
                polarities = {r.get("polarity") for r in by_arm.values()}
                if len(polarities) != 1:
                    print(
                        f"[WARN] cid={cid}: contradiction/placebo dispararon polaridades "
                        f"distintas ({sorted(str(p) for p in polarities)}); no son comparables."
                    )
                else:
                    print(
                        f"[INFO] cid={cid}: polaridad emparejable={next(iter(polarities))}, "
                        "pero los prefijos siguen siendo trayectorias distintas."
                    )
    print(f"\nOutput: {out_path}")


if __name__ == "__main__":
    main()
