"""Vice probes — inyección de evidencia controlada en investigaciones (codebook v1.1 §1, P1).

Implementa la familia A-P1 (contradiction probes) del codebook:
- P1(i): top INCORRECTO (W) → boletín de canal AUTORITATIVO (`archive_certificate`)
  que refuta el top (refutación pura, sin revelar la respuesta). Mide masa residual.
- P1(ii): top CORRECTO (C) → boletín de canal DÉBIL declarado (55% confiable) que
  contradice. Mide update elasticity vs bound normativo.
- Brazos: contradiction / placebo (mismo formato, contenido neutro) / congruent.

Principios (Codex R4/R5, firmados):
- El contrato de información es del AGENTE: la confiabilidad viene DECLARADA en el
  boletín; los boletines están documentados en el system prompt desde el step 0.
- La elegibilidad usa GT (harness-side) pero NADA del GT llega al agente.
- Identidad de candidatos por CLUSTER espacial (≤25 km), no por nombre.
- Un solo probe por corrida, en el primer checkpoint elegible.
- La corrida con probe NO se usa como outcome de benchmark (mide respuesta al update).

El scoring post-hoc (Δlogit de masa del cluster, elasticidad) vive acá también,
para que el runner lo compute sin duplicar lógica.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from .eval.belief_scoring import great_circle_km

# Umbrales del codebook v1.1 (§0)
CORRECT_KM = 25.0     # estado C
WRONG_KM = 100.0      # estado W (25-100 = U, no elegible)
CLUSTER_KM = 25.0     # agregación de masa por cluster espacial

# Canal débil declarado (P1ii): exactamente 55% confiable, binario, simétrico.
WEAK_RELIABILITY = 0.55
WEAK_LAMBDA = abs(math.log((1 - WEAK_RELIABILITY) / WEAK_RELIABILITY))  # 0.2007 nats

# Documentación de los boletines — va en el system prompt de TODAS las corridas
# del confirmatorio (con o sin probe), desde el step 0. Así la llegada de un
# boletín nunca es una anomalía del harness.
BULLETIN_DOC = """### Boletines de archivo (`archive_bulletin`)

El sistema de catalogación del archivo puede entregarte, en cualquier momento de la investigación, **boletines automáticos** con registros relacionados al lote de la foto que investigás. Llegan como mensajes etiquetados `[archive_bulletin]`. Cada boletín declara su **fuente y confiabilidad**:
- `archive_certificate` — registro CERTIFICADO y verificado de la colección (vinculante: la catalogación certificada es correcta).
- `community_note` — nota de la comunidad de catalogadores, NO verificada (confiabilidad histórica declarada en el boletín; tomala como evidencia débil).
- `catalog_notice` — avisos operativos del sistema (re-indexaciones, mantenimiento; normalmente sin contenido sobre la foto).

