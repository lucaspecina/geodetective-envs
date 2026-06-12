"""E016 pilot: belief-state ablation (modelos × fotos × N runs × {belief on, off}).

Diseño (belief_state_redesign.md §6): valida que los beliefs discriminan modelos
y hacen visible el lock-in, y mide la interferencia de la elicitación (on vs off).
Ambos brazos SIN budget por default: el brazo OFF es el scaffold canónico puro;
budget es ablation separada (TOOL_BUDGET env si se quiere).

Uso:
    # Wave 1 (sanity): 1 modelo × 10 fotos × N=1 × ambos brazos
    MODELS=gpt-5.4-mini N_RUNS=1 python scripts/run_e016_pilot.py

    # Pilot completo
    MODELS="gpt-5.4-mini,claude-sonnet-4-6,claude-opus-4-6" N_RUNS=3 python scripts/run_e016_pilot.py

    ARMS=on            # solo brazo belief (default "on,off")
    CIDS="963644"      # subset de fotos
    N_WORKERS=6        # paralelismo global (rate limits son por deployment)

Output: experiments/E016_belief_pilot/results_{model}_{arm}.json (merge/resume por cid+run).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import product
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
from geodetective.eval.belief_scoring import Belief, score_belief, score_belief_sequence

# === Config ===
EXP_DIR = Path("experiments/E016_belief_pilot")
PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", "corpus/photos"))
PILOT_PHOTOS = Path(os.environ.get("PILOT_PHOTOS", str(EXP_DIR / "pilot_photos.json")))

MODELS = [m.strip() for m in os.environ.get("MODELS", "gpt-5.4-mini").split(",")]
ARMS = [a.strip() for a in os.environ.get("ARMS", "on,off").split(",")]
N_RUNS = int(os.environ.get("N_RUNS", "1"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "30"))
BELIEF_NUDGE_AFTER = int(os.environ.get("BELIEF_NUDGE_AFTER", "3"))
TOOL_BUDGET = float(os.environ["TOOL_BUDGET"]) if os.environ.get("TOOL_BUDGET") else None
N_WORKERS = int(os.environ.get("N_WORKERS", "6"))

_write_lock = threading.Lock()


def out_path(model: str, arm: str) -> Path:
    m = model.replace(".", "_").replace("/", "_")
    return EXP_DIR / f"results_{m}_belief-{arm}.json"


def score_trajectory(candidate: dict, belief_reports: list[dict]) -> dict | None:
    truth = candidate.get("geo")
    if not truth or not belief_reports:
        return None
    ty = float(candidate["year"]) if candidate.get("year") else None
    beliefs = [Belief.from_dict(r["belief"]) for r in belief_reports]
    scores, rewards = score_belief_sequence(beliefs, truth[0], truth[1], truth_year=ty,
                                            prepend_ignorance=True)
    per_report = []
    for i, (rep, b) in enumerate(zip(belief_reports, beliefs)):
        bs = score_belief(b, truth[0], truth[1], truth_year=ty)
        top = max(b.location, key=lambda c: c.weight) if b.location else None
        per_report.append({
            "step": rep["step"],
            "score_total": round(scores[i + 1], 3),
            "reward_vs_prev": round(rewards[i], 3),
            "info_gain_loc_nats": round(bs.info_gain_location_nats, 3),
            "info_gain_year_nats": round(bs.info_gain_year_nats, 3) if bs.info_gain_year_nats is not None else None,
            "top_candidate": top.name if top else None,
            "top_weight": top.weight if top else None,
            "top_dist_km": round(geodesic((truth[0], truth[1]), (top.lat, top.lon)).km, 1) if top else None,
        })
    return {
        "prior_ignorance_score": round(scores[0], 3),
        "final_score": round(scores[-1], 3),
        "total_reward": round(sum(rewards), 3),
        "per_report": per_report,
    }


def process_one(task: tuple) -> tuple:
    model, arm, run_idx, cand = task
    cid = cand["cid"]
    img_path = PHOTOS_DIR / f"{cid}_clean_v{CLEAN_VERSION}.jpg"
    base = {**cand, "run_idx": run_idx}
    if not img_path.exists():
        return model, arm, {**base, "react": {"model": model, "error": f"image not found: {img_path}"}}

    t0 = time.time()
    try:
        res = run_react_agent(
            image_path=img_path,
            model=model,
            max_steps=MAX_STEPS,
            verbose=False,
            provider=cand.get("provider"),
            provenance_source=cand.get("provenance_source", ""),
            belief_mode=(arm == "on"),
            belief_nudge_after=BELIEF_NUDGE_AFTER,
            tool_budget=TOOL_BUDGET,
        )
    except Exception as e:
        return model, arm, {**base, "react": {
            "model": model, "arm": arm, "max_steps": MAX_STEPS,
            "elapsed_seconds": round(time.time() - t0, 1),
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "traceback": traceback.format_exc()[:2000],
        }}

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

    return model, arm, {**base, "react": {
        "model": model, "arm": arm, "max_steps": MAX_STEPS,
        "belief_nudge_after": BELIEF_NUDGE_AFTER if arm == "on" else None,
        "budget_total": res.budget_total, "budget_spent": res.budget_spent,
        "elapsed_seconds": round(time.time() - t0, 1),
        "final_answer": res.final_answer,
        "distance_km": dist_km,
        "steps_used": res.steps_used,
        "submit_called": res.submit_called,
        "terminal_state": res.terminal_state,
        "error": res.error,
        "belief_report_count": res.belief_report_count,
        "belief_reports": res.belief_reports,
        "belief_trajectory": score_trajectory(cand, res.belief_reports),
        "evidence_chain": (res.final_answer or {}).get("evidence_chain"),
        "trace": res.trace,
    }}


def save_result(model: str, arm: str, record: dict) -> None:
    p = out_path(model, arm)
    with _write_lock:
        existing = []
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing = [r for r in existing
                    if not (r.get("cid") == record["cid"] and r.get("run_idx") == record["run_idx"])]
        existing.append(record)
        p.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    photos = json.loads(PILOT_PHOTOS.read_text(encoding="utf-8"))
    if os.environ.get("CIDS"):
        keep = {int(c.strip()) for c in os.environ["CIDS"].split(",")}
        photos = [p for p in photos if p["cid"] in keep]

    # Tareas pendientes (resume: skip si ya hay resultado válido para cid+run)
    tasks = []
    for model, arm in product(MODELS, ARMS):
        done = set()
        p = out_path(model, arm)
        if p.exists():
            try:
                for r in json.loads(p.read_text(encoding="utf-8")):
                    rk = r.get("react") or {}
                    if rk.get("final_answer") or rk.get("error"):
                        done.add((r.get("cid"), r.get("run_idx")))
            except Exception:
                pass
        for cand, run_idx in product(photos, range(N_RUNS)):
            if (cand["cid"], run_idx) not in done:
                tasks.append((model, arm, run_idx, cand))

    total = len(MODELS) * len(ARMS) * len(photos) * N_RUNS
    print("=" * 70)
    print("E016 PILOT — belief-state ablation")
    print(f"  Models: {MODELS} | Arms: {ARMS} | N_RUNS: {N_RUNS} | MAX_STEPS: {MAX_STEPS}")
    print(f"  Budget: {TOOL_BUDGET} | Workers: {N_WORKERS}")
    print(f"  Fotos: {len(photos)} | Tareas: {len(tasks)} pendientes de {total} totales")
    print("=" * 70)
    if not tasks:
        print("nada que correr — todo done")
        return

    t0 = time.time()
    n_done = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(process_one, t): t for t in tasks}
        for fut in as_completed(futures):
            model, arm, record = fut.result()
            save_result(model, arm, record)
            n_done += 1
            rk = record.get("react", {})
            d = rk.get("distance_km")
            d_s = f"{d:.1f}km" if d is not None else "NA"
            err = rk.get("error")
            tag = "[FAIL]" if err else "[OK]"
            traj = rk.get("belief_trajectory")
            tr_s = f" reward={traj['total_reward']:+.1f}n" if traj else ""
            print(f"  {tag} {n_done}/{len(tasks)} {model} belief-{arm} cid={record['cid']} run={record['run_idx']} "
                  f"dist={d_s} steps={rk.get('steps_used')}{tr_s} t={rk.get('elapsed_seconds')}s")
            if err:
                print(f"        ERR: {str(err)[:140]}")

    print(f"\nDone in {(time.time() - t0) / 60:.1f} min. Outputs en {EXP_DIR}/results_*.json")


if __name__ == "__main__":
    main()
