"""End-to-end engine pipeline: features -> edges -> duplicates -> clusters (+ state on disk)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from fakecollector.core.config import make_context, resolve_path
from fakecollector.core.models import Cluster, Context, Edge
from fakecollector.engine import cluster as cl
from fakecollector.engine import correlate as co
from fakecollector.engine.features import (aggregate_incidents, collect_signals, load_feature_tables,
                                           normalize_signals)

log = logging.getLogger("fakecollector.engine")

DUP_KINDS = {"html", "mhtml", "image", "video"}   # pages/creatives; assets are NOT duplicates


@dataclass
class Result:
    features: dict[str, dict[str, Any]]
    signals: dict[str, dict[str, Any]]
    edges: list[Edge]                    # campaign-level edges (class "campaign" signals)
    clusters: list[Cluster]
    duplicate_groups: list[list[str]] = field(default_factory=list)
    cfg: dict[str, Any] = field(default_factory=dict)
    family_edges: list[Edge] = field(default_factory=list)   # family-level edges (class "family")
    families: list[cl.Family] = field(default_factory=list)

    @property
    def family_of(self) -> dict[str, str]:
        """campaign_id -> family_id"""
        return cl.family_of_campaign(self.families)


# --------------------------------------------------------------------------- incidents index (W1 output)
def load_incident_index(interim_dir: Path) -> tuple[dict[str, str], dict[str, set[str]], list[str]]:
    """Read W1's incidents file (jsonl, or parquet fallback).

    Returns (material_id -> incident_id, incident -> duplicate-relevant material ids, all incident ids).
    Missing file = empty result (engine then works from the feature tables alone).
    """
    records: list[dict[str, Any]] = []
    jsonl = interim_dir / "incidents.jsonl"
    parquet = interim_dir / "incidents.parquet"
    try:
        if jsonl.exists():
            records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        elif parquet.exists():
            records = pd.read_parquet(parquet).to_dict("records")
    except Exception as exc:
        log.warning("cannot read incidents index: %s", exc)
    mat_to_inc: dict[str, str] = {}
    dup_mats: dict[str, set[str]] = {}
    for inc in records:
        iid = inc.get("incident_id")
        mats = inc.get("materials") or []
        dup_mats[iid] = set()
        for m in mats:
            mat_to_inc.setdefault(m["material_id"], iid)
            if m.get("kind") in DUP_KINDS and not m.get("is_common_lib"):
                dup_mats[iid].add(m["material_id"])
    return mat_to_inc, dup_mats, [r.get("incident_id") for r in records if r.get("incident_id")]


# --------------------------------------------------------------------------- core run
def run(
    features: dict[str, dict[str, Any]],
    signals: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    incident_materials: dict[str, set[str]] | None = None,
    method: str | None = None,
) -> Result:
    """In-memory pipeline (also used by the evaluation experiments)."""
    edges = co.compute_edges(features, signals, cfg, "campaign")
    family_edges = co.compute_edges(features, signals, cfg, "family")
    dups = cl.duplicate_groups(features, edges, float(cfg["tau_dup"]), incident_materials)
    clusters = cl.build_clusters(features, edges, features, signals, cfg, dups, method)
    families = cl.build_families(clusters, family_edges, features, signals, cfg)
    return Result(features=features, signals=signals, edges=edges, clusters=clusters,
                  duplicate_groups=dups, cfg=cfg, family_edges=family_edges, families=families)


def load_features(ctx: Context, signals: dict[str, dict[str, Any]] | None = None
                  ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, set[str]]]:
    """Aggregate data/features/*.parquet to incident level.

    Returns (incident features, signals, duplicate-relevant materials per incident).
    """
    cfg = co.engine_cfg(ctx.settings)
    signals = normalize_signals(signals, cfg["signal_params"], cfg["signal_class"]) if signals is not None \
        else collect_signals(cfg["signal_params"], classes=cfg["signal_class"])
    tables = load_feature_tables(resolve_path(ctx, "features"))
    mat_to_inc, dup_mats, incident_ids = load_incident_index(resolve_path(ctx, "interim"))
    feats = aggregate_incidents(tables, signals, ctx.settings.get("stoplist"), mat_to_inc, extra_ids=incident_ids)
    return feats, signals, dup_mats


def run_from_disk(ctx: Context | None = None, signals: dict[str, dict[str, Any]] | None = None,
                  method: str | None = None, write: bool = True) -> Result:
    """`python -m fakecollector correlate`: read feature parquets, write edges + clusters."""
    ctx = ctx or make_context()
    cfg = co.engine_cfg(ctx.settings)
    feats, signals, dup_mats = load_features(ctx, signals)
    if not feats:
        log.warning("no incidents found - are there parquet files in %s?", resolve_path(ctx, "features"))
    result = run(feats, signals, cfg, dup_mats, method)
    if write:
        graph = resolve_path(ctx, "graph")
        co.save_edges({"campaign": result.edges, "family": result.family_edges}, graph / "edges.parquet")
        cl.save_clusters(result.clusters, result.duplicate_groups, graph / "clusters.json",
                         {"tau_campaign": cfg["tau_campaign"], "tau_family": cfg["tau_family"],
                          "tau_new": cfg["tau_new"], "method": method or cfg["cluster_method"],
                          "n_incidents": len(feats), "signals": sorted(signals)},
                         result.families)
    return result


def resolve_incident_ids(wanted: list[str] | None, known) -> set[str]:
    """Accept full ids ("nask:47") or bare folder numbers ("47"); unknown ids are ignored."""
    out: set[str] = set()
    known = set(known)
    for w in wanted or []:
        w = str(w)
        for cand in (w, f"nask:{w}"):
            if cand in known:
                out.add(cand)
    return out


def load_state(ctx: Context | None = None, signals: dict[str, dict[str, Any]] | None = None,
               exclude: list[str] | None = None) -> Result:
    """Engine state for `assign`.

    Normally features are recomputed from disk and the clusters are read from clusters.json.
    With `exclude` the listed incidents are dropped from the base IN MEMORY and the grouping is
    recomputed without them (fast for small corpora), so a "new campaign" demo needs no second
    database. Nothing is written to disk.
    """
    ctx = ctx or make_context()
    cfg = co.engine_cfg(ctx.settings)
    feats, signals, dup_mats = load_features(ctx, signals)
    gone = resolve_incident_ids(exclude, feats)
    if gone:
        feats = {i: f for i, f in feats.items() if i not in gone}
        dup_mats = {i: m for i, m in dup_mats.items() if i not in gone}
        return run(feats, signals, cfg, dup_mats)
    path = resolve_path(ctx, "graph") / "clusters.json"
    clusters, dups, families = cl.load_clusters(path) if path.exists() else ([], [], [])
    return Result(features=feats, signals=signals, edges=[], clusters=clusters, duplicate_groups=dups,
                  cfg=cfg, families=families)
