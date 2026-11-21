"""Visual features of ad screenshots, page images and video frames (owner: W3).

Features per picture (image, eligible asset, or sampled video frame):
  phash, dhash        imagehash perceptual hashes (64 bit, hex)   -> image_near_dup
  clip_emb            open_clip ViT-B-32 image embedding, L2-normalised (512 x float32) -> visual_style
  ocr_text            Tesseract pol+eng (None if Tesseract is not installed)
  logos               zero-shot CLIP over brand names from config/reference/entities.yaml -> shared_logo
  logo_scores         [[brand, prob], ...] for logos above threshold (explainability)
  dominant_colors     3 hex colours by k-means, most frequent first

Videos produce one record per frame, entity_id = "<material_id>#f<n>".
See CONTRACTS.md section 4/5. Purely offline (model weights are downloaded once to data/models).
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from fakecollector.core.models import Context, FeatureRecord, Material
from fakecollector.features import _media

log = logging.getLogger("fakecollector.features.visual")

MODULE = "visual"
LEVEL = "material"
KINDS = ["image", "video", "asset"]

SIGNALS = {
    # 64-bit pHash; floor 0.75 => hamming distance >= 16 counts as 0 (unrelated pictures)
    "image_near_dup": {"type": "hamming_hash", "field": "phash", "bits": 64, "floor": 0.75},
    # CLIP cosine is 0.5-0.83 even across campaigns (pair table), so only >= 0.85 counts
    "visual_style": {"type": "cosine", "field": "clip_emb", "floor": 0.85},
    "shared_logo": {"type": "set_overlap", "field": "logos"},
}
# campaign = the same creative (near-identical picture); family = shared look / branding of an actor
SIGNAL_CLASS = {
    "image_near_dup": "campaign",
    "visual_style": "family",
    "shared_logo": "family",
}

CLIP_ARCH = "ViT-B-32-quickgelu"
CLIP_PRETRAINED = "openai"
DEFAULT_LOGO_THRESHOLD = 0.6
# Background classes so that "no logo" pictures do not get forced onto a brand.
_NEGATIVE_PROMPTS = [
    "a photo of a person", "a photo of a face", "a screenshot of a news article with text",
    "a screenshot of a mobile phone screen", "a product photo", "a photo of a building",
    "a photo of a car", "a chart or graph", "a photo of money", "an abstract background",
]

_lock = threading.Lock()
_clip: dict[str, Any] = {}
_ocr_state: dict[str, Any] = {}


# --------------------------------------------------------------------------- CLIP
def _load_clip(ctx: Context | None) -> dict[str, Any]:
    with _lock:
        if _clip:
            return _clip
        import open_clip
        import torch

        torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
        cache = _media.models_dir(ctx) / "open_clip"
        cache.mkdir(parents=True, exist_ok=True)
        arch = _media.setting(ctx, "visual.clip_arch", CLIP_ARCH)
        pretrained = _media.setting(ctx, "visual.clip_pretrained", CLIP_PRETRAINED)
        model, _, preprocess = open_clip.create_model_and_transforms(
            arch, pretrained=pretrained, cache_dir=str(cache))
        model.eval()
        _clip.update(model=model, preprocess=preprocess, tokenizer=open_clip.get_tokenizer(arch),
                     torch=torch, name=f"open_clip {arch}/{pretrained}")
        return _clip


def clip_embed(images: list, ctx: Context | None) -> np.ndarray:
    """L2-normalised CLIP embeddings, shape (n, 512)."""
    c = _load_clip(ctx)
    torch = c["torch"]
    with torch.no_grad():
        batch = torch.stack([c["preprocess"](im) for im in images])
        emb = c["model"].encode_image(batch).float()
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb.cpu().numpy().astype(np.float32)


def _load_brands(ctx: Context | None) -> list[str]:
    import yaml

    root = Path(ctx.repo_root) if ctx is not None else Path.cwd()
    path = root / _media.setting(ctx, "visual.entities_path", "config/reference/entities.yaml")
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    names: list[str] = []
    for b in data.get("brands") or []:
        name = b.get("name") if isinstance(b, dict) else str(b)
        if name and name not in names:
            names.append(str(name))
    return names


def _brand_text_features(ctx: Context | None) -> tuple[list[str], np.ndarray] | None:
    c = _load_clip(ctx)
    if "brand_feats" in c:
        return c["brand_feats"]
    brands = _load_brands(ctx)
    if not brands:
        c["brand_feats"] = None
        return None
    prompts = [f"the logo of {b}" for b in brands] + _NEGATIVE_PROMPTS
    torch = c["torch"]
    with torch.no_grad():
        tf = c["model"].encode_text(c["tokenizer"](prompts)).float()
        tf = tf / tf.norm(dim=-1, keepdim=True)
    c["brand_feats"] = (brands, tf.cpu().numpy().astype(np.float32))
    return c["brand_feats"]


def zero_shot_logos(emb: np.ndarray, ctx: Context | None) -> tuple[list[str], list[list[Any]]] | None:
    bf = _brand_text_features(ctx)
    if bf is None:
        return None
    brands, tf = bf
    logits = 100.0 * (tf @ emb)
    probs = np.exp(logits - logits.max())
    probs /= probs.sum()
    thr = float(_media.setting(ctx, "visual.logo_threshold", DEFAULT_LOGO_THRESHOLD))
    hits = [(brands[i], float(probs[i])) for i in range(len(brands)) if probs[i] >= thr]
    hits.sort(key=lambda x: -x[1])
    return [h[0] for h in hits], [{"brand": h[0], "p": round(h[1], 3)} for h in hits]


# --------------------------------------------------------------------------- OCR
_WINDOWS_DEFAULTS = (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")


def _tesseract_cmd(ctx: Context | None = None) -> tuple[str | None, str | None]:
    """Locate the Tesseract binary. Returns (cmd, error).

    Order: TESSERACT_CMD env var (.env) -> settings visual.tesseract_cmd -> PATH (shutil.which,
    works on macOS/Linux/Docker) -> default Windows install locations.
    """
    explicit = os.environ.get("TESSERACT_CMD") or _media.setting(ctx, "visual.tesseract_cmd", None)
    if explicit:
        explicit = str(explicit).strip().strip('"')
        resolved = explicit if Path(explicit).is_file() else shutil.which(explicit)
        if resolved:
            return resolved, None
        return None, f"ocr: TESSERACT_CMD points to a missing binary ({explicit})"
    found = shutil.which("tesseract")
    if found:
        return found, None
    for cand in _WINDOWS_DEFAULTS:
        if Path(cand).is_file():
            return cand, None
    return None, "ocr: Tesseract binary not found (set TESSERACT_CMD or add tesseract to PATH)"


def _ocr_setup(ctx: Context | None) -> tuple[str | None, str | None]:
    """Return (lang, error). lang=None means OCR unavailable."""
    if "lang" in _ocr_state or "error" in _ocr_state:
        return _ocr_state.get("lang"), _ocr_state.get("error")
    try:
        import pytesseract
    except ImportError:
        _ocr_state["error"] = "ocr: pytesseract not installed"
        return None, _ocr_state["error"]
    cmd, err = _tesseract_cmd(ctx)
    if not cmd:
        _ocr_state["error"] = err
        return None, _ocr_state["error"]
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception as exc:
        _ocr_state["error"] = f"ocr: {exc}"
        return None, _ocr_state["error"]
    wanted = [x for x in str(_media.setting(ctx, "visual.ocr_lang", "pol+eng")).split("+") if x in langs]
    if not wanted:
        _ocr_state["error"] = f"ocr: no requested language installed (have {sorted(langs)})"
        return None, _ocr_state["error"]
    _ocr_state["lang"] = "+".join(wanted)
    _ocr_state["version"] = str(pytesseract.get_tesseract_version())
    return _ocr_state["lang"], None


def ocr(img, ctx: Context | None) -> tuple[str | None, str | None]:
    """Return (text, error). Tesseract is optional (README): when it is not available the result is
    (None, None) and a single warning is logged for the whole run, not an error on every record.
    An error is returned only when OCR is available but fails on this particular picture."""
    lang, err = _ocr_setup(ctx)
    if lang is None:
        if not _ocr_state.get("warned"):
            log.warning("%s - OCR disabled, ocr_text = None for all pictures "
                        "(optional: install Tesseract + pol data or set TESSERACT_CMD)", err)
            _ocr_state["warned"] = True
        return None, None
    import pytesseract
    try:
        gray = img.convert("L")
        if max(gray.size) < 1000:      # small ad screenshots read better upscaled
            gray = gray.resize((gray.width * 2, gray.height * 2))
        text = pytesseract.image_to_string(gray, lang=lang, timeout=60)
    except Exception as exc:
        return None, f"ocr: {type(exc).__name__}: {exc}"
    text = " ".join(text.split())
    return (text or None), None


# --------------------------------------------------------------------------- hashes / colours
def hashes(img) -> tuple[str, str]:
    import imagehash
    return str(imagehash.phash(img)), str(imagehash.dhash(img))


def dominant_colors(img, k: int = 3) -> list[str]:
    import cv2
    small = np.asarray(img.convert("RGB").resize((64, 64))).reshape(-1, 3).astype(np.float32)
    k = min(k, len(np.unique(small, axis=0)))
    if k < 1:
        return []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)
    _, labels, centers = cv2.kmeans(small, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    return ["#%02x%02x%02x" % tuple(int(round(v)) for v in centers[i]) for i in order]


# --------------------------------------------------------------------------- extract
def _features_for(unit: _media.Unit, ctx: Context | None, errors: list[str]) -> dict[str, Any]:
    f: dict[str, Any] = {"phash": None, "dhash": None, "clip_emb": None, "ocr_text": None,
                         "logos": None, "logo_scores": None, "dominant_colors": None,
                         "width": unit.image.width, "height": unit.image.height,
                         "frame_index": unit.meta.get("frame_index"), "t_s": unit.meta.get("t_s")}
    try:
        f["phash"], f["dhash"] = hashes(unit.image)
    except Exception as exc:
        errors.append(f"hash: {type(exc).__name__}: {exc}")
    try:
        emb = clip_embed([unit.image], ctx)[0]
        f["clip_emb"] = emb.tolist()
        try:
            res = zero_shot_logos(emb, ctx)
            if res is None:
                errors.append("logos: config/reference/entities.yaml missing or has no brands")
            else:
                f["logos"], f["logo_scores"] = res
        except Exception as exc:
            errors.append(f"logos: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"clip: {type(exc).__name__}: {exc}")
    if _media.setting(ctx, "visual.ocr", True):
        text, err = ocr(unit.image, ctx)
        f["ocr_text"] = text
        if err:
            errors.append(err)
    try:
        f["dominant_colors"] = dominant_colors(unit.image)
    except Exception as exc:
        errors.append(f"colors: {type(exc).__name__}: {exc}")
    return f


def _provenance() -> dict[str, str]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prov = {"phash": f"imagehash@{now}", "clip_emb": f"{_clip.get('name', 'open_clip')}@{now}",
            "dominant_colors": f"opencv kmeans@{now}"}
    if _ocr_state.get("lang"):
        prov["ocr_text"] = f"tesseract {_ocr_state.get('version', '')} {_ocr_state['lang']}@{now}"
    elif _ocr_state.get("error"):  # optional OCR off: say why ocr_text is None (shown in UI)
        prov["ocr_text"] = f"unavailable ({_ocr_state['error'].removeprefix('ocr: ')})@{now}"
    return prov


def extract_many(material: Material, ctx: Context) -> list[FeatureRecord]:
    """All records for a material: [] if skipped (icon, not an image), 1 for image, N for video."""
    try:
        units, base_errors = _media.units_for(material, ctx)
    except Exception as exc:  # never break the batch
        return [_media.empty_record(material, MODULE, [f"{type(exc).__name__}: {exc}"])]
    if not units:
        if base_errors and all(e.startswith("skipped:") for e in base_errors):
            return []
        return [_media.empty_record(material, MODULE, base_errors)]
    out = []
    for unit in units:
        errors = list(base_errors)
        try:
            feats = _features_for(unit, ctx, errors)
        except Exception as exc:
            feats, errors = {}, errors + [f"{type(exc).__name__}: {exc}"]
        feats["source_kind"] = material.kind
        out.append(FeatureRecord(entity_id=unit.entity_id, level=LEVEL, module=MODULE, features=feats,
                                 provenance=_provenance(), errors=errors,
                                 incident_id=material.incident_id))
    return out


def extract(material: Material, ctx: Context) -> list[FeatureRecord]:
    """Contract entry point. Returns a list (see extract_many): videos yield one record per frame."""
    return extract_many(material, ctx)

