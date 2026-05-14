"""Process evaluation annotator (CORRAL-adapted).

Ver `research/synthesis/process_eval_design.md` para el diseño completo.

Pipeline:
- serialize_trace: trace agéntica → texto consumible por judge.
- prompts: system + user prompts para Stage 1 (nodes) + Stage 2 (edges).
- annotator: orquesta Stage 1+2 via llm_adapter, devuelve grafo.
- pattern_matcher: Stage 3a deterministic Python sobre el grafo.
"""
from .annotator import annotate_trace, AnnotatorResult
from .pattern_matcher import detect_patterns_structural

__all__ = ["annotate_trace", "AnnotatorResult", "detect_patterns_structural"]
