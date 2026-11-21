"""Evaluation experiments (CONTRACTS section 9). All work on aggregated incident features."""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

import pandas as pd

from fakecollector.engine import cluster as cl
from fakecollector.engine.assign import assign
from fakecollector.engine.features import aggregate_incidents, sources_of
from fakecollector.engine.pipeline import Result, run
from fakecollector.eval.metrics import base_id, error_pairs, pairwise_prf

# Signals that fire on byte-identical files - the working labels were found with exactly this kind
# of evidence, so results WITHOUT them are the honest ones (contract 9.1).
CIRCULAR_SIGNALS = {"shared_assets", "same_material"}


def _truth_for(items, truth: dict[str, str]) -> dict[str, str]:
    return {i: truth[base_id(i)] for i in items if base_id(i) in truth}


def cluster_eval(feats, signals, cfg, truth, method: str | None = None, materials=None,
                 family_truth: dict[str, str] | None = None) -> tuple[dict[str, Any], Result]:
    """Run the pipeline and score campaigns (and families, if `family_truth` is given).

    Pseudo-incident ids ('<incident>#<part>') are mapped back to their original incident.
    Family metrics are returned under the `fam_` prefix.
    """
    res = run(feats, signals, cfg, materials, method)
    pred = cl.labels_of(res.clusters)
    metrics = pairwise_prf(_truth_for(pred, truth), pred)
    metrics["n_clusters"] = len(res.clusters)
    metrics["n_edges"] = sum(e.score >= cfg["tau_campaign"] for e in res.edges)
    if family_truth is not None:
        fpred = cl.family_labels_of(res.clusters, res.families)
        fm = pairwise_prf(_truth_for(fpred, family_truth), fpred)
        metrics.update({f"fam_{k}": v for k, v in fm.items()})
        metrics["n_families"] = len(res.families)
    return metrics, res


def without_signals(signals: dict[str, dict[str, Any]], drop: set[str]) -> dict[str, dict[str, Any]]:
    return {n: s for n, s in signals.items() if n not in drop}


def without_module(signals: dict[str, dict[str, Any]], module: str) -> dict[str, dict[str, Any]]:
    """Remove one feature module; a signal fed by several modules keeps its other sources."""
    out = {}
    for n, s in signals.items():
        left = [src for src in sources_of(s) if src["module"] != module]
        if left:
            out[n] = {**s, "sources": left}
    return out


def modules_of(signals: dict[str, dict[str, Any]]) -> list[str]:
    return sorted({src["module"] for s in signals.values() for src in sources_of(s)})


def ablation(feats, signals, cfg, truth, family_truth=None) -> list[dict[str, Any]]:
    """Baseline, leave-one-module-out, and 'no identical-file signals' variants (both levels)."""
    rows = []
    base, _ = cluster_eval(feats, signals, cfg, truth, family_truth=family_truth)
    rows.append({"variant": "all signals", **base})
    for module in modules_of(signals):
        m, _ = cluster_eval(feats, without_module(signals, module), cfg, truth, family_truth=family_truth)
        rows.append({"variant": f"without module: {module}", **m})
    sub = without_signals(signals, CIRCULAR_SIGNALS)
    m, _ = cluster_eval(feats, sub, cfg, truth, family_truth=family_truth)
    rows.append({"variant": "without identical-file signals (shared_assets, same_material)", **m})
    return rows


def threshold_sweep(feats, signals, cfg, truth, family_truth=None, key: str = "tau_campaign",
                    taus=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8)) -> list[dict[str, Any]]:
    """Sweep one threshold (`tau_campaign` or `tau_family`) and score both levels."""
    rows = []
    for tau in taus:
        m, _ = cluster_eval(feats, signals, {**cfg, key: tau}, truth, family_truth=family_truth)
        rows.append({key: tau, **m})
    return rows


def method_comparison(feats, signals, cfg, truth) -> list[dict[str, Any]]:
    rows = []
    for method in ("louvain", "hdbscan"):
        try:
            m, _ = cluster_eval(feats, signals, cfg, truth, method=method)
        except Exception as exc:  # e.g. too few points for HDBSCAN
            rows.append({"method": method, "error": str(exc)})
            continue
        rows.append({"method": method, **m})
    return rows


