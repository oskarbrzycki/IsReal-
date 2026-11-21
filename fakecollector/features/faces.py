"""Face detection, embedding and identity matching (owner: W3).

Detector:  OpenCV YuNet  (face_detection_yunet_2023mar.onnx,   opencv_zoo, Apache-2.0)
Embedding: OpenCV SFace  (face_recognition_sface_2021dec.onnx, opencv_zoo, Apache-2.0)
Both run on CPU via cv2.dnn, no compilation needed. Model files live in data/models/ (never in git).

Output per picture (image, eligible asset or video frame):
  faces: [{bbox:[x,y,w,h], det_score, emb (128 x float32, L2-norm; None if face not usable),
           quality 0..1, identity (str|None), id_score (float|None)}]
  face_count

`quality` = det_score * sqrt(size_term * sharpness_term)   (replaces MagFace)
  size_term      = clip((min(w,h) - 24) / (112 - 24), 0, 1)
  sharpness_term = clip(var(Laplacian(aligned 112x112 crop)) / 150, 0, 1)
The engine's cosine is a plain max over pairs, so "max cosine weighted by quality" is
implemented as a filter: a face is *usable* (gets `emb` and `identity`) only if
quality >= faces.min_quality (0.5) and its shorter side >= faces.min_emb_face_px (60 px).
Smaller/blurred faces are still listed (bbox, quality) for the UI, but never link incidents.

Identity: nearest centroid in data/interim/face_ref.npz (built by face_ref.py), cos >= 0.45.
  named cluster (config/reference/faces.yaml)  -> the name
  cluster named "noise"                        -> None (blurred/cropped background faces)
  single-face cluster                          -> None (one sighting is not an identity)
  unnamed cluster                              -> "face:<cluster_id>"
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from fakecollector.core.models import Context, FeatureRecord, Material
from fakecollector.features import _media

log = logging.getLogger("fakecollector.features.faces")

MODULE = "faces"
LEVEL = "material"
KINDS = ["image", "video", "asset"]

SIGNALS = {
    # max over many face pairs reaches ~0.4 by chance (pair table), so only >= 0.50 counts
    "face_match": {"type": "cosine", "field": "faces.emb", "floor": 0.50},
    "same_identity": {"type": "set_overlap", "field": "faces.identity", "metric": "overlap"},
}
# A face is usually a stolen celebrity image reused across narratives: points to the actor
# (family), not proof of one campaign.
SIGNAL_CLASS = {
    "face_match": "family",
    "same_identity": "family",
}

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
MODEL_URLS = {
    YUNET_FILE: "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
                "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    SFACE_FILE: "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
                "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
DET_SCORE = 0.8
MIN_FACE_PX = 24
MIN_QUALITY = 0.5
MIN_EMB_FACE_PX = 60
MIN_CLUSTER_SIZE = 2
NOISE = "noise"
ID_THRESHOLD = 0.45

_lock = threading.Lock()
_models: dict[str, Any] = {}
_ref: dict[str, Any] = {}


# --------------------------------------------------------------------------- models
def ensure_models(ctx: Context | None, download: bool = True) -> tuple[Path, Path]:
    """Return local model paths; download from opencv_zoo (GitHub) once if missing."""
    mdir = _media.models_dir(ctx)
    mdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in (YUNET_FILE, SFACE_FILE):
        p = mdir / name
        if not p.exists() or p.stat().st_size < 10_000:
            if not download:
                raise FileNotFoundError(f"face model missing: {p}")
            import urllib.request
            log.info("downloading %s", name)
            urllib.request.urlretrieve(MODEL_URLS[name], p)  # trusted source: opencv_zoo on GitHub
        paths.append(p)
    return paths[0], paths[1]


def _load(ctx: Context | None) -> dict[str, Any]:
    with _lock:
        if _models:
            return _models
        import cv2
        det_path, rec_path = ensure_models(ctx, download=not bool(_media.setting(ctx, "faces.no_download", False)))
        score = float(_media.setting(ctx, "faces.det_score", DET_SCORE))
        _models["det"] = cv2.FaceDetectorYN.create(str(det_path), "", (320, 320), score, 0.3, 5000)
        _models["rec"] = cv2.FaceRecognizerSF.create(str(rec_path), "")
        return _models


def load_reference(ctx: Context | None, reload: bool = False) -> dict[str, Any]:
    """Centroids from data/interim/face_ref.npz + names from config/reference/faces.yaml."""
    if _ref and not reload:
        return _ref
    _ref.clear()
    _ref["centroids"], _ref["cluster_ids"], _ref["sizes"], _ref["names"] = None, [], [], {}
    npz = _media.interim_dir(ctx) / "face_ref.npz"
    if npz.exists():
        data = np.load(npz, allow_pickle=False)
        _ref["centroids"] = data["centroids"].astype(np.float32)
        _ref["cluster_ids"] = [str(x) for x in data["cluster_ids"]]
        _ref["sizes"] = [int(x) for x in data["sizes"]] if "sizes" in data.files else []
    root = Path(ctx.repo_root) if ctx is not None else Path.cwd()
    yml = root / "config" / "reference" / "faces.yaml"
    if yml.exists():
        import yaml
        with open(yml, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        clusters = raw.get("clusters", raw) if isinstance(raw, dict) else {}
        for cid, val in (clusters or {}).items():
            name = val.get("name") if isinstance(val, dict) else val
            if name:
                _ref["names"][str(cid)] = str(name)
    return _ref


# --------------------------------------------------------------------------- core
def _quality(det_score: float, w: float, h: float, aligned_bgr: np.ndarray) -> float:
    import cv2
    size_term = float(np.clip((min(w, h) - MIN_FACE_PX) / (112 - MIN_FACE_PX), 0.0, 1.0))
    gray = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2GRAY)
    sharp_term = float(np.clip(cv2.Laplacian(gray, cv2.CV_64F).var() / 150.0, 0.0, 1.0))
    return round(float(det_score) * float(np.sqrt(size_term * sharp_term)), 4)


def identify(emb: np.ndarray, ctx: Context | None) -> tuple[str | None, float | None]:
    ref = load_reference(ctx)
    cents = ref.get("centroids")
    if cents is None or len(cents) == 0:
        return None, None
    sims = cents @ emb
    i = int(np.argmax(sims))
    score = float(sims[i])
    thr = float(_media.setting(ctx, "faces.id_threshold", ID_THRESHOLD))
    if score < thr:
        return None, round(score, 4)
    cid = ref["cluster_ids"][i]
    name = ref["names"].get(cid)
    sizes = ref.get("sizes") or []
    min_size = int(_media.setting(ctx, "faces.min_cluster_size", MIN_CLUSTER_SIZE))
    if name == NOISE or (i < len(sizes) and sizes[i] < min_size):
        return None, round(score, 4)
    return name or f"face:{cid}", round(score, 4)


def detect_faces(img, ctx: Context | None, with_crops: bool = False) -> list[dict[str, Any]]:
    """Detect + embed faces in a PIL image. Optionally returns aligned BGR crops ('crop')."""
    m = _load(ctx)
    bgr = _media.pil_to_bgr(img)
    h, w = bgr.shape[:2]
    m["det"].setInputSize((w, h))
    _, dets = m["det"].detect(bgr)
    if dets is None:
        return []
    min_px = int(_media.setting(ctx, "faces.min_face_px", MIN_FACE_PX))
    min_q = float(_media.setting(ctx, "faces.min_quality", MIN_QUALITY))
    min_emb_px = int(_media.setting(ctx, "faces.min_emb_face_px", MIN_EMB_FACE_PX))
    out = []
    for row in dets:
        x, y, fw, fh = (float(v) for v in row[:4])
        if min(fw, fh) < min_px:
            continue
        aligned = m["rec"].alignCrop(bgr, row)
        emb = m["rec"].feature(aligned).flatten().astype(np.float32)
        n = float(np.linalg.norm(emb))
        if n > 0:
            emb = emb / n
        q = _quality(float(row[14]), fw, fh, aligned)
        usable = q >= min_q and min(fw, fh) >= min_emb_px
        identity, id_score = identify(emb, ctx) if usable else (None, None)
        face = {"bbox": [int(round(x)), int(round(y)), int(round(fw)), int(round(fh))],
                "det_score": round(float(row[14]), 4),
                "emb": emb.tolist() if usable else None,
                "quality": q, "identity": identity, "id_score": id_score}
        if with_crops:
            face["crop"] = aligned
            face["emb_full"] = emb
        out.append(face)
    out.sort(key=lambda f: -f["quality"])
    return out


# --------------------------------------------------------------------------- extract
def extract_many(material: Material, ctx: Context) -> list[FeatureRecord]:
    """All records for a material: [] if skipped (icon, not an image), 1 for image, N for video."""
    try:
        units, base_errors = _media.units_for(material, ctx)
    except Exception as exc:
        return [_media.empty_record(material, MODULE, [f"{type(exc).__name__}: {exc}"])]
    if not units:
        if base_errors and all(e.startswith("skipped:") for e in base_errors):
            return []
        return [_media.empty_record(material, MODULE, base_errors)]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prov = {"faces": f"opencv YuNet 2023mar + SFace 2021dec (opencv_zoo)@{now}"}
    if load_reference(ctx).get("centroids") is not None:
        prov["identity"] = f"data/interim/face_ref.npz + config/reference/faces.yaml@{now}"
    out = []
    for unit in units:
        errors = list(base_errors)
        try:
            faces = detect_faces(unit.image, ctx)
            feats: dict[str, Any] = {"faces": faces or None, "face_count": len(faces)}
        except Exception as exc:
            feats = {"faces": None, "face_count": None}
            errors.append(f"faces: {type(exc).__name__}: {exc}")
        feats["frame_index"] = unit.meta.get("frame_index")
        feats["t_s"] = unit.meta.get("t_s")
        feats["source_kind"] = material.kind
        out.append(FeatureRecord(entity_id=unit.entity_id, level=LEVEL, module=MODULE, features=feats,
                                 provenance=prov, errors=errors, incident_id=material.incident_id))
    return out


def extract(material: Material, ctx: Context) -> list[FeatureRecord]:
    """Contract entry point. Returns a list (see extract_many): videos yield one record per frame."""
    return extract_many(material, ctx)

