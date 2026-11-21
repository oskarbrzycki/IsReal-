"""Shared data types for FakeCollector (see CONTRACTS.md, section 3).

Owner: W5. Changes only via coordinator (CONTRACTS.md changelog).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MaterialKind = Literal["html", "asset", "har", "image", "video", "mhtml", "json", "other"]
FeatureLevel = Literal["material", "incident"]


@dataclass
class Material:
    material_id: str                    # sha1(bytes)[:16]
    incident_id: str                    # e.g. "nask:36"
    kind: MaterialKind
    path: str                           # path relative to repo root, under data/ (never committed)
    original_url: str | None = None     # from "saved from url", og:url, canonical, HAR, manifest
    mime: str | None = None
    size_bytes: int = 0
    is_common_lib: bool = False         # matched config/stoplist.yaml
    parent_html: str | None = None      # for kind="asset": material_id of the owning page
    meta: dict[str, Any] = field(default_factory=dict)  # e.g. {"chain_index": 1}


@dataclass
class Incident:
    incident_id: str
    source: str                         # "nask" | "upload" | "url" | "adlib"
    materials: list[Material]
    label_campaign: str | None = None   # ground truth if known - evaluation only
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureRecord:
    entity_id: str                      # material_id or incident_id
    level: FeatureLevel
    module: str                         # "html_struct" | "text" | "visual" | "faces" | "infra"
    features: dict[str, Any]            # flat values, lists or vectors; None = unavailable
    provenance: dict[str, str] = field(default_factory=dict)  # source -> tool/url + fetched_at
    errors: list[str] = field(default_factory=list)
    incident_id: str | None = None      # always filled, so the engine can aggregate


@dataclass
class Reason:
    signal: str                         # e.g. "shared_assets", "face_match"
    score: float                        # similarity on this signal, 0..1
    weight: float                       # contribution to the combined score
    detail: str                         # human-readable (Polish), shown in UI


@dataclass
class Edge:
    a: str                              # incident_id
    b: str
    score: float                        # combined, 0..1
    reasons: list[Reason]


@dataclass
class Cluster:
    campaign_id: str                    # "C001", ...
    members: list[str]                  # incident_ids
    label: str                          # auto-generated name
    top_signals: list[str]
    cohesion: float


@dataclass
class Assignment:
    incident_id: str
    campaign_id: str | None             # None = new campaign
    confidence: float
    nearest: list[Edge]


@dataclass
class Context:
    """Runtime context passed to every feature extractor."""
    repo_root: Path
    data_dir: Path
    settings: dict[str, Any]
    offline: bool = True
