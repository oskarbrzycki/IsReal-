"""Weight sensitivity analysis and an informational logistic-regression check (W5).

Neither replaces the hand-set weights: with ~45 incident pairs (4 same-campaign, 10 same-family)
there is far too little data to learn weights, so both are diagnostics only.
"""
from __future__ import annotations

from itertools import combinations
from typing import Any

import numpy as np

from fakecollector.engine.similarity import compute
from fakecollector.eval import experiments as ex


def active_signals(feats: dict[str, dict[str, Any]], signals: dict[str, dict[str, Any]]) -> list[str]:
    """Signals that have a value for at least two incidents (otherwise they cannot matter)."""
    return [n for n in signals if sum(n in f for f in feats.values()) >= 2]


def weight_sensitivity(feats, signals, cfg, truth, family_truth, factors=(0.5, 1.5)) -> list[dict[str, Any]]:
    """Scale each weight by each factor (one at a time); report F1 on both levels.

    Rows are sorted by the largest absolute F1 change, i.e. by how much the result depends on
    that weight. A flat row means the weight is not what decides the grouping on these samples.
    """
    base, _ = ex.cluster_eval(feats, signals, cfg, truth, family_truth=family_truth)
    rows = []
    for name in active_signals(feats, signals):
        w0 = float(cfg["weights"].get(name, cfg["default_weight"]))
        row: dict[str, Any] = {"signal": name, "class": signals[name]["class"], "w": w0}
        worst = 0.0
        for f in factors:
            cfg2 = {**cfg, "weights": {**cfg["weights"], name: w0 * f}}
            m, _ = ex.cluster_eval(feats, signals, cfg2, truth, family_truth=family_truth)
            dc, df = round(m["f1"] - base["f1"], 3), round(m["fam_f1"] - base["fam_f1"], 3)
            row[f"dF1_camp x{f}"], row[f"dF1_fam x{f}"] = dc, df
            worst = max(worst, abs(dc), abs(df))
        row["max_abs_dF1"] = round(worst, 3)
        rows.append(row)
    rows.sort(key=lambda r: (-r["max_abs_dF1"], r["signal"]))
    return rows


def pair_matrix(feats, signals, names) -> tuple[list[tuple[str, str]], np.ndarray]:
    """Similarity of every incident pair on every signal (0 where it cannot be compared)."""
    ids = sorted(feats)
    pairs = list(combinations(ids, 2))
    X = np.zeros((len(pairs), len(names)))
    for i, (a, b) in enumerate(pairs):
        for j, n in enumerate(names):
            sim, _ = compute(signals[n], feats[a].get(n), feats[b].get(n))
            X[i, j] = 0.0 if sim is None else sim
    return pairs, X


def logistic_check(feats, signals, cfg, truth, family_truth) -> dict[str, Any]:
    """L2 logistic regression 'same campaign?' / 'same family?' on pair similarities.

    Informational only: confirms the DIRECTION of the manual weights (positive coefficient = the signal
    helps), it does not set them. Coefficients are not comparable across levels or with weights.
    """
    from sklearn.linear_model import LogisticRegression

    names = active_signals(feats, signals)
    pairs, X = pair_matrix(feats, signals, names)
    out: dict[str, Any] = {"n_pairs": len(pairs), "signals": names, "levels": {}}
    for level, labels in (("campaign", truth), ("family", family_truth)):
        y = np.array([int(labels.get(a) is not None and labels.get(a) == labels.get(b)) for a, b in pairs])
        info: dict[str, Any] = {"n_pos": int(y.sum())}
        if y.sum() == 0 or y.sum() == len(y):
            out["levels"][level] = {**info, "note": "no positive/negative pairs"}
            continue
        clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000).fit(X, y)
        info["coef"] = {n: round(float(c), 3) for n, c in zip(names, clf.coef_[0])}
        info["train_accuracy"] = round(float(clf.score(X, y)), 3)
        out["levels"][level] = info
    return out


def direction_table(check: dict[str, Any], signals, cfg) -> list[dict[str, Any]]:
    """Manual weight next to the logistic coefficient sign per level."""
    rows = []
    for n in check["signals"]:
        row: dict[str, Any] = {"signal": n, "class": signals[n]["class"],
                               "w": cfg["weights"].get(n, cfg["default_weight"])}
        for level in ("campaign", "family"):
            c = check["levels"].get(level, {}).get("coef", {}).get(n)
            row[f"coef_{level}"] = "" if c is None else c
        rows.append(row)
    return rows
