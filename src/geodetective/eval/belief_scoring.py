"""Scoring de creencias (belief-state) con proper scoring rules geodésicas.

Pieza central del rediseño belief-state (ver research/synthesis/belief_state_redesign.md):
el agente reporta una distribución de creencia sobre (ubicación, año) y este módulo
la puntúa contra ground truth. Todo mecánico — sin LLM judge.

Modelo de la creencia de ubicación: mezcla de kernels von Mises-Fisher sobre la
esfera + componente uniforme de fondo ("no sé") + piso epsilon que garantiza
score acotado (nunca -inf).

    p(x) = (1-eps) * [ sum_k w_k * vMF(x; mu_k, kappa_k) + w_bg * U ] + eps * U

donde w_bg = 1 - sum(w_k) (la masa no asignada es "no sé") y U = 1/(4*pi).
kappa_k se deriva del radio reportado: kappa = (R_TIERRA / radius_km)^2, de modo
que el desvío estándar de la distancia geodésica al centro ~ radius_km.

Scores implementados:
- log-score:  S(b) = -log p(x_truth)   (estrictamente proper; menor = mejor)
- energy score (análogo geodésico del CRPS, vía Monte Carlo; proper, menos
  severo con el confiado-equivocado — comparación en scripts/test_belief_scoring.py)

Reward denso por paso: r_t = S(b_{t-1}) - S(b_t). La suma telescopea a
S(b_0) - S(b_T), así que los offsets constantes (unidades de la densidad)
cancelan en el reward.

Unidades: densidades sobre la esfera unitaria (por estereorradián) y por año;
scores en nats. info_gain = log p - log U = nats por encima de la ignorancia.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

EARTH_RADIUS_KM = 6371.0
LOG_UNIFORM_SPHERE = -math.log(4.0 * math.pi)  # log U, U = 1/(4*pi)

# Piso de probabilidad: masa mínima reservada al uniforme (evita -inf y hace
# que "no sé" sea un reporte legítimo con score acotado).
DEFAULT_EPS = 0.01

# Radio mínimo aceptado (km): debajo de esto se clampea (evita kappa infinito).
MIN_RADIUS_KM = 0.1

# Rango de fondo para la creencia de año (cubre el corpus 1826-2000 con margen).
YEAR_BACKGROUND = (1800.0, 2030.0)


# === Schema de la creencia ===

@dataclass
class LocationComponent:
    """Un candidato de ubicación: centro + peso + radio de incertidumbre."""
    lat: float
    lon: float
    weight: float
    radius_km: float
    name: str = ""


@dataclass
class YearComponent:
    """Un rango candidato de años con peso."""
    year_from: float
    year_to: float
    weight: float


@dataclass
class Belief:
    """Creencia completa reportada por el agente en un paso."""
    location: list[LocationComponent] = field(default_factory=list)
    year: list[YearComponent] = field(default_factory=list)
    rationale: str = ""  # NO entra al score; para viewer/annotator

    @classmethod
    def from_dict(cls, d: dict) -> "Belief":
        """Parsear el schema JSON de report_belief (belief_state_redesign.md §2.1)."""
        loc = [
            LocationComponent(
                lat=float(c["lat"]), lon=float(c["lon"]),
                weight=float(c["weight"]), radius_km=float(c["radius_km"]),
                name=str(c.get("name", "")),
            )
            for c in d.get("location_belief", [])
        ]
        yr = [
            YearComponent(
                year_from=float(c["from"]), year_to=float(c["to"]),
                weight=float(c["weight"]),
            )
            for c in d.get("year_belief", [])
        ]
        return cls(location=loc, year=yr, rationale=str(d.get("rationale", "")))


# === Helpers geométricos ===

def _to_unit_vector(lat: float, lon: float) -> tuple[float, float, float]:
    la, lo = math.radians(lat), math.radians(lon)
    return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))


def _dot(a: tuple, b: tuple) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia geodésica esférica en km."""
    c = _dot(_to_unit_vector(lat1, lon1), _to_unit_vector(lat2, lon2))
    return EARTH_RADIUS_KM * math.acos(max(-1.0, min(1.0, c)))


