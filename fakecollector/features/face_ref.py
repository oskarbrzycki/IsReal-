"""Build the face reference base from the dataset itself (owner: W3).

  python -m fakecollector.features.face_ref [--data data/raw/nask] [--threshold 0.40]

Steps:
  1. detect + embed every face (same selection rules as faces.py: images, video frames, assets
     >= 15 KB and >= 100x100 px), keep only usable faces (quality >= 0.5, shorter side >= 60 px);
  2. agglomerative clustering on cosine distance (average linkage, cut at 1 - threshold);
  3. new clusters inherit the id of the matching cluster of the previous build (centroid cos >= 0.6),
     so names typed by the leader stay attached to the same person;
  4. write data/interim/face_ref.npz  (centroids, cluster_ids, sizes)   -- never committed;
  5. write review thumbnails data/interim/faces_review/<cluster_id>.jpg for clusters with >= 2 faces;
  6. rewrite config/reference/faces.yaml with clusters of >= 2 faces
     (`cluster_id: {name, faces, incidents}`); existing names are preserved by id.

After naming, re-run `python -m fakecollector features --module faces` to fill `identity`.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np

from fakecollector.features import _media, faces
from fakecollector.features.runner import make_context
from fakecollector.ingest.loader import load_incidents, read_jsonl
from fakecollector.ingest.util import REPO_ROOT

log = logging.getLogger("fakecollector.features.face_ref")
MATCH_COS = 0.6   # min centroid cosine to inherit a cluster id from the previous build


def collect(incidents, ctx) -> list[dict]:
    items = []
    for inc in incidents:
        for m in inc.materials:
            if m.kind not in faces.KINDS or m.is_common_lib:
                continue
            units, _ = _media.units_for(m, ctx)
            for u in units:
                try:
                    found = faces.detect_faces(u.image, ctx, with_crops=True)
                except Exception as exc:
                    log.warning("face detect failed on %s: %s", u.entity_id, exc)
                    continue
                for f in found:
                    if f["emb"] is None:          # below min quality
                        continue
                    items.append({"entity_id": u.entity_id, "incident_id": inc.incident_id,
                                  "emb": f["emb_full"], "crop": f["crop"], "quality": f["quality"]})
    return items


def cluster(embs: np.ndarray, threshold: float) -> np.ndarray:
    if len(embs) == 1:
        return np.zeros(1, dtype=int)
    from sklearn.cluster import AgglomerativeClustering
    model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                    distance_threshold=1.0 - threshold)
    return model.fit_predict(embs)


def contact_sheet(crops: list[np.ndarray], path: Path, cols: int = 8) -> None:
    import cv2
    crops = crops[:32]
    rows = (len(crops) + cols - 1) // cols
    sheet = np.full((rows * 112, min(cols, len(crops)) * 112, 3), 255, dtype=np.uint8)
    for i, c in enumerate(crops):
        r, k = divmod(i, cols)
        sheet[r * 112:(r + 1) * 112, k * 112:(k + 1) * 112] = cv2.resize(c, (112, 112))
    cv2.imwrite(str(path), sheet)


def write_yaml(clusters: dict[str, dict], path: Path) -> None:
    import yaml
    existing = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        existing = raw.get("clusters", {}) or {}
    out = {}
    for cid, info in clusters.items():
        prev = existing.get(cid)
        name = prev.get("name") if isinstance(prev, dict) else prev
        out[cid] = {"name": name, "faces": info["faces"], "incidents": info["incidents"]}
    header = ("# Face reference clusters (owner: W3 generates, leader names).\n"
              "# Type the person's full name in `name` after reviewing data/interim/faces_review/<id>.jpg.\n"
              "# Names only - no photos or embeddings in git. Ids survive rebuilds (centroid matching).\n"
              "# name: noise = blurred/cropped background faces, never used as identity.\n"
              "# Single-face clusters are not listed: they never yield an identity.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump({"clusters": out}, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _load_previous(ctx) -> tuple[np.ndarray | None, list[str]]:
    npz = _media.interim_dir(ctx) / "face_ref.npz"
    if not npz.exists():
        return None, []
    data = np.load(npz, allow_pickle=False)
    return data["centroids"].astype(np.float32), [str(x) for x in data["cluster_ids"]]


def match_previous_ids(new_cents: np.ndarray, old_cents: np.ndarray | None, old_ids: list[str],
                       min_cos: float = MATCH_COS) -> list[str | None]:
    """Greedy 1:1 matching of new clusters to the previous build, so reviewed names survive a rebuild."""
    out: list[str | None] = [None] * len(new_cents)
    if old_cents is None or not len(old_cents) or not len(new_cents):
        return out
    sims = new_cents @ old_cents.T
    used_new, used_old = set(), set()
    for flat in np.argsort(-sims, axis=None):
        i, j = divmod(int(flat), sims.shape[1])
        if sims[i, j] < min_cos:
            break
        if i in used_new or j in used_old:
            continue
        out[i] = old_ids[j]
        used_new.add(i)
        used_old.add(j)
    return out


def build(incidents, ctx, threshold: float) -> dict:
    old_cents, old_ids = _load_previous(ctx)
    faces.load_reference(ctx, reload=True)
    faces._ref.update(centroids=None, cluster_ids=[], sizes=[])   # no identities while building
    items = collect(incidents, ctx)
    review = _media.interim_dir(ctx) / "faces_review"
    review.mkdir(parents=True, exist_ok=True)
    for old in review.glob("*.jpg"):
        old.unlink()
    if not items:
        return {"faces": 0, "clusters": 0}
    embs = np.stack([it["emb"] for it in items]).astype(np.float32)
    labels = cluster(embs, threshold)
    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[int(lab)].append(i)
    # deterministic order: clusters spanning more incidents / more faces first
    ordered = sorted(groups.values(), key=lambda idx: (-len({items[i]["incident_id"] for i in idx}), -len(idx)))
    cents = []
    for idx in ordered:
        c = embs[idx].mean(axis=0)
        cents.append(c / (np.linalg.norm(c) or 1.0))
    new_cents = np.stack(cents).astype(np.float32)
    inherited = match_previous_ids(new_cents, old_cents, old_ids)
    next_n = max([int(x[1:]) for x in old_ids if x[1:].isdigit()] + [0]) + 1
    cids, sizes, meta = [], [], {}
    for idx, cid in zip(ordered, inherited):
        if cid is None:
            cid, next_n = f"P{next_n:03d}", next_n + 1
        cids.append(cid)
        sizes.append(len(idx))
        info = {"faces": len(idx), "incidents": sorted({items[i]["incident_id"] for i in idx})}
        meta[cid] = info
        if len(idx) >= faces.MIN_CLUSTER_SIZE:      # singletons never yield identity: nothing to review
            idx_sorted = sorted(idx, key=lambda i: -items[i]["quality"])
            contact_sheet([items[i]["crop"] for i in idx_sorted], review / f"{cid}.jpg")
    np.savez(_media.interim_dir(ctx) / "face_ref.npz", centroids=new_cents,
             cluster_ids=np.array(cids), sizes=np.array(sizes))
    multi = {c: v for c, v in meta.items() if v["faces"] >= faces.MIN_CLUSTER_SIZE}
    write_yaml(multi, REPO_ROOT / "config" / "reference" / "faces.yaml")
    ref = faces.load_reference(ctx, reload=True)
    kept = [c for c in cids if c in old_ids]
    return {"faces": len(items), "clusters": len(cids), "clusters_size_ge2": len(multi),
            "singletons": len(cids) - len(multi),
            "clusters_multi_incident": sum(1 for v in multi.values() if len(v["incidents"]) > 1),
            "ids_kept_from_previous": len(kept), "previous_ids_dropped": sorted(set(old_ids) - set(cids)),
            "named": {c: ref["names"][c] for c in cids if c in ref["names"]},
            "details": multi}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", default=str(REPO_ROOT / "data" / "interim" / "incidents.jsonl"),
                    help="loader output (W1); if missing, --data is scanned with the loader")
    ap.add_argument("--data", default=str(REPO_ROOT / "data" / "raw" / "nask"))
    ap.add_argument("--threshold", type=float, default=0.40, help="min cosine to merge faces")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ctx = make_context()
    jsonl = Path(args.incidents)
    incidents = read_jsonl(jsonl) if jsonl.exists() else load_incidents(Path(args.data))
    stats = build(incidents, ctx, args.threshold)
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
