"""Assign a NEW incident to a known campaign / family or declare it a new pattern (CONTRACTS 6.6).

Outcomes (`status`):
  known_campaign             best campaign-level neighbours >= tau_new  -> campaign_id (+ its family)
  new_campaign_known_family  no campaign matches, but family-class signals reach tau_family
                             -> campaign_id None, family_id X ("nowa kampania, ale pasuje do rodziny X")
  new_family                 compared, nothing matches (open set: a genuinely new pattern)
  insufficient_data          too little comparable data to judge either level

Every outcome carries `nearest` (top-k closest known incidents WITH reasons, never empty when anything
was comparable) and `reason`, a one-line Polish justification the UI can show as it is.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fakecollector.core.models import Assignment, Cluster, Edge
from fakecollector.engine.correlate import score_pair


@dataclass
class FamilyAssignment(Assignment):
    """`Assignment` (contract) plus the family level. Still usable wherever Assignment is expected.

    family_confidence is the score backing `family_id` and is 0.0 whenever family_id is None
    (so the two can never disagree). `closest_*` always describe the best neighbour found.
    """
    family_id: str | None = None
    family_confidence: float = 0.0
    status: str = "insufficient_data"
    family_nearest: list[Edge] = field(default_factory=list)
    reason: str = ""
    closest_id: str | None = None
    closest_score: float | None = None
    closest_level: str | None = None            # "campaign" | "family" | "luźne" (relaxed comparison)


def _neighbours(new_features, known_features, signals, cfg, incident_id, level, relaxed=False) -> list[Edge]:
    edges = []
    for other, feats in known_features.items():
        if other == incident_id:
            continue
        e = score_pair(incident_id, other, new_features, feats, signals, cfg, level, relaxed)
        if e is not None:
            edges.append(e)
    edges.sort(key=lambda e: e.score, reverse=True)
    return edges


def _other(e: Edge, incident_id: str) -> str:
    return e.b if e.a == incident_id else e.a


def _vote(edges: list[Edge], incident_id: str, owner: dict[str, str], threshold: float, k: int
          ) -> tuple[str | None, float]:
    """Group with the highest summed score among the top-k neighbours >= threshold."""
    votes: dict[str, float] = defaultdict(float)
    best: dict[str, float] = defaultdict(float)
    for e in edges[:k]:
        if e.score < threshold:
            continue
        group = owner.get(_other(e, incident_id))
        if group is None:
            continue
        votes[group] += e.score
        best[group] = max(best[group], e.score)
    if not votes:
        return None, 0.0
    winner = max(votes, key=lambda g: (votes[g], best[g]))
    return winner, best[winner]


def _fmt(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def assign(
    new_features: dict[str, Any],
    known_features: dict[str, dict[str, Any]],
    clusters: list[Cluster],
    signals: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    incident_id: str = "upload:new",
    families: dict[str, str] | None = None,
) -> FamilyAssignment:
    """Compare `new_features` (aggregated, signal -> value) with all known incidents.

    families: campaign_id -> family_id (from the clustering run). Without it only the campaign
    level is evaluated and family_id stays None.

    confidence: score of the best neighbour in the chosen campaign; for "new" it is 1 - best campaign
    score (0.0 when nothing was comparable). family_confidence: score backing family_id, else 0.0.
    """
    families = families or {}
    k = int(cfg["top_k"])
    tau_new, tau_fam = float(cfg["tau_new"]), float(cfg["tau_family"])
    camp_owner = {m: c.campaign_id for c in clusters for m in c.members}
    camp_edges = _neighbours(new_features, known_features, signals, cfg, incident_id, "campaign")
    fam_edges = _neighbours(new_features, known_features, signals, cfg, incident_id, "family")

    campaign, conf = _vote(camp_edges, incident_id, camp_owner, tau_new, k)
    if campaign is not None:
        top = camp_edges[0]
        return FamilyAssignment(
            incident_id=incident_id, campaign_id=campaign, confidence=round(conf, 4), nearest=camp_edges[:k],
            family_id=families.get(campaign), family_confidence=round(conf, 4) if families.get(campaign) else 0.0,
            status="known_campaign", family_nearest=fam_edges[:k],
            reason=f"najbliższy znany incydent {_other(top, incident_id)}: wynik {_fmt(top.score)} "
                   f">= próg {_fmt(tau_new)}, kampania {campaign}",
            closest_id=_other(top, incident_id), closest_score=top.score, closest_level="campaign")

    # no campaign matches. Neighbours to show: strict campaign edges, else family edges, else a loose comparison.
    family, fam_conf = _vote(fam_edges, incident_id,
                             {m: families[cid] for m, cid in camp_owner.items() if cid in families}, tau_fam, k)
    loose: list[Edge] = []
    if not camp_edges and not fam_edges:
        loose = _neighbours(new_features, known_features, signals, cfg, incident_id, "campaign", relaxed=True)
        if not loose:
            loose = _neighbours(new_features, known_features, signals, cfg, incident_id, "family", relaxed=True)
    shown, level = (camp_edges, "campaign") if camp_edges else (fam_edges, "family") if fam_edges else (loose, "luźne")
    nearest = shown[:k]

    if not nearest:
        return FamilyAssignment(incident_id=incident_id, campaign_id=None, confidence=0.0, nearest=[],
                                status="insufficient_data",
                                reason="za mało danych do porównania: żaden sygnał nie ma odpowiednika "
                                       "w znanych incydentach")
    top = nearest[0]
    closest = _other(top, incident_id)
    camp_best = camp_edges[0].score if camp_edges else 0.0
    base = dict(incident_id=incident_id, campaign_id=None, confidence=round(1.0 - camp_best, 4), nearest=nearest,
                family_nearest=fam_edges[:k], closest_id=closest, closest_score=top.score, closest_level=level)

    if family is not None:
        return FamilyAssignment(
            **base, family_id=family, family_confidence=round(fam_conf, 4), status="new_campaign_known_family",
            reason=f"nowa kampania: najbliższy znany incydent {closest}, wynik kampanii {_fmt(camp_best)} "
                   f"< próg {_fmt(tau_new)}; pasuje do rodziny {family} (wynik rodziny {_fmt(fam_conf)} "
                   f">= próg {_fmt(tau_fam)})")
    fam_best = fam_edges[0].score if fam_edges else 0.0
    if camp_best >= tau_new:       # close enough, but the neighbours belong to no known campaign
        return FamilyAssignment(
            **base, family_id=None, family_confidence=0.0, status="new_family",
            reason=f"najbliższy znany incydent {closest}: wynik {_fmt(top.score)} >= próg {_fmt(tau_new)}, ale nie "
                   "należy do żadnej znanej kampanii (brak zapisanego grupowania: uruchom `correlate`)")
    loose_note = "" if camp_edges or fam_edges else " (porównanie luźne: za mało twardych dowodów na krawędź)"
    return FamilyAssignment(
        **base, family_id=None, family_confidence=0.0, status="new_family",
        reason=f"nowy wzorzec: najbliższy znany incydent {closest}: wynik {_fmt(top.score)}{loose_note}; "
               f"kampania {_fmt(camp_best)} < próg {_fmt(tau_new)}, rodzina {_fmt(fam_best)} < próg {_fmt(tau_fam)}")