def _log_sinh(k: float) -> float:
    """log(sinh(k)) numéricamente estable para k grande."""
    if k < 30.0:
        return math.log(math.sinh(k))
    # sinh(k) = e^k (1 - e^{-2k}) / 2
    return k - math.log(2.0) + math.log1p(-math.exp(-2.0 * k))


def _kappa_from_radius(radius_km: float) -> float:
    r = max(float(radius_km), MIN_RADIUS_KM)
    return (EARTH_RADIUS_KM / r) ** 2


def _log_vmf(cos_theta: float, kappa: float) -> float:
    """log densidad vMF en S^2 (por estereorradián) a ángulo theta del centro.

    f(x; mu, kappa) = kappa / (4*pi*sinh(kappa)) * exp(kappa * mu.x)
    """
    if kappa < 1e-9:
        return LOG_UNIFORM_SPHERE
    return math.log(kappa) - math.log(4.0 * math.pi) - _log_sinh(kappa) + kappa * cos_theta


def _logsumexp(terms: list[float]) -> float:
    m = max(terms)
    if m == -math.inf:
        return -math.inf
    return m + math.log(sum(math.exp(t - m) for t in terms))


# === Validación / normalización de pesos ===

def _validate_weights(weights: list[float]) -> tuple[list[float], float]:
    """Devuelve (pesos, masa de fondo). Si suman >1 se normalizan; negativos = error."""
    for w in weights:
        if w < 0:
            raise ValueError(f"peso negativo en belief: {w}")
    s = sum(weights)
    if s > 1.0 + 1e-9:
        weights = [w / s for w in weights]
        s = 1.0
    return weights, max(0.0, 1.0 - s)


# === Log-score de ubicación ===

def location_log_density(
    components: list[LocationComponent],
    lat: float,
    lon: float,
    eps: float = DEFAULT_EPS,
) -> float:
    """log p(lat, lon) bajo la mezcla con fondo uniforme y piso eps."""
    weights, w_bg = _validate_weights([c.weight for c in components])
    x = _to_unit_vector(lat, lon)
    terms: list[float] = []
    for c, w in zip(components, weights):
        if w <= 0:
            continue
        cos_theta = _dot(x, _to_unit_vector(c.lat, c.lon))
        kappa = _kappa_from_radius(c.radius_km)
        terms.append(math.log((1.0 - eps) * w) + _log_vmf(cos_theta, kappa))
    bg_mass = (1.0 - eps) * w_bg + eps
    terms.append(math.log(bg_mass) + LOG_UNIFORM_SPHERE)
    return _logsumexp(terms)


def location_score(
    components: list[LocationComponent],
    truth_lat: float,
    truth_lon: float,
    eps: float = DEFAULT_EPS,
) -> float:
    """Log-score S = -log p(truth). Menor = mejor. Acotado por -log(eps*U)."""
    return -location_log_density(components, truth_lat, truth_lon, eps=eps)


# === Log-score de año ===

def year_log_density(
    components: list[YearComponent],
    year: float,
    eps: float = DEFAULT_EPS,
    background: tuple[float, float] = YEAR_BACKGROUND,
) -> float:
    """log p(year) bajo mezcla de uniformes por rango + fondo uniforme + piso."""
    for c in components:
        if c.year_to < c.year_from:
            raise ValueError(f"rango de año invertido: {c.year_from}-{c.year_to}")
    weights, w_bg = _validate_weights([c.weight for c in components])
    bg_width = background[1] - background[0]
    density = 0.0
    for c, w in zip(components, weights):
        width = max(c.year_to - c.year_from, 1.0)
        if c.year_from <= year <= c.year_to:
            density += w / width
    bg_density = (1.0 / bg_width) if background[0] <= year <= background[1] else 0.0
    p = (1.0 - eps) * (density + w_bg * bg_density) + eps * bg_density
    if p <= 0.0:
        # truth fuera incluso del rango de fondo: piso absoluto
        p = eps / bg_width
    return math.log(p)


