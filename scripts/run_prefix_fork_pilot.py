"""Piloto exploratorio: forks P1 desde prefijos idénticos de una investigación real.

1. Corre UNA trayectoria base con belief-mode y documentación de boletines, sin
   inyectar evidencia.
2. Captura el historial exacto al final de cada step con report_belief.
3. En checkpoints correctos y sin tools coemitidas, bifurca el MISMO prefijo en
   contradiction vs placebo.
4. Mide el report inmediato y la primera acción posterior (sin ejecutar la tool).

No es un experimento confirmatorio: una sola trayectoria base, reports elicitados
y checkpoints seleccionados por elegibilidad. Sí elimina el confound más grosero
del smoke live: los brazos comparten bytes idénticos hasta la intervención.

Uso:
    MODEL=claude-sonnet-4-6 CID=1425423 \
      conda run -n geodetective python scripts/run_prefix_fork_pilot.py

Output: experiments/E018_temporal_belief_pilot/prefix_forks_{model}_{cid}.json

`TARGET_STATE=C` prueba contradicciones débiles sobre un top correcto;
`TARGET_STATE=W` prueba certificados vinculantes sobre un top incorrecto.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip()

sys.path.insert(0, str(Path("src").resolve()))

from geodetective.agents.react import (
    _count_images_in_messages,
    _prune_old_images,
    _validate_belief,
    run_react_agent,
)
from geodetective.corpus import CLEAN_VERSION
from geodetective.llm_adapter import complete as llm_complete
from geodetective.probes import (
    CLUSTER_KM,
    WEAK_LAMBDA,
    ProbeConfig,
    ProbeInjector,
    classify_state,
    cluster_mass,
    top_candidate,
)


MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
CID = int(os.environ.get("CID", "1425423"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "30"))
MIN_STEPS = int(os.environ.get("MIN_STEPS", "0"))
BELIEF_NUDGE_AFTER = int(os.environ.get("BELIEF_NUDGE_AFTER", "3"))
MAX_FORKS = int(os.environ.get("MAX_FORKS", "3"))
FORK_REPS = int(os.environ.get("FORK_REPS", "1"))
FORK_TEMPERATURE = float(os.environ.get("FORK_TEMPERATURE", "0"))
TARGET_STATE = os.environ.get("TARGET_STATE", "C").strip().upper()
if TARGET_STATE not in {"C", "W"}:
    raise ValueError("TARGET_STATE debe ser C (top correcto) o W (top incorrecto)")

PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", "corpus/photos"))
CANDIDATES_PATH = Path(
    os.environ.get("CANDIDATES_PATH", "experiments/E016_belief_pilot/pilot_photos.json")
)
OUT_DIR = Path("experiments/E018_temporal_belief_pilot")


def _tool_calls(message: Any) -> list[dict]:
    out = []
    for tc in getattr(message, "tool_calls", None) or []:
        out.append({
            "id": tc.id,
            "name": tc.function.name,
            "arguments_raw": tc.function.arguments,
        })
    return out


def _assistant_message(message: Any, calls: list[dict]) -> dict:
    turn: dict[str, Any] = {
        "role": "assistant",
        "content": message.content if message.content is not None else "",
    }
    if calls:
        turn["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments_raw"],
                },
            }
            for call in calls
        ]
    return turn


def _parse_json(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _without_binary(value: Any) -> Any:
    """Copia serializable para output/medición sin persistir imágenes base64."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in {"base64_jpeg", "grid_image_b64", "data"} and isinstance(item, str):
                out[key] = f"<stripped:{len(item)} chars>"
            elif key == "url" and isinstance(item, str) and item.startswith("data:image"):
                out[key] = f"<data-image-stripped:{len(item)} chars>"
            else:
                out[key] = _without_binary(item)
        return out
    if isinstance(value, list):
        return [_without_binary(item) for item in value]
    return value


