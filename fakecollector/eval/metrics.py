"""Clustering metrics against ground-truth labels (pairwise P/R/F1, ARI)."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

import yaml
from sklearn.metrics import adjusted_rand_score


def load_labels(path: Path) -> dict[str, str]:
    """eval/labels.yaml -> {incident_id: campaign label}; every singleton gets its own label."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    truth: dict[str, str] = {}
    for camp, members in (data.get("campaigns") or {}).items():
        for m in members:
            truth[str(m)] = str(camp)
    for s in data.get("singletons") or []:
        truth.setdefault(str(s), f"S:{s}")
    return truth


def load_family_labels(path: Path, truth: dict[str, str]) -> dict[str, str]:
    """Family-level ground truth from the `families:` section of labels.yaml.

    Incidents outside every listed family are their own family (`F:<incident>`). Without a
    `families:` section the family truth equals the campaign truth.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    fams = data.get("families")
    if not fams:
        return dict(truth)
    out: dict[str, str] = {}
    for fam, members in fams.items():
        for m in members:
            out[str(m)] = f"F:{fam}"
    for inc in truth:
        out.setdefault(inc, f"F:{inc}")
    return out


def base_id(incident_id: str) -> str:
    """Pseudo-incidents are named '<incident>#<part>' - strip the part."""
    return incident_id.split("#", 1)[0]


def pairwise_prf(true: dict[str, str], pred: dict[str, str]) -> dict[str, Any]:
    """Pairwise precision/recall/F1 and ARI over items present in both labelings."""
    items = sorted(set(true) & set(pred))
    tp = fp = fn = 0
    for a, b in combinations(items, 2):
        same_t = true[a] == true[b]
        same_p = pred[a] == pred[b]
        tp += same_t and same_p
        fp += (not same_t) and same_p
        fn += same_t and (not same_p)
    p = tp / (tp + fp) if tp + fp else 1.0     # no predicted pairs -> nothing wrongly merged
    r = tp / (tp + fn) if tp + fn else 1.0     # no true pairs -> nothing missed
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    ari = adjusted_rand_score([true[i] for i in items], [pred[i] for i in items]) if len(items) > 1 else 1.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            "ari": round(float(ari), 4), "n": len(items), "tp": tp, "fp": fp, "fn": fn}


def error_pairs(true: dict[str, str], pred: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """Wrongly merged (fp) and wrongly separated (fn) pairs - for the error analysis section."""
    items = sorted(set(true) & set(pred))
    fp, fn = [], []
    for a, b in combinations(items, 2):
        same_t, same_p = true[a] == true[b], pred[a] == pred[b]
        if same_p and not same_t:
            fp.append((a, b))
        elif same_t and not same_p:
            fn.append((a, b))
    return {"false_merge": fp, "false_split": fn}