def year_score(
    components: list[YearComponent],
    truth_year: float,
    eps: float = DEFAULT_EPS,
) -> float:
    """Log-score de año. Menor = mejor."""
    return -year_log_density(components, truth_year, eps=eps)


# === Score combinado + info gain ===

@dataclass
class BeliefScore:
    """Resultado de puntuar una creencia contra ground truth."""
    location_score: float                 # nats, menor = mejor
    year_score: Optional[float]           # nats, menor = mejor (None si no hay year belief que puntuar)
    total: float                          # location + alpha_year * year
    info_gain_location_nats: float        # nats por encima de la ignorancia (mayor = mejor)
    info_gain_year_nats: Optional[float]

    def to_dict(self) -> dict:
        return {
            "location_score": self.location_score,
            "year_score": self.year_score,
            "total": self.total,
            "info_gain_location_nats": self.info_gain_location_nats,
            "info_gain_year_nats": self.info_gain_year_nats,
        }


def score_belief(
    belief: Belief,
    truth_lat: float,
    truth_lon: float,
    truth_year: Optional[float] = None,
    alpha_year: float = 1.0,
    eps: float = DEFAULT_EPS,
) -> BeliefScore:
    """Puntuar una creencia completa. total = S_loc + alpha_year * S_year.

    Si truth_year es None, el componente de año no se puntúa (total = S_loc).
    Una creencia vacía es "no sé" legítimo: puntúa como el fondo uniforme.
    """
    s_loc = location_score(belief.location, truth_lat, truth_lon, eps=eps)
    ig_loc = -s_loc - LOG_UNIFORM_SPHERE  # log p - log U

    s_year: Optional[float] = None
    ig_year: Optional[float] = None
    if truth_year is not None:
        s_year = year_score(belief.year, truth_year, eps=eps)
        bg_width = YEAR_BACKGROUND[1] - YEAR_BACKGROUND[0]
        ig_year = -s_year - math.log(1.0 / bg_width)

    total = s_loc + (alpha_year * s_year if s_year is not None else 0.0)
    return BeliefScore(
        location_score=s_loc, year_score=s_year, total=total,
        info_gain_location_nats=ig_loc, info_gain_year_nats=ig_year,
    )


# === Reward denso por paso ===

def step_rewards(scores: list[float]) -> list[float]:
    """r_t = S_{t-1} - S_t sobre la secuencia de scores de la trayectoria.

    Propiedad telescópica: sum(step_rewards) = scores[0] - scores[-1].
    """
    return [scores[i - 1] - scores[i] for i in range(1, len(scores))]


def score_belief_sequence(
    beliefs: list[Belief],
    truth_lat: float,
    truth_lon: float,
    truth_year: Optional[float] = None,
    alpha_year: float = 1.0,
    prepend_ignorance: bool = True,
    eps: float = DEFAULT_EPS,
) -> tuple[list[float], list[float]]:
    """Puntuar la trayectoria de creencias de un episodio.

    Devuelve (scores_totales, rewards_por_paso). Con prepend_ignorance=True el
    primer reward mide la mejora respecto del prior uniforme ("no sé") — así
    el primer report_belief también queda valuado.
    """
    scores = [
        score_belief(b, truth_lat, truth_lon, truth_year, alpha_year=alpha_year, eps=eps).total
        for b in beliefs
    ]
    if prepend_ignorance:
        s0 = score_belief(Belief(), truth_lat, truth_lon, truth_year,
                          alpha_year=alpha_year, eps=eps).total
        scores = [s0] + scores
    return scores, step_rewards(scores)


# === Energy score (análogo geodésico del CRPS, vía Monte Carlo) ===

