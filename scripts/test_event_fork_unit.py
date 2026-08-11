"""Checks offline del protocolo de evento fijo E019."""
from __future__ import annotations

import copy
import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path("src").resolve()))
sys.path.insert(0, str(Path("scripts").resolve()))

from geodetective.agents.react import BELIEF_TOOL_SCHEMA
from run_event_fork_pilot import (
    TOTAL_BP,
    _augment_belief_tool,
    _bulletin,
    _choose_checkpoint,
    _continuation_summary,
    _score_update,
    _validate_event_report,
)


EVENT = {
    "event_id": "disk25_m36.85000_p174.76000",
    "lat": -36.85,
    "lon": 174.76,
    "radius_km": 25.0,
}


def _belief(inside: int, ring: int, outside: int) -> dict:
    assert inside + ring + outside == TOTAL_BP
    return {
        "location_belief": [{
            "name": "Auckland",
            "lat": EVENT["lat"],
            "lon": EVENT["lon"],
            "weight": inside / TOTAL_BP,
            "radius_km": 5,
        }],
        "year_belief": [{"from": 1900, "to": 1910, "weight": 1.0}],
        "event_belief": {
            "event_id": EVENT["event_id"],
            "inside_25km_bp": inside,
            "ring_25_100km_bp": ring,
            "outside_100km_bp": outside,
        },
        "rationale": "test",
    }


def main() -> None:
    original = copy.deepcopy(BELIEF_TOOL_SCHEMA)
    tools = _augment_belief_tool([BELIEF_TOOL_SCHEMA], EVENT)
    params = tools[0]["function"]["parameters"]
    assert "event_belief" in params["required"]
    assert "event_belief" not in original["function"]["parameters"]["required"]
    print("OK: el schema del fork exige bins fijos sin mutar el schema global")

    pre = _belief(7000, 1000, 2000)
    ok, error = _validate_event_report(pre, EVENT)
    assert ok and error is None
    malformed = copy.deepcopy(pre)
    malformed["event_belief"]["inside_25km_bp"] = 7001
    ok, error = _validate_event_report(malformed, EVENT)
    assert not ok and "suman" in error
    print("OK: los tres bins deben ser enteros, fijos y sumar 10000")

    # Con prior .70 y señal OUT de un canal 70/30, Bayes da posterior .50.
    post = _belief(5000, 1667, 3333)
    scored = _score_update(pre, post, EVENT, "contradiction")
    expected = math.log(0.3 / 0.7)
    assert abs(scored["delta_logit_inside"] - expected) < 1e-4, scored
    assert abs(scored["response_ratio"] - 1.0) < 1e-4, scored
    assert abs(scored["outside_ring_share_pre"] - scored["outside_ring_share_post"]) < 1e-4
    placebo = _score_update(pre, pre, EVENT, "placebo")
    assert placebo["delta_logit_inside"] == 0.0
    print("OK: el score recupera la actualización bayesiana conocida y el placebo nulo")

    contradiction = _bulletin(EVENT, "contradiction")
    placebo_text = _bulletin(EVENT, "placebo")
    for text in (contradiction, placebo_text):
        assert EVENT["event_id"] in text
        assert "calibrated_geo_channel" in text
        assert "PRÓXIMA y ÚNICA" in text
    assert '"signal": "OUTSIDE_SIGNAL"' in contradiction
    assert '"likelihood_ratio_inside_vs_outside": 1.0' in placebo_text
    print("OK: ambos brazos hablan del mismo evento y declaran su LR")

    continued = SimpleNamespace(
        trace=[
            {"step": 5, "type": "empty_response_diagnosis", "finish_reason": "end_turn"},
            {"step": 6, "type": "web_search_error", "query": "test", "error": "offline"},
        ],
        final_answer=None,
        terminal_state="continuation_horizon_reached",
        steps_used=6,
        submit_called=False,
        belief_reports=[],
        error=None,
    )
    summary = _continuation_summary(continued, EVENT, [EVENT["lat"], EVENT["lon"]])
    assert summary["protocol_perturbations"][0]["type"] == "empty_response_diagnosis"
    assert summary["first_actions"][0]["attempted_action"] == "web_search"
    print("OK: correctivos invalidantes y acciones fallidas quedan visibles")

    checkpoint = {
        "step": 5,
        "belief": _belief(7000, 1000, 2000),
        "coemitted_tools": ["web_search"],
        "context": {},
        "checkpoint_hash": "test",
    }
    chosen, inventory = _choose_checkpoint([checkpoint])
    assert chosen is checkpoint and inventory[0]["eligible"]
    print("OK: una coemisión ya resuelta no contamina el pre común posterior")


if __name__ == "__main__":
    main()
