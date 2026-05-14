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

    # 1. evidence_led_hypothesis: existe ≥1 E con tiempo < tiempo de la primera H, y E informs H.
    first_h_time = min((h.get("time", 999999) for h in h_nodes), default=None)
    e_before_h = [e for e in e_nodes if first_h_time is not None and e.get("time", 0) < first_h_time]
    informs_e2h = [
        ed for ed in edges
        if ed.get("relation") == "informs" and any(e["node_id"] == ed.get("src") for e in e_nodes)
        and any(h["node_id"] == ed.get("dst") for h in h_nodes)
    ]
    productive["evidence_led_hypothesis"] = {
        "present": len(e_before_h) >= 1 and len(informs_e2h) >= 1,
        "nodes": [e["node_id"] for e in e_before_h[:3]],
    }

    # 2. hypothesis_reranking: ≥1 edge competing entre H.
    competing_edges = [ed for ed in edges if ed.get("relation") == "competing"]
    productive["hypothesis_reranking"] = {
        "present": len(competing_edges) >= 1,
        "nodes": list({e.get("src") for e in competing_edges} | {e.get("dst") for e in competing_edges}),
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

    # 4. explore_then_test_transition: hay E (especialmente visual_crop) antes de la primera H.
    early_e_visual = [
        e for e in e_nodes
        if first_h_time is not None and e.get("time", 0) < first_h_time
        and e.get("modality") in ("visual_primary", "visual_crop")
    ]
    productive["explore_then_test_transition"] = {
        "present": len(early_e_visual) >= 1,
        "nodes": [e["node_id"] for e in early_e_visual[:3]],
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
    fixed_tuning = False
    fixed_h: list[str] = []
    for h in h_nodes:
        testing_edges = [ed for ed in edges if ed.get("relation") == "testing" and ed.get("src") == h["node_id"]]
        if len(testing_edges) >= 2:
            updates_to_h = [ed for ed in edges if ed.get("relation") == "updating" and ed.get("dst") == h["node_id"]]
            if not updates_to_h:
                fixed_tuning = True
                fixed_h.append(h["node_id"])
    productive["fixed_hypothesis_test_tuning"] = {
        "present": fixed_tuning,
        "nodes": fixed_h,
    }

    # 7. evidence_guided_test_redesign: J → T → E chain donde J no tiene H que la respalde via H→J relation (heurística).
    # Simplificación: J con incoming informs E + outgoing edge a un T.
    redesign = False
    redesign_nodes: list[str] = []
    for j in j_nodes:
        j_incoming_e = any(ed.get("relation") == "informs" and ed.get("dst") == j["node_id"] for ed in edges)
        j_outgoing_t = any(ed.get("src") == j["node_id"] and ed.get("dst") in {t["node_id"] for t in t_nodes} for ed in edges)
        if j_incoming_e and j_outgoing_t:
            redesign = True
            redesign_nodes.append(j["node_id"])
    productive["evidence_guided_test_redesign"] = {
        "present": redesign,
        "nodes": redesign_nodes,
    }

    # 8. temporal_spatial_anchoring (geo-specific): ≥2 H con texts que tocan temporal y espacial.
    # Heurística: H.text matchea keywords temporales (year, decade, century, 19xx) vs espaciales (city, town, country names).
    import re
    temporal_re = re.compile(r"\b(year|decade|century|18\d{2}|19\d{2}|20\d{2})\b", re.IGNORECASE)
    spatial_re = re.compile(r"\b(city|town|village|country|region|near|in)\b", re.IGNORECASE)
    h_temporal = [h for h in h_nodes if temporal_re.search(h.get("text", ""))]
    h_spatial = [h for h in h_nodes if spatial_re.search(h.get("text", ""))]
    productive["temporal_spatial_anchoring"] = {
        "present": len(h_temporal) >= 1 and len(h_spatial) >= 1,
        "nodes": [h["node_id"] for h in (h_temporal[:1] + h_spatial[:1])],
    }

    # 9. language_pivot_productive (geo-specific): T con query en idioma X (low Cyrillic content) seguido de T con query en idioma Y (Cyrillic / non-ASCII).
    # Heurística: ¿alguna T cuyo texto contiene caracteres no-ASCII después de una T con texto puramente ASCII?
    def _is_nonascii(s: str) -> bool:
        return any(ord(c) > 127 for c in (s or ""))
    t_sorted = sorted(t_nodes, key=lambda n: n.get("time", 0))
    pivot = False
    pivot_nodes: list[str] = []
    for i, t1 in enumerate(t_sorted[:-1]):
        t1_text = t1.get("text", "")
        for t2 in t_sorted[i+1:]:
            t2_text = t2.get("text", "")
            if not _is_nonascii(t1_text) and _is_nonascii(t2_text):
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

    # 2. contradiction_without_repair: E→H contradicting sin U posterior modificando esa H.
    contra_no_repair = []
    for ed in edges:
        if ed.get("relation") != "contradicting":
            continue
        dst = ed.get("dst")
        ed_time = ed.get("time", 0)
        # ¿hay un U targeting dst después de ed_time?
        repair = any(
            u_ed.get("relation") == "updating" and u_ed.get("src") == ed.get("src")
            and any(uu.get("dst") == dst and uu.get("time", 0) > ed_time for uu in edges if uu.get("relation") == "updating")
            for u_ed in edges
        )
        if not repair:
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
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "nodes_by_type": {k: len(v) for k, v in by_type.items()},
    }
