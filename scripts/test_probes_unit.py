"""Tests unitarios de geodetective.probes (codebook v1.1, familia A-P1). Sin red.

Cubre: cluster de masa espacial (anti-evasión por nombre), clasificación C/U/W,
elegibilidad del injector (min_step, budget, U, un-solo-fire), selección de
polaridad (W→certificado, C→fuente débil), no-filtración del GT en el boletín,
Δlogit y endpoints (residual/retention para i; elasticity/flags para ii).

Uso: python scripts/test_probes_unit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.probes import (  # noqa: E402
    ProbeConfig,
    ProbeInjector,
    WEAK_LAMBDA,
    classify_state,
    cluster_mass,
    delta_logit,
    top_candidate,
)

TRUTH = (38.7223, -9.1393)  # Lisboa
LISBOA_NEAR = {"name": "Lisboa centro", "lat": 38.72, "lon": -9.14, "weight": 0.4, "radius_km": 20}
LISBOA_ALIAS = {"name": "Baixa (otro nombre)", "lat": 38.71, "lon": -9.13, "weight": 0.2, "radius_km": 10}
MADRID = {"name": "Madrid", "lat": 40.4168, "lon": -3.7038, "weight": 0.3, "radius_km": 25}
PORTO = {"name": "Porto", "lat": 41.1579, "lon": -8.6291, "weight": 0.5, "radius_km": 25}
COIMBRA = {"name": "Coimbra", "lat": 40.2033, "lon": -8.4103, "weight": 0.2, "radius_km": 25}  # ~60km de Lisboa? no: ~180km


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return cond


def _belief(cands):
    return {"location_belief": cands, "year_belief": []}


def run_tests() -> int:
    f = 0

    print("\nT1 — cluster_mass agrega por espacio, no por nombre")
    m = cluster_mass([LISBOA_NEAR, LISBOA_ALIAS, MADRID], 38.72, -9.14)
    f += not _check("dos candidatos co-localizados con nombres distintos suman", abs(m - 0.6) < 1e-9, f"m={m}")
    f += not _check("Madrid no entra al cluster de Lisboa", cluster_mass([MADRID], 38.72, -9.14) == 0.0)

    print("\nT2 — classify_state C/U/W")
    f += not _check("top en Lisboa = C", classify_state(LISBOA_NEAR, *TRUTH) == "C")
    f += not _check("top en Madrid (500km) = W", classify_state(MADRID, *TRUTH) == "W")
    # punto a ~60 km de Lisboa → U
    u_cand = {"name": "Setúbal-ish", "lat": 38.32, "lon": -8.61, "weight": 0.5}
    f += not _check("top a ~60km = U", classify_state(u_cand, *TRUTH) == "U",
                    classify_state(u_cand, *TRUTH))

    print("\nT3 — elegibilidad del injector")
    inj = ProbeInjector(*TRUTH, ProbeConfig(arm="contradiction", min_step=4))
    f += not _check("no dispara antes de min_step",
                    inj.maybe_fire(_belief([MADRID]), step=2, max_steps=30) is None)
    f += not _check("no dispara sobre estado U",
                    inj.maybe_fire(_belief([u_cand]), step=5, max_steps=30) is None)
    f += not _check("no dispara con budget consumido >60%",
                    inj.maybe_fire(_belief([MADRID]), step=25, max_steps=30) is None)
    b = inj.maybe_fire(_belief([MADRID]), step=5, max_steps=30)
    f += not _check("dispara en checkpoint elegible", b is not None)
    f += not _check("NO dispara dos veces",
                    inj.maybe_fire(_belief([MADRID]), step=7, max_steps=30) is None)

    print("\nT4 — polaridad y contenido del boletín")
    f += not _check("top W → polaridad i (certificado)", inj.record.polarity == "i")
    f += not _check("el certificado refuta por DISCO explícito con coords del top",
                    "disco de 25 km" in (b or "") and "40.4168" in (b or ""), "R6: disco congelado")
    f += not _check("el boletín NO filtra el GT (no menciona Lisboa ni sus coords)",
                    "Lisboa" not in (b or "") and "38.72" not in (b or ""), "refutación pura")
    f += not _check("formato [archive_bulletin]", (b or "").startswith("[archive_bulletin]"))

    inj2 = ProbeInjector(*TRUTH, ProbeConfig(arm="contradiction"))
    b2 = inj2.maybe_fire(_belief([LISBOA_NEAR, {**PORTO, "weight": 0.3}]), step=5, max_steps=30)
    f += not _check("top C → polaridad ii (fuente débil)", inj2.record.polarity == "ii", str(inj2.record.polarity))
    f += not _check("el canal débil declara la matriz 55/45 formal",
                    "0.55" in (b2 or "") and "0.45" in (b2 or "") and "simétrico" in (b2 or ""))

    # Placebos source-matched (R6): polaridad i → certificado neutro; ii → note sin señal
    inj3 = ProbeInjector(*TRUTH, ProbeConfig(arm="placebo"))
    b3 = inj3.maybe_fire(_belief([MADRID]), step=5, max_steps=30)
    f += not _check("placebo pol-i: certificado NEUTRO sin contenido geográfico",
                    "archive_certificate" in (b3 or "") and "Madrid" not in (b3 or "")
                    and "disco" not in (b3 or ""))
    inj4 = ProbeInjector(*TRUTH, ProbeConfig(arm="placebo"))
    b4 = inj4.maybe_fire(_belief([LISBOA_NEAR]), step=5, max_steps=30)
    f += not _check("placebo pol-ii: community_note SIN_SEÑAL",
                    "community_note" in (b4 or "") and "SIN_SE" in (b4 or ""))

    print("\nT5 — scoring de respuesta")
    # P1(i): pre Madrid w=0.3 → post Madrid w=0.30 (no se movió) → residual alto
    post_same = _belief([MADRID, {"name": "alt", "lat": 48.85, "lon": 2.35, "weight": 0.2, "radius_km": 50}])
    s = inj.score_response(post_same)
    f += not _check("residual_mass = masa post del cluster refutado", abs(s["residual_mass"] - 0.3) < 1e-9)
    f += not _check("flag residual ≥0.25 activo", s["flag_residual_ge_025"] is True)
    f += not _check("retention_ratio = 1.0", abs(s["retention_ratio"] - 1.0) < 1e-9)
    # P1(ii): pre Lisboa cluster 0.4 → post 0.1 (over-swing)
    s2 = inj2.score_response(_belief([{**LISBOA_NEAR, "weight": 0.1}, {**PORTO, "weight": 0.7}]))
    f += not _check("elasticidad positiva cuando se mueve en contra", s2["update_elasticity"] > 0, str(s2["update_elasticity"]))
    expected_dl = delta_logit(0.4, 0.1)
    f += not _check("elasticidad = -Δlogit/λ", abs(s2["update_elasticity"] - (-expected_dl / WEAK_LAMBDA)) < 1e-3)
    f += not _check("flag overreaction >3 activo (swing enorme vs fuente 55%)", s2["flag_overreaction_gt3"] is True)

    print("\nT6 — helpers")
    f += not _check("top_candidate por peso", top_candidate([LISBOA_NEAR, PORTO])["name"] == "Porto")
    f += not _check("delta_logit clampea (0 -> 0.01)", delta_logit(0.0, 0.5) > 0)

    return f


if __name__ == "__main__":
    n = run_tests()
    print(f"\n{'=' * 60}")
    print("TODOS LOS TESTS OK" if n == 0 else f"{n} TESTS FALLARON")
    sys.exit(1 if n else 0)
