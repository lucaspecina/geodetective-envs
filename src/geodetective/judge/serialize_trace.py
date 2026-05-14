"""Convierte una trace ReAct (results JSON entry) → texto consumible por judge.

Diseño post-`process_eval_design.md` §5.2:
- Cada evento del trace se enumera como [MSG N] con su rol.
- Tool calls + sus argumentos breves visibles.
- Tool results resumidos textualmente (NO base64 images en v1 stub — text-only judge).
- Thinking events explícitos como blocks H/J candidates.
- Visual evidence (crops, SV panoramas, image_search) anotada con metadata
  (zoom, region, hamming_distance) sin pasar bytes.

v1 limitación documentada: visual content como descripción textual, no imagen real.
Para detectar `visual_hallucination` o `multi_modal_cross_validation` se necesita
multimodal judge (Stage 3b, iteración 2).
"""
from __future__ import annotations

import json
from typing import Any


def _summarize_tool_event(ev: dict[str, Any]) -> str:
    """Resumen one-line de un evento de tool result en el trace."""
    t = ev.get("type", "?")

    if t == "web_search":
        q = ev.get("query", "")
        n = ev.get("result_count", 0)
        blocked = ev.get("blocked", 0)
        tops = ev.get("top_results", []) or []
        parts = [f"web_search(query={q!r}) → {n} results ({blocked} blocked)"]
        for i, r in enumerate(tops[:3], 1):
            url = (r.get("url") or "")[:80]
            title = (r.get("title") or "")[:80]
            snip = (r.get("snippet") or "")[:180]
            parts.append(f"    [{i}] {title} | {url}")
            if snip:
                parts.append(f"        snippet: {snip}")
        return "\n".join(parts)

    if t == "fetch_url":
        url = (ev.get("url") or "")[:120]
        tlen = ev.get("text_len", 0)
        title = (ev.get("title") or "")[:100]
        snippet = (ev.get("text_snippet") or "")[:300]
        return f"fetch_url({url}) → title={title!r} text_len={tlen}\n    snippet: {snippet}"

    if t == "fetch_url_with_images":
        url = (ev.get("url") or "")[:120]
        n_imgs = ev.get("n_images", 0)
        target = ev.get("target_match", 0)
        title = (ev.get("title") or "")[:100]
        snippet = (ev.get("text_snippet") or "")[:200]
        return (
            f"fetch_url_with_images({url}) → title={title!r} "
            f"text_len={ev.get('text_len', 0)} images={n_imgs} target_matches_hidden={target}\n"
            f"    snippet: {snippet}"
        )

    if t == "image_search":
        q = ev.get("query", "")
        n = ev.get("n_images", 0)
        target = ev.get("target_match", 0)
        return f"image_search(query={q!r}) → {n} images, {target} target_matches_hidden"

    if t in ("geocode", "reverse_geocode"):
        args = ev.get("args", {}) or {}
        n = ev.get("n_results", 0)
        tops = ev.get("top_results", []) or []
        parts = [f"{t}({json.dumps(args, ensure_ascii=False)[:120]}) → {n} results"]
        for r in tops[:3]:
            lat = r.get("lat")
            lon = r.get("lon")
            name = (r.get("display_name") or "")[:120]
            parts.append(f"    ({lat}, {lon}) {name}")
        return "\n".join(parts)

    if t == "historical_query":
        args = ev.get("args", {}) or {}
        n = ev.get("n_features", 0)
        return f"historical_query({json.dumps(args, ensure_ascii=False)[:200]}) → {n} features"

    if t in ("crop_image", "crop_image_relative"):
        region = ev.get("region")
        return f"{t}(region={region}) → cropped (image not shown — text-only judge)"

    if t == "static_map":
        args = ev.get("args", {}) or {}
        return f"static_map({json.dumps(args, ensure_ascii=False)[:120]}) → map image (not shown — text-only judge)"

    if t == "street_view":
        args = ev.get("args", {}) or {}
        n = ev.get("n_images", 0)
        return (
            f"street_view({json.dumps(args, ensure_ascii=False)[:120]}) → "
            f"{n} panoramas at ({ev.get('actual_lat')}, {ev.get('actual_lon')}) "
            f"dist_to_pano={ev.get('distance_to_pano_m')}m pano_date={ev.get('pano_date')}"
        )

    if t == "submit":
        ans = ev.get("answer", {}) or {}
        return (
            f"submit_answer(\n"
            f"    location={ans.get('location', '')!r},\n"
            f"    lat={ans.get('lat')}, lon={ans.get('lon')}, year={ans.get('year')!r},\n"
            f"    confidence={ans.get('confidence')!r}\n"
            f"    reasoning={ans.get('reasoning', '')[:300]!r}\n"
            f"    visual_clues={ans.get('visual_clues', [])!r}\n"
            f"    external_evidence={ans.get('external_evidence', [])!r}\n"
            f"    rejected_alternatives={ans.get('rejected_alternatives', [])!r}\n"
            f"    verification_checks={ans.get('verification_checks', [])!r}\n"
            f"    uncertainty_reason={ans.get('uncertainty_reason', '')[:300]!r}\n"
            f")"
        )

    if t == "submit_rejected":
        return f"submit_answer REJECTED: {ev.get('error', '')}"

    if t in ("thinking", "thinking_block"):
        return f"<verbalized> {(ev.get('content') or '')[:1200]}"

    if t == "no_tool_call_in_response":
        return f"<no_tool_call_text> {(ev.get('content') or '')[:400]}"

    if t.endswith("_error"):
        return f"{t}: {ev.get('error', '?')}"

    # Fallback
    return f"{t}: {json.dumps({k: v for k, v in ev.items() if k != 'type'}, ensure_ascii=False)[:300]}"