def _prefix_hash(messages: list[dict], tools: list[dict]) -> str:
    raw = json.dumps(
        {"messages": messages, "tools": tools},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _context_stats(messages: list[dict]) -> dict:
    compact = _without_binary(messages)
    return {
        "n_messages": len(messages),
        "n_tool_results": sum(m.get("role") == "tool" for m in messages),
        "n_images": sum(
            1
            for m in messages
            for part in (m.get("content") if isinstance(m.get("content"), list) else [])
            if isinstance(part, dict) and part.get("type") == "image_url"
        ),
        "textualized_chars": len(json.dumps(compact, ensure_ascii=False)),
    }


def _choose_checkpoints(
    checkpoints: list[dict], truth: list[float], target_state: str = "C"
) -> list[tuple[str, dict]]:
    eligible = []
    for cp in checkpoints:
        top = top_candidate((cp.get("belief") or {}).get("location_belief") or [])
        if top is None or cp.get("coemitted_tools"):
            continue
        try:
            if float(top["radius_km"]) > CLUSTER_KM:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if classify_state(top, truth[0], truth[1]) != target_state:
            continue
        eligible.append(cp)

    if not eligible:
        return []
    if len(eligible) == 1 or MAX_FORKS == 1:
        indices = [0]
    elif len(eligible) == 2 or MAX_FORKS == 2:
        indices = [0, len(eligible) - 1]
    else:
        indices = [0, len(eligible) // 2, len(eligible) - 1]
    indices = list(dict.fromkeys(indices))[:MAX_FORKS]
    labels = {
        1: ["only_eligible"],
        2: ["first_eligible", "last_eligible"],
        3: ["first_eligible", "middle_eligible", "last_eligible"],
    }[len(indices)]
    return [(label, eligible[idx]) for label, idx in zip(labels, indices)]


def _prepare_canonical_next_turn(messages: list[dict], checkpoint_step: int) -> dict:
    """Replica el preámbulo determinista del siguiente turn del loop canónico."""
    n_images_before = _count_images_in_messages(messages)
    removed = 0
    if n_images_before >= 45:
        removed = _prune_old_images(messages, target_count=40, step=checkpoint_step + 1)

    remaining = MAX_STEPS - checkpoint_step
    reminder = None
    if remaining == 1:
        reminder = (
            "Este es tu ÚLTIMO turn. Llamá `submit_answer` AHORA con tu mejor hipótesis "
            "(incluso si la confidence es baja). Si realmente no podés geolocalizar la foto, "
            "submit con confidence='baja' y explicá el motivo en uncertainty_reason."
        )
    elif remaining in (3, 5):
        reminder = (
            f"[Recordatorio: te quedan {remaining} turns. Si tu evidencia es fuerte "
            "(2+ citables + <25km alta prob), submit YA. Sino, hacé 1-2 "
            "verificaciones rápidas más antes del hard cap.]"
        )
    if reminder:
        messages.append({"role": "user", "content": reminder})
    return {
        "remaining_turns": remaining,
        "images_before": n_images_before,
        "images_removed": removed,
        "reminder_added": reminder is not None,
    }


def _run_branch(cp: dict, truth: list[float], stage: str, arm: str, rep: int) -> dict:
    belief = cp["belief"]
    top = top_candidate(belief.get("location_belief") or [])
    seed = CID * 1000 + cp["step"] * 10 + rep
    injector = ProbeInjector(
        truth[0], truth[1],
        ProbeConfig(arm=arm, seed=seed, min_step=0, max_budget_frac=1.0),
    )
    bulletin = injector.maybe_fire(belief, cp["step"], MAX_STEPS)
    if bulletin is None:
        return {"stage": stage, "arm": arm, "rep": rep, "error": "probe_not_eligible"}

    messages = copy.deepcopy(cp["messages"])
    tools = copy.deepcopy(cp["tools"])
    messages.append({"role": "user", "content": bulletin})
    pre_turn = _prepare_canonical_next_turn(messages, cp["step"])
    started = time.time()
    try:
        response = llm_complete(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=8000,
            timeout=180.0,
            temperature=FORK_TEMPERATURE,
        )
        msg = response.choices[0].message
        calls = _tool_calls(msg)
    except Exception as exc:
        return {
            "stage": stage, "arm": arm, "rep": rep,
            "error": f"post_report_api: {type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-1200:],
        }

    report_calls = [call for call in calls if call["name"] == "report_belief"]
    post_belief = _parse_json(report_calls[0]["arguments_raw"]) if report_calls else None
    valid_report = False
    validation_error = "missing report_belief"
    if post_belief is not None:
        valid_report, validation_error = _validate_belief(post_belief)
    protocol_ok = len(calls) == 1 and len(report_calls) == 1 and valid_report
    score = injector.score_response(post_belief) if valid_report else None

    next_calls: list[dict] = []
    next_content = None
    next_error = None
    if valid_report:
        messages.append(_assistant_message(msg, calls))
        for call in calls:
            if call["name"] == "report_belief":
                n_loc = len((post_belief or {}).get("location_belief") or [])
                n_year = len((post_belief or {}).get("year_belief") or [])
                tool_result = f"belief_recorded ({n_loc} candidatos de ubicación, {n_year} rangos de año)."
            else:
                tool_result = (
                    "Bloqueado por protocolo: la primera acción posterior al boletín debía ser "
                    "únicamente report_belief."
                )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": tool_result})
        try:
            response2 = llm_complete(
                model=MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_completion_tokens=8000,
                timeout=180.0,
                temperature=FORK_TEMPERATURE,
            )
            msg2 = response2.choices[0].message
            next_calls = _tool_calls(msg2)
            next_content = msg2.content
        except Exception as exc:
            next_error = f"next_action_api: {type(exc).__name__}: {exc}"

    q0 = cluster_mass(
        belief.get("location_belief") or [], float(top["lat"]), float(top["lon"])
    )
    normative_post = None
    if injector.record.polarity == "ii" and arm == "contradiction":
        normative_post = (q0 * 0.45) / (q0 * 0.45 + (1.0 - q0) * 0.55)
    elif injector.record.polarity == "i" and arm == "contradiction":
        normative_post = 0.0

    return {
        "stage": stage,
        "arm": arm,
        "rep": rep,
        "checkpoint_step": cp["step"],
        "checkpoint_hash": cp["checkpoint_hash"],
        "context": cp["context"],
        "canonical_pre_turn": pre_turn,
        "pre_top": injector.record.pre_top,
        "pre_mass": injector.record.pre_mass,
        "polarity": injector.record.polarity,
        "normative_post_mass": round(normative_post, 6) if normative_post is not None else None,
        "bulletin": bulletin,
        "post_tool_calls": [call["name"] for call in calls],
        "post_content": msg.content,
        "protocol_ok": protocol_ok,
        "report_valid": valid_report,
        "report_error": None if valid_report else validation_error,
        "post_belief": post_belief,
        "response": score,
        "next_tool_calls": [call["name"] for call in next_calls],
        "next_tool_args": [
            {"name": call["name"], "args": _parse_json(call["arguments_raw"])} for call in next_calls
        ],
        "next_content": next_content,
        "next_error": next_error,
        "immediate_stop": any(call["name"] == "submit_answer" for call in next_calls),
        "elapsed_s": round(time.time() - started, 1),
    }


def _paired_summary(branches: list[dict]) -> list[dict]:
    paired = []
    keys = sorted({(b["stage"], b["rep"]) for b in branches})
    for stage, rep in keys:
        by_arm = {b["arm"]: b for b in branches if b["stage"] == stage and b["rep"] == rep}
        contradiction = by_arm.get("contradiction")
        placebo = by_arm.get("placebo")
        reasons = []
        if contradiction is None:
            reasons.append("missing_contradiction")
        if placebo is None:
            reasons.append("missing_placebo")
        if reasons:
            paired.append({"stage": stage, "rep": rep, "comparable": False,
                           "exclusion_reasons": reasons})
            continue
        if contradiction.get("checkpoint_hash") != placebo.get("checkpoint_hash"):
            reasons.append("different_prefix_hash")
        if not contradiction.get("protocol_ok"):
            reasons.append("contradiction_protocol_failure")
        if not placebo.get("protocol_ok"):
            reasons.append("placebo_protocol_failure")
        cr = contradiction.get("response") or {}
        pr = placebo.get("response") or {}
        if not cr:
            reasons.append("missing_contradiction_score")
        if not pr:
            reasons.append("missing_placebo_score")
        polarity = cr.get("polarity") or contradiction.get("polarity")
        if polarity == "ii" and cr.get("at_boundary"):
            reasons.append("contradiction_boundary_mass")
        if polarity == "ii" and pr.get("at_boundary"):
            reasons.append("placebo_boundary_mass")
        c_delta = cr.get("delta_logit")
        p_delta = pr.get("delta_logit")
        if c_delta is None:
            reasons.append("missing_contradiction_delta")
        if p_delta is None:
            reasons.append("missing_placebo_delta")
        comparable = not reasons
        adjusted_delta = c_delta - p_delta if comparable else None
        c_post = cr.get("post_mass")
        p_post = pr.get("post_mass")
        paired.append({
            "stage": stage,
            "rep": rep,
            "comparable": comparable,
            "exclusion_reasons": reasons,
            "checkpoint_step": contradiction.get("checkpoint_step"),
            "checkpoint_hash_equal": contradiction.get("checkpoint_hash") == placebo.get("checkpoint_hash"),
            "pre_mass": contradiction.get("pre_mass"),
            "polarity": polarity,
            "contradiction_post_mass": c_post,
            "placebo_post_mass": p_post,
            "placebo_adjusted_mass_change": (
                round(c_post - p_post, 4)
                if comparable and c_post is not None and p_post is not None else None
            ),
            "contradiction_delta_logit": c_delta,
            "placebo_delta_logit": p_delta,
            "placebo_adjusted_delta_logit": round(adjusted_delta, 4) if adjusted_delta is not None else None,
            "placebo_adjusted_elasticity": (
                round(-adjusted_delta / WEAK_LAMBDA, 4)
                if adjusted_delta is not None and polarity == "ii" else None
            ),
            "contradiction_next": contradiction.get("next_tool_calls"),
            "placebo_next": placebo.get("next_tool_calls"),
            "contradiction_stop": contradiction.get("immediate_stop"),
            "placebo_stop": placebo.get("immediate_stop"),
        })
    return paired


def main() -> None:
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    candidate = next((c for c in candidates if int(c["cid"]) == CID), None)
    if candidate is None:
        raise SystemExit(f"cid={CID} no está en {CANDIDATES_PATH}")
    image_path = PHOTOS_DIR / f"{CID}_clean_v{CLEAN_VERSION}.jpg"
    if not image_path.exists():
        raise SystemExit(f"falta {image_path}")

    checkpoints: list[dict] = []

    def observe(payload: dict) -> None:
        payload["checkpoint_hash"] = _prefix_hash(payload["messages"], payload["tools"])
        payload["context"] = _context_stats(payload["messages"])
        checkpoints.append(payload)

    print("=" * 78)
    print(f"E018 PREFIX-FORK PILOT — model={MODEL} cid={CID}")
    print(f"base max_steps={MAX_STEPS} min_steps={MIN_STEPS} nudge={BELIEF_NUDGE_AFTER}")
    print("=" * 78)
    base_started = time.time()
    base = run_react_agent(
        image_path=image_path,
        model=MODEL,
        max_steps=MAX_STEPS,
        min_steps=MIN_STEPS,
        verbose=True,
        provider=candidate.get("provider"),
        provenance_source=candidate.get("provenance_source", ""),
        belief_mode=True,
        belief_nudge_after=BELIEF_NUDGE_AFTER,
        bulletin_mode=True,
        checkpoint_observer=observe,
    )

    chosen = _choose_checkpoints(checkpoints, candidate["geo"], TARGET_STATE)
    print(f"\nBase: steps={base.steps_used} reports={len(checkpoints)} "
          f"clean+correct={len(chosen)} terminal={base.terminal_state}")
    branches = []
    for stage, cp in chosen:
        print(f"\nFork {stage}: step={cp['step']} hash={cp['checkpoint_hash'][:12]} "
              f"context_chars={cp['context']['textualized_chars']}")
        for rep in range(FORK_REPS):
            for arm in ("contradiction", "placebo"):
                print(f"  {arm} rep={rep}...", flush=True)
                result = _run_branch(cp, candidate["geo"], stage, arm, rep)
                branches.append(result)
                response = result.get("response") or {}
                print(
                    f"    Δlogit={response.get('delta_logit')} "
                    f"next={result.get('next_tool_calls')} stop={result.get('immediate_stop')} "
                    f"err={result.get('error') or result.get('next_error')}"
                )

    output = {
        "status": "failed_base" if base.error else "exploratory_not_confirmatory",
        "design": "same-prefix contradiction/placebo one-step forks",
        "limitations": [
            "beliefs are prompt-elicited reports",
            "checkpoints are selected from one natural base trajectory",
            "eligibility conditions on a correct top hypothesis",
            "stage labels are ordinal among eligible checkpoints, not temporal thirds",
            "bulletin documentation is present from step 0 and can alter the base trajectory",
            "the post-report next action is sampled but not executed",
            "the branch path does not reproduce canonical retry/min_steps handling after the immediate report",
            "temperature-zero repetitions are not independent replicates",
            "no temporal claim is supported without replication across photos and models",
        ],
        "model": MODEL,
        "cid": CID,
        "candidate": {k: candidate.get(k) for k in ("title", "geo", "year", "provider")},
        "config": {
            "max_steps": MAX_STEPS,
            "min_steps": MIN_STEPS,
            "belief_nudge_after": BELIEF_NUDGE_AFTER,
            "max_forks": MAX_FORKS,
            "fork_reps": FORK_REPS,
            "fork_temperature": FORK_TEMPERATURE,
            "target_state": TARGET_STATE,
        },
        "base": {
            "steps_used": base.steps_used,
            "terminal_state": base.terminal_state,
            "error": base.error,
            "elapsed_s": round(time.time() - base_started, 1),
            "final_answer": base.final_answer,
            "belief_reports": base.belief_reports,
            "trace": _without_binary(base.trace),
        },
        "checkpoint_inventory": [
            {
                "step": cp["step"],
                "checkpoint_hash": cp["checkpoint_hash"],
                "coemitted_tools": cp["coemitted_tools"],
                "context": cp["context"],
                "belief": cp["belief"],
            }
            for cp in checkpoints
        ],
        "branches": branches,
        "paired": _paired_summary(branches),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_model = MODEL.replace(".", "_").replace("/", "_")
    state_suffix = "" if TARGET_STATE == "C" else f"_state-{TARGET_STATE.lower()}"
    out_path = OUT_DIR / f"prefix_forks_{safe_model}_{CID}{state_suffix}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nPaired summary:")
    for row in output["paired"]:
        print(
            f"  {row['stage']:<16} step={str(row.get('checkpoint_step', '-')):<2} "
            f"E_adj={row.get('placebo_adjusted_elasticity')} "
            f"comparable={row.get('comparable')} reasons={row.get('exclusion_reasons')} "
            f"next C={row.get('contradiction_next')} P={row.get('placebo_next')}"
        )
    print(f"\nOutput: {out_path}")
    if base.error:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