def dropout(feats, signals, cfg, truth, p: float = 0.3, trials: int = 20, seed: int = 0) -> dict[str, Any]:
    """Randomly blank whole modalities of single incidents (dead page, no HAR, no image...).

    Reproducible: fixed seed AND a fixed iteration order (sorted incidents and modules), so the result
    does not depend on dict/set ordering, Python hash randomization or the order in which files were read.
    """
    rng = random.Random(seed)
    by_module: dict[str, list[str]] = defaultdict(list)
    for n in sorted(signals):
        by_module[signals[n].get("module")].append(n)        # primary module of the signal
    modules = sorted(by_module, key=str)
    f1s, aris = [], []
    for _ in range(trials):
        degraded = {}
        for inc in sorted(feats):
            gone = {n for mod in modules if rng.random() < p for n in by_module[mod]}
            degraded[inc] = {k: v for k, v in feats[inc].items() if k not in gone}
        m, _ = cluster_eval(degraded, signals, cfg, truth)
        f1s.append(m["f1"])
        aris.append(m["ari"])
    return {"p": p, "trials": trials, "seed": seed, "f1_mean": round(sum(f1s) / len(f1s), 4),
            "f1_min": round(min(f1s), 4), "ari_mean": round(sum(aris) / len(aris), 4)}


def pseudo_variants(tables, signals, stoplist, cfg, truth, material_parts: dict[str, str] | None = None
                    ) -> dict[str, Any]:
    """Split multi-part incidents (e.g. a 3-page chain, two saves of one page) into pseudo-incidents.

    Every part keeps only its own material-level features (incident-level data such as HAR is
    dropped, otherwise it would trivially glue the parts back together). The parts inherit the
    label of the original incident; a good method regroups them with their campaign mates.
    """
    parts_of: dict[str, set[str]] = defaultdict(set)

    def part_key(rec) -> str:
        mid = str(rec["entity_id"]).split("#", 1)[0]       # video frames "<id>#f3" belong to their file
        return (material_parts or {}).get(mid, mid)

    for df in tables.values():
        for rec in df.to_dict("records"):
            if rec.get("level") == "material" and isinstance(rec.get("incident_id"), str):
                parts_of[rec["incident_id"]].add(part_key(rec))
    split = {i for i, p in parts_of.items() if len(p) >= 2 and i in truth}
    if not split:
        return {"n_split_incidents": 0, "note": "no incident has >= 2 separable parts"}

    def group_fn(rec):
        inc = rec["incident_id"]
        if inc not in split:
            return inc
        if rec.get("level") != "material":
            return None
        return f"{inc}#{part_key(rec)}"

    feats = aggregate_incidents(tables, signals, stoplist, group_fn=group_fn)
    feats = {i: f for i, f in feats.items() if f}          # parts without any usable signal vanish
    m, res = cluster_eval(feats, signals, cfg, truth)
    pred = cl.labels_of(res.clusters)
    # sibling recall: share of part pairs of the same original incident that ended up together
    pairs = [(a, b) for a in pred for b in pred if a < b and base_id(a) == base_id(b) and "#" in a + b]
    together = sum(pred[a] == pred[b] for a, b in pairs)
    return {"n_split_incidents": len(split), "n_pseudo_incidents": sum("#" in i for i in feats),
            "sibling_pairs": len(pairs), "sibling_recall": round(together / len(pairs), 4) if pairs else None,
            **{k: m[k] for k in ("precision", "recall", "f1", "ari")}}


def open_set(feats, signals, cfg, truth, family_truth=None) -> dict[str, Any]:
    """Two open-set protocols.

    LOCO (leave-one-campaign-out): remove a whole campaign from the known set; its incidents must be
    reported as NEW (campaign_id None). LOO (leave-one-incident-out): remove one incident; if it has
    campaign mates it must land in a cluster holding a mate, a true singleton must come out as NEW.
    """
    ids = sorted(i for i in feats if i in truth)
    members: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        members[truth[i]].append(i)

    loco_total = loco_new = fam_total = fam_hit = 0
    for camp, mem in members.items():
        if len(mem) < 2:
            continue
        known = {i: f for i, f in feats.items() if i not in mem}
        res = run(known, signals, cfg)
        fam_of_inc = cl.family_labels_of(res.clusters, res.families)
        for m in mem:
            a = assign(feats[m], known, res.clusters, signals, cfg, m, res.family_of)
            loco_total += 1
            loco_new += a.campaign_id is None
            if family_truth is not None:
                # the removed campaign has relatives (same TRUE family) that stayed in the known set
                relatives = {k for k in known if k in family_truth and family_truth[k] == family_truth[m]}
                if relatives:
                    fam_total += 1
                    fam_hit += a.campaign_id is None and a.family_id in {fam_of_inc.get(r) for r in relatives}

    multi_ok = multi_total = single_ok = single_total = 0
    for i in ids:
        known = {k: f for k, f in feats.items() if k != i}
        res = run(known, signals, cfg)
        a = assign(feats[i], known, res.clusters, signals, cfg, i, res.family_of)
        mates = {m for m in members[truth[i]] if m != i}
        if mates:
            good = {c.campaign_id for c in res.clusters if mates & set(c.members)}
            multi_total += 1
            multi_ok += a.campaign_id in good
        else:
            single_total += 1
            single_ok += a.campaign_id is None
    rate = lambda a, b: round(a / b, 4) if b else None
    return {"loco_new_rate": rate(loco_new, loco_total), "loco_n": loco_total,
            "loco_family_hit_rate": rate(fam_hit, fam_total), "loco_family_n": fam_total,
            "loo_assign_accuracy": rate(multi_ok, multi_total), "loo_assign_n": multi_total,
            "loo_singleton_new_rate": rate(single_ok, single_total), "loo_singleton_n": single_total}