def serialize_trace(
    cid: int,
    model: str,
    prompt_version: str,
    trace: list[dict],
    ground_truth: dict | None = None,
    final_answer: dict | None = None,
    distance_km: float | None = None,
    year_error: float | None = None,
) -> str:
    """Trace ReAct → texto estructurado, indexado por step.

    El judge recibe este texto plano. msg_idx en sus annotations referencia
    los marcadores [MSG N] de este texto.

    NOTE: para v1 text-only judge, las imágenes (crops, static_map, SV, etc.)
    se describen como metadata. v2 multimodal judge va a recibir las imágenes
    embebidas.
    """
    lines: list[str] = []
    lines.append(f"=== TRACE METADATA ===")
    lines.append(f"cid: {cid}")
    lines.append(f"model: {model}")
    lines.append(f"prompt_version: {prompt_version}")
    if ground_truth:
        lines.append(f"ground_truth: geo={ground_truth.get('geo')} year={ground_truth.get('year')} country={ground_truth.get('country')}")
    if final_answer:
        lines.append(
            f"final_answer: location={final_answer.get('location', '')[:80]!r} "
            f"lat={final_answer.get('lat')} lon={final_answer.get('lon')} "
            f"year={final_answer.get('year')!r} confidence={final_answer.get('confidence')!r}"
        )
    if distance_km is not None:
        lines.append(f"outcome_distance_km: {distance_km:.1f}")
    if year_error is not None:
        lines.append(f"outcome_year_error: {year_error}")
    lines.append("")
    lines.append("=== TRACE EVENTS (chronological) ===")
    lines.append("[MSG 0] role=user (initial task brief)")
    lines.append("The agent receives a target photograph and the task: investigate this photo")
    lines.append("and submit coordinates (lat, lon) + year + reasoning via the `submit_answer` tool.")
    lines.append("This is E (visual_primary).")
    lines.append("")

    msg_idx = 1
    last_step = -1
    for ev in trace:
        step = ev.get("step", 0)
        t = ev.get("type", "?")
        if t in ("thinking", "thinking_block"):
            lines.append(f"[MSG {msg_idx}] role=assistant (step {step}, thinking_block)")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        elif t == "no_tool_call_in_response":
            lines.append(f"[MSG {msg_idx}] role=assistant (step {step}, no_tool_call)")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        elif t in ("submit", "submit_rejected"):
            lines.append(f"[MSG {msg_idx}] role=assistant_tool_call (step {step}, {t})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        else:
            # Tool call + result combined event
            lines.append(f"[MSG {msg_idx}] role=tool_result (step {step}, {t})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        last_step = step
        lines.append("")

    return "\n".join(lines)