def _sample_vmf(mu: tuple, kappa: float, rng: random.Random) -> tuple:
    """Samplear un punto de vMF(mu, kappa) en S^2 (método estándar de inversión)."""
    u = rng.random()
    if kappa < 1e-9:
        w = 2.0 * u - 1.0
    else:
        e2k = math.exp(-2.0 * kappa)
        w = 1.0 + math.log(u + (1.0 - u) * e2k) / kappa
    w = max(-1.0, min(1.0, w))
    # base ortonormal perpendicular a mu
    ref = (1.0, 0.0, 0.0) if abs(mu[0]) < 0.9 else (0.0, 1.0, 0.0)
    e1 = _cross(mu, ref)
    e1 = _normalize(e1)
    e2 = _cross(mu, e1)
    phi = rng.random() * 2.0 * math.pi
    s = math.sqrt(max(0.0, 1.0 - w * w))
    return tuple(
        mu[i] * w + s * (math.cos(phi) * e1[i] + math.sin(phi) * e2[i]) for i in range(3)
    )


def _cross(a: tuple, b: tuple) -> tuple:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalize(v: tuple) -> tuple:
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n)


def _sample_uniform_sphere(rng: random.Random) -> tuple:
    z = 2.0 * rng.random() - 1.0
    phi = rng.random() * 2.0 * math.pi
    s = math.sqrt(max(0.0, 1.0 - z * z))
    return (s * math.cos(phi), s * math.sin(phi), z)


def _sample_mixture(
    components: list[LocationComponent],
    n: int,
    rng: random.Random,
    eps: float,
) -> list[tuple]:
    """Samplear n puntos de la misma p(x) que usa el log-score (con fondo + piso)."""
    weights, w_bg = _validate_weights([c.weight for c in components])
    eff = [(1.0 - eps) * w for w in weights]
    bg_mass = (1.0 - eps) * w_bg + eps
    mus = [_to_unit_vector(c.lat, c.lon) for c in components]
    kappas = [_kappa_from_radius(c.radius_km) for c in components]
    out = []
    for _ in range(n):
        r = rng.random()
        acc = 0.0
        chosen = -1
        for i, w in enumerate(eff):
            acc += w
            if r < acc:
                chosen = i
                break
        if chosen < 0:
            out.append(_sample_uniform_sphere(rng))  # fondo (masa bg_mass)
        else:
            out.append(_sample_vmf(mus[chosen], kappas[chosen], rng))
    assert abs(sum(eff) + bg_mass - 1.0) < 1e-9
    return out


def location_energy_score(
    components: list[LocationComponent],
    truth_lat: float,
    truth_lon: float,
    n_samples: int = 2048,
    seed: int = 0,
    eps: float = DEFAULT_EPS,
) -> float:
    """Energy score geodésico: ES = E d(X, truth) - 0.5 E d(X, X'). En km, menor = mejor.

    Proper (la distancia de gran círculo es un kernel de tipo negativo en la
    esfera). Estimado por Monte Carlo con seed fija — determinístico.
    """
    rng = random.Random(seed)
    xt = _to_unit_vector(truth_lat, truth_lon)
    xs = _sample_mixture(components, n_samples, rng, eps)
    ys = _sample_mixture(components, n_samples, rng, eps)

    def d(a: tuple, b: tuple) -> float:
        return EARTH_RADIUS_KM * math.acos(max(-1.0, min(1.0, _dot(a, b))))

    term1 = sum(d(x, xt) for x in xs) / n_samples
    term2 = sum(d(x, y) for x, y in zip(xs, ys)) / n_samples
    return term1 - 0.5 * term2


__all__ = [
    "EARTH_RADIUS_KM",
    "DEFAULT_EPS",
    "YEAR_BACKGROUND",
    "LocationComponent",
    "YearComponent",
    "Belief",
    "BeliefScore",
    "great_circle_km",
    "location_log_density",
    "location_score",
    "year_log_density",
    "year_score",
    "score_belief",
    "step_rewards",
    "score_belief_sequence",
    "location_energy_score",
]
