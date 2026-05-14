"""Stage 3a: pattern detection graph-structural (Python determinista, NO LLM).

Detecta productive motifs y reasoning breakdowns que se pueden definir
puramente sobre la estructura del grafo (nodos + edges).

Productive motifs structural (7 de CORRAL + 2 geo-específicos = 9):
- evidence_led_hypothesis: existe edge E→H informs antes que la propia H se use como source.
- hypothesis_reranking: 2+ H con edge competing entre sí.
- refutation_driven_belief_revision: cadena H1 →testing T → E (contradicting) → U → updating H2.
- explore_then_test_transition: hay E (visual_crop o textual) antes que la primera H.
- convergent_multi_test_evidence: una H tiene ≥2 T independientes con edges observing → E.
- fixed_hypothesis_test_tuning: una H tiene ≥2 T sin updates a esa H entre ellos.
- evidence_guided_test_redesign: cadena J → T → E donde la J no está conectada a una H.
- temporal_spatial_anchoring (geo): existen 2 H simultáneas con dominios distintos (temporal y espacial) que reciben updates.
- language_pivot_productive (geo): patrón T(query lang A, E vacía) → T(query lang B, E informativa).

Breakdowns structural (7 de CORRAL):
- untested_claim: H sin edge testing a ningún T.
- contradiction_without_repair: edge E→H contradicting sin U ni H' subsiguiente.
- premature_commitment: C terminal sin T anterior (counter-based).
- evidence_non_uptake: E sin edges salientes.
- disconnected_evidence: E sin ningún edge incidente.
- uninformative_test: T sin E observada (T sin edge observing).
- fixed_belief_trace: trace sin ningún U.
- stalled_revision: U → H pero H sin T después.

Patterns NO structural (defer a Stage 3b LLM judge):
- one_sided_confirmation, unsupported_judgment, precommitted_test_plan
- proxy_substitution, tool_channel_mismatch, geocoding_loop
- language_monolingual_fixation, visual_hallucination, multi_modal_cross_validation
"""
from __future__ import annotations

from typing import Any


def _nodes_by_type(nodes: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"H": [], "T": [], "E": [], "J": [], "U": [], "C": []}
    for n in nodes:
        t = n.get("type")
        if t in out:
            out[t].append(n)
    return out


