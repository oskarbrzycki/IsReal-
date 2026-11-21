"""Grouping of incidents into campaigns (CONTRACTS 6.4-6.5).

1. duplicate groups (very high score or the same non-common material) are contracted first,
2. graph of edges >= tau_edge -> Louvain communities (fixed seed) or HDBSCAN on 1-score,
3. every cluster gets a label, its strongest signals and a cohesion value,
4. campaigns are joined into families via family-class signals (`build_families`).
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import numpy as np

from fakecollector.core.models import Cluster, Edge
from fakecollector.engine.mask import mask_value

log = logging.getLogger("fakecollector.engine")

# signals whose shared values make the best campaign name, in order of preference
LABEL_SIGNALS = ("same_platform_name", "shared_entities", "same_registered_domain", "shared_trackers")


class _UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def duplicate_groups(
    incident_ids: Iterable[str],
    edges: list[Edge],
    tau_dup: float,
    incident_materials: dict[str, set[str]] | None = None,
) -> list[list[str]]:
    """Groups (size >= 2) of incidents that are copies of the same message.

    Linked by an edge with score >= tau_dup, or by a shared page/image/video material id
    (`incident_materials`: incident -> ids of non-asset, non-common materials; optional).
    """
    ids = sorted(set(incident_ids))
    uf = _UnionFind(ids)
    for e in edges:
        if e.score >= tau_dup and e.a in uf.parent and e.b in uf.parent:
            uf.union(e.a, e.b)
    if incident_materials:
        owner: dict[str, str] = {}
        for inc in ids:
            for mid in incident_materials.get(inc, ()):
                if mid in owner:
                    uf.union(owner[mid], inc)
                else:
                    owner[mid] = inc
    groups: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        groups[uf.find(i)].append(i)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _partition_louvain(nodes: list[str], pair_w: dict[tuple[str, str], float], cfg: dict[str, Any]) -> list[set[str]]:
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for (a, b), w in pair_w.items():
        g.add_edge(a, b, weight=w)
    return [set(c) for c in nx.community.louvain_communities(
        g, weight="weight", resolution=float(cfg["louvain_resolution"]), seed=int(cfg["seed"]))]


def _partition_hdbscan(nodes: list[str], pair_w: dict[tuple[str, str], float], cfg: dict[str, Any]) -> list[set[str]]:
    from sklearn.cluster import HDBSCAN

    idx = {n: i for i, n in enumerate(nodes)}
    dist = np.ones((len(nodes), len(nodes)), dtype=float)
    np.fill_diagonal(dist, 0.0)
    for (a, b), w in pair_w.items():
        dist[idx[a], idx[b]] = dist[idx[b], idx[a]] = 1.0 - w
    if len(nodes) < 3:
        return [{n} for n in nodes]
    labels = HDBSCAN(min_cluster_size=2, metric="precomputed").fit_predict(dist)
    parts: dict[int, set[str]] = defaultdict(set)
    out: list[set[str]] = []
    for n, lab in zip(nodes, labels):
        if lab < 0:
            out.append({n})          # noise = its own (singleton) campaign
        else:
            parts[int(lab)].add(n)
    return out + list(parts.values())


def _top_shared(members: list[str], features: dict[str, dict[str, Any]], signals: dict[str, dict[str, Any]]) -> str:
    """Most frequent value (present in >= 2 members) of the best label signal."""
    for sig in LABEL_SIGNALS:
        if sig not in signals:
            continue
        counter: Counter[str] = Counter()
        for m in members:
            val = features.get(m, {}).get(sig)
            if val:
                counter.update(val)
        common = [v for v, c in counter.most_common() if c >= 2]
        if common:
            return " / ".join(mask_value(v)[:30] for v in common[:2])
    return ""


def build_clusters(
    incident_ids: Iterable[str],
    edges: list[Edge],
    features: dict[str, dict[str, Any]],
    signals: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    dup_groups: list[list[str]] | None = None,
    method: str | None = None,
) -> list[Cluster]:
    """Cluster incidents; duplicate groups are contracted so they always stay together."""
    ids = sorted(set(incident_ids))
    rep = {i: i for i in ids}
    for grp in dup_groups or []:
        for m in grp:
            rep[m] = grp[0]
    nodes = sorted(set(rep.values()))

    pair_w: dict[tuple[str, str], float] = {}
    for e in edges:
        if e.score < float(cfg["tau_campaign"]) or e.a not in rep or e.b not in rep:
            continue
        ra, rb = sorted((rep[e.a], rep[e.b]))
        if ra != rb:
            pair_w[(ra, rb)] = max(pair_w.get((ra, rb), 0.0), e.score)

    method = method or cfg["cluster_method"]
    parts = (_partition_hdbscan if method == "hdbscan" else _partition_louvain)(nodes, pair_w, cfg)

    members_of_rep: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        members_of_rep[rep[i]].append(i)
    groups = [sorted(m for r in part for m in members_of_rep[r]) for part in parts]
    groups.sort(key=lambda g: (-len(g), g[0]))

    edge_by_pair = {(e.a, e.b): e for e in edges}
    clusters: list[Cluster] = []
    for n, members in enumerate(groups, start=1):
        contrib: Counter[str] = Counter()
        sims: list[float] = []
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                e = edge_by_pair.get((a, b))
                sims.append(e.score if e else 0.0)
                if e:
                    for r in e.reasons:
                        contrib[r.signal] += r.weight * r.score
        top = [s for s, v in contrib.most_common(3) if v > 0]
        shared = _top_shared(members, features, signals)
        label = shared or (f"{len(members)} incydentów" if len(members) > 1 else members[0])
        clusters.append(Cluster(
            campaign_id=f"C{n:03d}", members=members, label=label, top_signals=top,
            cohesion=round(float(np.mean(sims)), 4) if sims else 1.0))
    return clusters


@dataclass
class Family:
    """Campaigns sharing a kit / actor / theme (CONTRACTS 6.4, second level)."""
    family_id: str                      # "F001"...
    campaigns: list[str]                # campaign_ids
    members: list[str]                  # incident_ids of all those campaigns
    label: str
    top_signals: list[str] = field(default_factory=list)


def build_families(
    clusters: list[Cluster],
    family_edges: list[Edge],
    features: dict[str, dict[str, Any]],
    signals: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
) -> list[Family]:
    """Join campaigns into families when family-class signals link their incidents.

    Two campaigns are linked with weight = best family score between any of their incidents
    (>= tau_family). Louvain on that campaign graph (fixed seed) avoids long chains of weak links.
    A campaign without any link is its own one-campaign family.
    """
    of_inc = {m: c.campaign_id for c in clusters for m in c.members}
    pair_w: dict[tuple[str, str], float] = {}
    for e in family_edges:
        if e.score < float(cfg["tau_family"]) or e.a not in of_inc or e.b not in of_inc:
            continue
        ca, cb = sorted((of_inc[e.a], of_inc[e.b]))
        if ca != cb:
            pair_w[(ca, cb)] = max(pair_w.get((ca, cb), 0.0), e.score)
    nodes = sorted(c.campaign_id for c in clusters)
    parts = _partition_louvain(nodes, pair_w, cfg)
    members_of = {c.campaign_id: c.members for c in clusters}
    groups = [sorted(part) for part in parts]
    groups.sort(key=lambda g: (-sum(len(members_of[c]) for c in g), g[0]))

    by_pair = {(e.a, e.b): e for e in family_edges}
    families: list[Family] = []
    for n, camps in enumerate(groups, start=1):
        members = sorted(m for c in camps for m in members_of[c])
        contrib: Counter[str] = Counter()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                e = by_pair.get((a, b))
                if e:
                    for r in e.reasons:
                        contrib[r.signal] += r.weight * r.score
        top = [s for s, v in contrib.most_common(3) if v > 0]
        label = _top_shared(members, features, signals) or (
            f"{len(camps)} kampanii" if len(camps) > 1 else next(c.label for c in clusters if c.campaign_id == camps[0]))
        families.append(Family(family_id=f"F{n:03d}", campaigns=camps, members=members, label=label, top_signals=top))
    return families


def family_of_campaign(families: list[Family]) -> dict[str, str]:
    """campaign_id -> family_id."""
    return {c: f.family_id for f in families for c in f.campaigns}


def family_labels_of(clusters: list[Cluster], families: list[Family]) -> dict[str, str]:
    """incident_id -> family_id."""
    fam = family_of_campaign(families)
    return {m: fam[c.campaign_id] for c in clusters for m in c.members if c.campaign_id in fam}


def labels_of(clusters: list[Cluster]) -> dict[str, str]:
    """incident_id -> campaign_id."""
    return {m: c.campaign_id for c in clusters for m in c.members}


def save_clusters(clusters: list[Cluster], dup_groups: list[list[str]], path: Path, params: dict[str, Any],
                  families: list[Family] | None = None) -> None:
    """clusters.json: every cluster carries `family_id` (CONTRACTS 6.4); `families` lists the groups."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fam_of = family_of_campaign(families or [])
    payload = {
        "params": params,
        "duplicate_groups": dup_groups,
        "clusters": [{**asdict(c), "family_id": fam_of.get(c.campaign_id)} for c in clusters],
        "families": [asdict(f) for f in families or []],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_clusters(path: Path) -> tuple[list[Cluster], list[list[str]], list[Family]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = {"campaign_id", "members", "label", "top_signals", "cohesion"}
    clusters = [Cluster(**{k: v for k, v in c.items() if k in names}) for c in payload["clusters"]]
    families = [Family(**f) for f in payload.get("families", [])]
    return clusters, payload.get("duplicate_groups", []), families
