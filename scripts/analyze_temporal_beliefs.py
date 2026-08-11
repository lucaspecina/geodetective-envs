#!/usr/bin/env python3
"""Análisis descriptivo y reproducible de las trayectorias de creencia de E016.

Lee exclusivamente los ``results_*_belief-{on,off}.slim.json`` de E016 y genera:

* ``experiments/E018_temporal_belief_pilot/analysis.json``: resultados estructurados;
* ``experiments/E018_temporal_belief_pilot/report.md``: síntesis humana de esos datos.

Incluye fases normalizadas, contraste pareado early→late, generación/ausencia de
región correcta y acción posterior separada entre checkpoints report-only y
reportes coemitidos con tools informativas (donde existe evidencia intermedia).

El análisis describe qué reportó el agente, cómo cambió y qué acción ejecutó en el
turn siguiente. No estima la fuerza normativa de la evidencia web, no afirma que
una actualización haya sido bayesianamente correcta y no identifica causalidad.

Uso, desde cualquier directorio::

    python scripts/analyze_temporal_beliefs.py

También se pueden cambiar las rutas::

    python scripts/analyze_temporal_beliefs.py \
      --input-dir experiments/E016_belief_pilot \
      --output-dir experiments/E018_temporal_belief_pilot

Sólo usa la biblioteca estándar. Los resultados no incluyen fecha de generación,
por lo que, con los mismos inputs, los archivos producidos son byte-a-byte iguales.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "experiments" / "E016_belief_pilot"
DEFAULT_OUTPUT_DIR = ROOT / "experiments" / "E018_temporal_belief_pilot"

PHASES = ("early", "middle", "late")
REGION_THRESHOLDS_KM = (25.0, 100.0, 250.0, 500.0, 1000.0)
LARGE_SWITCH_KM = 100.0
HIGH_CONFIDENCE = 0.8
EPS = 1e-12
EARTH_RADIUS_KM = 6371.0
MAX_LOCATION_ENTROPY_BINS = 6  # hasta 5 candidatos + masa residual
MAX_YEAR_ENTROPY_BINS = 5  # hasta 4 intervalos + masa residual

WEB_ACTIONS = {"web_search", "fetch_url", "fetch_url_with_images"}
VISUAL_ACTIONS = {
    "image_search",
    "image_search_pick",
    "crop_image",
    "crop_image_relative",
}
MAP_HISTORY_ACTIONS = {
    "geocode",
    "reverse_geocode",
    "street_view",
    "static_map",
    "historical_query",
    "historical_query_at",
}
ACTION_CATEGORIES = ("web", "visual", "map_history", "submit")

PHASE_METRICS = (
    "top_weight",
    "location_entropy_nats",
    "location_entropy_fixed_normalized",
    "location_entropy_current_support_normalized",
    "top_distance_km",
    "top_radius_km",
    "exact_disk_mass",
    "region_mass_25km",
    "region_mass_100km",
    "region_mass_250km",
    "region_mass_500km",
    "region_mass_1000km",
    "year_top_weight",
    "year_entropy_nats",
    "year_entropy_fixed_normalized",
    "year_entropy_current_support_normalized",
    "year_top_width",
    "year_truth_overlap_mass",
)

LIMITATIONS = [
    "E016 contiene sólo diez fotos y tres réplicas por celda; reportes y transiciones "
    "de una misma corrida no son observaciones independientes.",
    "Los checkpoints son autoelegidos y los modelos tienen distinta longitud de corrida; "
    "early/middle/late normaliza por steps_used, pero no iguala exposición a evidencia.",
    "La fase usa la duración final de una corrida endógena a la decisión de parar e incluye "
    "el turn de submit; se reporta cuántos reportes cambiarían al excluir ese turn.",
    "El contraste early-late está condicionado a corridas que tienen checkpoints en ambas "
    "fases. Es pareado y descriptivo, pero no representa todas las corridas ni autoriza "
    "inferencia con estos tamaños muestrales.",
    "El nudge para reportar creencias es una intervención. El brazo off no contiene una "
    "trayectoria latente comparable.",
    "La entropía discreta ignora radios geográficos y trata la masa no asignada como un "
    "único bin. La serie primaria usa Shannon en nats y normalización de soporte fijo; la "
    "normalización por soporte no nulo se conserva sólo como diagnóstico porque K cambia.",
    "La masa regional suma candidatos por distancia de su centro; 500 km es un umbral "
    "operativo arbitrario, por eso se reporta sensibilidad entre 25 y 1000 km.",
    "La masa temporal cuenta intervalos que solapan la verdad y por lo tanto favorece "
    "intervalos amplios; no es una densidad temporal ni una proper scoring rule.",
    "El último reporte no coincide con la creencia al submit en 88/89 corridas y una tool "
    "coemitida en el mismo turn todavía no había devuelto su resultado al agente. Por eso "
    "'ausente al final' significa ausente en el último checkpoint observado.",
    "En checkpoints coemitidos, el resultado de la tool media entre belief y siguiente turn; "
    "no se interpreta como acoplamiento directo. En report-only la adyacencia es más limpia, "
    "pero sigue siendo observacional y no prueba causalidad ni valor informativo.",
    "Los slim preservan texto y metadata, pero no los píxeles base64 devueltos por crops, "
    "mapas y Street View; esos estímulos no pueden reauditarse bit a bit aquí.",
    "Las certificaciones de las diez fotos del piloto siguen en estado draft.",
    "Este análisis no modela likelihoods ni la fuerza normativa de evidencia web; no "
    "califica una actualización como correcta o incorrecta dado lo observado.",
]


def mean(values: Iterable[float]) -> float | None:
    xs = list(values)
    return sum(xs) / len(xs) if xs else None


def median(values: Iterable[float]) -> float | None:
    xs = list(values)
    return statistics.median(xs) if xs else None


def quantile(values: Iterable[float], q: float) -> float | None:
    """Cuantil lineal, equivalente al método lineal usual de numpy."""
    xs = sorted(values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summary(values: Iterable[float | int | None]) -> dict[str, Any]:
    xs = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs) if xs else None,
        "max": max(xs) if xs else None,
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def round_floats(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = round(value, 6)
        return 0.0 if rounded == -0.0 else rounded
    if isinstance(value, list):
        return [round_floats(v) for v in value]
    if isinstance(value, dict):
        return {k: round_floats(v) for k, v in value.items()}
    return value


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    cosine = (
        math.sin(la1) * math.sin(la2)
        + math.cos(la1) * math.cos(la2) * math.cos(lo1 - lo2)
    )
    return EARTH_RADIUS_KM * math.acos(max(-1.0, min(1.0, cosine)))


def discrete_entropy(explicit_weights: Iterable[float], max_bins: int) -> dict[str, float | None]:
    """Shannon discreta sobre candidatos más masa residual.

    ``fixed_normalized`` divide por el soporte máximo del schema y conserva una
    escala comparable aunque cambie el número de candidatos. ``current_support``
    reproduce el diagnóstico exploratorio H/log(K_no_cero), pero no debe usarse
    para firmar actualizaciones: K puede cambiar entre reportes.
    """
    weights = [max(0.0, float(w)) for w in explicit_weights]
    residual = max(0.0, 1.0 - sum(weights))
    if residual > EPS:
        weights.append(residual)
    weights = [w for w in weights if w > EPS]
    total = sum(weights)
    if total <= EPS:
        return {"nats": None, "fixed_normalized": None, "current_support_normalized": None}
    probabilities = [w / total for w in weights]
    entropy_nats = -sum(p * math.log(p) for p in probabilities)
    current_support = (
        entropy_nats / math.log(len(probabilities)) if len(probabilities) > 1 else 0.0
    )
    return {
        "nats": entropy_nats,
        "fixed_normalized": entropy_nats / math.log(max_bins),
        "current_support_normalized": current_support,
    }


def phase_for(step: int, steps_used: int) -> str:
    progress = step / max(1, steps_used)
    if progress <= 1.0 / 3.0:
        return "early"
    if progress <= 2.0 / 3.0:
        return "middle"
    return "late"


def run_key(record: dict[str, Any]) -> str:
    react = record.get("react") or {}
    return f"{react.get('model')}|{react.get('arm')}|{record.get('cid')}|{record.get('run_idx')}"


def top_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [c for c in candidates if c.get("weight") is not None]
    return max(valid, key=lambda c: float(c["weight"])) if valid else None


def event_base_type(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    return event_type.removesuffix("_error")


def action_category(event: dict[str, Any]) -> str | None:
    event_type = event_base_type(event)
    if event_type in WEB_ACTIONS:
        return "web"
    if event_type in VISUAL_ACTIONS:
        return "visual"
    if event_type in MAP_HISTORY_ACTIONS:
        return "map_history"
    if event_type == "submit":
        return "submit"
    return None


def next_substantive_turn(
    trace: list[dict[str, Any]], report_step: int
) -> list[dict[str, Any]]:
    """Todas las acciones del primer turn sustantivo posterior al reporte.

    Un modelo puede emitir tool calls paralelas. El orden de esos eventos dentro
    del trace no expresa una elección secuencial, por lo que devolver sólo el
    primero sería arbitrario.
    """
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, event in enumerate(trace):
        step = event.get("step")
        if not isinstance(step, int) or step <= report_step:
            continue
        if action_category(event) is not None:
            candidates.append((step, index, event))
    if not candidates:
        return []
    first_step = min(step for step, _index, _event in candidates)
    return [
        event
        for step, _index, event in sorted(candidates, key=lambda x: (x[0], x[1]))
        if step == first_step
    ]


def coemitted_substantive_tools(
    trace: list[dict[str, Any]], report_step: int
) -> list[dict[str, Any]]:
    """Tools coemitidas con el report, cuyos resultados llegan después del belief.

    Esos resultados son evidencia intermedia antes del siguiente turn del modelo,
    aun si la tool falla. Submit no cuenta como tool/evidencia intermedia.
    """
    return [
        event
        for event in trace
        if event.get("step") == report_step
        and action_category(event) in {"web", "visual", "map_history"}
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_records(input_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pattern = re.compile(r"results_(.+)_belief-(on|off)\.slim\.json$")
    records: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("results_*_belief-*.slim.json")):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{path}: el nivel superior debe ser un array")
        inputs.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
                "n_records": len(payload),
            }
        )
        for record in payload:
            react = record.get("react") or {}
            record = dict(record)
            record["_source"] = str(path.relative_to(ROOT))
            record["_model"] = react.get("model") or match.group(1)
            record["_arm"] = react.get("arm") or match.group(2)
            records.append(record)
    if not records:
        raise FileNotFoundError(f"No encontré slim de E016 en {input_dir}")
    return records, inputs


def enrich_report(record: dict[str, Any], report: dict[str, Any], index: int) -> dict[str, Any]:
    react = record.get("react") or {}
    belief = report.get("belief") or {}
    locations = belief.get("location_belief") or []
    years = belief.get("year_belief") or []
    truth_geo = record.get("geo") or []
    truth_lat = float(truth_geo[0])
    truth_lon = float(truth_geo[1])
    top = top_candidate(locations)

    location_weights = [float(c.get("weight", 0.0)) for c in locations]
    location_entropy = discrete_entropy(location_weights, MAX_LOCATION_ENTROPY_BINS)
    candidate_distances: list[tuple[dict[str, Any], float]] = []
    for candidate in locations:
        try:
            distance = great_circle_km(
                float(candidate["lat"]),
                float(candidate["lon"]),
                truth_lat,
                truth_lon,
            )
        except (KeyError, TypeError, ValueError):
            continue
        candidate_distances.append((candidate, distance))

    metrics: dict[str, float | None] = {
        "top_weight": float(top["weight"]) if top else None,
        "location_entropy_nats": location_entropy["nats"],
        "location_entropy_fixed_normalized": location_entropy["fixed_normalized"],
        "location_entropy_current_support_normalized": location_entropy[
            "current_support_normalized"
        ],
        "top_distance_km": None,
        "top_radius_km": float(top["radius_km"]) if top and top.get("radius_km") is not None else None,
        "exact_disk_mass": sum(
            float(candidate.get("weight", 0.0))
            for candidate, distance in candidate_distances
            if distance <= float(candidate.get("radius_km", 0.0))
        ),
    }
    if top:
        metrics["top_distance_km"] = great_circle_km(
            float(top["lat"]), float(top["lon"]), truth_lat, truth_lon
        )
    for threshold in REGION_THRESHOLDS_KM:
        metrics[f"region_mass_{int(threshold)}km"] = sum(
            float(candidate.get("weight", 0.0))
            for candidate, distance in candidate_distances
            if distance <= threshold
        )

    year_weights = [float(component.get("weight", 0.0)) for component in years]
    year_entropy = discrete_entropy(year_weights, MAX_YEAR_ENTROPY_BINS)
    top_year = top_candidate(years)
    truth_from = float(record["year"])
    truth_to = float(record.get("year2") if record.get("year2") is not None else record["year"])
    truth_from, truth_to = min(truth_from, truth_to), max(truth_from, truth_to)
    overlap_mass = 0.0
    for component in years:
        lo = float(component["from"])
        hi = float(component["to"])
        lo, hi = min(lo, hi), max(lo, hi)
        if lo <= truth_to and hi >= truth_from:
            overlap_mass += float(component.get("weight", 0.0))
    metrics.update(
        {
            "year_top_weight": float(top_year["weight"]) if top_year else None,
            "year_entropy_nats": year_entropy["nats"],
            "year_entropy_fixed_normalized": year_entropy["fixed_normalized"],
            "year_entropy_current_support_normalized": year_entropy[
                "current_support_normalized"
            ],
            "year_top_width": (
                abs(float(top_year["to"]) - float(top_year["from"])) if top_year else None
            ),
            "year_truth_overlap_mass": overlap_mass,
        }
    )

    step = int(report["step"])
    return {
        "run_key": run_key(record),
        "cid": record.get("cid"),
        "run_idx": record.get("run_idx"),
        "model": record["_model"],
        "arm": record["_arm"],
        "report_index": index,
        "step": step,
        "steps_used": int(react.get("steps_used") or 0),
        "phase": phase_for(step, int(react.get("steps_used") or 0)),
        "top_name": top.get("name") if top else None,
        "top_lat": float(top["lat"]) if top else None,
        "top_lon": float(top["lon"]) if top else None,
        **metrics,
    }


def build_inventory(records: list[dict[str, Any]], input_dir: Path) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rejected_attempts = 0
    tool_error_events_by_arm: Counter[str] = Counter()
    accepted_reports = 0
    quality_issues: list[str] = []
    first_steps: dict[str, Counter[int]] = defaultdict(Counter)
    gap_by_model: dict[str, Counter[int]] = defaultdict(Counter)
    all_gaps: Counter[int] = Counter()
    submit_minus_last_report: Counter[int] = Counter()
    same_turn_substantive = 0

    for record in records:
        groups[(record["_model"], record["_arm"])].append(record)
        react = record.get("react") or {}
        reports = react.get("belief_reports") or []
        trace = react.get("trace") or []
        accepted_reports += len(reports)
        rejected_attempts += sum(1 for event in trace if event.get("type") == "report_belief_rejected")
        tool_error_events_by_arm[record["_arm"]] += sum(
            1
            for event in trace
            if str(event.get("type") or "").endswith("_error")
            and event.get("type") != "report_belief_rejected"
        )

        expected = react.get("belief_report_count")
        trace_reports = sum(1 for event in trace if event.get("type") == "report_belief")
        trajectory_reports = len(((react.get("belief_trajectory") or {}).get("per_report") or []))
        if expected != len(reports) or trace_reports != len(reports):
            quality_issues.append(f"{run_key(record)}: conteos de reports no coinciden")
        if reports and trajectory_reports != len(reports):
            quality_issues.append(f"{run_key(record)}: trajectory y reports no coinciden")

        if reports:
            steps = [int(report["step"]) for report in reports]
            first_steps[record["_model"]][steps[0]] += 1
            for gap in (b - a for a, b in zip(steps, steps[1:])):
                gap_by_model[record["_model"]][gap] += 1
                all_gaps[gap] += 1
            submit_steps = [int(e["step"]) for e in trace if e.get("type") == "submit"]
            if submit_steps:
                submit_minus_last_report[min(submit_steps) - steps[-1]] += 1
            report_step_counts = Counter(steps)
            substantive_steps = {
                int(event["step"])
                for event in trace
                if isinstance(event.get("step"), int) and action_category(event) not in {None, "submit"}
            }
            same_turn_substantive += sum(
                count for step, count in report_step_counts.items() if step in substantive_steps
            )

    by_model_arm = []
    for (model, arm), rows in sorted(groups.items()):
        steps = [int((row.get("react") or {}).get("steps_used") or 0) for row in rows]
        n_reports = [len((row.get("react") or {}).get("belief_reports") or []) for row in rows]
        by_model_arm.append(
            {
                "model": model,
                "arm": arm,
                "n_runs": len(rows),
                "n_submitted": sum(
                    1 for row in rows if (row.get("react") or {}).get("terminal_state") == "submitted"
                ),
                "n_errors": sum(1 for row in rows if (row.get("react") or {}).get("error")),
                "steps": summary(steps),
                "accepted_reports": sum(n_reports),
                "reports_per_run": summary(n_reports),
            }
        )

    models = sorted({record["_model"] for record in records})
    arms = sorted({record["_arm"] for record in records})
    cids = sorted({record.get("cid") for record in records})
    run_indices = sorted({record.get("run_idx") for record in records})
    present = {
        (record["_model"], record["_arm"], record.get("cid"), record.get("run_idx"))
        for record in records
    }
    missing_cells = [
        {"model": model, "arm": arm, "cid": cid, "run_idx": run_idx}
        for model in models
        for arm in arms
        for cid in cids
        for run_idx in run_indices
        if (model, arm, cid, run_idx) not in present
    ]

    certifications = {}
    for record in records:
        certifications.setdefault(str(record.get("cid")), (record.get("certification") or {}).get("status"))
    raw_files = [
        p for p in input_dir.glob("results_*_belief-*.json") if not p.name.endswith(".slim.json")
    ]
    return {
        "total_runs": len(records),
        "belief_on_runs": sum(1 for record in records if record["_arm"] == "on"),
        "belief_off_runs": sum(1 for record in records if record["_arm"] == "off"),
        "accepted_reports": accepted_reports,
        "rejected_report_attempts": rejected_attempts,
        "tool_error_events": sum(tool_error_events_by_arm.values()),
        "tool_error_events_by_arm": dict(sorted(tool_error_events_by_arm.items())),
        "by_model_arm": by_model_arm,
        "missing_cells_against_observed_grid": missing_cells,
        "checkpoint_timing": {
            "first_report_step_by_model": {
                model: {str(k): v for k, v in sorted(counts.items())}
                for model, counts in sorted(first_steps.items())
            },
            "inter_report_gap_all": {str(k): v for k, v in sorted(all_gaps.items())},
            "inter_report_gap_by_model": {
                model: {str(k): v for k, v in sorted(counts.items())}
                for model, counts in sorted(gap_by_model.items())
            },
            "submit_step_minus_last_report_step": {
                str(k): v for k, v in sorted(submit_minus_last_report.items())
            },
            "reports_with_substantive_tool_coemitted_same_turn": same_turn_substantive,
        },
        "quality_checks": {
            "report_count_alignment_ok": not quality_issues,
            "issues": quality_issues,
            "certification_status_by_cid": certifications,
            "raw_result_files_present": [str(path.relative_to(ROOT)) for path in sorted(raw_files)],
            "viewer_html_present": sorted(
                str(path.relative_to(ROOT)) for path in input_dir.glob("*.html")
            ),
        },
    }


def aggregate_phase_metrics(report_rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_run_phase: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in report_rows:
        per_run_phase[(row["model"], row["run_key"], row["phase"])].append(row)

    run_means: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (model, _run, phase), rows in per_run_phase.items():
        item: dict[str, Any] = {"n_reports": len(rows)}
        for metric in PHASE_METRICS:
            item[metric] = mean(row.get(metric) for row in rows if row.get(metric) is not None)
        run_means[(model, phase)].append(item)

    models = sorted({row["model"] for row in report_rows})
    by_model: dict[str, Any] = {}
    for model in models:
        by_model[model] = {}
        for phase in PHASES:
            rows = run_means.get((model, phase), [])
            by_model[model][phase] = {
                "n_runs": len(rows),
                "n_reports": sum(row["n_reports"] for row in rows),
                "metrics": {metric: summary(row.get(metric) for row in rows) for metric in PHASE_METRICS},
            }
    sensitivity_all: Counter[str] = Counter()
    sensitivity_by_model: dict[str, Counter[str]] = defaultdict(Counter)
    for row in report_rows:
        alternative = phase_for(row["step"], max(1, row["steps_used"] - 1))
        if alternative != row["phase"]:
            transition = f"{row['phase']}->{alternative}"
            sensitivity_all[transition] += 1
            sensitivity_by_model[row["model"]][transition] += 1
    return {
        "phase_definition": "early: step/steps_used <= 1/3; middle: <= 2/3; late: > 2/3",
        "aggregation": (
            "Cada métrica se promedia primero dentro de corrida-fase. Las medias y medianas "
            "reportadas después usan esas unidades corrida-fase."
        ),
        "sensitivity_excluding_submit_turn": {
            "n_reports_changing_phase": sum(sensitivity_all.values()),
            "transition_counts": dict(sorted(sensitivity_all.items())),
            "by_model": {
                model: dict(sorted(counts.items()))
                for model, counts in sorted(sensitivity_by_model.items())
            },
        },
        "by_model": by_model,
    }


def paired_early_late_analysis(
    reports_by_run: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Deltas late−early dentro de las corridas que observan ambas fases."""
    metrics = (
        "top_weight",
        "region_mass_500km",
        "year_truth_overlap_mass",
        "location_entropy_fixed_normalized",
    )
    paired_rows: list[dict[str, Any]] = []
    for run, reports in reports_by_run.items():
        early = [report for report in reports if report["phase"] == "early"]
        late = [report for report in reports if report["phase"] == "late"]
        if not early or not late:
            continue
        row: dict[str, Any] = {
            "run_key": run,
            "model": reports[0]["model"],
            "n_early_reports": len(early),
            "n_late_reports": len(late),
            "delta_late_minus_early": {},
        }
        for metric in metrics:
            early_mean = mean(report[metric] for report in early)
            late_mean = mean(report[metric] for report in late)
            row["delta_late_minus_early"][metric] = late_mean - early_mean
        paired_rows.append(row)

    by_model: dict[str, Any] = {}
    for model in sorted({row["model"] for row in paired_rows}):
        rows = [row for row in paired_rows if row["model"] == model]
        by_model[model] = {
            "n_paired_runs": len(rows),
            "delta_late_minus_early": {
                metric: summary(
                    row["delta_late_minus_early"][metric] for row in rows
                )
                for metric in metrics
            },
            "run_keys": [row["run_key"] for row in rows],
        }
    return {
        "definition": (
            "Sólo corridas con al menos un checkpoint early y uno late. Se promedia cada "
            "métrica dentro de fase y luego se calcula late−early por corrida. Las medias y "
            "medianas agregan esos deltas pareados; no se hace inferencia estadística."
        ),
        "by_model": by_model,
    }


