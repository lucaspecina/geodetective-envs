"""Métricas post-hoc para evaluar agent runs (refs #32).

Análisis sobre los results_*.json existentes (E005, E009, E010, E012, E013, etc.)
sin necesidad de re-correr el agente. Útil porque el agente ya nos devuelve:
- year predicho
- confidence (alta/media/baja)
- verification_checks
- trace completo de tool calls

...pero hasta ahora solo medíamos `distance_km`.

Métricas implementadas:
- Distance: media, std, mediana, hit rates por bucket (1/5/25/100/500/1000 km)
- Year: error absoluto, accuracy por bucket (±5/±10/±20 años)
- Calibration: correlación confidence ↔ distance (Spearman)
- Verification: % submits con al menos 1 tool visual antes de submit_answer
- Overconfidence rate: % submits con confidence=alta y distance > 100 km
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Buckets para hit rate de distancia (km)
DIST_BUCKETS_KM = [1, 5, 25, 100, 500, 1000]
# Buckets para year error (años)
YEAR_BUCKETS = [5, 10, 20]

VISUAL_TOOLS = {"static_map", "street_view", "crop_image", "crop_image_relative",
                "fetch_url_with_images", "image_search", "image_search_pick"}


@dataclass
class PerRunMetrics:
    """Métricas calculadas por corrida (modelo × foto × run)."""
    cid: int
    model: str
    submit_called: bool
    distance_km: Optional[float] = None
    year_error: Optional[int] = None  # |pred - truth|
    confidence: Optional[str] = None  # alta/media/baja
    visual_verification_before_submit: bool = False
    steps_used: int = 0
    terminal_state: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "cid": self.cid, "model": self.model, "submit_called": self.submit_called,
            "distance_km": self.distance_km, "year_error": self.year_error,
            "confidence": self.confidence,
            "visual_verification_before_submit": self.visual_verification_before_submit,
            "steps_used": self.steps_used, "terminal_state": self.terminal_state,
        }


@dataclass
class AggregatedMetrics:
    """Métricas agregadas por modelo (o slice arbitrario)."""
    label: str  # nombre del slice (ej "gpt-5.4-mini" o "tier=easy")
    n_runs: int = 0
    n_submitted: int = 0

    # Distance
    dist_mean: Optional[float] = None
    dist_median: Optional[float] = None
    dist_std: Optional[float] = None
    dist_hit_rates: dict = field(default_factory=dict)  # {"<1km": 0.1, "<5km": 0.3, ...}

    # Year
    year_mae: Optional[float] = None  # mean absolute error
    year_hit_rates: dict = field(default_factory=dict)  # {"±5y": 0.4, ...}

    # Calibration
    overconfidence_rate: Optional[float] = None  # % con conf=alta y dist > 100
    confidence_dist: dict = field(default_factory=dict)  # {"alta": N, "media": N, "baja": N}
    avg_dist_by_confidence: dict = field(default_factory=dict)

    # Verification
    visual_verification_rate: Optional[float] = None  # % submits con tool visual antes

    # Steps
    avg_steps: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "label": self.label, "n_runs": self.n_runs, "n_submitted": self.n_submitted,
            "dist": {
                "mean": self.dist_mean, "median": self.dist_median, "std": self.dist_std,
                "hit_rates": self.dist_hit_rates,
            },
            "year": {
                "mae": self.year_mae, "hit_rates": self.year_hit_rates,
            },
            "calibration": {
                "overconfidence_rate": self.overconfidence_rate,
                "confidence_dist": self.confidence_dist,
                "avg_dist_by_confidence": self.avg_dist_by_confidence,
            },
            "verification": {
                "visual_before_submit_rate": self.visual_verification_rate,
            },
            "avg_steps": self.avg_steps,
        }


# === Helpers ===

def _parse_year(year_str) -> Optional[float]:
    """Parsear año (acepta '1965', '1960-1970', '1960', 1965). Devuelve float."""
    if year_str is None:
        return None
    s = str(year_str).strip()
    if not s or s.lower() == "unknown":
        return None
    if "-" in s:
        try:
            a, b = s.split("-", 1)
            return (int(a.strip()) + int(b.strip())) / 2
        except (ValueError, AttributeError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _check_visual_verification(trace: list[dict]) -> bool:
    """¿Hubo al menos 1 tool visual antes del submit_answer?"""
    for ev in trace:
        if ev.get("type") in VISUAL_TOOLS:
            return True
        if ev.get("type") == "submit":
            return False
    return False


def compute_per_run(record: dict) -> Optional[PerRunMetrics]:
    """Computar métricas de una corrida individual del results.json."""
    cid = record.get("cid")
    rk = record.get("react") or {}
    model = rk.get("model", "unknown")
    submit_called = rk.get("submit_called", False)
    final_answer = rk.get("final_answer") or {}
    trace = rk.get("trace") or []

    # Distance: ya viene calculada
    distance_km = rk.get("distance_km")

    # Year error
    year_error = None
    truth_year = record.get("year")
    pred_year = _parse_year(final_answer.get("year"))
    if truth_year is not None and pred_year is not None:
        try:
            year_error = int(abs(pred_year - float(truth_year)))
        except (ValueError, TypeError):
            pass

    confidence = (final_answer.get("confidence") or "").strip().lower() or None

    visual_verif = _check_visual_verification(trace) if submit_called else False

    return PerRunMetrics(
        cid=cid, model=model, submit_called=submit_called,
        distance_km=distance_km, year_error=year_error, confidence=confidence,
        visual_verification_before_submit=visual_verif,
        steps_used=rk.get("steps_used", 0),
        terminal_state=rk.get("terminal_state"),
    )


def aggregate(per_runs: list[PerRunMetrics], label: str) -> AggregatedMetrics:
    """Calcular métricas agregadas a partir de lista de per-run."""
    agg = AggregatedMetrics(label=label, n_runs=len(per_runs))
    submitted = [r for r in per_runs if r.submit_called]
    agg.n_submitted = len(submitted)

    # Distance
    dists = [r.distance_km for r in submitted if r.distance_km is not None]
    if dists:
        agg.dist_mean = sum(dists) / len(dists)
        agg.dist_median = sorted(dists)[len(dists) // 2]
        if len(dists) > 1:
            m = agg.dist_mean
            agg.dist_std = math.sqrt(sum((d - m) ** 2 for d in dists) / (len(dists) - 1))
        agg.dist_hit_rates = {
            f"<{b}km": sum(1 for d in dists if d < b) / len(dists)
            for b in DIST_BUCKETS_KM
        }

    # Year
    year_errs = [r.year_error for r in submitted if r.year_error is not None]
    if year_errs:
        agg.year_mae = sum(year_errs) / len(year_errs)
        agg.year_hit_rates = {
            f"±{b}y": sum(1 for y in year_errs if y <= b) / len(year_errs)
            for b in YEAR_BUCKETS
        }

    # Calibration
    confs = [r.confidence for r in submitted if r.confidence]
    agg.confidence_dist = {c: confs.count(c) for c in set(confs)}
    overconf = sum(1 for r in submitted
                   if r.confidence == "alta" and r.distance_km is not None and r.distance_km > 100)
    if submitted:
        agg.overconfidence_rate = overconf / len(submitted)
    # Avg distance by confidence band
    for c in ("alta", "media", "baja"):
        ds = [r.distance_km for r in submitted if r.confidence == c and r.distance_km is not None]
        if ds:
            agg.avg_dist_by_confidence[c] = sum(ds) / len(ds)

    # Verification
    if submitted:
        agg.visual_verification_rate = sum(1 for r in submitted if r.visual_verification_before_submit) / len(submitted)

    # Steps
    steps = [r.steps_used for r in per_runs if r.steps_used]
    if steps:
        agg.avg_steps = sum(steps) / len(steps)

    return agg


def load_results_file(path: Path) -> list[dict]:
    """Cargar results.json; tolera shapes [list] o {records: [...]}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("results") or []


def compute_metrics_for_file(path: Path) -> tuple[list[PerRunMetrics], dict]:
    """Devolver (per_run list, agg por modelo dict)."""
    records = load_results_file(path)
    per_runs = []
    for r in records:
        m = compute_per_run(r)
        if m is not None:
            per_runs.append(m)

    # Agrupar por modelo
    by_model: dict[str, list[PerRunMetrics]] = {}
    for r in per_runs:
        by_model.setdefault(r.model, []).append(r)

    agg_by_model = {
        model: aggregate(runs, label=model).to_dict()
        for model, runs in by_model.items()
    }
    return per_runs, agg_by_model
