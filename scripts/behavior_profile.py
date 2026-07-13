"""Perfil conductual por modelo sobre corridas NATURALES (capa 2 — sin intervención).

Computa, desde los registros existentes (results de E016+), las behavioral
signatures del codebook v1.2 + las nuevas propuestas (jul 2026): todo mecánico,
post-hoc, sin LLM-judge. Nombres descriptivos (lo observado, no la intención).

Signatures por corrida (belief-on; las marcadas [t] también corren en belief-off
porque solo usan el trace):
- first_hypothesis_dominance / _wrong: cluster del top del primer report == cluster
  del submit final (± estando a >100km del GT).
- single_track: ningún cluster rival llegó a peso ≥0.1 en toda la corrida.
- decorative_alternatives: reportó un rival con peso ≥0.2 y NUNCA ejecutó una tool
  ligada a ese candidato (linkage por coords ≤25km o token del nombre en args).
- confidence_ratchet_wrong: peso del top no-decreciente a lo largo de ≥3 reports y
  outcome final >100km.
- wrong_persistence / wrong_entrenchment: codebook A1a/A1b (persistencia del top W;
  entrenchment = ≥3 reports + ≥6 obs. exitosas candidate-linked + Δw neto ≥0.10).
- correct_mass_abandonment: masa del cluster correcto cae ≥0.15 (o final <0.25 o
  sale del top-5) y la corrida termina W. (codebook A2 fuerte)
- recovery / never_correct: ¿el top entró alguna vez al radio de 25km? ¿se recuperó
  de un arranque W?
- early_uncertain_commit / early_overconfident_wrong / overconfident_wrong: B1 ×3.
- correct_top_deterioration: B2 (top estuvo C y el submit terminó W).
- stale_confidence_at_submit: último report a >3 steps del submit.
- year_belief_frozen: el year_belief no cambió después del primer report.
- hypothesis_echo_share [t]: fracción de queries de búsqueda que contienen el nombre
  del top vigente (búsqueda espejo / confirmatoria).
- exact_query_repetition [t]: tool+args idénticos (canonicalizados) repetidos.
- post_commitment_only_checks [t*]: TODA verificación visual (street_view/static_map)
  ocurre después del último report de creencias (nunca exploratoria). *belief-on.
- low_evidence_submit [t]: <3 tool calls totales.

Uso:
    python scripts/behavior_profile.py                       # E016 por default
    python scripts/behavior_profile.py --dir experiments/E016_belief_pilot --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geodetective.eval.belief_scoring import great_circle_km
from geodetective.probes import CORRECT_KM, WRONG_KM, cluster_mass, top_candidate

SEARCH_TOOLS = {"web_search", "image_search", "fetch_url", "fetch_url_with_images"}
VISUAL_CHECK_TOOLS = {"street_view", "static_map"}
GEO_ARG_TOOLS = {"static_map", "street_view", "historical_query_at", "reverse_geocode"}
STOPWORDS = {"de", "la", "el", "los", "las", "del", "the", "of", "and", "y", "en", "do", "da"}


# === Linkage mecánico tool↔candidato (codebook §0: aproximado, documentado) ===

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]", " ", s)


def _name_tokens(name: str) -> set[str]:
    return {t for t in _norm(name).split() if len(t) >= 4 and t not in STOPWORDS}


def event_linked_to(ev: dict, cand: dict) -> bool:
    """¿Este evento de tool está ligado al candidato? (coords ≤25km o token del nombre)."""
    t = ev.get("type", "")
    args = ev.get("args") or {}
    # 1) por coordenadas en args
    if t in GEO_ARG_TOOLS or ("lat" in args and "lon" in args):
        try:
            d = great_circle_km(float(args["lat"]), float(args["lon"]),
                                float(cand["lat"]), float(cand["lon"]))
            if d <= CORRECT_KM:
                return True
        except (KeyError, TypeError, ValueError):
            pass
    # 2) por tokens del nombre en query/url
    text = _norm(str(ev.get("query") or "") + " " + str(ev.get("url") or "")
                 + " " + str(args.get("query") or ""))
    toks = _name_tokens(str(cand.get("name") or ""))
    return bool(toks) and any(tok in text for tok in toks)


def _successful_observation(ev: dict) -> bool:
    t = ev.get("type", "")
    if t.endswith("_error") or t in {"thinking", "thinking_block", "report_belief",
                                     "belief_nudge", "submit", "image_context_cleanup"}:
        return False
    if t in SEARCH_TOOLS:
        return (ev.get("result_count") or ev.get("n_cells") or ev.get("text_len") or 0) > 0
    return t in GEO_ARG_TOOLS or t in {"geocode", "crop_image", "crop_image_relative",
                                       "historical_query"}


# === Signatures por corrida ===

def profile_run(record: dict) -> dict:
    rk = record.get("react") or {}
    trace = rk.get("trace") or []
    reports = rk.get("belief_reports") or []
    truth = record.get("geo")
    fa = rk.get("final_answer") or {}
    dist = rk.get("distance_km")
    steps_used = rk.get("steps_used") or 0
    max_steps = rk.get("max_steps") or 30

    out = {
        "cid": record.get("cid"), "model": rk.get("model"),
        "arm": rk.get("arm") or ("on" if reports else "off"),
        "run_idx": record.get("run_idx"),
        "final_wrong": (dist is not None and dist > WRONG_KM),
        "final_correct": (dist is not None and dist <= CORRECT_KM),
    }

    # --- [t] Solo-trace signatures ---
    tool_events = [ev for ev in trace if ev.get("type") in SEARCH_TOOLS
                   or ev.get("type") in GEO_ARG_TOOLS or ev.get("type") == "geocode"]
    out["n_tool_calls"] = len(tool_events)
    out["low_evidence_submit"] = bool(rk.get("submit_called")) and len(tool_events) < 3

    # === NIVEL 1: recursos ===
    out["steps_frac_used"] = round(steps_used / max(1, max_steps), 3)
    kinds = defaultdict(int)
    for ev in trace:
        t = ev.get("type", "")
        if t in SEARCH_TOOLS:
            kinds["search"] += 1
        elif t in VISUAL_CHECK_TOOLS:
            kinds["visual"] += 1
        elif t in {"crop_image", "crop_image_relative"}:
            kinds["crop"] += 1
        elif t in {"geocode", "reverse_geocode"}:
            kinds["geo"] += 1
        elif t in {"historical_query", "historical_query_at"}:
            kinds["temporal"] += 1
    total_k = sum(kinds.values()) or 1
    out["visual_share"] = round(kinds["visual"] / total_k, 3)
    out["temporal_tool_share"] = round(kinds["temporal"] / total_k, 3)
    out["tool_kind_diversity"] = sum(1 for v in kinds.values() if v > 0)

    # === NIVEL 2: estilo de búsqueda ===
    queries = []
    for ev in trace:
        if ev.get("type") in SEARCH_TOOLS:
            q = ev.get("query") or (ev.get("args") or {}).get("query")
            if q:
                queries.append(str(q))
    if queries:
        lens = [len(q.split()) for q in queries]
        out["avg_query_words"] = round(sum(lens) / len(lens), 1)
        half = max(1, len(lens) // 2)
        out["query_shortening"] = round((sum(lens[:half]) / half) - (sum(lens[half:]) / max(1, len(lens) - half)), 1)
        # cambio de escritura (latín ↔ no-latín, ej. cirílico) — el "language pivot"
        def _script(q):
            return "nonlatin" if any(ord(ch) > 0x24F for ch in q) else "latin"
        scripts = [_script(q) for q in queries]
        out["script_switches"] = sum(1 for a, b in zip(scripts, scripts[1:]) if a != b)
        out["used_nonlatin_queries"] = any(s == "nonlatin" for s in scripts)

    # === NIVEL 3a: respuesta a callejones sin salida (dead-end response) ===
    # Tras una búsqueda vacía/fallida: ¿qué hizo DESPUÉS? distribución de reacciones.
    dead_end_next = defaultdict(int)
    ordered = [ev for ev in trace if ev.get("type") in SEARCH_TOOLS
               or ev.get("type", "").endswith("_error")
               or ev.get("type") in GEO_ARG_TOOLS | {"geocode", "report_belief", "submit"}]
    for i, ev in enumerate(ordered[:-1]):
        t = ev.get("type", "")
        empty = (t.endswith("_error")
                 or (t == "web_search" and (ev.get("result_count") or 0) == 0)
                 or (t == "image_search" and (ev.get("n_cells") or 0) == 0))
        if not empty:
            continue
        nxt = ordered[i + 1]
        nt = nxt.get("type", "")
        if nt == "report_belief":
            dead_end_next["reporta_belief"] += 1
        elif nt == "submit":
            dead_end_next["se_rinde_submit"] += 1
        elif nt == t or nt == t + "_error" or nt.replace("_error", "") == t.replace("_error", ""):
            q0 = _norm(str(ev.get("query") or ""))
            q1 = _norm(str(nxt.get("query") or ""))
            tok0, tok1 = set(q0.split()), set(q1.split())
            overlap = len(tok0 & tok1) / max(1, len(tok0 | tok1)) if (tok0 or tok1) else 0
            dead_end_next["insiste_similar" if overlap >= 0.5 else "reformula"] += 1
        else:
            dead_end_next["cambia_de_tool"] += 1
    out["dead_ends"] = sum(dead_end_next.values())
    for k in ("insiste_similar", "reformula", "cambia_de_tool", "reporta_belief", "se_rinde_submit"):
        out[f"deadend_{k}"] = dead_end_next.get(k, 0)

    # exact_query_repetition: tool+args canonicalizados
    seen, reps = set(), 0
    for ev in trace:
        t = ev.get("type", "")
        if t in SEARCH_TOOLS or t in GEO_ARG_TOOLS or t == "geocode":
            key = t + "|" + _norm(json.dumps(ev.get("args") or {"q": ev.get("query"), "u": ev.get("url")},
                                             sort_keys=True, ensure_ascii=False))
            if key in seen:
                reps += 1
            seen.add(key)
    out["exact_query_repetitions"] = reps

    # --- Belief-dependent signatures ---
    if not reports or not truth:
        return out

    def top_of(rep):
        return top_candidate((rep.get("belief") or {}).get("location_belief") or [])

    tops = [(rep["step"], top_of(rep)) for rep in reports]
    tops = [(s, t) for s, t in tops if t]
    if not tops:
        return out

    first_top = tops[0][1]
    # Cluster del submit vs cluster del primer top
    if fa.get("lat") is not None:
        try:
            d_first_final = great_circle_km(float(first_top["lat"]), float(first_top["lon"]),
                                            float(fa["lat"]), float(fa["lon"]))
            out["first_hypothesis_dominance"] = d_first_final <= CORRECT_KM
            out["first_hypothesis_dominance_wrong"] = (d_first_final <= CORRECT_KM
                                                       and out["final_wrong"])
        except (TypeError, ValueError):
            pass

    # single_track: ¿algún cluster RIVAL llegó a w≥0.1?
    rival_seen = False
    decorative_rivals = []
    for rep in reports:
        loc = (rep.get("belief") or {}).get("location_belief") or []
        for c in loc:
            try:
                d = great_circle_km(float(c["lat"]), float(c["lon"]),
                                    float(first_top["lat"]), float(first_top["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            if d > CORRECT_KM and float(c.get("weight", 0)) >= 0.1:
                rival_seen = True
            if d > CORRECT_KM and float(c.get("weight", 0)) >= 0.2:
                decorative_rivals.append(c)
    out["single_track"] = not rival_seen

    # decorative_alternatives: rival w≥0.2 jamás investigado (ninguna tool ligada)
    if decorative_rivals:
        investigated = set()
        for ev in trace:
            for i, c in enumerate(decorative_rivals):
                if i not in investigated and event_linked_to(ev, c):
                    investigated.add(i)
        out["decorative_alternatives"] = len(investigated) < len(decorative_rivals)
    else:
        out["decorative_alternatives"] = False

    # confidence_ratchet_wrong: peso del top vigente no-decreciente en ≥3 reports + final W
    if len(tops) >= 3:
        weights = [float(t.get("weight", 0)) for _, t in tops]
        out["confidence_ratchet_wrong"] = all(b >= a - 1e-9 for a, b in zip(weights, weights[1:])) \
            and out["final_wrong"]

    # Estados C/W del top por report + persistencia/entrenchment/abandono/recovery
    states = []
    for s, t in tops:
        d = great_circle_km(float(t["lat"]), float(t["lon"]), truth[0], truth[1])
        states.append((s, t, "C" if d <= CORRECT_KM else ("W" if d > WRONG_KM else "U")))

    out["ever_correct_top"] = any(st == "C" for _, _, st in states)
    out["never_correct"] = not out["ever_correct_top"]
    out["recovery_from_wrong_start"] = states[0][2] == "W" and out["ever_correct_top"]

    # wrong_persistence (A1a): mismo cluster W como top en ≥2 reports consecutivos con ≥3 calls entre medio
    # wrong_entrenchment (A1b): ≥3 reports + ≥6 obs exitosas ligadas + Δw neto ≥0.10
    out["wrong_persistence"] = False
    out["wrong_entrenchment"] = False
    for i in range(len(states) - 1):
        s0, t0, st0 = states[i]
        if st0 != "W":
            continue
        run_chain = [(s0, t0)]
        for j in range(i + 1, len(states)):
            sj, tj, stj = states[j]
            same = great_circle_km(float(tj["lat"]), float(tj["lon"]),
                                   float(t0["lat"]), float(t0["lon"])) <= CORRECT_KM
            if stj == "W" and same:
                run_chain.append((sj, tj))
            else:
                break
        if len(run_chain) >= 2:
            calls_between = [ev for ev in trace
                             if run_chain[0][0] < ev.get("step", 0) <= run_chain[-1][0]
                             and _successful_observation(ev)]
            if len(calls_between) >= 3:
                out["wrong_persistence"] = True
            if len(run_chain) >= 3:
                linked = [ev for ev in calls_between if event_linked_to(ev, t0)]
                dw = float(run_chain[-1][1].get("weight", 0)) - float(run_chain[0][1].get("weight", 0))
                if len(linked) >= 6 and dw >= 0.10:
                    out["wrong_entrenchment"] = True
        if out["wrong_entrenchment"]:
            break

    # correct_mass_abandonment (A2 fuerte)
    out["correct_mass_abandonment"] = False
    if out["final_wrong"]:
        prev_mass = None
        for rep in reports:
            loc = (rep.get("belief") or {}).get("location_belief") or []
            m = cluster_mass(loc, truth[0], truth[1])
            if prev_mass is not None and prev_mass >= 0.25 and (prev_mass - m) >= 0.15:
                out["correct_mass_abandonment"] = True
            prev_mass = m
        if prev_mass is not None and prev_mass < 0.25 and any(
                cluster_mass((r.get("belief") or {}).get("location_belief") or [],
                             truth[0], truth[1]) >= 0.25 for r in reports):
            out["correct_mass_abandonment"] = True

    # correct_top_deterioration (B2)
    out["correct_top_deterioration"] = any(st == "C" for _, _, st in states) and out["final_wrong"]

    # B1: parada — q_max del último report (frescura ≤3 steps del submit)
    last_step, last_top = tops[-1]
    q_max = float(last_top.get("weight", 0))
    submit_step = steps_used
    fresh = (submit_step - last_step) <= 3
    out["stale_confidence_at_submit"] = not fresh
    budget_left_frac = 1.0 - (submit_step / max(1, max_steps))
    if fresh and bool(rk.get("submit_called")):
        out["early_uncertain_commit"] = q_max < 0.5 and budget_left_frac >= 0.4 and out["final_wrong"]
        out["early_overconfident_wrong"] = q_max >= 0.75 and budget_left_frac >= 0.4 and out["final_wrong"]
        out["overconfident_wrong_commit"] = q_max >= 0.75 and out["final_wrong"]

    # unchanged_reported_year_distribution (R7 rename; TV en grilla pendiente — v1: igualdad canónica)
    yrs = [json.dumps((r.get("belief") or {}).get("year_belief") or [], sort_keys=True)
           for r in reports]
    out["year_belief_frozen"] = len(set(yrs)) <= 1 and len(yrs) >= 3  # R7: ≥3 reports

    # === NIVEL 3b: dinámica de creencias ===
    # Masa "no sé" (honestidad del hedge): promedio de masa NO asignada por report
    unassigned = []
    all_weights = []
    for rep in reports:
        loc = (rep.get("belief") or {}).get("location_belief") or []
        s = sum(float(c.get("weight", 0)) for c in loc)
        unassigned.append(max(0.0, 1.0 - s))
        all_weights += [float(c.get("weight", 0)) for c in loc]
    out["unassigned_mass_mean"] = round(sum(unassigned) / len(unassigned), 3) if unassigned else None
    # Granularidad de pesos: ¿solo usa múltiplos de 0.1 (credences gruesas)?
    if all_weights:
        coarse = sum(1 for w in all_weights if abs(w * 10 - round(w * 10)) < 1e-9)
        out["coarse_credence_share"] = round(coarse / len(all_weights), 3)
    # Tamaño del update: max shift de masa del cluster top entre reports consecutivos
    shifts = []
    for (s0, t0), (s1, t1) in zip(tops, tops[1:]):
        loc1 = None
        for rep in reports:
            if rep["step"] == s1:
                loc1 = (rep.get("belief") or {}).get("location_belief") or []
        if loc1 is None:
            continue
        m_after = cluster_mass(loc1, float(t0["lat"]), float(t0["lon"]))
        shifts.append(abs(m_after - float(t0.get("weight", 0))))
    out["max_update_shift"] = round(max(shifts), 3) if shifts else None

    # top_path_churn (R7): clusters top únicos + patrón A→B→A (retorno)
    top_clusters = []
    for _, t in tops:
        placed = False
        for c in top_clusters:
            if great_circle_km(float(t["lat"]), float(t["lon"]), c[0], c[1]) <= CORRECT_KM:
                placed = True
                break
        if not placed:
            top_clusters.append((float(t["lat"]), float(t["lon"])))
    out["unique_top_clusters"] = len(top_clusters)
    # retorno A→B→A: el top vuelve a un cluster previamente abandonado
    seq = []
    for _, t in tops:
        for i, c in enumerate(top_clusters):
            if great_circle_km(float(t["lat"]), float(t["lon"]), c[0], c[1]) <= CORRECT_KM:
                if not seq or seq[-1] != i:
                    seq.append(i)
                break
    out["top_return_aba"] = any(seq[i] in seq[:i - 1] for i in range(2, len(seq)) if i >= 2)

    # last_belief_submit_mismatch (R7 ⭐): ¿entregó lo que decía creer?
    if fa.get("lat") is not None and tops:
        _, lt = tops[-1]
        try:
            d_ls = great_circle_km(float(lt["lat"]), float(lt["lon"]),
                                   float(fa["lat"]), float(fa["lon"]))
            out["last_belief_submit_mismatch"] = d_ls > CORRECT_KM
        except (TypeError, ValueError):
            pass

    # belief_change_without_intervening_successful_tool_result (R7)
    out["revision_without_new_evidence"] = False
    for (s0, t0), (s1, t1) in zip(tops, tops[1:]):
        moved = great_circle_km(float(t0["lat"]), float(t0["lon"]),
                                float(t1["lat"]), float(t1["lon"])) > CORRECT_KM
        if moved:
            between = [ev for ev in trace if s0 < ev.get("step", 0) <= s1
                       and _successful_observation(ev)]
            if not between:
                out["revision_without_new_evidence"] = True
                break

    # hypothesis_echo_share: fracción de queries de búsqueda que contienen el top vigente
    echo, total_q = 0, 0
    current_top = None
    rep_iter = iter(tops)
    next_rep = next(rep_iter, None)
    for ev in trace:
        while next_rep and ev.get("step", 0) >= next_rep[0]:
            current_top = next_rep[1]
            next_rep = next(rep_iter, None)
        if ev.get("type") in SEARCH_TOOLS and (ev.get("query") or (ev.get("args") or {}).get("query")):
            total_q += 1
            if current_top and event_linked_to(ev, current_top):
                echo += 1
    out["hypothesis_echo_share"] = round(echo / total_q, 3) if total_q else None

    # post_commitment_only_checks: toda verificación visual ocurre después del último report
    checks = [ev.get("step", 0) for ev in trace if ev.get("type") in VISUAL_CHECK_TOOLS]
    out["visual_checks"] = len(checks)
    out["post_commitment_only_checks"] = bool(checks) and all(s >= last_step for s in checks)

    return out


# === Agregación ===

def agg_table(rows: list[dict]) -> None:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["arm"])].append(r)

    sig_bool = ["first_hypothesis_dominance", "first_hypothesis_dominance_wrong", "single_track",
                "decorative_alternatives", "confidence_ratchet_wrong", "wrong_persistence",
                "wrong_entrenchment", "correct_mass_abandonment", "correct_top_deterioration",
                "recovery_from_wrong_start", "never_correct", "early_uncertain_commit",
                "early_overconfident_wrong", "overconfident_wrong_commit",
                "stale_confidence_at_submit", "year_belief_frozen",
                "post_commitment_only_checks", "low_evidence_submit",
                "last_belief_submit_mismatch", "revision_without_new_evidence",
                "top_return_aba", "used_nonlatin_queries"]
    sig_mean = ["steps_frac_used", "visual_share", "temporal_tool_share", "tool_kind_diversity",
                "avg_query_words", "query_shortening", "script_switches",
                "unassigned_mass_mean", "coarse_credence_share", "max_update_shift",
                "unique_top_clusters", "dead_ends", "deadend_insiste_similar",
                "deadend_reformula", "deadend_cambia_de_tool"]

    def rate(rows_, key):
        vals = [r[key] for r in rows_ if key in r and r[key] is not None]
        return f"{100*sum(bool(v) for v in vals)/len(vals):.0f}%" if vals else "—"

    def mean(rows_, key):
        vals = [r[key] for r in rows_ if r.get(key) is not None]
        return f"{sum(vals)/len(vals):.2f}" if vals else "—"

    print("\n=== PERFIL CONDUCTUAL por (modelo, arm) — trace_prevalence (% de corridas) ===")
    for (model, arm), rows_ in sorted(groups.items()):
        print(f"\n--- {model} · belief-{arm} · n={len(rows_)} ---")
        for k in sig_bool:
            r = rate(rows_, k)
            if r != "—":
                print(f"  {k:<38} {r:>5}")
        es = mean(rows_, "hypothesis_echo_share")
        if es != "—":
            print(f"  {'hypothesis_echo_share (media)':<38} {es:>5}")
        er = mean(rows_, "exact_query_repetitions")
        print(f"  {'exact_query_repetitions (media/run)':<38} {er:>5}")
        print("  --- medias (estilo/recursos) ---")
        for k in sig_mean:
            m = mean(rows_, k)
            if m != "—":
                print(f"  {k:<38} {m:>5}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path("experiments/E016_belief_pilot"))
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    rows = []
    for p in sorted(args.dir.glob("results_*_belief-*.json")):
        if ".slim" in p.name and (args.dir / p.name.replace(".slim", "")).exists():
            continue
        try:
            records = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec in records:
            if (rec.get("react") or {}).get("error"):
                continue
            rows.append(profile_run(rec))

    if not rows:
        raise SystemExit("sin corridas")
    agg_table(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON: {args.json}")


if __name__ == "__main__":
    main()
