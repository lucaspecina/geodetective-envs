"""Tests sintéticos del belief-mode en el scaffold ReAct (E016, #47).

Cubre (sin llamar al LLM):
- _validate_belief: casos válidos (incluida lista vacía = "no sé"), pesos > 1,
  lat/lon fuera de rango, radius <= 0, year from > to, > 5 candidatos, campos faltantes.
- Ensamblado de schemas: BELIEF_TOOL_SCHEMA bien formado; evidence_chain presente
  en la copia belief-mode del submit y AUSENTE en el SUBMIT_TOOL_SCHEMA canónico
  (sin mutación — el brazo OFF de la ablation tiene que quedar idéntico).
- Round-trip: un report_belief válido parsea con Belief.from_dict y puntúa
  con score_belief (integración scaffold → scorer post-hoc).

Uso: python scripts/test_belief_tool.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.agents.react import (  # noqa: E402
    BELIEF_PROMPT_SECTION,
    BELIEF_TOOL_SCHEMA,
    DEFAULT_TOOL_COSTS,
    SUBMIT_TOOL_SCHEMA,
    _budget_prompt_section,
    _submit_schema_with_evidence_chain,
    _validate_belief,
)
from geodetective.eval.belief_scoring import Belief, score_belief  # noqa: E402


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return cond


def _belief(loc=None, yr=None) -> dict:
    return {"location_belief": loc if loc is not None else [], "year_belief": yr if yr is not None else []}


VALID_LOC = {"name": "Lisboa", "lat": 38.72, "lon": -9.14, "weight": 0.5, "radius_km": 30}
VALID_YR = {"from": 1925, "to": 1940, "weight": 0.7}


def run_tests() -> int:
    failures = 0

    print("\nT1 — _validate_belief: casos válidos")
    ok, err = _validate_belief(_belief([VALID_LOC], [VALID_YR]))
    failures += not _check("belief típico válido", ok, str(err))
    ok, err = _validate_belief(_belief([], []))
    failures += not _check("listas vacías válidas ('no sé')", ok, str(err))
    ok, err = _validate_belief(_belief(
        [dict(VALID_LOC, weight=0.6), dict(VALID_LOC, name="Porto", lat=41.16, lon=-8.63, weight=0.4)],
        [VALID_YR],
    ))
    failures += not _check("pesos que suman exactamente 1 válidos", ok, str(err))

    print("\nT2 — _validate_belief: rechazos")
    cases = [
        ("pesos loc > 1", _belief([dict(VALID_LOC, weight=0.7), dict(VALID_LOC, name="x", weight=0.5)], [])),
        ("lat fuera de rango", _belief([dict(VALID_LOC, lat=95.0)], [])),
        ("lon fuera de rango", _belief([dict(VALID_LOC, lon=-200.0)], [])),
        ("radius_km = 0", _belief([dict(VALID_LOC, radius_km=0)], [])),
        ("weight negativo", _belief([dict(VALID_LOC, weight=-0.1)], [])),
        ("falta radius_km", _belief([{k: v for k, v in VALID_LOC.items() if k != "radius_km"}], [])),
        ("year from > to", _belief([], [{"from": 1950, "to": 1940, "weight": 0.5}])),
        ("pesos year > 1", _belief([], [dict(VALID_YR, weight=0.8), dict(VALID_YR, weight=0.4)])),
        (">5 candidatos", _belief([dict(VALID_LOC, weight=0.1) for _ in range(6)], [])),
        ("location_belief no es lista", {"location_belief": "Lisboa", "year_belief": []}),
        ("falta year_belief", {"location_belief": []}),
    ]
    for name, payload in cases:
        ok, err = _validate_belief(payload)
        failures += not _check(f"rechaza: {name}", not ok and bool(err))

    print("\nT3 — schemas belief-mode")
    fn = BELIEF_TOOL_SCHEMA["function"]
    failures += not _check("tool se llama report_belief", fn["name"] == "report_belief")
    props = fn["parameters"]["properties"]
    failures += not _check("schema tiene location_belief + year_belief + rationale",
                           {"location_belief", "year_belief", "rationale"} <= set(props))
    failures += not _check("prompt section menciona proper scoring rule",
                           "proper scoring rule" in BELIEF_PROMPT_SECTION)

    submit_belief = _submit_schema_with_evidence_chain()
    sb_props = submit_belief["function"]["parameters"]["properties"]
    failures += not _check("submit belief-mode tiene evidence_chain", "evidence_chain" in sb_props)
    ec_item = sb_props["evidence_chain"]["items"]
    failures += not _check("evidence_chain items requieren claim+step+tool",
                           set(ec_item["required"]) == {"claim", "step", "tool"})
    canon_props = SUBMIT_TOOL_SCHEMA["function"]["parameters"]["properties"]
    failures += not _check("SUBMIT canónico NO mutado (sin evidence_chain)",
                           "evidence_chain" not in canon_props,
                           "el brazo OFF de la ablation debe quedar idéntico")

    print("\nT4 — budget económico")
    agent_tools = {
        "web_search", "fetch_url", "fetch_url_with_images", "image_search",
        "geocode", "reverse_geocode", "historical_query", "historical_query_at",
        "crop_image", "crop_image_relative", "static_map", "street_view",
        "report_belief", "submit_answer",
    }
    failures += not _check("DEFAULT_TOOL_COSTS cubre las 14 tools",
                           set(DEFAULT_TOOL_COSTS) == agent_tools,
                           f"diff={set(DEFAULT_TOOL_COSTS) ^ agent_tools or '{}'}")
    failures += not _check("report_belief y submit_answer gratis",
                           DEFAULT_TOOL_COSTS["report_belief"] == 0 and DEFAULT_TOOL_COSTS["submit_answer"] == 0)
    failures += not _check("el resto cuesta > 0",
                           all(v > 0 for k, v in DEFAULT_TOOL_COSTS.items()
                               if k not in ("report_belief", "submit_answer")))
    section = _budget_prompt_section(40.0, DEFAULT_TOOL_COSTS)
    failures += not _check("prompt section menciona el total y las tools gratis",
                           "40" in section and "GRATIS" in section)

    print("\nT5 — round-trip scaffold -> scorer post-hoc")
    report = {
        "location_belief": [
            {"name": "Lisboa, Portugal", "lat": 38.72, "lon": -9.14, "weight": 0.55, "radius_km": 30},
            {"name": "Porto, Portugal", "lat": 41.15, "lon": -8.61, "weight": 0.25, "radius_km": 30},
        ],
        "year_belief": [{"from": 1925, "to": 1940, "weight": 0.7}],
        "rationale": "señalética portuguesa + tranvía",
    }
    ok, err = _validate_belief(report)
    failures += not _check("el report pasa la validación del scaffold", ok, str(err))
    b = Belief.from_dict(report)
    bs = score_belief(b, 38.7223, -9.1393, truth_year=1931.0)
    failures += not _check("y puntúa post-hoc con score_belief", math.isfinite(bs.total),
                           f"total={bs.total:.3f}")

    return failures


if __name__ == "__main__":
    n = run_tests()
    print(f"\n{'=' * 60}")
    if n == 0:
        print("TODOS LOS TESTS OK")
    else:
        print(f"{n} TESTS FALLARON")
    sys.exit(1 if n else 0)
