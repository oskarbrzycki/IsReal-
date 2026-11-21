"""Pairwise correlation of incidents: weighted similarity over the signals available for BOTH sides.

score = sum(w_s * sim_s) / sum(w_s)   over signals where both incidents have data (CONTRACTS 6.3).
A pair needs at least `min_signals` comparable signals to become an edge at all.
"""
from __future__ import annotations

import itertools
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from fakecollector.core.models import Edge, Reason
from fakecollector.engine.similarity import compute, describe

log = logging.getLogger("fakecollector.engine")

LEVELS = ("campaign", "family")

DEFAULTS: dict[str, Any] = {
    "tau_campaign": 0.5, "tau_family": 0.4, "tau_new": 0.35, "tau_store": 0.2, "tau_dup": 0.95,
    "min_signals": 2, "min_signals_family": 1, "absence_discount": 1.0,
    "family_positive_only": False,
    "hard_identifiers": ["shared_trackers", "shared_har_trackers", "shared_ad_account",
                         "same_registered_domain", "shared_assets"], "signal_class": {},
    "default_weight": 1.0, "all_pairs_max": 200, "cluster_method": "louvain",
    "louvain_resolution": 1.0, "seed": 42, "top_k": 5, "weights": {}, "signal_params": {},
}


def engine_cfg(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Engine section of settings.yaml with defaults filled in."""
    section = (settings or {}).get("engine", {}) or {}
    cfg = dict(DEFAULTS)
    cfg.update(section)
    if "tau_campaign" not in section and "tau_edge" in section:   # legacy name (contract v0.3)
        cfg["tau_campaign"] = section["tau_edge"]
    cfg["weights"] = dict(section.get("weights", {}) or {})
    return cfg


RULE_SIGNAL = "regula_kampanii"       # pseudo-signal (weight 0) that explains a demotion to family level
RULE_TEXT = "za mało twardych dowodów na tę samą kampanię"


def _reasons(fa, fb, signals, cfg, classes, a_id="", b_id="", positive_only=False) -> list[Reason]:
    """Reasons for all comparable signals whose class is in `classes`.

    positive_only: a signal whose similarity is at/below its own `floor` is treated as missing instead of
    as a 0 in the weighted mean (used for the family level only, see `family_positive_only`)."""
    reasons: list[Reason] = []
    weights = cfg["weights"]
    for name, spec in signals.items():
        if spec.get("class", "campaign") not in classes:
            continue
        va, vb = fa.get(name), fb.get(name)
        if va is None or vb is None:
            continue
        try:
            sim, evidence = compute(spec, va, vb)
        except Exception as exc:  # one broken signal must not kill the pair
            log.warning("signal %s failed for %s~%s: %s", name, a_id, b_id, exc)
            continue
        if sim is None:
            continue
        if positive_only and evidence.get("below_floor"):
            continue            # weak evidence must not LOWER the score: below its floor = no data (None)
        w = float(weights.get(name, cfg["default_weight"]))
        if sim == 0.0 and spec["type"] in ("set_overlap", "exact"):
            # No shared identifier is only weak evidence AGAINST: pages of one campaign (a chain of
            # pages) often differ in domain or name. `absence_discount` = 1 is the plain contract formula.
            w *= float(cfg["absence_discount"])
        reasons.append(Reason(signal=name, score=round(float(sim), 4), weight=w,
                              detail=describe(name, spec, float(sim), evidence)))
    return reasons


def campaign_rule_ok(reasons: list[Reason], cfg: dict[str, Any]) -> bool:
    """A campaign edge needs >= 1 hard identifier match OR >= min_signals distinct campaign signals
    with positive similarity (CONTRACTS 6.4). A single soft signal (e.g. one near-duplicate image)
    is evidence of a family, not of one campaign."""
    positive = [r for r in reasons if r.score > 0]
    hard = set(cfg["hard_identifiers"])
    return any(r.signal in hard for r in positive) or len(positive) >= int(cfg["min_signals"])


def _edge(a_id: str, b_id: str, reasons: list[Reason]) -> Edge | None:
    den = sum(r.weight for r in reasons)
    if den <= 0:
        return None
    reasons = sorted(reasons, key=lambda r: r.weight * r.score, reverse=True)
    a, b = sorted((a_id, b_id))
    return Edge(a=a, b=b, score=round(sum(r.weight * r.score for r in reasons) / den, 4), reasons=reasons)


def score_pair(
    a_id: str, b_id: str,
    fa: dict[str, Any], fb: dict[str, Any],
    signals: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    level: str = "campaign",
    relaxed: bool = False,
) -> Edge | None:
    """Combined score and explanation for one pair at one level; None if there is no edge.

    relaxed=True skips the edge rules (hard-evidence rule, min signals): it only answers "how close
    is this pair anyway?", used by assign() to explain a "new campaign" verdict. Never used for clustering.

    level="campaign": signals of class campaign; the edge exists only if `campaign_rule_ok`.
    level="family":   signals of class family. If the pair has campaign-class matches but fails the
                      campaign rule they are demoted into this family edge, with a `regula_kampanii`
                      reason saying why they did not make a campaign edge.
    """
    if level == "campaign":
        reasons = _reasons(fa, fb, signals, cfg, {"campaign"}, a_id, b_id)
        if not relaxed and not campaign_rule_ok(reasons, cfg):
            return None
        return _edge(a_id, b_id, reasons)

    reasons = _reasons(fa, fb, signals, cfg, {"family"}, a_id, b_id,
                       positive_only=bool(cfg.get("family_positive_only")))
    camp = _reasons(fa, fb, signals, cfg, {"campaign"}, a_id, b_id)
    positive = [r for r in camp if r.score > 0]
    note = []
    if positive and not campaign_rule_ok(camp, cfg):
        reasons += positive
        note = [Reason(signal=RULE_SIGNAL, score=0.0, weight=0.0,
                       detail=f"{RULE_TEXT} (tylko: {', '.join(r.signal for r in positive)}) - "
                              "powiązanie na poziomie rodziny, nie kampanii")]
    if len(reasons) < (1 if relaxed else int(cfg["min_signals_family"])):
        return None
    edge = _edge(a_id, b_id, reasons)
    if edge is not None:
        edge.reasons += note
    return edge


# --------------------------------------------------------------------------- candidate pairs
def _band_keys(sig: np.ndarray, bands: int = 16) -> Iterable[tuple[int, bytes]]:
    rows = max(1, len(sig) // bands)
    for i in range(bands):
        chunk = sig[i * rows:(i + 1) * rows]
        if len(chunk):
            yield i, chunk.tobytes()


def candidate_pairs(
    features: dict[str, dict[str, Any]],
    signals: dict[str, dict[str, Any]],
    all_pairs_max: int = 200,
) -> set[tuple[str, str]]:
    """All pairs for small n; otherwise blocking on shared exact/set elements, MinHash bands and
    identical hashes (cosine-only neighbours are not found by blocking - add ANN here if needed)."""
    ids = sorted(features)
    if len(ids) <= all_pairs_max:
        return set(itertools.combinations(ids, 2))
    index: dict[tuple, list[str]] = {}
    for inc in ids:
        for name, spec in signals.items():
            val = features[inc].get(name)
            if val is None:
                continue
            t = spec["type"]
            if t in ("set_overlap", "exact"):
                keys = [(name, x) for x in val]
            elif t == "hamming_hash":
                keys = [(name, h >> 48) for h in val]           # top 16 bits as a coarse bucket
            elif t == "jaccard_minhash":
                keys = [(name, "set", x) for x in val["set"]]
                for sig in val["sigs"]:
                    keys += [(name, i, k) for i, k in _band_keys(sig)]
            else:
                continue
            for k in keys:
                index.setdefault(k, []).append(inc)
    pairs: set[tuple[str, str]] = set()
    for members in index.values():
        uniq = sorted(set(members))
        if len(uniq) > 200:       # key shared by a huge share of the corpus carries no information
            continue
        pairs.update(itertools.combinations(uniq, 2))
    return pairs


def compute_edges(
    features: dict[str, dict[str, Any]],
    signals: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    level: str = "campaign",
) -> list[Edge]:
    """Score all candidate pairs at `level`, keep edges with score >= tau_store."""
    level_signals = {n: s for n, s in signals.items() if s.get("class", "campaign") == level}
    edges: list[Edge] = []
    for a, b in sorted(candidate_pairs(features, level_signals, int(cfg["all_pairs_max"]))):
        e = score_pair(a, b, features[a], features[b], signals, cfg, level)
        if e is not None and e.score >= float(cfg["tau_store"]):
            edges.append(e)
    return edges


# --------------------------------------------------------------------------- persistence
def edges_to_frame(edges: list[Edge], level: str = "campaign") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "level": [level] * len(edges),
            "a": [e.a for e in edges],
            "b": [e.b for e in edges],
            "score": [e.score for e in edges],
            "n_signals": [len(e.reasons) for e in edges],
            "reasons": [json.dumps([asdict(r) for r in e.reasons], ensure_ascii=False) for e in edges],
        }
    )


def frame_to_edges(df: pd.DataFrame) -> list[Edge]:
    return [
        Edge(a=r.a, b=r.b, score=float(r.score), reasons=[Reason(**x) for x in json.loads(r.reasons)])
        for r in df.itertuples(index=False)
    ]


def save_edges(edges_by_level: dict[str, list[Edge]], path: Path) -> None:
    """edges.parquet holds both levels, told apart by the `level` column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = [edges_to_frame(e, lvl) for lvl, e in edges_by_level.items()]
    pd.concat(frames, ignore_index=True).to_parquet(path, index=False)


def load_edges(path: Path, level: str | None = None) -> list[Edge]:
    df = pd.read_parquet(path)
    if level is not None:
        df = df[df["level"] == level]
    return frame_to_edges(df)
