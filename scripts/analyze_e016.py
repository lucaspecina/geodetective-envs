"""Análisis E016: comparación cross-model × arm + métricas belief + material cualitativo.

Produce, a partir de experiments/E016_belief_pilot/results_*.json:

1. QUANT — tabla por (modelo, arm): submit rate, distancia (mediana/media/buckets),
   year MAE, steps, beliefs/run, reward total medio, % de steps de investigación
   "muerta" (reward<=0), lock-in rate (top candidato inicial == final Y >100km),
   switches de hipótesis top, citation validity del evidence_chain.
2. PAIRED — on vs off por (modelo, cid): delta de distancia y steps (la ablation
   de interferencia).
3. DIGEST (--digest) — markdown cualitativo por corrida: thinking de steps clave,
   trayectoria de beliefs (top candidato + peso + dist por report), evidence chain
   con verificación estructural (¿el step citado tiene un evento de esa tool?),
   terminal state. Materia prima para las autopsias de failure modes del paper.

Uso:
    python scripts/analyze_e016.py                 # tablas quant + paired
    python scripts/analyze_e016.py --digest        # + experiments/E016_belief_pilot/digest.md
    python scripts/analyze_e016.py --json out.json # dump estructurado
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

EXP_DIR = Path("experiments/E016_belief_pilot")

LOCKIN_DIST_KM = 100.0  # top inicial == top final Y a más de esto del truth → lock-in


# === Carga ===

def load_all() -> list[dict]:
    """Cargar todos los results_{model}_belief-{arm}.json → records con model/arm.

    Prefiere el crudo si existe (tiene imágenes para el viewer); si solo está el
    .slim (lo que se commitea), usa ese — el análisis no necesita los base64.
    """
    records = []
    seen_stems = set()
    # Crudos primero; los .slim solo si no está el crudo correspondiente.
    candidates = sorted(EXP_DIR.glob("results_*_belief-*.json"),
                        key=lambda p: p.name.endswith(".slim.json"))
    for p in candidates:
        stem = p.name.replace(".slim.json", "").replace(".json", "")
        if stem in seen_stems:
            continue
        m = re.match(r"results_(.+)_belief-(on|off)$", stem)
        if not m:
            continue
        seen_stems.add(stem)
        try:
            for r in json.loads(p.read_text(encoding="utf-8")):
                rk = r.get("react") or {}
                r["_model"] = rk.get("model") or m.group(1)
                r["_arm"] = m.group(2)
                records.append(r)
        except Exception as e:
            print(f"[WARN] no pude leer {p.name}: {e}")
    return records


# === Métricas por corrida ===

def _parse_year(y) -> float | None:
    if y is None:
        return None
    s = str(y).strip()
    if "-" in s:
        try:
            a, b = s.split("-", 1)
            return (float(a) + float(b)) / 2
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _top_of_report(rep: dict) -> dict | None:
    cands = (rep.get("belief") or {}).get("location_belief") or []
    if not cands:
        return None
    return max(cands, key=lambda c: c.get("weight", 0))


def check_evidence_chain(rk: dict) -> dict | None:
    """Verificación ESTRUCTURAL de claims: ¿el step citado tiene un evento de esa tool?

    No valida el contenido del claim (eso es el verificador semántico, pendiente);
    valida que la cita (step, tool) apunte a algo que existe en el log.
    """
    chain = (rk.get("final_answer") or {}).get("evidence_chain")
    if not chain:
        return None
    trace = rk.get("trace") or []
    by_step = defaultdict(set)
    for ev in trace:
        by_step[ev.get("step")].add(ev.get("type", ""))
    results = []
    for c in chain:
        tool = str(c.get("tool", "")).removeprefix("functions.")
        step = c.get("step")
        types = by_step.get(step, set())
        # match laxo: el type del trace puede ser variante (fetch_url_with_images, image_search_pick)
        ok = any(t == tool or t.startswith(tool) or tool.startswith(t) for t in types if t)
        results.append({"claim": c.get("claim", ""), "step": step, "tool": tool, "citation_valid": ok})
    n_ok = sum(1 for r in results if r["citation_valid"])
    return {"n_claims": len(results), "n_valid_citations": n_ok, "claims": results}


def per_run_metrics(r: dict) -> dict:
    rk = r.get("react") or {}
    reports = rk.get("belief_reports") or []
    traj = rk.get("belief_trajectory") or {}
    per_rep = traj.get("per_report") or []

    # Lock-in y switches sobre el top candidato de cada report
    tops = [t for t in (_top_of_report(rep) for rep in reports) if t]
    switches = sum(1 for a, b in zip(tops, tops[1:]) if a.get("name") != b.get("name"))
    lockin = None
    dist = rk.get("distance_km")
    if len(tops) >= 2 and dist is not None:
        lockin = tops[0].get("name") == tops[-1].get("name") and dist > LOCKIN_DIST_KM

    # PIVOT QUALITY: cada switch del top candidato, firmado por su reward.
    # Un pivot es PRODUCTIVO si el report donde ocurre acerca la creencia a la
    # verdad (reward > 0) — la versión mecánica de "refutation-driven belief
    # revision" de CORRAL, sin judge. Requiere alinear reports con per_report
    # del trajectory (mismo orden).
    pivots_productive = 0
    pivots_harmful = 0
    if len(per_rep) == len(reports):
        prev_name = None
        for rep, scored in zip(reports, per_rep):
            t = _top_of_report(rep)
            name = t.get("name") if t else None
            if prev_name is not None and name != prev_name:
                if (scored.get("reward_vs_prev") or 0) > 0:
                    pivots_productive += 1
                else:
                    pivots_harmful += 1
            prev_name = name

    dead_steps = sum(1 for p in per_rep if (p.get("reward_vs_prev") or 0) <= 0)

    year_err = None
    ty = r.get("year")
    py = _parse_year((rk.get("final_answer") or {}).get("year"))
    if ty is not None and py is not None:
        year_err = abs(float(ty) - py)

    ec = check_evidence_chain(rk)

    return {
        "cid": r.get("cid"), "model": r["_model"], "arm": r["_arm"],
        "run_idx": r.get("run_idx"),
        "error": (rk.get("error") or None),
        "submit": bool(rk.get("submit_called")),
        "distance_km": dist,
        "year_err": year_err,
        "steps": rk.get("steps_used"),
        "n_beliefs": len(reports),
        "total_reward": traj.get("total_reward"),
        "dead_reports": dead_steps,
        "n_reports_scored": len(per_rep),
        "switches": switches,
        "pivots_productive": pivots_productive,
        "pivots_harmful": pivots_harmful,
        "lockin": lockin,
        "ec_claims": ec["n_claims"] if ec else None,
        "ec_valid": ec["n_valid_citations"] if ec else None,
        "terminal_state": rk.get("terminal_state"),
    }


# === Agregación ===

def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def aggregate(rows: list[dict]) -> dict:
    out = {}
    dists = [x["distance_km"] for x in rows if x["distance_km"] is not None]
    yerrs = [x["year_err"] for x in rows if x["year_err"] is not None]
    steps = [x["steps"] for x in rows if x["steps"]]
    rewards = [x["total_reward"] for x in rows if x["total_reward"] is not None]
    lock = [x["lockin"] for x in rows if x["lockin"] is not None]
    ec_claims = sum(x["ec_claims"] or 0 for x in rows)
    ec_valid = sum(x["ec_valid"] or 0 for x in rows)
    dead = sum(x["dead_reports"] for x in rows)
    scored = sum(x["n_reports_scored"] for x in rows)

    out["n_runs"] = len(rows)
    out["n_fail"] = sum(1 for x in rows if x["error"])
    out["submit_rate"] = sum(1 for x in rows if x["submit"]) / len(rows) if rows else None
    out["dist_median"] = _med(dists)
    out["dist_mean"] = sum(dists) / len(dists) if dists else None
    out["lt25km"] = sum(1 for d in dists if d < 25) / len(dists) if dists else None
    out["gt1000km"] = sum(1 for d in dists if d > 1000) / len(dists) if dists else None
    out["year_mae"] = sum(yerrs) / len(yerrs) if yerrs else None
    out["steps_avg"] = sum(steps) / len(steps) if steps else None
    out["beliefs_avg"] = sum(x["n_beliefs"] for x in rows) / len(rows) if rows else None
    out["reward_avg"] = sum(rewards) / len(rewards) if rewards else None
    out["dead_report_rate"] = dead / scored if scored else None
    out["lockin_rate"] = sum(lock) / len(lock) if lock else None
    out["switches_avg"] = (sum(x["switches"] for x in rows) / len(rows)) if rows else None
    piv_p = sum(x["pivots_productive"] for x in rows)
    piv_h = sum(x["pivots_harmful"] for x in rows)
    out["pivot_productive_rate"] = piv_p / (piv_p + piv_h) if (piv_p + piv_h) else None
    out["citation_valid_rate"] = ec_valid / ec_claims if ec_claims else None
    return out


def fmt(v, spec=".1f", pct=False):
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.0f}%"
    return format(v, spec)


def print_quant(per_runs: list[dict]) -> dict:
    groups = defaultdict(list)
    for x in per_runs:
        groups[(x["model"], x["arm"])].append(x)
    aggs = {k: aggregate(v) for k, v in sorted(groups.items())}

    print("\n=== QUANT por (modelo, arm) ===")
    hdr = (f"{'modelo':<22} {'arm':<4} {'n':>3} {'fail':>4} {'med_km':>8} {'<25km':>6} "
           f"{'>1000':>6} {'yMAE':>6} {'steps':>6} {'belfs':>6} {'reward':>7} "
           f"{'dead%':>6} {'lockin':>7} {'sw':>4} {'piv+%':>6} {'cit_ok':>7}")
    print(hdr)
    print("-" * len(hdr))
    for (model, arm), a in aggs.items():
        print(f"{model:<22} {arm:<4} {a['n_runs']:>3} {a['n_fail']:>4} "
              f"{fmt(a['dist_median'], '.0f'):>8} {fmt(a['lt25km'], pct=True):>6} "
              f"{fmt(a['gt1000km'], pct=True):>6} {fmt(a['year_mae'], '.0f'):>6} "
              f"{fmt(a['steps_avg']):>6} {fmt(a['beliefs_avg']):>6} "
              f"{fmt(a['reward_avg'], '+.1f'):>7} {fmt(a['dead_report_rate'], pct=True):>6} "
              f"{fmt(a['lockin_rate'], pct=True):>7} {fmt(a['switches_avg']):>4} "
              f"{fmt(a['pivot_productive_rate'], pct=True):>6} "
              f"{fmt(a['citation_valid_rate'], pct=True):>7}")
    return {f"{m}|{a}": v for (m, a), v in aggs.items()}


def print_paired(per_runs: list[dict]) -> None:
    """on vs off por (modelo, cid): media de distancia entre runs."""
    cell = defaultdict(list)
    for x in per_runs:
        if x["distance_km"] is not None:
            cell[(x["model"], x["cid"], x["arm"])].append(x["distance_km"])
    pairs = defaultdict(dict)
    for (model, cid, arm), ds in cell.items():
        pairs[(model, cid)][arm] = sum(ds) / len(ds)

    print("\n=== PAIRED on vs off (media por foto; Δ>0 = on peor) ===")
    by_model = defaultdict(list)
    for (model, cid), arms in sorted(pairs.items()):
        if "on" in arms and "off" in arms:
            delta = arms["on"] - arms["off"]
            by_model[model].append(delta)
            print(f"  {model:<22} cid={cid:>8}  off={arms['off']:>9.1f}km  on={arms['on']:>9.1f}km  Δ={delta:>+9.1f}km")
    for model, deltas in by_model.items():
        print(f"  --> {model}: Δ mediana {sorted(deltas)[len(deltas)//2]:+.1f} km sobre {len(deltas)} fotos "
              f"(on peor en {sum(1 for d in deltas if d > 0)}/{len(deltas)})")


# === Digest cualitativo ===

def make_digest(records: list[dict], per_runs: list[dict], out_path: Path) -> None:
    by_key = {(x["model"], x["arm"], x["cid"], x["run_idx"]): x for x in per_runs}
    lines = ["# E016 — digest cualitativo por corrida",
             "",
             "> Generado por `scripts/analyze_e016.py --digest`. Materia prima para autopsias",
             "> de failure modes. Cada corrida: beliefs (top + dist al truth), thinking de los",
             "> steps clave (primero, switches, último), evidence chain con check estructural.",
             ""]
    for r in sorted(records, key=lambda x: (x["_model"], x["_arm"], x.get("cid", 0), x.get("run_idx", 0))):
        rk = r.get("react") or {}
        m = by_key.get((r["_model"], r["_arm"], r.get("cid"), r.get("run_idx")), {})
        dist = rk.get("distance_km")
        fa = rk.get("final_answer") or {}
        lines.append(f"## {r['_model']} · belief-{r['_arm']} · cid={r.get('cid')} run={r.get('run_idx')} "
                     f"— {'%.1f km' % dist if dist is not None else 'NA'} · year {fa.get('year', '—')} "
                     f"(truth {r.get('year')}) · {rk.get('terminal_state')}")
        lines.append(f"*{r.get('title', '')}* — {r.get('bucket_pais')}/{r.get('bucket_decada')}")
        if rk.get("error"):
            lines.append(f"**ERROR**: {str(rk['error'])[:200]}")

        # Trayectoria de beliefs
        traj = (rk.get("belief_trajectory") or {}).get("per_report") or []
        if traj:
            lines.append("")
            lines.append("| step | top | w | dist_top | reward |")
            lines.append("|---|---|---|---|---|")
            for p in traj:
                lines.append(f"| {p['step']} | {p.get('top_candidate') or '—'} | {p.get('top_weight') or 0} "
                             f"| {p.get('top_dist_km')} km | {p.get('reward_vs_prev'):+.2f} |")

        # Thinking de steps clave: primero, último, y donde cambió el top
        trace = rk.get("trace") or []
        thoughts = [(ev.get("step"), ev.get("content", "")) for ev in trace if ev.get("type") == "thinking"]
        key_steps = set()
        if thoughts:
            key_steps.add(thoughts[0][0])
            key_steps.add(thoughts[-1][0])
        reports = rk.get("belief_reports") or []
        prev_top = None
        for rep in reports:
            t = _top_of_report(rep)
            name = t.get("name") if t else None
            if prev_top is not None and name != prev_top:
                key_steps.add(rep["step"])
            prev_top = name
        for s, txt in thoughts:
            if s in key_steps and txt.strip():
                lines.append(f"\n**thinking s{s}**: {txt.strip()[:450]}")

        # Evidence chain con check estructural
        ec = check_evidence_chain(rk)
        if ec:
            lines.append("")
            lines.append(f"**Evidence chain** ({ec['n_valid_citations']}/{ec['n_claims']} citas estructuralmente válidas):")
            for c in ec["claims"]:
                mark = "✓" if c["citation_valid"] else "✗ CITA INVÁLIDA"
                lines.append(f"- [{mark}] (s{c['step']}, {c['tool']}) {c['claim'][:160]}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDigest cualitativo: {out_path} ({len(records)} corridas)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", action="store_true", help="generar digest.md cualitativo")
    ap.add_argument("--json", type=Path, default=None, help="dump estructurado a JSON")
    args = ap.parse_args()

    records = load_all()
    if not records:
        raise SystemExit(f"no hay results en {EXP_DIR}")
    per_runs = [per_run_metrics(r) for r in records]

    aggs = print_quant(per_runs)
    print_paired(per_runs)

    if args.digest:
        make_digest(records, per_runs, EXP_DIR / "digest.md")
    if args.json:
        args.json.write_text(json.dumps({"aggregates": aggs, "per_run": per_runs},
                                        indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON: {args.json}")


if __name__ == "__main__":
    main()
