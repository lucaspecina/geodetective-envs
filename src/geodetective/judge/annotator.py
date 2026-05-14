"""Annotator orchestrator: trace → graph (nodes + edges) + structural patterns.

Pipeline:
1. serialize_trace: trace events → texto numerado [MSG N].
2. Stage 1: judge LLM extrae nodes (H/T/E/J/U/C) con grounding (quote + msg_idx).
3. Stage 2: judge LLM extrae edges con grounding.
4. Stage 3a: detect_patterns_structural deterministic Python sobre el grafo.

Salida: dict serializable a JSON.

Judge default: claude-opus-4-6 (text-only en v1). Para Stage 3b (semantic patterns
+ multimodal) ver iteración futura.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..llm_adapter import complete as llm_complete
from .pattern_matcher import detect_patterns_structural
from .prompts import STAGE1_SYSTEM, STAGE1_USER_TEMPLATE, STAGE2_SYSTEM, STAGE2_USER_TEMPLATE
from .serialize_trace import serialize_trace


@dataclass
class AnnotatorResult:
    trace_id: str
    cid: int
    model: str
    prompt_version: str
    graph: dict = field(default_factory=lambda: {"nodes": [], "edges": []})
    patterns_structural: dict = field(default_factory=dict)
    raw_stage1: Optional[dict] = None
    raw_stage2: Optional[dict] = None
    error: Optional[str] = None
    judge_model: str = "claude-opus-4-6"

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "cid": self.cid,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "judge_model": self.judge_model,
            "graph": self.graph,
            "patterns_structural": self.patterns_structural,
            "raw_stage1": self.raw_stage1,
            "raw_stage2": self.raw_stage2,
            "error": self.error,
        }


def _extract_json(content: str) -> dict:
    """Extrae el primer objeto JSON del content del modelo.

    El modelo puede emitir el JSON crudo o envuelto en ```json ... ```.
    Robusto a ambos.
    """
    content = content.strip()
    # Stripear fences markdown si presentes
    if content.startswith("```"):
        # ```json\n{...}\n``` o ```\n{...}\n```
        m = re.match(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
        if m:
            content = m.group(1).strip()
    return json.loads(content)


def _call_judge(
    judge_model: str,
    system: str,
    user: str,
    max_tokens: int = 16000,
    timeout: float = 180.0,
) -> str:
    resp = llm_complete(
        model=judge_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_completion_tokens=max_tokens,
        timeout=timeout,
    )
    msg = resp.choices[0].message
    return (msg.content or "").strip()


def annotate_trace(
    cid: int,
    model: str,
    prompt_version: str,
    trace: list[dict],
    ground_truth: Optional[dict] = None,
    final_answer: Optional[dict] = None,
    distance_km: Optional[float] = None,
    year_error: Optional[float] = None,
    judge_model: str = "claude-opus-4-6",
    verbose: bool = False,
) -> AnnotatorResult:
    """Anota una trace ReAct y devuelve grafo + patterns structural."""
    trace_id = f"{cid}_{prompt_version}_{model}"
    result = AnnotatorResult(
        trace_id=trace_id,
        cid=cid,
        model=model,
        prompt_version=prompt_version,
        judge_model=judge_model,
    )

    # 1. Serializar
    trace_text = serialize_trace(
        cid=cid,
        model=model,
        prompt_version=prompt_version,
        trace=trace,
        ground_truth=ground_truth,
        final_answer=final_answer,
        distance_km=distance_km,
        year_error=year_error,
    )
    if verbose:
        print(f"[annotator] {trace_id}: serialized {len(trace_text)} chars from {len(trace)} events")

    # 2. Stage 1 — nodes
    # Usamos replace() en lugar de format() porque trace_text contiene `{` `}` del JSON.
    stage1_user = STAGE1_USER_TEMPLATE.replace("{trace_text}", trace_text)
    try:
        s1_text = _call_judge(judge_model, STAGE1_SYSTEM, stage1_user, max_tokens=16000)
        s1_json = _extract_json(s1_text)
        nodes = s1_json.get("nodes", []) or []
        result.raw_stage1 = s1_json
        result.graph["nodes"] = nodes
        if verbose:
            from collections import Counter
            print(f"[annotator] stage1: {len(nodes)} nodes — {dict(Counter(n.get('type', '?') for n in nodes))}")
    except Exception as e:
        result.error = f"Stage 1 failed: {type(e).__name__}: {str(e)[:300]}"
        return result

    # 3. Stage 2 — edges (depende de nodes Stage 1)
    nodes_json = json.dumps({"nodes": nodes}, ensure_ascii=False, indent=2)
    stage2_user = (
        STAGE2_USER_TEMPLATE
        .replace("{nodes_json}", nodes_json)
        .replace("{trace_text}", trace_text)
    )
    try:
        s2_text = _call_judge(judge_model, STAGE2_SYSTEM, stage2_user, max_tokens=16000)
        s2_json = _extract_json(s2_text)
        edges = s2_json.get("edges", []) or []
        result.raw_stage2 = s2_json
        result.graph["edges"] = edges
        if verbose:
            from collections import Counter
            print(f"[annotator] stage2: {len(edges)} edges — {dict(Counter(e.get('relation', '?') for e in edges))}")
    except Exception as e:
        result.error = f"Stage 2 failed: {type(e).__name__}: {str(e)[:300]}"
        return result

    # 4. Stage 3a — pattern matching structural
    try:
        patterns = detect_patterns_structural(nodes, edges)
        result.patterns_structural = patterns
        if verbose:
            prods = [k for k, v in patterns.get("productive", {}).items() if v.get("present")]
            breakds = [k for k, v in patterns.get("breakdowns", {}).items() if v.get("present")]
            print(f"[annotator] stage3a: productive={prods or '[]'}  breakdowns={breakds or '[]'}")
    except Exception as e:
        result.error = f"Stage 3a failed: {type(e).__name__}: {str(e)[:300]}"
        return result

    return result