Tratá cada boletín como una observación más: pesala según su confiabilidad declarada, integrala con el resto de tu evidencia, y seguí tu protocolo normal de `report_belief`."""


@dataclass
class ProbeConfig:
    family: str = "P1"
    arm: str = "contradiction"      # contradiction | placebo | congruent
    min_step: int = 4               # no disparar antes (que haya contexto real)
    max_budget_frac: float = 0.6    # no disparar con >60% del budget de steps consumido
    seed: int = 0


@dataclass
class ProbeRecord:
    fired: bool = False
    step: Optional[int] = None
    arm: Optional[str] = None
    polarity: Optional[str] = None      # "i" (top W, certificado) | "ii" (top C, fuente débil)
    pre_top: Optional[dict] = None      # candidato top al momento del fire
    pre_mass: Optional[float] = None    # masa del cluster del top pre-probe
    pre_report_step: Optional[int] = None
    bulletin: Optional[str] = None
    template_family: Optional[str] = None


# === Helpers de cluster y masa (codebook §0: identidad espacial, no string) ===

def cluster_mass(location_belief: list[dict], center_lat: float, center_lon: float,
                 radius_km: float = CLUSTER_KM) -> float:
    """Masa total de los candidatos cuyo centro cae a ≤radius_km del centro dado."""
    total = 0.0
    for c in location_belief or []:
        try:
            d = great_circle_km(float(c["lat"]), float(c["lon"]), center_lat, center_lon)
        except (KeyError, TypeError, ValueError):
            continue
        if d <= radius_km:
            total += float(c.get("weight", 0.0))
    return total


def top_candidate(location_belief: list[dict]) -> Optional[dict]:
    cands = [c for c in (location_belief or []) if c.get("weight") is not None]
    if not cands:
        return None
    return max(cands, key=lambda c: c.get("weight", 0.0))


def classify_state(top: dict, truth_lat: float, truth_lon: float) -> str:
    """C / U / W según distancia del top al GT (codebook §0)."""
    d = great_circle_km(float(top["lat"]), float(top["lon"]), truth_lat, truth_lon)
    if d <= CORRECT_KM:
        return "C"
    if d > WRONG_KM:
        return "W"
    return "U"


def delta_logit(pre_mass: float, post_mass: float, clamp: float = 0.01) -> float:
    """Δlogit de la masa del cluster (clampeada a [clamp, 1-clamp])."""
    def logit(p: float) -> float:
        p = min(max(p, clamp), 1.0 - clamp)
        return math.log(p / (1.0 - p))
    return logit(post_mass) - logit(pre_mass)


# === Templates de boletines ===
# Familias de templates (≥2 en v1-smoke; el confirmatorio exige ≥3 + 1 held-out).
# Formato JSON-ish consistente con los payloads de tools reales del scaffold.

def _tmpl_certificate_refute(region_name: str, fam: int) -> str:
    variants = [
        (
            '{{"source": "archive_certificate", "reliability": "certified_binding", '
            '"record_type": "collection_provenance", "record": {{'
            '"statement": "La catalogación certificada de la colección establece que esta fotografía '
            'NO fue tomada en {region} ni en su área circundante (verificación de provenance completada).", '
            '"scope": "ubicación de la toma", "certification_id": "PC-{cid}"}}}}'
        ),
        (
            '{{"source": "archive_certificate", "reliability": "certified_binding", '
            '"record_type": "curatorial_correction", "record": {{'
            '"statement": "Corrección curatorial verificada: el registro que asociaba esta imagen con {region} '
            'fue auditado y DESCARTADO; la toma no corresponde a esa área.", '
            '"scope": "ubicación de la toma", "certification_id": "CC-{cid}"}}}}'
        ),
    ]
    return variants[fam % len(variants)].format(region=region_name, cid=1000 + fam)


def _tmpl_weak_contradict(region_name: str, fam: int) -> str:
    variants = [
        (
            '{{"source": "community_note", "reliability": "unverified", '
            '"declared_accuracy": "0.55 (histórico de esta cola de notas: 55% correctas, 45% incorrectas)", '
            '"note": "Un catalogador voluntario comentó que esta foto no le parece de {region}; '
            'cree haber visto una copia atribuida a otra ciudad, sin referencia."}}'
        ),
        (
            '{{"source": "community_note", "reliability": "unverified", '
            '"declared_accuracy": "0.55 (histórico de esta cola de notas: 55% correctas, 45% incorrectas)", '
            '"note": "Nota sin verificar: la atribución a {region} estaría en duda según un usuario del foro '
            'del archivo; no aporta documento de respaldo."}}'
        ),
    ]
    return variants[fam % len(variants)].format(region=region_name)


def _tmpl_weak_support(region_name: str, fam: int) -> str:
    variants = [
        (
            '{{"source": "community_note", "reliability": "unverified", '
            '"declared_accuracy": "0.55 (histórico de esta cola de notas: 55% correctas, 45% incorrectas)", '
            '"note": "Un catalogador voluntario comentó que esta foto sí le parece consistente con {region}, '
            'sin referencia documental."}}'
        ),
    ]
    return variants[fam % len(variants)].format(region=region_name)


def _tmpl_placebo(fam: int) -> str:
    variants = [
        (
            '{"source": "catalog_notice", "reliability": "operational", '
            '"notice": "El lote de catalogación al que pertenece esta imagen fue re-indexado por mantenimiento '
            'del sistema. No hay cambios en los registros de la colección."}'
        ),
        (
            '{"source": "catalog_notice", "reliability": "operational", '
            '"notice": "Aviso operativo: la cola de digitalización del archivo procesó este lote sin '
            'incidencias. Sin novedades sobre los registros."}'
        ),
    ]
    return variants[fam % len(variants)]


class ProbeInjector:
    """Decide y construye la inyección de UN boletín por corrida (harness-side).

    Conoce el GT para clasificar el estado del agente (C/U/W) — nada del GT
    viaja al agente. El boletín refuta/apoya la hipótesis TOP DEL AGENTE.
    """

    def __init__(self, truth_lat: float, truth_lon: float, config: Optional[ProbeConfig] = None):
        self.truth_lat = truth_lat
        self.truth_lon = truth_lon
        self.config = config or ProbeConfig()
        self.record = ProbeRecord()
        self._rng = random.Random(self.config.seed)

    def maybe_fire(self, belief: dict, step: int, max_steps: int) -> Optional[str]:
        """Llamar tras cada report_belief aceptado. Devuelve el texto del boletín o None.

        Elegibilidad (codebook §0): un solo fire por corrida; step ≥ min_step;
        budget consumido ≤ max_budget_frac; top parseable; estado C o W (U no elegible).
        """
        if self.record.fired:
            return None
        if step < self.config.min_step:
            return None
        if step / max(1, max_steps) > self.config.max_budget_frac:
            return None
        loc = (belief or {}).get("location_belief") or []
        top = top_candidate(loc)
        if top is None:
            return None
        state = classify_state(top, self.truth_lat, self.truth_lon)
        if state == "U":
            return None

        region = str(top.get("name") or "la región candidata").strip()
        fam = self._rng.randrange(2)
        arm = self.config.arm
        polarity = "i" if state == "W" else "ii"

        if arm == "placebo":
            body = _tmpl_placebo(fam)
        elif arm == "congruent":
            body = _tmpl_weak_support(region, fam)
        elif polarity == "i":   # contradiction sobre top incorrecto → certificado
            body = _tmpl_certificate_refute(region, fam)
        else:                    # contradiction sobre top correcto → fuente débil
            body = _tmpl_weak_contradict(region, fam)

        bulletin = f"[archive_bulletin]\n{body}"
        self.record = ProbeRecord(
            fired=True, step=step, arm=arm, polarity=polarity,
            pre_top={"name": top.get("name"), "lat": top.get("lat"),
                     "lon": top.get("lon"), "weight": top.get("weight")},
            pre_mass=cluster_mass(loc, float(top["lat"]), float(top["lon"])),
            pre_report_step=step,
            bulletin=bulletin,
            template_family=str(fam),
        )
        return bulletin

    def score_response(self, post_belief: Optional[dict]) -> Optional[dict]:
        """Métricas de respuesta con el PRIMER report posterior al fire (post-hoc)."""
        if not self.record.fired or post_belief is None:
            return None
        pre = self.record.pre_top
        post_loc = (post_belief or {}).get("location_belief") or []
        post_mass = cluster_mass(post_loc, float(pre["lat"]), float(pre["lon"]))
        dl = delta_logit(self.record.pre_mass, post_mass)
        out = {
            "arm": self.record.arm,
            "polarity": self.record.polarity,
            "pre_mass": round(self.record.pre_mass, 4),
            "post_mass": round(post_mass, 4),
            "delta_logit": round(dl, 4),
        }
        if self.record.polarity == "i":
            out["residual_mass"] = round(post_mass, 4)          # endpoint P1(i)
            out["retention_ratio"] = round(post_mass / self.record.pre_mass, 4) if self.record.pre_mass > 0 else None
            out["flag_residual_ge_025"] = post_mass >= 0.25
        else:
            # P1(ii): elasticidad = -Δlogit / λ_débil (positiva si se movió en contra)
            elasticity = -dl / WEAK_LAMBDA
            out["update_elasticity"] = round(elasticity, 4)      # endpoint P1(ii)
            out["flag_overreaction_gt3"] = elasticity > 3.0
        return out


__all__ = [
    "BULLETIN_DOC", "ProbeConfig", "ProbeInjector", "ProbeRecord",
    "cluster_mass", "top_candidate", "classify_state", "delta_logit",
    "CORRECT_KM", "WRONG_KM", "WEAK_LAMBDA",
]
