"""Synthetic FeatureRecord tables for developing/testing the engine before real features exist.

3 campaigns (4+3+3 incidents) + 3 singletons, with deliberate traps:
  - K1 and K2 share an ASN and a generic CDN domain (weak, must NOT merge them),
  - K2 and K3 tell a similar story (close text embeddings) but differ in infrastructure,
  - singleton S3 shares only the stoplisted CDN domain with campaign K1,
  - some incidents miss whole modalities (no HAR/infra, no text, no image).
Tables use the on-disk layout: entity_id, level, module, incident_id + flattened features.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DIM = 16
SYNTH_SIGNALS: dict[str, dict[str, Any]] = {
    "shared_trackers": {"module": "html_struct", "type": "set_overlap", "field": "tracker_ids"},
    "shared_assets": {"module": "html_struct", "type": "set_overlap", "field": "asset_hashes"},
    "dom_template": {"module": "html_struct", "type": "hamming_hash", "field": "dom_simhash"},
    "text_semantic": {"module": "text", "type": "cosine", "field": "text_emb"},
    "text_near_dup": {"module": "text", "type": "jaccard_minhash", "field": "minhash"},
    "shared_entities": {"module": "text", "type": "set_overlap", "field": "entities"},
    "same_platform_name": {"module": "text", "type": "exact", "field": "platform_name"},
    "image_near_dup": {"module": "visual", "type": "hamming_hash", "field": "phash"},
    "visual_style": {"module": "visual", "type": "cosine", "field": "clip_emb"},
    "same_registered_domain": {"module": "infra", "type": "set_overlap", "field": "domains"},
    "shared_ip_asn": {"module": "infra", "type": "exact", "field": "asn"},
}

CDN = "cdnjs.cloudflare.com"   # present in config/stoplist.yaml
STOPLIST = {"domains": [CDN], "filenames": ["jquery"], "sha1": []}

# campaign -> (member suffixes, latent ids). Missing modalities are listed per incident below.
CAMPAIGNS = {"K1": 4, "K2": 3, "K3": 3}
SINGLETONS = ["S1", "S2", "S3"]
NO_INFRA = {"K1-2", "K3-3", "S2"}        # HAR missing / dead page
NO_TEXT = {"K1-4", "K2-3"}
NO_VISUAL = {"K2-2", "S1"}
TWO_PAGES = {"K1-1", "K2-1", "K3-1"}     # incidents with two html pages (chain)


def _flip(h: int, k: int, rng: np.random.Generator) -> int:
    for bit in rng.choice(64, size=k, replace=False):
        h ^= 1 << int(bit)
    return h


def _vec(center: np.ndarray, noise: float, rng: np.random.Generator) -> list[float]:
    return (center + rng.normal(0, noise, DIM)).astype(np.float32).tolist()


def _latent(rng: np.random.Generator, tag: str) -> dict[str, Any]:
    return {
        "tracker": str(int(rng.integers(10**14, 10**15))),
        "platform": f"Platforma {tag}",
        "domains": [f"{tag.lower()}-invest{i}.example" for i in range(3)],
        "template": int(rng.integers(0, 2**63)) * 2 + int(rng.integers(0, 2)),
        "text": rng.normal(0, 1, DIM),
        "style": rng.normal(0, 1, DIM),
        "entities": [f"Osoba {tag}", f"Marka {tag}"],
        "asn": f"AS{int(rng.integers(10000, 99999))}",
        "phash": int(rng.integers(0, 2**63)) * 2,
        "assets": [f"{tag}-asset-{i}" for i in range(5)],
        "minhash": rng.integers(0, 2**32, 32).tolist(),
    }


def _incident_rows(inc: str, lat: dict[str, Any], rng: np.random.Generator, shared_cdn: bool
                   ) -> list[dict[str, Any]]:
    short = inc.split(":")[1]
    rows: list[dict[str, Any]] = []
    n_pages = 2 if short in TWO_PAGES else 1
    for p in range(n_pages):
        mid = f"{short}-page{p}"
        base = {"entity_id": mid, "level": "material", "incident_id": inc}
        trackers = [lat["tracker"]] + ([f"UA-{int(rng.integers(10**6, 10**7))}"] if rng.random() < 0.5 else [])
        assets = list(rng.choice(lat["assets"], size=3, replace=False)) + [f"uniq-{short}-{p}"]
        rows.append({**base, "module": "html_struct", "tracker_ids": trackers, "asset_hashes": assets,
                     "dom_simhash": _flip(lat["template"], int(rng.integers(0, 7)), rng)})
        if short not in NO_TEXT:
            mh = np.array(lat["minhash"])
            mask = rng.random(32) < 0.25
            mh = np.where(mask, rng.integers(0, 2**32, 32), mh)
            rows.append({**base, "module": "text", "text_emb": _vec(lat["text"], 0.15, rng),
                         "minhash": mh.tolist(), "entities": lat["entities"][: int(rng.integers(1, 3))],
                         "platform_name": lat["platform"]})
        if short not in NO_VISUAL and p == 0:
            rows.append({**base, "module": "visual", "phash": _flip(lat["phash"], int(rng.integers(0, 6)), rng),
                         "clip_emb": _vec(lat["style"], 0.2, rng)})
    if short not in NO_INFRA:
        domains = list(lat["domains"][: int(rng.integers(1, 4))]) + ([CDN] if shared_cdn else [])
        rows.append({"entity_id": inc, "level": "incident", "module": "infra", "incident_id": inc,
                     "domains": domains, "asn": lat["asn"]})
    return rows


def make_synthetic(seed: int = 7) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Return ({module: DataFrame}, truth {incident_id: campaign label})."""
    rng = np.random.default_rng(seed)
    lat = {c: _latent(rng, c) for c in CAMPAIGNS}
    # trap 1: K1 and K2 share an ASN; trap 2: K3's story is a noisy copy of K2's
    lat["K2"]["asn"] = lat["K1"]["asn"]
    lat["K3"]["text"] = lat["K2"]["text"] + rng.normal(0, 0.5, DIM)
    rows: list[dict[str, Any]] = []
    truth: dict[str, str] = {}
    for camp, n in CAMPAIGNS.items():
        for i in range(1, n + 1):
            inc = f"syn:{camp}-{i}"
            truth[inc] = camp
            rows += _incident_rows(inc, lat[camp], rng, shared_cdn=(camp == "K1"))
    for s in SINGLETONS:
        inc = f"syn:{s}"
        truth[inc] = f"S:{s}"
        rows += _incident_rows(inc, _latent(rng, s), rng, shared_cdn=(s == "S3"))
    df = pd.DataFrame(rows)
    tables = {m: g.dropna(axis=1, how="all").reset_index(drop=True) for m, g in df.groupby("module")}
    return tables, truth


def write_synthetic(features_dir, labels_path, seed: int = 7) -> dict[str, str]:
    """Write the tables as parquet (one per module) and a labels.yaml - the real on-disk layout."""
    from pathlib import Path

    import yaml

    tables, truth = make_synthetic(seed)
    Path(features_dir).mkdir(parents=True, exist_ok=True)
    for module, df in tables.items():
        df.to_parquet(Path(features_dir) / f"{module}.parquet", index=False)
    campaigns: dict[str, list[str]] = {}
    singles = []
    for inc, lab in truth.items():
        (singles.append(inc) if lab.startswith("S:") else campaigns.setdefault(lab, []).append(inc))
    Path(labels_path).write_text(yaml.safe_dump({"campaigns": campaigns, "singletons": singles}), encoding="utf-8")
    return truth
