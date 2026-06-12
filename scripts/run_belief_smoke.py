"""Smoke test del belief-mode end-to-end (E016, #47).

Corre el agente ReAct con belief_mode=True sobre 1+ fotos del corpus y puntúa
post-hoc la trayectoria de creencias contra ground truth (el runtime NO puntúa
— acá es donde el ground truth entra por primera vez).

Uso:
    python scripts/run_belief_smoke.py                          # gpt-5.4-mini × foto default
    MODEL=claude-sonnet-4-6 python scripts/run_belief_smoke.py
    CIDS="2165013,1248470" python scripts/run_belief_smoke.py
    MAX_STEPS=30 BELIEF_NUDGE_AFTER=3 python scripts/run_belief_smoke.py

Output: experiments/E016_belief_pilot/smoke_{model}.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# UTF-8 stdout en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path("src").resolve()))
from geopy.distance import geodesic

from geodetective.agents.react import run_react_agent
from geodetective.corpus import CLEAN_VERSION
from geodetective.eval.belief_scoring import Belief, score_belief, score_belief_sequence

# === Config ===
EXP_DIR = Path(os.environ.get("EXP_DIR", "experiments/E016_belief_pilot"))
PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", "corpus/photos"))
CANDIDATES_PATH = Path(os.environ.get("CANDIDATES_PATH", "experiments/E007_sample_diverso/candidates_v2_final.json"))

MODEL = os.environ.get("MODEL", "gpt-5.4-mini")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "50"))
BELIEF_NUDGE_AFTER = int(os.environ.get("BELIEF_NUDGE_AFTER", "3"))
TOOL_BUDGET = float(os.environ["TOOL_BUDGET"]) if os.environ.get("TOOL_BUDGET") else None
DEFAULT_CIDS = "1140232"  # Estocolmo 1916, corpus v2


def load_candidates(cids: set[int]) -> list[dict]:
    all_candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    found = [c for c in all_candidates if c["cid"] in cids]
    missing = cids - {c["cid"] for c in found}
    if missing:
        print(f"[WARN] cids no encontrados en {CANDIDATES_PATH}: {missing}")
    return found


def score_trajectory(candidate: dict, belief_reports: list[dict]) -> dict:
    """Scoring post-hoc de la trayectoria de creencias contra ground truth."""
    truth = candidate.get("geo")
    truth_year = candidate.get("year")
    beliefs = [Belief.from_dict(r["belief"]) for r in belief_reports]
    scores, rewards = score_belief_sequence(
        beliefs, truth[0], truth[1],
        truth_year=float(truth_year) if truth_year else None,
        prepend_ignorance=True,
    )
    per_report = []
    for i, (rep, b) in enumerate(zip(belief_reports, beliefs)):
        bs = score_belief(b, truth[0], truth[1],
                          truth_year=float(truth_year) if truth_year else None)
        top = max(b.location, key=lambda c: c.weight) if b.location else None
        top_dist = geodesic((truth[0], truth[1]), (top.lat, top.lon)).km if top else None
        per_report.append({
            "step": rep["step"],
            "n_location": len(b.location),
            "n_year": len(b.year),
            "top_candidate": top.name if top else None,
            "top_weight": top.weight if top else None,
            "top_dist_km": round(top_dist, 1) if top_dist is not None else None,
            "score_total": round(scores[i + 1], 3),       # [0] es el prior de ignorancia
            "reward_vs_prev": round(rewards[i], 3),
            "info_gain_loc_nats": round(bs.info_gain_location_nats, 3),
            "rationale": b.rationale[:200],
        })
    return {
        "prior_ignorance_score": round(scores[0], 3),
        "final_score": round(scores[-1], 3),
        "total_reward": round(sum(rewards), 3),
        "per_report": per_report,
    }


def main() -> None:
    cids = {int(c.strip()) for c in os.environ.get("CIDS", DEFAULT_CIDS).split(",")}
    candidates = load_candidates(cids)
    if not candidates:
        raise SystemExit("no hay fotos para correr")

    EXP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXP_DIR / f"smoke_{MODEL.replace('.', '_').replace('/', '_')}.json"
    # Merge por cid: corridas previas de OTRAS fotos se preservan; re-corridas
    # de la misma foto se reemplazan.
    results = []
    if out_path.exists():
        try:
            results = [r for r in json.loads(out_path.read_text(encoding="utf-8"))
                       if r.get("cid") not in cids]
        except Exception:
            results = []

    print("=" * 70)
    print("E016 BELIEF-MODE SMOKE TEST")
    print(f"  Model: {MODEL} | MAX_STEPS: {MAX_STEPS} | nudge_after: {BELIEF_NUDGE_AFTER} | budget: {TOOL_BUDGET}")
    print(f"  Fotos: {sorted(cids)}")
    print("=" * 70)

    for cand in candidates:
        cid = cand["cid"]
        img_path = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
        if not img_path.exists():
            print(f"[SKIP] cid={cid}: no existe {img_path}")
            continue
        print(f"\n### cid={cid} | {cand.get('title', '')[:70]} | truth={cand.get('geo')} year={cand.get('year')}\n")
        t0 = time.time()
        try:
            res = run_react_agent(
                image_path=img_path,
                model=MODEL,
                max_steps=MAX_STEPS,
                verbose=True,
                provider=cand.get("provider"),
                provenance_source=cand.get("provenance_source", ""),
                belief_mode=True,
                belief_nudge_after=BELIEF_NUDGE_AFTER,
                tool_budget=TOOL_BUDGET,
            )
        except Exception as e:
            print(f"[FAIL] {type(e).__name__}: {e}")
            results.append({**cand, "react": {"model": MODEL, "error": str(e)[:500],
                                              "traceback": traceback.format_exc()[:2000]}})
            continue
        elapsed = time.time() - t0

        truth = cand.get("geo")
        dist_km = None
        if res.final_answer and truth:
            try:
                dist_km = geodesic(
                    (truth[0], truth[1]),
                    (float(res.final_answer["lat"]), float(res.final_answer["lon"])),
                ).km
            except (TypeError, ValueError, KeyError):
                pass

        trajectory = None
        if res.belief_reports:
            try:
                trajectory = score_trajectory(cand, res.belief_reports)
            except Exception as e:
                print(f"[WARN] scoring de trayectoria falló: {type(e).__name__}: {e}")

        results.append({**cand, "react": {
            "model": MODEL, "max_steps": MAX_STEPS,
            "belief_mode": True, "belief_nudge_after": BELIEF_NUDGE_AFTER,
            "elapsed_seconds": round(elapsed, 1),
            "final_answer": res.final_answer,
            "distance_km": dist_km,
            "steps_used": res.steps_used,
            "submit_called": res.submit_called,
            "terminal_state": res.terminal_state,
            "error": res.error,
            "belief_report_count": res.belief_report_count,
            "budget_total": res.budget_total,
            "budget_spent": res.budget_spent,
            "budget_spent_by_tool": res.budget_spent_by_tool,
            "budget_blocked_count": res.budget_blocked_count,
            "belief_reports": res.belief_reports,
            "belief_trajectory": trajectory,
            "evidence_chain": (res.final_answer or {}).get("evidence_chain"),
            "trace": res.trace,
        }})
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

        # === Resumen en consola ===
        print(f"\n{'-' * 70}")
        print(f"cid={cid} | dist_final={f'{dist_km:.1f}km' if dist_km is not None else 'NA'} | "
              f"steps={res.steps_used} | beliefs={res.belief_report_count} | t={elapsed:.0f}s")
        if trajectory:
            print(f"\nCurva de creencias (S menor = mejor; prior ignorancia = {trajectory['prior_ignorance_score']}):")
            print(f"{'step':>5} {'S_total':>9} {'reward':>8} {'top candidato':<30} {'w':>5} {'dist_top':>9}")
            for p in trajectory["per_report"]:
                dist_top_s = f"{p['top_dist_km']}km" if p["top_dist_km"] is not None else "NA"
                print(f"{p['step']:>5} {p['score_total']:>9.3f} {p['reward_vs_prev']:>+8.3f} "
                      f"{(p['top_candidate'] or '-')[:30]:<30} {p['top_weight'] or 0:>5.2f} "
                      f"{dist_top_s:>9}")
            print(f"\nReward total (mejora vs ignorancia): {trajectory['total_reward']:+.3f} nats")
        ec = (res.final_answer or {}).get("evidence_chain")
        if ec:
            print(f"\nEvidence chain ({len(ec)} claims):")
            for c in ec:
                print(f"  - [step {c.get('step')}, {c.get('tool')}] {str(c.get('claim'))[:120]}")
        else:
            print("\nEvidence chain: NO reportada")

    print(f"\nOutput: {out_path}")


if __name__ == "__main__":
    main()
