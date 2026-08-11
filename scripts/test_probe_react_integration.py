"""Integración mínima del probe con el loop ReAct, sin red ni APIs."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path("src").resolve()))

from geodetective.agents.react import (
    SUBMIT_TOOL_SCHEMA,
    TOOL_SCHEMA_CROP_RELATIVE,
    run_react_agent,
)
from geodetective.corpus import CLEAN_VERSION
from geodetective.probes import ProbeConfig, ProbeInjector
from run_prefix_fork_pilot import _paired_summary
from run_probe_smoke import _run_key


CID = 1425423
PHOTO = Path("corpus/photos") / f"{CID}_clean_v{CLEAN_VERSION}.jpg"
TRUTH = (-36.8443, 174.7668)


def _belief(weight: float) -> dict:
    return {
        "location_belief": [{
            "name": "Auckland",
            "lat": TRUTH[0],
            "lon": TRUTH[1],
            "weight": weight,
            "radius_km": 2,
        }],
        "year_belief": [{"from": 1900, "to": 1910, "weight": 0.8}],
        "rationale": "test",
    }


def _call(call_id: str, name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _response(*calls: SimpleNamespace) -> SimpleNamespace:
    message = SimpleNamespace(
        content="",
        tool_calls=list(calls),
        thinking_blocks=[],
        finish_reason="tool_calls",
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])


def main() -> None:
    if not PHOTO.exists():
        raise SystemExit(f"Falta foto local para el test: {PHOTO}")

    scripted = iter([
        # Debe deferir: el report comparte turn con una tool que produce evidencia.
        _response(
            _call("r1", "report_belief", _belief(0.85)),
            _call("c1", "crop_image_relative", {"region": "center"}),
        ),
        # Primer checkpoint report-only: acá sí debe disparar.
        _response(_call("r2", "report_belief", _belief(0.85))),
        # Report inmediato posterior al boletín.
        _response(_call("r3", "report_belief", _belief(0.75))),
        _response(_call("s1", "submit_answer", {
            "location": "Auckland",
            "lat": TRUTH[0],
            "lon": TRUTH[1],
            "year": "1905",
            "reasoning": "test",
            "confidence": "alta",
            "final_belief_top": {
                "name": "Auckland",
                "lat": TRUTH[0],
                "lon": TRUTH[1],
                "weight": 0.75,
            },
        })),
    ])

    def fake_complete(**_: object) -> SimpleNamespace:
        return next(scripted)

    injector = ProbeInjector(
        *TRUTH,
        ProbeConfig(family="P1", arm="contradiction", min_step=1, max_budget_frac=1.0),
    )
    with patch("geodetective.agents.react.llm_complete", side_effect=fake_complete):
        result = run_react_agent(
            image_path=PHOTO,
            model="fake",
            max_steps=4,
            belief_mode=True,
            belief_nudge_after=99,
            probe_injector=injector,
            verbose=False,
        )

    deferred = [e for e in result.trace if e.get("type") == "probe_deferred_coemitted_tools"]
    injections = [e for e in result.trace if e.get("type") == "probe_injection"]
    assert deferred and deferred[0]["step"] == 1, deferred
    assert deferred[0]["coemitted_tools"] == ["crop_image_relative"], deferred
    assert len(injections) == 1 and injections[0]["step"] == 2, injections
    assert injector.record.fired and injector.record.step == 2, injector.record
    assert result.submit_called and result.terminal_state == "submitted", result
    print("OK: probe deferido en coemisión y disparado en el siguiente report-only")

    base_record = {
        "cid": CID,
        "arm": "contradiction",
        "family": "P1",
        "agent_max_steps": 20,
        "agent_min_steps": 0,
        "probe_min_step": 4,
        "probe_max_budget_frac": 0.6,
    }
    assert _run_key(base_record) != _run_key({**base_record, "family": "P5"})
    assert _run_key(base_record) != _run_key({**base_record, "agent_max_steps": 30})

    def branch(
        arm: str, delta: float, boundary: bool = False,
        polarity: str = "ii", post_mass: float = 0.7,
    ) -> dict:
        return {
            "stage": "first_eligible",
            "rep": 0,
            "arm": arm,
            "checkpoint_step": 4,
            "checkpoint_hash": "same",
            "protocol_ok": True,
            "pre_mass": 0.8,
            "polarity": polarity,
            "response": {
                "polarity": polarity,
                "delta_logit": delta,
                "post_mass": post_mass,
                "at_boundary": boundary,
            },
            "next_tool_calls": ["web_search"],
            "immediate_stop": False,
        }

    good = _paired_summary([branch("contradiction", -0.4), branch("placebo", 0.0)])
    assert good[0]["comparable"] and good[0]["placebo_adjusted_elasticity"] > 0, good
    boundary = _paired_summary([
        branch("contradiction", -0.4), branch("placebo", 0.0, boundary=True)
    ])
    assert not boundary[0]["comparable"], boundary
    assert "placebo_boundary_mass" in boundary[0]["exclusion_reasons"], boundary
    decisive = _paired_summary([
        branch("contradiction", -4.0, boundary=True, polarity="i", post_mass=0.01),
        branch("placebo", 0.0, boundary=True, polarity="i", post_mass=0.8),
    ])
    assert decisive[0]["comparable"], decisive
    assert decisive[0]["placebo_adjusted_mass_change"] == -0.79, decisive
    assert decisive[0]["placebo_adjusted_elasticity"] is None, decisive
    print("OK: keys separan configuración y pares inválidos quedan excluidos")

    # Resume exacto: debe usar el historial recibido y continuar con numeración
    # absoluta, sin reconstruir otro prefijo.
    resume_prefix = [
        {"role": "system", "content": "test resume"},
        {"role": "user", "content": "continuá"},
    ]
    seen: list[dict] = []

    def fake_resume(**kwargs: object) -> SimpleNamespace:
        seen.append(kwargs)
        return _response(_call("s2", "submit_answer", {
            "location": "Auckland",
            "lat": TRUTH[0],
            "lon": TRUTH[1],
            "year": "1905",
            "reasoning": "resume test",
            "confidence": "alta",
        }))

    with patch("geodetective.agents.react.llm_complete", side_effect=fake_resume):
        resumed = run_react_agent(
            image_path=PHOTO,
            model="fake",
            max_steps=6,
            start_step=5,
            resume_messages=resume_prefix,
            resume_tools=[SUBMIT_TOOL_SCHEMA],
            verbose=False,
        )
    assert seen and seen[0]["messages"][:2] == resume_prefix, seen
    assert resumed.steps_used == 6 and resumed.terminal_state == "submitted", resumed
    print("OK: resume continúa el prefijo exacto y conserva la numeración absoluta")

    # El horizonte experimental corta la copia sin hacerle creer al agente que
    # agotó el budget original.
    with patch(
        "geodetective.agents.react.llm_complete",
        return_value=_response(
            _call("c2", "crop_image_relative", {"region": "center"})
        ),
    ):
        horizon = run_react_agent(
            image_path=PHOTO,
            model="fake",
            max_steps=10,
            start_step=4,
            continuation_steps=1,
            resume_messages=resume_prefix,
            resume_tools=[TOOL_SCHEMA_CROP_RELATIVE],
            verbose=False,
        )
    assert horizon.steps_used == 5, horizon
    assert horizon.terminal_state == "continuation_horizon_reached", horizon
    assert any(e.get("step") == 5 and e.get("type") == "crop_image_relative"
               for e in horizon.trace), horizon.trace
    print("OK: continuation_steps ejecuta tools reales y corta con estado propio")

    # Un observer puede detener una trayectoria base exactamente después de un
    # checkpoint, sin ejecutar turns que ya no se usarán.
    observed: list[dict] = []

    def stop_on_checkpoint(payload: dict) -> bool:
        observed.append(payload)
        return True

    with patch(
        "geodetective.agents.react.llm_complete",
        return_value=_response(_call("r4", "report_belief", _belief(0.7))),
    ):
        stopped = run_react_agent(
            image_path=PHOTO,
            model="fake",
            max_steps=10,
            belief_mode=True,
            checkpoint_observer=stop_on_checkpoint,
            capture_runtime_state=True,
            verbose=False,
        )
    assert stopped.steps_used == 1
    assert stopped.terminal_state == "checkpoint_observer_stop", stopped
    assert len(observed) == 1 and observed[0]["step"] == 1
    assert "runtime_state" in observed[0]
    print("OK: la base se detiene justo después del primer checkpoint elegible")


if __name__ == "__main__":
    main()