def errors(res: Result, truth: dict[str, str]) -> dict[str, list]:
    """False merges / splits with the strongest reasons (signal names only - no data content)."""
    pred = cl.labels_of(res.clusters)
    err = error_pairs(_truth_for(pred, truth), pred)
    by_pair = {(e.a, e.b): e for e in res.edges}
    out = {}
    for kind, pairs in err.items():
        rows = []
        for a, b in pairs:
            e = by_pair.get(tuple(sorted((a, b))))
            rows.append({"a": a, "b": b, "score": e.score if e else None,
                         "top_signals": [r.signal for r in e.reasons[:3]] if e else []})
        out[kind] = rows
    return out


def edge_table(res: Result, limit: int = 15, level: str = "campaign") -> pd.DataFrame:
    edges = res.edges if level == "campaign" else res.family_edges
    top = sorted(edges, key=lambda e: e.score, reverse=True)[:limit]
    return pd.DataFrame([{"a": e.a, "b": e.b, "score": e.score,
                          "signals": ", ".join(r.signal for r in e.reasons if r.score > 0)[:80]} for e in top])


def family_variant_check(feats, signals, cfg, truth, family_truth) -> dict[str, Any]:
    """Compare the family level with and without `family_positive_only` (signals below their floor = None).

    Acceptance conditions for making the variant the default: family precision stays 1.0, open-set
    new-campaign rate stays 100%, singletons stay 100% "new", no family edge appears that links incidents
    of different TRUE families which the current method did not draw, and campaign edges are unchanged.
    """
    runs: dict[str, dict[str, Any]] = {}
    for name, flag in (("current", False), ("positive_only", True)):
        c = {**cfg, "family_positive_only": flag}
        res = run(feats, signals, c)
        fpred = cl.family_labels_of(res.clusters, res.families)
        m = pairwise_prf(_truth_for(fpred, family_truth), fpred)
        edges = {(e.a, e.b) for e in res.family_edges if e.score >= c["tau_family"]}
        o = open_set(feats, signals, c, truth, family_truth)
        runs[name] = {
            "family_precision": m["precision"], "family_recall": m["recall"], "family_f1": m["f1"],
            "family_ari": m["ari"], "n_families": len(res.families), "n_family_edges": len(edges),
            "false_family_edges": sorted(p for p in edges if family_truth.get(p[0]) != family_truth.get(p[1])),
            "loco_new_rate": o["loco_new_rate"], "loco_family_hit_rate": o["loco_family_hit_rate"],
            "singleton_new_rate": o["loo_singleton_new_rate"], "loo_assign_accuracy": o["loo_assign_accuracy"],
            "campaign_edges": sorted((e.a, e.b, e.score) for e in res.edges),
        }
    cur, pos = runs["current"], runs["positive_only"]
    cond = {
        "family_precision_1.0": pos["family_precision"] == 1.0,
        "open_set_new_rate_100%": pos["loco_new_rate"] == 1.0,
        "singletons_100%": pos["singleton_new_rate"] == 1.0,
        "no_new_false_family_edges": not (set(map(tuple, pos["false_family_edges"])) - set(map(tuple, cur["false_family_edges"]))),
        "campaign_edges_unchanged": pos["campaign_edges"] == cur["campaign_edges"],
    }
    for r in runs.values():
        r.pop("campaign_edges")
    return {"current": cur, "positive_only": pos, "conditions": cond, "conditions_met": all(cond.values())}
