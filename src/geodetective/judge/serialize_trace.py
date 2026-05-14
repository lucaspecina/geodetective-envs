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


def _summarize_tool_call(ev: dict[str, Any]) -> str:
    """Resumen de la INVOCACIÓN de tool (T), sin el resultado todavía."""
    t = ev.get("type", "?")
    if t == "web_search":
        return f"web_search(query={ev.get('query', '')!r}, max_results=?)"
    if t == "fetch_url":
        return f"fetch_url(url={(ev.get('url') or '')[:120]!r})"
    if t == "fetch_url_with_images":
        return f"fetch_url_with_images(url={(ev.get('url') or '')[:120]!r})"
    if t == "image_search":
        return f"image_search(query={ev.get('query', '')!r})"
    if t in ("geocode", "reverse_geocode"):
        return f"{t}({json.dumps(ev.get('args', {}) or {}, ensure_ascii=False)[:160]})"
    if t == "historical_query":
        return f"historical_query({json.dumps(ev.get('args', {}) or {}, ensure_ascii=False)[:200]})"
    if t in ("crop_image", "crop_image_relative"):
        return f"{t}(region={ev.get('region')})"
    if t == "static_map":
        return f"static_map({json.dumps(ev.get('args', {}) or {}, ensure_ascii=False)[:120]})"
    if t == "street_view":
        return f"street_view({json.dumps(ev.get('args', {}) or {}, ensure_ascii=False)[:120]})"
    return f"{t}(...)"


def serialize_trace(
    cid: int,
    model: str,
    prompt_version: str,
    trace: list[dict],
    ground_truth: dict | None = None,  # ACEPTADO pero NO USADO — blind judge
    final_answer: dict | None = None,  # ACEPTADO pero NO USADO — blind judge
    distance_km: float | None = None,
    year_error: float | None = None,
) -> str:
    """Trace ReAct → texto estructurado, indexado por step.

    BLIND JUDGE (post-Codex review): NO incluimos ground_truth, final_answer,
    distance_km ni year_error en el texto que recibe el judge. Estos sesgarían
    la anotación de nodes/edges/patterns por outcome. Los aceptamos como
    parámetros por compatibilidad pero se IGNORAN al construir el texto.

    Cada tool call genera DOS bloques [MSG]:
    - assistant_tool_call: el T (Test) — el agente invoca una tool con args
    - tool_result: el E (Evidence) — el output observado de esa tool
    Esto preserva la separación causal T → E para el grafo CORRAL.

    NOTE: para v1 text-only judge, las imágenes (crops, static_map, SV, etc.)
    se describen como metadata. v2 multimodal judge recibirá las imágenes
    embebidas.
    """
    lines: list[str] = []
    lines.append(f"=== TRACE METADATA (NEUTRAL — no outcome info) ===")
    lines.append(f"trace_id: {cid}_{prompt_version}_{model}")
    lines.append(f"(model identity withheld from judge to avoid bias; outcome data withheld for blind annotation)")
    lines.append("")
    lines.append("=== TRACE EVENTS (chronological) ===")
    lines.append("[MSG 0] role=user (initial task brief)")
    lines.append("The agent receives a target photograph and the task: investigate this photo")
    lines.append("and submit coordinates (lat, lon) + year + reasoning via the `submit_answer` tool.")
    lines.append("The target photograph itself is the initial perceptual evidence (E, modality=visual_primary).")
    lines.append("")

    msg_idx = 1
    error_types = {"web_search_error", "fetch_url_error", "fetch_url_with_images_error",
                   "image_search_error", "geocode_error", "reverse_geocode_error",
                   "historical_query_error", "crop_image_error", "crop_image_relative_error",
                   "static_map_error", "street_view_error"}
    tool_call_types = {"web_search", "fetch_url", "fetch_url_with_images", "image_search",
                       "geocode", "reverse_geocode", "historical_query",
                       "crop_image", "crop_image_relative", "static_map", "street_view"}

    for ev in trace:
        step = ev.get("step", 0)
        t = ev.get("type", "?")
        if t in ("thinking", "thinking_block"):
            lines.append(f"[MSG {msg_idx}] role=assistant_thinking (step {step})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        elif t == "no_tool_call_in_response":
            lines.append(f"[MSG {msg_idx}] role=assistant_no_tool_call (step {step})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        elif t in ("submit", "submit_rejected"):
            lines.append(f"[MSG {msg_idx}] role=assistant_tool_call (step {step}, {t})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        elif t in tool_call_types:
            # Emitimos DOS bloques separados: tool_call (T) y tool_result (E).
            lines.append(f"[MSG {msg_idx}] role=assistant_tool_call (step {step}, {t})")
            lines.append(_summarize_tool_call(ev))
            msg_idx += 1
            lines.append("")
            lines.append(f"[MSG {msg_idx}] role=tool_result (step {step}, {t})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        elif t in error_types:
            # Tool call que falló: emitimos call + error como result.
            base = t.replace("_error", "")
            lines.append(f"[MSG {msg_idx}] role=assistant_tool_call (step {step}, {base})")
            lines.append(f"{base}(...) -- call failed")
            msg_idx += 1
            lines.append("")
            lines.append(f"[MSG {msg_idx}] role=tool_result (step {step}, {t})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        else:
            # Fallback: 1 bloque genérico
            lines.append(f"[MSG {msg_idx}] role=tool_result (step {step}, {t})")
            lines.append(_summarize_tool_event(ev))
            msg_idx += 1
        lines.append("")

    return "\n".join(lines)
