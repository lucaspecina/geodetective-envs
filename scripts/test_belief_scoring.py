"""Tests sintéticos de geodetective.eval.belief_scoring (E016, belief_state_redesign.md §6).

Verifica que el scoring rule tiene las propiedades que promete la teoría ANTES
de usarlo sobre corridas reales:

- T1: ordenamiento canónico del log-score (truth=Lisboa):
      certeza correcta < hedge honesto < vago correcto < ignorancia < certeza incorrecta
- T2: piso eps — confiado-equivocado con w=1.0 da score finito (nunca -inf)
- T3: ignorancia == fondo uniforme, info_gain ~ 0
- T4: properness (Monte Carlo) — si la verdad se genera de una distribución G,
      reportar G honestamente gana en promedio vs sobreconfiado / vago / ignorante
- T5: propiedad telescópica del reward denso
- T6: ordenamiento del log-score de año
- T7: energy score — ordenamiento básico + la divergencia decision-relevante:
      log-score castiga al confiado-equivocado peor que la ignorancia;
      energy score lo perdona (mejor que ignorancia). Input para log vs CRPS.
- T8: validación de pesos (suma>1 normaliza, negativo lanza, radio 0 clampea)
- T9: parseo end-to-end del schema JSON de report_belief

Uso: python scripts/test_belief_scoring.py
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from geodetective.eval.belief_scoring import (  # noqa: E402
    Belief,
    LocationComponent,
    YearComponent,
    location_energy_score,
    location_log_density,
    location_score,
    score_belief,
    score_belief_sequence,
    step_rewards,
    year_score,
)

# Ground truth de los escenarios: Lisboa
LISBOA = (38.7223, -9.1393)
MADRID = (40.4168, -3.7038)
PORTO = (41.1579, -8.6291)
IBERIA_CENTER = (40.0, -4.0)


def _check(name: str, cond: bool, detail: str = "") -> bool:
    mark = "OK " if cond else "FAIL"
    print(f"  [{mark}] {name}{(': ' + detail) if detail else ''}")
    return cond


def _loc(latlon, w, r, name="") -> LocationComponent:
    return LocationComponent(lat=latlon[0], lon=latlon[1], weight=w, radius_km=r, name=name)


# Escenarios canónicos (§ "scorer con tests sintéticos")
def scenario_A():  # certeza correcta
    return [_loc(LISBOA, 0.9, 20, "Lisboa")]


def scenario_B():  # certeza incorrecta
    return [_loc(MADRID, 0.9, 20, "Madrid")]


def scenario_C():  # hedge honesto
    return [_loc(LISBOA, 0.5, 20, "Lisboa"), _loc(PORTO, 0.3, 20, "Porto")]


def scenario_D():  # vago pero correcto
    return [_loc(IBERIA_CENTER, 0.8, 800, "Península Ibérica")]


def scenario_E():  # ignorancia total
    return []


def run_tests() -> int:
    failures = 0

    # === T1: ordenamiento del log-score ===
    print("\nT1 — ordenamiento canónico log-score (menor = mejor)")
    s = {k: location_score(fn(), *LISBOA) for k, fn in
         [("A", scenario_A), ("B", scenario_B), ("C", scenario_C),
          ("D", scenario_D), ("E", scenario_E)]}
    for k, v in s.items():
        print(f"        S_{k} = {v:8.3f}")
    failures += not _check("A (certeza correcta) es el mejor", s["A"] < s["C"])
    failures += not _check("C (hedge honesto) < D (vago correcto)", s["C"] < s["D"])
    failures += not _check("D (vago correcto) < E (ignorancia)", s["D"] < s["E"])
    failures += not _check("E (ignorancia) < B (certeza incorrecta)", s["E"] < s["B"],
                           "el confiado-equivocado pierde contra 'no sé'")

    # === T2: piso eps, nunca -inf ===
    print("\nT2 — piso: confiado-equivocado extremo (w=1.0, r=1km) queda acotado")
    s_extreme = location_score([_loc(MADRID, 1.0, 1)], *LISBOA)
    failures += not _check("score finito", math.isfinite(s_extreme), f"S={s_extreme:.3f}")
    failures += not _check("peor que ignorancia", s_extreme > s["E"])
    s_radius0 = location_score([_loc(MADRID, 1.0, 0.0)], *LISBOA)
    failures += not _check("radio 0 clampeado, finito", math.isfinite(s_radius0))

    # === T3: ignorancia = fondo uniforme ===
    print("\nT3 — ignorancia puntúa como el uniforme, info_gain ~ 0")
    expected_e = math.log(4.0 * math.pi)
    failures += not _check(
        "S_E == log(4*pi)", abs(s["E"] - expected_e) < 1e-9,
        f"{s['E']:.6f} vs {expected_e:.6f}",
    )
    bs_e = score_belief(Belief(), *LISBOA)
    failures += not _check("info_gain ~ 0", abs(bs_e.info_gain_location_nats) < 1e-9)
    bs_a = score_belief(Belief(location=scenario_A()), *LISBOA)
    failures += not _check("info_gain de A > 0", bs_a.info_gain_location_nats > 5.0,
                           f"{bs_a.info_gain_location_nats:.2f} nats")

    # === T4: properness por Monte Carlo ===
    # La verdad se genera de G = vMF(centro Iberia, 800km). El reporte honesto
    # (mismo G) debe ganar EN PROMEDIO contra sobreconfiado, vago e ignorante.
    # Esto además detecta errores de normalización del kernel (si la constante
    # de vMF estuviera mal, la honestidad perdería contra el reporte vago).
    print("\nT4 — properness: reportar la distribución generadora gana en promedio")
    from geodetective.eval.belief_scoring import _sample_mixture  # type: ignore
    rng = random.Random(42)
    gen = [_loc(IBERIA_CENTER, 1.0, 800)]
    samples = _sample_mixture(gen, 2000, rng, eps=0.0)
    reports = {
        "honesto (800km)": gen,
        "sobreconfiado (50km)": [_loc(IBERIA_CENTER, 1.0, 50)],
        "vago (4000km)": [_loc(IBERIA_CENTER, 1.0, 4000)],
        "ignorante": [],
    }
    mean_s = {}
    for label, rep in reports.items():
        tot = 0.0
        for x, y, z in samples:
            lat = math.degrees(math.asin(max(-1.0, min(1.0, z))))
            lon = math.degrees(math.atan2(y, x))
            tot += -location_log_density(rep, lat, lon)
        mean_s[label] = tot / len(samples)
        print(f"        E[S] {label:24s} = {mean_s[label]:8.3f}")
    for rival in ("sobreconfiado (50km)", "vago (4000km)", "ignorante"):
        failures += not _check(f"honesto < {rival}",
                               mean_s["honesto (800km)"] < mean_s[rival])

    # === T5: telescopía del reward denso ===
    print("\nT5 — reward denso telescopea a S_0 - S_T")
    seq = [
        Belief(),                                        # arranca sin idea
        Belief(location=scenario_D()),                   # acota a Iberia
        Belief(location=scenario_C()),                   # Lisboa vs Porto
        Belief(location=scenario_A()),                   # converge a Lisboa
    ]
    scores, rewards = score_belief_sequence(seq, *LISBOA, prepend_ignorance=True)
    failures += not _check(
        "sum(r_t) == S_0 - S_T",
        abs(sum(rewards) - (scores[0] - scores[-1])) < 1e-9,
        f"sum={sum(rewards):.3f}",
    )
    failures += not _check("cada paso que converge gana reward > 0",
                           all(r > 0 for r in rewards[1:]),
                           f"rewards={[f'{r:.2f}' for r in rewards]}")

    # === T6: ordenamiento del log-score de año (truth=1931) ===
    print("\nT6 — log-score de año")
    truth_year = 1931.0
    y_narrow_ok = year_score([YearComponent(1925, 1940, 0.8)], truth_year)
    y_wide_ok = year_score([YearComponent(1900, 1960, 0.8)], truth_year)
    y_ignorant = year_score([], truth_year)
    y_narrow_wrong = year_score([YearComponent(1960, 1980, 0.9)], truth_year)
    print(f"        narrow_ok={y_narrow_ok:.3f}  wide_ok={y_wide_ok:.3f}  "
          f"ignorante={y_ignorant:.3f}  narrow_wrong={y_narrow_wrong:.3f}")
    failures += not _check("narrow correcto < wide correcto", y_narrow_ok < y_wide_ok)
    failures += not _check("wide correcto < ignorancia", y_wide_ok < y_ignorant)
    failures += not _check("ignorancia < narrow incorrecto", y_ignorant < y_narrow_wrong)
    try:
        year_score([YearComponent(1950, 1940, 0.5)], truth_year)
        failures += not _check("rango invertido lanza ValueError", False)
    except ValueError:
        failures += not _check("rango invertido lanza ValueError", True)

    # === T7: energy score — ordenamiento + divergencia con log-score ===
    print("\nT7 — energy score (análogo CRPS) y la divergencia decision-relevante")
    es = {k: location_energy_score(fn(), *LISBOA, n_samples=2048, seed=7)
          for k, fn in [("A", scenario_A), ("B", scenario_B),
                        ("C", scenario_C), ("E", scenario_E)]}
    for k, v in es.items():
        print(f"        ES_{k} = {v:9.1f} km")
    failures += not _check("ES: A < C", es["A"] < es["C"])
    failures += not _check("ES: C < E", es["C"] < es["E"])
    # La divergencia: ¿cómo tratan al confiado-equivocado (B, Madrid a ~500km)?
    failures += not _check(
        "log-score: B PEOR que ignorancia (severo con el lock-in)",
        s["B"] > s["E"],
    )
    failures += not _check(
        "energy score: B MEJOR que ignorancia (perdona el error moderado)",
        es["B"] < es["E"],
        "ambos proper; difieren en el incentivo — input para la decisión log vs CRPS",
    )

    # === T8: validación de pesos ===
    print("\nT8 — validación de pesos")
    s_over = location_score(
        [_loc(LISBOA, 0.9, 20), _loc(PORTO, 0.9, 20)], *LISBOA)  # suma 1.8 → normaliza
    failures += not _check("suma de pesos > 1 normaliza sin romper", math.isfinite(s_over))
    try:
        location_score([_loc(LISBOA, -0.2, 20)], *LISBOA)
        failures += not _check("peso negativo lanza ValueError", False)
    except ValueError:
        failures += not _check("peso negativo lanza ValueError", True)

    # === T9: schema JSON end-to-end ===
    print("\nT9 — parseo del schema de report_belief + score combinado")
    payload = {
        "location_belief": [
            {"name": "Lisboa, Portugal", "lat": 38.72, "lon": -9.14,
             "weight": 0.55, "radius_km": 30},
            {"name": "Porto, Portugal", "lat": 41.15, "lon": -8.61,
             "weight": 0.25, "radius_km": 30},
        ],
        "year_belief": [
            {"from": 1925, "to": 1940, "weight": 0.7},
            {"from": 1910, "to": 1925, "weight": 0.3},
        ],
        "rationale": "tranvía de vía estrecha + azulejos + señalética portuguesa",
    }
    b = Belief.from_dict(payload)
    failures += not _check("parsea componentes", len(b.location) == 2 and len(b.year) == 2)
    bs = score_belief(b, *LISBOA, truth_year=1931.0)
    failures += not _check("score combinado finito", math.isfinite(bs.total),
                           f"total={bs.total:.3f} (loc={bs.location_score:.3f}, "
                           f"year={bs.year_score:.3f})")
    failures += not _check("info gains positivos (creencia informativa y correcta)",
                           bs.info_gain_location_nats > 0 and bs.info_gain_year_nats > 0)

    return failures


if __name__ == "__main__":
    n = run_tests()
    print(f"\n{'=' * 60}")
    if n == 0:
        print("TODOS LOS TESTS OK")
    else:
        print(f"{n} TESTS FALLARON")
    sys.exit(1 if n else 0)