def make_transitions(
    reports_by_run: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    for rows in reports_by_run.values():
        for previous, current in zip(rows, rows[1:]):
            top_jump = None
            if None not in (
                previous.get("top_lat"),
                previous.get("top_lon"),
                current.get("top_lat"),
                current.get("top_lon"),
            ):
                top_jump = great_circle_km(
                    previous["top_lat"],
                    previous["top_lon"],
                    current["top_lat"],
                    current["top_lon"],
                )
            closer_by = None
            if previous.get("top_distance_km") is not None and current.get("top_distance_km") is not None:
                closer_by = previous["top_distance_km"] - current["top_distance_km"]
            transitions.append(
                {
                    "run_key": current["run_key"],
                    "report_index": current["report_index"],
                    "model": current["model"],
                    "phase": current["phase"],
                    "top_jump_km": top_jump,
                    "abs_delta_top_weight": abs(current["top_weight"] - previous["top_weight"]),
                    "delta_top_weight": current["top_weight"] - previous["top_weight"],
                    "abs_delta_entropy_fixed_normalized": abs(
                        current["location_entropy_fixed_normalized"]
                        - previous["location_entropy_fixed_normalized"]
                    ),
                    "delta_entropy_fixed_normalized": (
                        current["location_entropy_fixed_normalized"]
                        - previous["location_entropy_fixed_normalized"]
                    ),
                    "delta_entropy_current_support_normalized": (
                        current["location_entropy_current_support_normalized"]
                        - previous["location_entropy_current_support_normalized"]
                    ),
                    "closer_by_km": closer_by,
                    "delta_region_mass_500km": (
                        current["region_mass_500km"] - previous["region_mass_500km"]
                    ),
                }
            )
    return transitions


def aggregate_transition_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    jumps = [row["top_jump_km"] for row in rows if row.get("top_jump_km") is not None]
    return {
        "n_transitions": len(rows),
        "top_jump_km": {**summary(jumps), "q75": quantile(jumps, 0.75), "q90": quantile(jumps, 0.90)},
        "abs_delta_top_weight": summary(row["abs_delta_top_weight"] for row in rows),
        "abs_delta_entropy_fixed_normalized": summary(
            row["abs_delta_entropy_fixed_normalized"] for row in rows
        ),
        "large_switch_gt_100km": {
            "n": sum(1 for row in rows if (row.get("top_jump_km") or 0.0) > LARGE_SWITCH_KM),
            "rate": ratio(
                sum(1 for row in rows if (row.get("top_jump_km") or 0.0) > LARGE_SWITCH_KM),
                len(jumps),
            ),
        },
        "confidence_increased_rate": ratio(
            sum(1 for row in rows if row["delta_top_weight"] > EPS), len(rows)
        ),
        "entropy_fixed_support_decreased_rate": ratio(
            sum(1 for row in rows if row["delta_entropy_fixed_normalized"] < -EPS),
            len(rows),
        ),
        "entropy_current_support_decreased_rate": ratio(
            sum(
                1
                for row in rows
                if row["delta_entropy_current_support_normalized"] < -EPS
            ),
            len(rows),
        ),
        "moved_closer_gt_100km_rate": ratio(
            sum(1 for row in rows if (row.get("closer_by_km") or 0.0) > LARGE_SWITCH_KM),
            len(rows),
        ),
        "moved_farther_gt_100km_rate": ratio(
            sum(1 for row in rows if (row.get("closer_by_km") or 0.0) < -LARGE_SWITCH_KM),
            len(rows),
        ),
    }


def aggregate_transitions(transitions: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for model in sorted({row["model"] for row in transitions}):
        model_rows = [row for row in transitions if row["model"] == model]
        output[model] = {
            "all": aggregate_transition_rows(model_rows),
            "by_destination_phase": {
                phase: aggregate_transition_rows([row for row in model_rows if row["phase"] == phase])
                for phase in PHASES
            },
        }
    return {
        "transition_definition": (
            "Cambio entre reportes consecutivos de una misma corrida; phase es la del "
            "reporte destino."
        ),
        "large_switch_threshold_km": LARGE_SWITCH_KM,
        "by_model": output,
    }


def consideration_analysis(
    reports_by_run: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    by_model_runs: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for rows in reports_by_run.values():
        if rows:
            by_model_runs[rows[0]["model"]].append(rows)

    output: dict[str, Any] = {}
    for model, runs in sorted(by_model_runs.items()):
        thresholds: dict[str, Any] = {}
        for threshold in REGION_THRESHOLDS_KM:
            metric = f"region_mass_{int(threshold)}km"
            statuses = []
            for rows in runs:
                present = [row[metric] > EPS for row in rows]
                first_index = next((index for index, value in enumerate(present) if value), None)
                statuses.append(
                    {
                        "run_key": rows[0]["run_key"],
                        "ever": any(present),
                        "already_first": present[0],
                        "introduced_later": (not present[0]) and any(present[1:]),
                        "never": not any(present),
                        "absent_at_last_observed_report": any(present) and not present[-1],
                        "first_consideration_report_index": first_index,
                        "first_consideration_step": (
                            rows[first_index]["step"] if first_index is not None else None
                        ),
                        "first_consideration_phase": (
                            rows[first_index]["phase"] if first_index is not None else None
                        ),
                    }
                )
            ever = sum(status["ever"] for status in statuses)
            absent_last = sum(status["absent_at_last_observed_report"] for status in statuses)
            thresholds[str(int(threshold))] = {
                "n_runs": len(statuses),
                "ever": ever,
                "already_first": sum(status["already_first"] for status in statuses),
                "introduced_later": sum(status["introduced_later"] for status in statuses),
                "never": sum(status["never"] for status in statuses),
                "absent_at_last_observed_report": absent_last,
                "absent_at_last_observed_report_rate_among_ever": ratio(absent_last, ever),
                "first_consideration_report_index_counts": {
                    str(index): count
                    for index, count in sorted(
                        Counter(
                            status["first_consideration_report_index"]
                            for status in statuses
                            if status["first_consideration_report_index"] is not None
                        ).items()
                    )
                },
                "first_consideration_step": summary(
                    status["first_consideration_step"] for status in statuses
                ),
                "first_consideration_phase_counts": dict(
                    sorted(
                        Counter(
                            status["first_consideration_phase"]
                            for status in statuses
                            if status["first_consideration_phase"] is not None
                        ).items()
                    )
                ),
                "case_ids": {
                    key: [status["run_key"] for status in statuses if status[key]]
                    for key in (
                        "introduced_later",
                        "never",
                        "absent_at_last_observed_report",
                    )
                },
                "introduced_later_case_details": [
                    {
                        "run_key": status["run_key"],
                        "report_index": status["first_consideration_report_index"],
                        "step": status["first_consideration_step"],
                        "phase": status["first_consideration_phase"],
                    }
                    for status in statuses
                    if status["introduced_later"]
                ],
            }

        date_statuses = []
        for rows in runs:
            present = [row["year_truth_overlap_mass"] > EPS for row in rows]
            date_statuses.append(
                {
                    "ever": any(present),
                    "already_first": present[0],
                    "introduced_later": (not present[0]) and any(present[1:]),
                    "never": not any(present),
                    "absent_at_last_observed_report": any(present) and not present[-1],
                }
            )
        date_ever = sum(status["ever"] for status in date_statuses)
        date_absent_last = sum(
            status["absent_at_last_observed_report"] for status in date_statuses
        )
        output[model] = {
            "location_by_threshold_km": thresholds,
            "date_interval_overlap": {
                "n_runs": len(date_statuses),
                "ever": date_ever,
                "already_first": sum(status["already_first"] for status in date_statuses),
                "introduced_later": sum(status["introduced_later"] for status in date_statuses),
                "never": sum(status["never"] for status in date_statuses),
                "absent_at_last_observed_report": date_absent_last,
                "absent_at_last_observed_report_rate_among_ever": ratio(
                    date_absent_last, date_ever
                ),
            },
        }
    return {
        "definition": (
            "Apareció una región en un checkpoint si recibió peso explícito en un candidato "
            "cuyo centro cae dentro del umbral. 'Never' significa que no apareció en ningún "
            "checkpoint elicitado. 'Absent at last observed report' es un proxy operativo de "
            "abandono, no una medición de la creencia exacta al submit."
        ),
        "by_model": output,
    }


def action_analysis(
    records: list[dict[str, Any]],
    reports_by_run: dict[str, list[dict[str, Any]]],
    transitions: list[dict[str, Any]],
) -> dict[str, Any]:
    records_by_key = {run_key(record): record for record in records}
    action_rows: list[dict[str, Any]] = []
    report_lookup: dict[tuple[str, int], dict[str, Any]] = {}

    for key, reports in reports_by_run.items():
        trace = (records_by_key[key].get("react") or {}).get("trace") or []
        for report in reports:
            events = next_substantive_turn(trace, report["step"])
            coemitted = coemitted_substantive_tools(trace, report["step"])
            categories = tuple(
                category
                for category in ACTION_CATEGORIES
                if any(action_category(event) == category for event in events)
            )
            row = {
                "run_key": key,
                "report_index": report["report_index"],
                "model": report["model"],
                "phase": report["phase"],
                "top_weight": report["top_weight"],
                "region_mass_500km": report["region_mass_500km"],
                "top_distance_km": report["top_distance_km"],
                "top_radius_km": report["top_radius_km"],
                "checkpoint_kind": "coemitted_tool" if coemitted else "report_only",
                "coemitted_tool_types": [event_base_type(event) for event in coemitted],
                "next_categories": categories,
                "next_types": [event_base_type(event) for event in events],
                "next_events": events,
                "failed_next_action_types": [
                    str(event.get("type"))
                    for event in events
                    if str(event.get("type") or "").endswith("_error")
                ],
            }
            action_rows.append(row)
            report_lookup[(key, report["report_index"])] = row

    checkpoint_kinds = ("report_only", "coemitted_tool")

    def by_model_phase_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for model in sorted({row["model"] for row in action_rows}):
            result[model] = {}
            for phase in PHASES:
                cell = [
                    row for row in rows if row["model"] == model and row["phase"] == phase
                ]
                counts = {
                    category: sum(category in row["next_categories"] for row in cell)
                    for category in ACTION_CATEGORIES
                }
                counts["missing"] = sum(not row["next_categories"] for row in cell)
                result[model][phase] = {
                    "n_reports": len(cell),
                    "n_action_events": sum(len(row["next_events"]) for row in cell),
                    "counts": counts,
                }
        return result

    by_checkpoint_kind = {
        kind: {
            "n_reports": sum(row["checkpoint_kind"] == kind for row in action_rows),
            "by_model_phase": by_model_phase_for(
                [row for row in action_rows if row["checkpoint_kind"] == kind]
            ),
        }
        for kind in checkpoint_kinds
    }

    def submit_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
        submits = sum("submit" in row["next_categories"] for row in rows)
        return {"n": len(rows), "submit_next": submits, "submit_next_rate": ratio(submits, len(rows))}

    def late_submit_by_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for model in sorted({row["model"] for row in action_rows}):
            late = [
                row
                for row in rows
                if row["model"] == model
                and row["phase"] == "late"
                and row["next_categories"]
            ]
            result[model] = {
                "high_top_weight_ge_0_8": submit_group(
                    [row for row in late if row["top_weight"] >= HIGH_CONFIDENCE]
                ),
                "lower_top_weight": submit_group(
                    [row for row in late if row["top_weight"] < HIGH_CONFIDENCE]
                ),
                "correct_region_mass_500km_positive": submit_group(
                    [row for row in late if row["region_mass_500km"] > EPS]
                ),
                "no_correct_region_mass_500km": submit_group(
                    [row for row in late if row["region_mass_500km"] <= EPS]
                ),
            }
        return result

    late_submit_by_kind_model = {
        kind: late_submit_by_model(
            [row for row in action_rows if row["checkpoint_kind"] == kind]
        )
        for kind in checkpoint_kinds
    }

    transition_action_rows = []
    for transition in transitions:
        action = report_lookup.get((transition["run_key"], transition["report_index"]))
        if not action or not action["next_categories"]:
            continue
        transition_action_rows.append(
            {
                **transition,
                "checkpoint_kind": action["checkpoint_kind"],
                "next_categories": action["next_categories"],
            }
        )

    coordinate_rows = []
    for row in action_rows:
        source_report = reports_by_run[row["run_key"]][row["report_index"]]
        for event in row["next_events"]:
            if action_category(event) != "map_history":
                continue
            args = event.get("args") or {}
            if args.get("lat") is None or args.get("lon") is None:
                continue
            try:
                distance_to_top = great_circle_km(
                    float(args["lat"]),
                    float(args["lon"]),
                    float(source_report["top_lat"]),
                    float(source_report["top_lon"]),
                )
            except (TypeError, ValueError):
                continue
            within_declared_or_25 = distance_to_top <= max(
                float(row.get("top_radius_km") or 0.0), 25.0
            )
            coordinate_rows.append(
                {
                    "report_key": f"{row['run_key']}|{row['report_index']}",
                    "checkpoint_kind": row["checkpoint_kind"],
                    "type": event_base_type(event),
                    "failed": str(event.get("type") or "").endswith("_error"),
                    "distance_to_reported_top_km": distance_to_top,
                    "within_100km": distance_to_top <= 100.0,
                    "within_max_radius_or_25km": within_declared_or_25,
                    "reported_top_more_than_500km_from_truth": row["top_distance_km"] > 500.0,
                    "follows_reported_top_while_top_gt_500km_from_truth": (
                        row["top_distance_km"] > 500.0 and within_declared_or_25
                    ),
                }
            )

    def transition_action_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
        result = submit_group(rows)
        result["next_turn_category_counts_nonexclusive"] = {
            category: sum(category in row["next_categories"] for row in rows)
            for category in ACTION_CATEGORIES
        }
        return result

    def switch_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        switched = [
            row
            for row in rows
            if row["top_jump_km"] is not None and row["top_jump_km"] > LARGE_SWITCH_KM
        ]
        stable = [
            row
            for row in rows
            if row["top_jump_km"] is not None and row["top_jump_km"] <= LARGE_SWITCH_KM
        ]
        return {
            "large_switch_gt_100km": transition_action_group(switched),
            "stable_le_100km": transition_action_group(stable),
            "late_large_switch_gt_100km": transition_action_group(
                [row for row in switched if row["phase"] == "late"]
            ),
            "late_stable_le_100km": transition_action_group(
                [row for row in stable if row["phase"] == "late"]
            ),
        }

    def coordinate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        wrong_top_following = [
            row
            for row in rows
            if row["follows_reported_top_while_top_gt_500km_from_truth"]
        ]
        return {
            "n_events": len(rows),
            "n_reports": len({row["report_key"] for row in rows}),
            "distance_to_reported_top_km": summary(
                row["distance_to_reported_top_km"] for row in rows
            ),
            "within_100km": sum(row["within_100km"] for row in rows),
            "within_max_radius_or_25km": sum(
                row["within_max_radius_or_25km"] for row in rows
            ),
            "following_reported_top_while_top_gt_500km_from_truth": len(
                wrong_top_following
            ),
            "following_wrong_top_action_type_counts": dict(
                sorted(Counter(row["type"] for row in wrong_top_following).items())
            ),
        }

    failed_by_kind = {
        kind: [
            failed
            for row in action_rows
            if row["checkpoint_kind"] == kind
            for failed in row["failed_next_action_types"]
        ]
        for kind in checkpoint_kinds
    }
    return {
        "definition": (
            "Set completo de acciones del primer turn sustantivo con event.step estrictamente "
            "mayor al step del report. Las categorías no son excluyentes porque puede haber "
            "tool calls paralelas. web=web_search/fetch; visual=image_search/pick/crop; "
            "map_history=geocode/map/Street View/historical; submit=submit. Los intentos "
            "fallidos conservan su categoría y se cuentan además por separado. Report-only "
            "no tiene una tool informativa/de investigación coemitida (submit no cuenta); "
            "coemitted-tool sí recibe su resultado entre belief y siguiente turn, por lo que "
            "allí no se atribuye acoplamiento directo."
        ),
        "n_reports": len(action_rows),
        "n_with_next_action": sum(bool(row["next_categories"]) for row in action_rows),
        "by_checkpoint_kind": {
            kind: {
                **by_checkpoint_kind[kind],
                "n_with_next_action": sum(
                    row["checkpoint_kind"] == kind and bool(row["next_categories"])
                    for row in action_rows
                ),
                "n_next_turns_with_multiple_action_events": sum(
                    row["checkpoint_kind"] == kind and len(row["next_events"]) > 1
                    for row in action_rows
                ),
                "n_next_turns_mixing_action_categories": sum(
                    row["checkpoint_kind"] == kind and len(row["next_categories"]) > 1
                    for row in action_rows
                ),
                "failed_action_attempts_in_next_turn": {
                    "n": len(failed_by_kind[kind]),
                    "type_counts": dict(sorted(Counter(failed_by_kind[kind]).items())),
                },
            }
            for kind in checkpoint_kinds
        },
        "late_submit_association_by_checkpoint_kind_and_model": (
            late_submit_by_kind_model
        ),
        "after_top_switch_by_checkpoint_kind": {
            kind: switch_summary(
                [
                    row
                    for row in transition_action_rows
                    if row["checkpoint_kind"] == kind
                ]
            )
            for kind in checkpoint_kinds
        },
        "coordinate_bearing_map_history_actions_by_checkpoint_kind": {
            kind: coordinate_summary(
                [row for row in coordinate_rows if row["checkpoint_kind"] == kind]
            )
            for kind in checkpoint_kinds
        },
    }


def fmt(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{100.0 * value:.{digits}f}%"


def render_markdown(result: dict[str, Any]) -> str:
    inventory = result["inventory"]
    phase_result = result["phase_metrics"]
    phase = phase_result["by_model"]
    paired = result["paired_early_late"]["by_model"]
    transitions = result["transition_metrics"]["by_model"]
    consideration = result["consideration"]["by_model"]
    actions = result["next_action_coupling"]

    lines = [
        "# E018 — análisis temporal descriptivo de creencias",
        "",
        "> **Alcance:** este informe describe reportes elicitados, cambios observados y la "
        "acción posterior. No estima fuerza normativa de evidencia web, corrección bayesiana "
        "de una actualización ni efectos causales.",
        "",
        "Generado determinísticamente por `python scripts/analyze_temporal_beliefs.py` "
        "a partir de los slim de E016.",
        "",
        "## Inventario",
        "",
        f"Estado material: **{inventory['total_runs']} corridas**, "
        f"{inventory['belief_on_runs']} belief-on, {inventory['belief_off_runs']} belief-off, "
        f"{inventory['accepted_reports']} reportes aceptados y "
        f"{inventory['rejected_report_attempts']} intentos rechazados.",
        "",
        "| Modelo | Arm | Runs | Steps rango / media | Reportes | Reportes/run rango / media |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in inventory["by_model_arm"]:
        steps = row["steps"]
        reports = row["reports_per_run"]
        lines.append(
            f"| {row['model']} | {row['arm']} | {row['n_runs']} | "
            f"{fmt(steps['min'], 0)}–{fmt(steps['max'], 0)} / {fmt(steps['mean'], 2)} | "
            f"{row['accepted_reports']} | {fmt(reports['min'], 0)}–{fmt(reports['max'], 0)} / "
            f"{fmt(reports['mean'], 2)} |"
        )
    missing = inventory["missing_cells_against_observed_grid"]
    lines += ["", f"Celdas faltantes contra la grilla observada: `{json.dumps(missing, ensure_ascii=False)}`.", ""]

    timing = inventory["checkpoint_timing"]
    lines += [
        "## Timing de los reportes",
        "",
        "Los checkpoints no son fijos. El agente puede reportar voluntariamente y el nudge "
        "se activa después de tres turns sin reporte.",
        "",
        "- Separación agregada entre reportes: `"
        f"{json.dumps(timing['inter_report_gap_all'], ensure_ascii=False)}`.",
        "- Submit menos último reporte: `"
        f"{json.dumps(timing['submit_step_minus_last_report_step'], ensure_ascii=False)}`.",
        f"- Reportes con una tool sustantiva coemitida en el mismo turn: "
        f"**{timing['reports_with_substantive_tool_coemitted_same_turn']}**. Esa tool no se "
        "considera evidencia previa al reporte.",
        "",
        "## Temprano / medio / tardío",
        "",
        "Fases: early `step/steps_used ≤ 1/3`; middle `≤ 2/3`; late `> 2/3`. "
        "Cada métrica se promedia primero dentro de la corrida-fase. Top weight, entropía, "
        "masa regional y masa temporal muestran la media entre corridas; distancia muestra "
        "la mediana de las medias por corrida.",
        f"Si se excluyera el turn de submit del denominador, cambiarían de fase "
        f"**{phase_result['sensitivity_excluding_submit_turn']['n_reports_changing_phase']}**/"
        f"{inventory['accepted_reports']} reportes: `"
        f"{json.dumps(phase_result['sensitivity_excluding_submit_turn']['transition_counts'], ensure_ascii=False)}`.",
        "",
        "| Modelo | Fase | Runs | Reports | Top weight | H loc. fija | Masa ≤500 km | "
        "Dist. top mediana | Masa fecha verdadera |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, phases in phase.items():
        for phase_name in PHASES:
            row = phases[phase_name]
            metrics = row["metrics"]
            lines.append(
                f"| {model} | {phase_name} | {row['n_runs']} | {row['n_reports']} | "
                f"{fmt(metrics['top_weight']['mean'], 3)} | "
                f"{fmt(metrics['location_entropy_fixed_normalized']['mean'], 3)} | "
                f"{fmt(metrics['region_mass_500km']['mean'], 3)} | "
                f"{fmt(metrics['top_distance_km']['median'], 1)} km | "
                f"{fmt(metrics['year_truth_overlap_mass']['mean'], 3)} |"
            )

    lines += [
        "",
        "La entropía primaria es Shannon sobre candidatos explícitos más un único bin "
        "residual, dividida por `log(6)` —soporte máximo fijo: cinco candidatos más fondo—. "
        "No es entropía espacial y no incorpora radios. El JSON conserva además nats y la "
        "normalización exploratoria por soporte actual; esta última no se usa para firmar "
        "cambios porque K varía entre reportes.",
        "",
        "## Contraste pareado early → late",
        "",
        "Sólo entran corridas con al menos un reporte en ambas fases. Para cada corrida se "
        "calcula `media(late) − media(early)` y después se resumen esos deltas. Es una "
        "comparación descriptiva sobre una muestra seleccionada; con estos N no se hace "
        "inferencia estadística.",
        "",
        "| Modelo | Pares | Δ top weight media / mediana | Δ masa ≤500 km | "
        "Δ masa fecha verdad | Δ H fija |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, row in paired.items():
        delta = row["delta_late_minus_early"]
        lines.append(
            f"| {model} | {row['n_paired_runs']} | "
            f"{fmt(delta['top_weight']['mean'], 4)} / "
            f"{fmt(delta['top_weight']['median'], 4)} | "
            f"{fmt(delta['region_mass_500km']['mean'], 4)} / "
            f"{fmt(delta['region_mass_500km']['median'], 4)} | "
            f"{fmt(delta['year_truth_overlap_mass']['mean'], 4)} / "
            f"{fmt(delta['year_truth_overlap_mass']['median'], 4)} | "
            f"{fmt(delta['location_entropy_fixed_normalized']['mean'], 4)} / "
            f"{fmt(delta['location_entropy_fixed_normalized']['median'], 4)} |"
        )

    lines += [
        "",
        "## Magnitud de cambios entre reportes",
        "",
        "| Modelo | Transiciones | Salto top mediano | >100 km | mediana abs(Δ top weight) | "
        "mediana abs(ΔH) | Confianza sube | Entropía baja |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, model_data in transitions.items():
        row = model_data["all"]
        lines.append(
            f"| {model} | {row['n_transitions']} | {fmt(row['top_jump_km']['median'], 1)} km | "
            f"{pct(row['large_switch_gt_100km']['rate'])} | "
            f"{fmt(row['abs_delta_top_weight']['median'], 3)} | "
            f"{fmt(row['abs_delta_entropy_fixed_normalized']['median'], 3)} | "
            f"{pct(row['confidence_increased_rate'])} | "
            f"{pct(row['entropy_fixed_support_decreased_rate'])} |"
        )

    lines += [
        "",
        "## Generación y abandono de la región correcta",
        "",
        "Definición principal: masa explícita positiva en un candidato cuyo centro está a "
        "≤500 km del ground truth. `Ausente en último reporte` exige que apareciera antes y "
        "terminara con masa cero; es un proxy de abandono, no la creencia exacta al submit.",
        "",
        "| Modelo | Runs | Alguna vez | Ya en primer reporte | Introducida después | Nunca | "
        "Ausente en último reporte |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model, model_data in consideration.items():
        row = model_data["location_by_threshold_km"]["500"]
        lines.append(
            f"| {model} | {row['n_runs']} | {row['ever']} | {row['already_first']} | "
            f"{row['introduced_later']} | {row['never']} | "
            f"{row['absent_at_last_observed_report']}/{row['ever']} |"
        )
    lines += [
        "",
        "`Nunca` significa que la región no apareció en los checkpoints elicitados; no prueba "
        "que el modelo jamás la haya pensado. Los índices/steps de primera aparición y los "
        "casos introducidos tarde están en `analysis.json`.",
        "",
        "Sensibilidad por umbral (`alguna vez / ausente en último reporte`):",
        "",
    ]
    for model, model_data in consideration.items():
        values = []
        for threshold in REGION_THRESHOLDS_KM:
            row = model_data["location_by_threshold_km"][str(int(threshold))]
            values.append(
                f"{int(threshold)} km: {row['ever']}/"
                f"{row['absent_at_last_observed_report']}"
            )
        lines.append(f"- **{model}:** " + "; ".join(values) + ".")

    lines += [
        "",
        "## Acoplamiento con la siguiente acción",
        "",
        "Se toma el set completo de acciones del primer turn sustantivo estrictamente "
        "posterior. Las columnas son multi-label: un mismo turn puede contener varias tool "
        "calls paralelas. `visual` incluye image search/pick/crops; `map_history` incluye "
        "geocode, mapas, Street View e historical query.",
        "",
        "La separación crítica es temporal: en un checkpoint `report-only` no hay tool "
        "informativa/de investigación coemitida —submit no cuenta—; en `coemitted-tool`, el "
        "resultado de esa tool llega después del belief pero antes del siguiente turn. Sólo "
        "el primer estrato admite una lectura directa belief→acción; el segundo se conserva "
        "descriptivamente como belief→evidencia intermedia→acción.",
        "",
        "| Estrato | Modelo | Reports | Web | Visual | Map/history | Submit | Sin acción |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for kind, kind_data in actions["by_checkpoint_kind"].items():
        for model, phases in kind_data["by_model_phase"].items():
            counts = {
                category: sum(
                    phases[phase]["counts"][category] for phase in PHASES
                )
                for category in (*ACTION_CATEGORIES, "missing")
            }
            n_reports = sum(phases[phase]["n_reports"] for phase in PHASES)
            lines.append(
                f"| {kind} | {model} | {n_reports} | {counts['web']} | "
                f"{counts['visual']} | {counts['map_history']} | {counts['submit']} | "
                f"{counts['missing']} |"
            )

    def submit_cell(group: dict[str, Any]) -> str:
        rate = pct(group["submit_next_rate"]) if group["n"] else "—"
        return f"{group['submit_next']}/{group['n']} ({rate})"

    late = actions["late_submit_association_by_checkpoint_kind_and_model"]
    lines += [
        "",
        "### Parada tardía, estratificada",
        "",
        "Cada celda es `submit en siguiente turn / checkpoints con siguiente acción`. No se "
        "combinan modelos; las celdas pequeñas —por ejemplo 1/1— no sostienen inferencia.",
        "",
        "| Estrato | Modelo | Top weight ≥.8 | Top weight <.8 | Masa500 positiva | "
        "Masa500 cero |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for kind in ("report_only", "coemitted_tool"):
        for model, groups in late[kind].items():
            lines.append(
                f"| {kind} | {model} | "
                f"{submit_cell(groups['high_top_weight_ge_0_8'])} | "
                f"{submit_cell(groups['lower_top_weight'])} | "
                f"{submit_cell(groups['correct_region_mass_500km_positive'])} | "
                f"{submit_cell(groups['no_correct_region_mass_500km'])} |"
            )

    report_only = actions["by_checkpoint_kind"]["report_only"]
    coemitted = actions["by_checkpoint_kind"]["coemitted_tool"]
    coords = actions["coordinate_bearing_map_history_actions_by_checkpoint_kind"]
    lines += [
        "",
        f"Hay {report_only['n_reports']} checkpoints report-only y "
        f"{coemitted['n_reports']} coemitted-tool. En sus siguientes turns, respectivamente, "
        f"{report_only['n_next_turns_with_multiple_action_events']} y "
        f"{coemitted['n_next_turns_with_multiple_action_events']} contienen múltiples acciones; "
        f"{report_only['n_next_turns_mixing_action_categories']} y "
        f"{coemitted['n_next_turns_mixing_action_categories']} mezclan categorías.",
        f"Acciones map/history con coordenadas tras report-only: "
        f"{coords['report_only']['n_events']} eventos en {coords['report_only']['n_reports']} "
        f"reportes; tras coemitted-tool: {coords['coemitted_tool']['n_events']} eventos en "
        f"{coords['coemitted_tool']['n_reports']} reportes.",
        "",
        "Incluso en report-only, estas tasas son asociaciones descriptivas: el tipo de "
        "checkpoint, la fase y la parada son decisiones endógenas del agente. No atribuyen "
        "fuerza a la evidencia ni efectos causales.",
        "",
        "## Limitaciones",
        "",
    ]
    lines.extend(f"- {limitation}" for limitation in result["limitations"])
    lines += [
        "",
        "## Reproducción",
        "",
        "```bash",
        "python scripts/analyze_temporal_beliefs.py",
        "```",
        "",
        "Los hashes SHA-256 exactos de los seis inputs están en `analysis.json`.",
        "",
    ]
    return "\n".join(lines)


def analyze(input_dir: Path) -> dict[str, Any]:
    records, inputs = load_records(input_dir)
    inventory = build_inventory(records, input_dir)

    reports_by_run: dict[str, list[dict[str, Any]]] = {}
    report_rows: list[dict[str, Any]] = []
    for record in records:
        reports = (record.get("react") or {}).get("belief_reports") or []
        if not reports:
            continue
        enriched = [enrich_report(record, report, index) for index, report in enumerate(reports)]
        reports_by_run[run_key(record)] = enriched
        report_rows.extend(enriched)

    transitions = make_transitions(reports_by_run)
    result = {
        "schema_version": 2,
        "analysis_kind": "descriptive_temporal_belief_audit",
        "normative_claims": False,
        "source_experiment": "E016_belief_pilot",
        "generated_by": "scripts/analyze_temporal_beliefs.py",
        "inputs": inputs,
        "metric_definitions": {
            "phases": "early <= 1/3, middle <= 2/3, late > 2/3 de step/steps_used",
            "location_entropy": (
                "Shannon sobre pesos explícitos más un bin residual: nats y normalización "
                "primaria por soporte fijo log(6). H/log(K no-cero) queda sólo diagnóstico."
            ),
            "region_mass": "Suma de pesos de candidatos cuyo centro cae dentro del umbral.",
            "exact_disk_mass": "Suma de pesos de candidatos cuya esfera declarada contiene la verdad.",
            "year_truth_overlap_mass": (
                "Suma de pesos de intervalos que solapan [year, year2]; no corrige por ancho."
            ),
            "first_consideration": (
                "Primer checkpoint elicitado con masa regional explícita positiva."
            ),
            "absent_at_last_observed_report": (
                "Masa positiva alguna vez y cero en el último checkpoint; proxy de abandono."
            ),
            "next_action": (
                "Set multi-label de acciones del primer turn sustantivo estrictamente posterior, "
                "separado según exista o no una tool coemitida entre belief y ese turn."
            ),
        },
        "inventory": inventory,
        "phase_metrics": aggregate_phase_metrics(report_rows),
        "paired_early_late": paired_early_late_analysis(reports_by_run),
        "transition_metrics": aggregate_transitions(transitions),
        "consideration": consideration_analysis(reports_by_run),
        "next_action_coupling": action_analysis(records, reports_by_run, transitions),
        "limitations": LIMITATIONS,
    }
    return round_floats(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    result = analyze(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "analysis.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    print(f"Wrote {json_path.relative_to(ROOT)}")
    print(f"Wrote {markdown_path.relative_to(ROOT)}")
    print(
        f"Runs={result['inventory']['total_runs']} | "
        f"belief-on={result['inventory']['belief_on_runs']} | "
        f"reports={result['inventory']['accepted_reports']}"
    )


if __name__ == "__main__":
    main()