def _index_edges(edges: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """(out_edges_by_src, in_edges_by_dst)."""
    out_by_src: dict[str, list[dict]] = {}
    in_by_dst: dict[str, list[dict]] = {}
    for e in edges:
        src = e.get("src")
        dst = e.get("dst")
        if src:
            out_by_src.setdefault(src, []).append(e)
        if dst:
            in_by_dst.setdefault(dst, []).append(e)
    return out_by_src, in_by_dst


def detect_patterns_structural(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """Detecta patterns sobre el grafo. Devuelve dict con:
    - productive: {motif_name: {present: bool, nodes: [ids]}}
    - breakdowns: {pattern_name: {present: bool, nodes: [ids]}}
    """
    by_type = _nodes_by_type(nodes)
    out_by_src, in_by_dst = _index_edges(edges)

    productive: dict[str, dict] = {}
    breakdowns: dict[str, dict] = {}

    # ---- Productive ----

    # untested_claim helpers
    h_nodes = by_type["H"]
    t_nodes = by_type["T"]
    e_nodes = by_type["E"]
    u_nodes = by_type["U"]
    c_nodes = by_type["C"]
    j_nodes = by_type["J"]

    # Helpers comunes a varios motifs
    first_h_time = min((h.get("time", 999999) for h in h_nodes), default=None)

    # 1. evidence_led_hypothesis: existe E con E.time < H.time + edge E→H informs
    # con el MISMO E. Codex review: la versión previa era tautológica (cualquier
    # E + cualquier informs E→H bastaba, sin relación causal).
    # Además excluimos MSG0 (la foto target inicial siempre precede a cualquier H,
    # eso no cuenta como "evidence-led" — necesitamos E generado por exploración).
    informs_pairs: list[tuple[str, str]] = [
        (ed.get("src"), ed.get("dst")) for ed in edges
        if ed.get("relation") == "informs"
    ]
    e_id_to_node = {e["node_id"]: e for e in e_nodes}
    h_id_to_node = {h["node_id"]: h for h in h_nodes}
    evidence_led = False
    evidence_led_nodes: list[str] = []
    for src_id, dst_id in informs_pairs:
        if src_id in e_id_to_node and dst_id in h_id_to_node:
            e_node = e_id_to_node[src_id]
            h_node = h_id_to_node[dst_id]
            # Excluir MSG0 (foto target inicial)
            if e_node.get("time", 0) == 0:
                continue
            if e_node.get("time", 0) < h_node.get("time", 999999):
                evidence_led = True
                evidence_led_nodes = [src_id, dst_id]
                break
    productive["evidence_led_hypothesis"] = {
        "present": evidence_led,
        "nodes": evidence_led_nodes,
    }

    # 2. hypothesis_reranking: competing edge + AMBAS H deben estar testeadas O haber update.
    # Codex review: solo "any competing edge" era lenient si el judge sobregenera.
    competing_edges = [ed for ed in edges if ed.get("relation") == "competing"]
    rerank_present = False
    rerank_nodes: list[str] = []
    for ce in competing_edges:
        src_id = ce.get("src")
        dst_id = ce.get("dst")
        src_tested = any(ed.get("relation") == "testing" and ed.get("src") == src_id for ed in edges)
        dst_tested = any(ed.get("relation") == "testing" and ed.get("src") == dst_id for ed in edges)
        either_updated = any(
            ed.get("relation") == "updating" and ed.get("dst") in (src_id, dst_id)
            for ed in edges
        )
        if (src_tested and dst_tested) or either_updated:
            rerank_present = True
            rerank_nodes = [src_id, dst_id]
            break
    productive["hypothesis_reranking"] = {
        "present": rerank_present,
        "nodes": rerank_nodes,
    }

    # 3. refutation_driven_belief_revision: cadena H → T → E (contradicting) → U → H'.
    refutation = False
    refutation_nodes: list[str] = []
    for u in u_nodes:
        # u must have outgoing updating edge to some H
        u_out = out_by_src.get(u["node_id"], [])
        has_updating = any(e.get("relation") == "updating" for e in u_out)
        # u should be near a contradicting E (any contradicting edge incoming to a J or H around u's time)
        u_time = u.get("time", 0)
        nearby_contradict = any(
            ed.get("relation") == "contradicting" and abs(ed.get("time", 0) - u_time) <= 4
            for ed in edges
        )
        if has_updating and nearby_contradict:
            refutation = True
            refutation_nodes.append(u["node_id"])
    productive["refutation_driven_belief_revision"] = {
        "present": refutation,
        "nodes": refutation_nodes,
    }

    # 4. explore_then_test_transition: hay E producido por TOOL EXPLORATION
    # (visual_crop o textual, NO el MSG0 foto inicial) antes de la primera H,
    # Y esa H después es testeada. Codex review: la versión previa era tautológica
    # porque MSG0 siempre tiene E visual_primary antes de H — eso no es "exploration".
    first_h_time_v = first_h_time if first_h_time is not None else 999999
    early_e_exploration = [
        e for e in e_nodes
        if e.get("time", 0) > 0  # excluye MSG0 (foto inicial)
        and e.get("time", 0) < first_h_time_v
        and e.get("modality") in ("visual_crop", "textual")
    ]
    # Y la H que sigue debe haber sido testeada (no quedó como claim suelto).
    first_h = next((h for h in h_nodes if h.get("time") == first_h_time), None)
    first_h_tested = False
    if first_h:
        first_h_tested = any(
            ed.get("relation") == "testing" and ed.get("src") == first_h["node_id"]
            for ed in edges
        )
    productive["explore_then_test_transition"] = {
        "present": len(early_e_exploration) >= 1 and first_h_tested,
        "nodes": [e["node_id"] for e in early_e_exploration[:3]],
    }

    # 5. convergent_multi_test_evidence: ≥1 H con ≥2 T testing edges + cada T tiene E observada.
    convergent = False
    convergent_h: list[str] = []
    for h in h_nodes:
        testing_edges = [ed for ed in edges if ed.get("relation") == "testing" and ed.get("src") == h["node_id"]]
        if len(testing_edges) >= 2:
            t_ids = [ed.get("dst") for ed in testing_edges]
            with_e = [tid for tid in t_ids if any(ed.get("relation") == "observing" and ed.get("src") == tid for ed in edges)]
            if len(with_e) >= 2:
                convergent = True
                convergent_h.append(h["node_id"])
    productive["convergent_multi_test_evidence"] = {
        "present": convergent,
        "nodes": convergent_h,
    }

    # 6. fixed_hypothesis_test_tuning: H con ≥2 T testing + sin U targeting esa H.
    # Codex review: conceptualmente ambiguo. Puede ser productive (refinar T) o
    # stubbornness. Movido a categoría 'neutral' — reportado pero NO contado
    # como productive por defecto.
    fixed_tuning = False
    fixed_h: list[str] = []
    for h in h_nodes:
        testing_edges = [ed for ed in edges if ed.get("relation") == "testing" and ed.get("src") == h["node_id"]]
        if len(testing_edges) >= 2:
            updates_to_h = [ed for ed in edges if ed.get("relation") == "updating" and ed.get("dst") == h["node_id"]]
            if not updates_to_h:
                fixed_tuning = True
                fixed_h.append(h["node_id"])
    # NOTE: reportado en sección separada `neutral`, no en `productive`.
    neutral_fixed_tuning = {
        "present": fixed_tuning,
        "nodes": fixed_h,
        "note": "ambiguo: refinement productive o stubbornness — necesita semantic judge",
    }

    # 7. evidence_guided_test_redesign: J informada por E genera reformulación
    # vía nueva H (no T directo — Stage2 schema no permite J→T).
    # Codex review: motif previo dependía de edge J→T que NO existe en el schema.
    # Re-definido: J recibe informs E (contradicting o no), seguido temporalmente
    # de una nueva H (no la misma), seguida de T sobre esa H.
    redesign = False
    redesign_nodes: list[str] = []
    for j in j_nodes:
        # ¿J recibió informs de alguna E?
        if not any(ed.get("relation") == "informs" and ed.get("dst") == j["node_id"] for ed in edges):
            continue
        j_time = j.get("time", 0)
        # ¿Hay una H nueva después de j_time?
        h_after = [h for h in h_nodes if h.get("time", 0) > j_time]
        if not h_after:
            continue
        # ¿Esa nueva H tiene T testing?
        for h in h_after:
            if any(ed.get("relation") == "testing" and ed.get("src") == h["node_id"] for ed in edges):
                redesign = True
                redesign_nodes = [j["node_id"], h["node_id"]]
                break
        if redesign:
            break
    productive["evidence_guided_test_redesign"] = {
        "present": redesign,
        "nodes": redesign_nodes,
    }

    # 8. temporal_spatial_anchoring (geo-specific): H temporal + H espacial
    # coexistentes y ambas testeadas. Codex review: regex previo con `\bin\b`
    # matcheaba media oración. Reescrito con keywords más estrictos y validación
    # de que AMBAS H están testeadas (no solo nombradas).
    import re
    temporal_re = re.compile(r"\b(year|decade|century|18\d{2}|19\d{2}|20\d{2}|1[89][0-9]0s|20\d{2}s)\b", re.IGNORECASE)
    # Spatial: nombres propios (capitalizados) o keywords geo explícitas, sin `in`.
    spatial_kw = re.compile(r"\b(city|town|village|country|region|province|district|state|capital|street|plaza|square)\b", re.IGNORECASE)
    spatial_propn = re.compile(r"\b[A-Z][a-z]{3,}(?:\s+[A-Z][a-z]+)?\b")  # palabras capitalizadas (heurística NER pobre)
    h_temporal = [h for h in h_nodes if temporal_re.search(h.get("text", ""))]
    h_spatial = [
        h for h in h_nodes
        if spatial_kw.search(h.get("text", "")) or spatial_propn.search(h.get("text", ""))
    ]
    # AMBOS tipos de H deben tener edge testing.
    def _is_tested(h_node: dict) -> bool:
        return any(ed.get("relation") == "testing" and ed.get("src") == h_node["node_id"] for ed in edges)
    h_temporal_tested = [h for h in h_temporal if _is_tested(h)]
    h_spatial_tested = [h for h in h_spatial if _is_tested(h)]
    productive["temporal_spatial_anchoring"] = {
        "present": len(h_temporal_tested) >= 1 and len(h_spatial_tested) >= 1,
        "nodes": [h["node_id"] for h in (h_temporal_tested[:1] + h_spatial_tested[:1])],
    }

    # 9. language_pivot_productive (geo-specific): T en idioma A seguido de T en
    # idioma B con uptake (B genera E que informa una H o J). Codex review: la
    # versión previa ignoraba si el pivot mejoró evidencia — solo verificaba orden
    # de idioma. Ahora requerimos: (a) cambio de script (ASCII↔nonASCII), (b) T2
    # tiene edge observing → E2, (c) E2 tiene outgoing edge a H o J.
    def _is_nonascii(s: str) -> bool:
        return any(ord(c) > 127 for c in (s or ""))
    t_sorted = sorted(t_nodes, key=lambda n: n.get("time", 0))
    pivot = False
    pivot_nodes: list[str] = []
    for i, t1 in enumerate(t_sorted[:-1]):
        t1_text = t1.get("text", "")
        for t2 in t_sorted[i+1:]:
            t2_text = t2.get("text", "")
            # Cambio de script entre t1 y t2
            if _is_nonascii(t1_text) == _is_nonascii(t2_text):
                continue
            # ¿t2 tiene observing → E (uptake)?
            t2_e_edges = [ed for ed in edges if ed.get("relation") == "observing" and ed.get("src") == t2["node_id"]]
            if not t2_e_edges:
                continue
            t2_e_ids = [ed.get("dst") for ed in t2_e_edges]
            # ¿Esa E informa o contradice a alguna H/J posterior?
            uptake_relations = {"informs", "contradicting"}
            e_used = any(
                ed.get("src") in t2_e_ids and ed.get("relation") in uptake_relations
                for ed in edges
            )
            if e_used:
                pivot = True
                pivot_nodes = [t1["node_id"], t2["node_id"]]
                break
        if pivot:
            break
    productive["language_pivot_productive"] = {
        "present": pivot,
        "nodes": pivot_nodes,
    }

    # ---- Breakdowns ----

    # 1. untested_claim: H sin edge testing.
    untested = []
    for h in h_nodes:
        has_test = any(ed.get("relation") == "testing" and ed.get("src") == h["node_id"] for ed in edges)
        if not has_test:
            untested.append(h["node_id"])
    breakdowns["untested_claim"] = {"present": len(untested) > 0, "nodes": untested[:3]}

    # 2. contradiction_without_repair: E→H/J contradicting sin U posterior con
    # updating edge a una H (la misma o una H' alternativa) después de ed_time.
    # Codex review: la versión previa tenía bug — buscaba `u_ed.src == ed.src`
    # pero `ed.src` es E node y `updating` sale de U node. No matcheaba semánticamente.
    # Reescritura: para cada contradicting edge a tiempo T_c, verificamos que
    # existe AL MENOS UN edge `updating` con time > T_c (el agente revisó algo
    # después de la contradicción).
    contra_no_repair = []
    for ed in edges:
        if ed.get("relation") != "contradicting":
            continue
        dst = ed.get("dst")
        ed_time = ed.get("time", 0)
        # ¿Hay algún edge `updating` posterior a ed_time? Esa es la señal de "repair".
        any_update_after = any(
            u_ed.get("relation") == "updating" and u_ed.get("time", 0) > ed_time
            for u_ed in edges
        )
        if not any_update_after:
            contra_no_repair.append(dst)
    breakdowns["contradiction_without_repair"] = {
        "present": len(contra_no_repair) > 0,
        "nodes": contra_no_repair[:3],
    }

    # 3. premature_commitment: C terminal con MUY pocos T antes.
    terminal_c = [c for c in c_nodes if c.get("terminal")]
    if terminal_c:
        c_time = min(c.get("time", 999999) for c in terminal_c)
        t_before = [t for t in t_nodes if t.get("time", 0) < c_time]
        premature = len(t_before) < 2
    else:
        premature = False
    breakdowns["premature_commitment"] = {
        "present": premature,
        "nodes": [c["node_id"] for c in terminal_c[:1]],
    }

    # 4. evidence_non_uptake: E sin edges salientes.
    non_uptake = [e["node_id"] for e in e_nodes if e["node_id"] not in out_by_src or not out_by_src[e["node_id"]]]
    breakdowns["evidence_non_uptake"] = {
        "present": len(non_uptake) >= 2,  # threshold relaxed: 2+ es señal sistemática
        "nodes": non_uptake[:5],
    }

    # 5. disconnected_evidence: E sin ningún edge in/out.
    disconnected = [
        e["node_id"] for e in e_nodes
        if e["node_id"] not in out_by_src and e["node_id"] not in in_by_dst
    ]
    breakdowns["disconnected_evidence"] = {
        "present": len(disconnected) >= 2,
        "nodes": disconnected[:5],
    }

    # 6. uninformative_test: T sin edge observing.
    uninformative = [
        t["node_id"] for t in t_nodes
        if not any(ed.get("relation") == "observing" and ed.get("src") == t["node_id"] for ed in edges)
    ]
    breakdowns["uninformative_test"] = {
        "present": len(uninformative) >= 2,
        "nodes": uninformative[:5],
    }

    # 7. fixed_belief_trace: cero U en la trace.
    breakdowns["fixed_belief_trace"] = {
        "present": len(u_nodes) == 0,
        "nodes": [],
    }

    # 8. stalled_revision: U → H pero H sin T después.
    stalled = []
    for u in u_nodes:
        targets = [ed.get("dst") for ed in out_by_src.get(u["node_id"], []) if ed.get("relation") == "updating"]
        for h_id in targets:
            h_obj = next((h for h in h_nodes if h["node_id"] == h_id), None)
            if h_obj:
                h_time = h_obj.get("time", 0)
                tested_after = any(
                    ed.get("relation") == "testing" and ed.get("src") == h_id and ed.get("time", 0) > h_time
                    for ed in edges
                )
                if not tested_after:
                    stalled.append(h_id)
    breakdowns["stalled_revision"] = {
        "present": len(stalled) > 0,
        "nodes": stalled[:3],
    }

    return {
        "productive": productive,
        "breakdowns": breakdowns,
        "neutral": {
            # Patterns conceptualmente ambiguos — reportados sin categorizar como prod/break.
            "fixed_hypothesis_test_tuning": neutral_fixed_tuning,
        },
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "nodes_by_type": {k: len(v) for k, v in by_type.items()},
    }
