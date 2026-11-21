"""Shared media helpers for the `visual` and `faces` modules (owner: W3).

Responsibilities:
  * decide which materials are worth processing (icons are skipped),
  * load raster images safely (by content, not by extension),
  * sample video frames in a streaming way (never loads a whole video into memory),
  * cache sampled frames under data/interim/frames/ so both modules reuse them.

Everything here is static/offline: no network, no HTML rendering, no JS.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from PIL import Image, ImageFile

from fakecollector.core.models import Context, FeatureRecord, Material

log = logging.getLogger("fakecollector.features.media")

ImageFile.LOAD_TRUNCATED_IMAGES = True          # tolerate truncated downloads
Image.MAX_IMAGE_PIXELS = 80_000_000             # guard against decompression bombs

MIN_ASSET_BYTES = 15 * 1024
MIN_ASSET_SIDE = 100
MAX_SIDE = 2048                                  # downscale huge screenshots before analysis
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".ts", ".mpg", ".mpeg", ".3gp"}
PLAYLIST_EXT = {".m3u8", ".m3u"}
SKIP_EXT = {".svg", ".js", ".css", ".html", ".htm", ".json", ".har", ".mhtml", ".txt", ".pobrane"}


@dataclass
class Unit:
    """One analysable picture: a still image or one sampled video frame."""
    entity_id: str
    image: Image.Image                 # RGB, max side <= MAX_SIDE
    meta: dict[str, Any]


# --------------------------------------------------------------------------- paths / settings
def resolve_path(material: Material, ctx: Context | None) -> Path:
    p = Path(material.path)
    if p.is_absolute() or ctx is None:
        return p
    return Path(ctx.repo_root) / p


def setting(ctx: Context | None, dotted: str, default: Any) -> Any:
    cur: Any = ctx.settings if ctx is not None else {}
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def interim_dir(ctx: Context | None) -> Path:
    root = Path(ctx.repo_root) if ctx is not None else Path.cwd()
    return root / setting(ctx, "paths.interim", "data/interim")


def models_dir(ctx: Context | None) -> Path:
    root = Path(ctx.repo_root) if ctx is not None else Path.cwd()
    return root / setting(ctx, "paths.models", "data/models")


def empty_record(material: Material, module: str, errors: list[str],
                 entity_id: str | None = None) -> FeatureRecord:
    return FeatureRecord(entity_id=entity_id or material.material_id, level="material", module=module,
                         features={}, provenance={}, errors=errors, incident_id=material.incident_id)


# --------------------------------------------------------------------------- selection
def _suffix(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".pobrane") or name.endswith(".pobierz"):
        return ".pobrane"
    return path.suffix.lower()


def is_video_path(path: Path) -> bool:
    return _suffix(path) in VIDEO_EXT


def is_playlist_path(path: Path) -> bool:
    return _suffix(path) in PLAYLIST_EXT


def probe_image(path: Path) -> tuple[int, int] | None:
    """Return (w, h) if `path` is a raster image PIL can read (sniffed by content), else None."""
    if _suffix(path) in SKIP_EXT or is_video_path(path) or is_playlist_path(path):
        return None
    try:
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None


def selection_reason(material: Material, ctx: Context | None) -> str | None:
    """None if the material should be processed, otherwise a short 'skipped: ...' reason."""
    path = resolve_path(material, ctx)
    if not path.exists():
        return f"skipped: file not found ({path.name})"
    if is_playlist_path(path):
        # Never hand a playlist to the decoder: it may reference remote URLs (network access).
        # Local segments (.ts) are separate materials and are processed on their own.
        return "skipped: HLS playlist (segments processed separately)"
    if material.kind == "video" or is_video_path(path):
        return None
    size = path.stat().st_size
    min_bytes = int(setting(ctx, "visual.min_asset_bytes", MIN_ASSET_BYTES))
    min_side = int(setting(ctx, "visual.min_asset_side", MIN_ASSET_SIDE))
    if material.kind == "asset" and size < min_bytes:
        return f"skipped: asset smaller than {min_bytes} B"
    dims = probe_image(path)
    if dims is None:
        return "skipped: not a raster image"
    if material.kind == "asset" and min(dims) < min_side:
        return f"skipped: asset smaller than {min_side}x{min_side} px"
    return None


# --------------------------------------------------------------------------- loading
def to_rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im = im.copy()
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im.seek(0)                      # first frame of GIF/animated WebP
        im.load()
        return to_rgb(im)


def _frame_cache_path(ctx: Context | None, material: Material, n: int) -> Path:
    return interim_dir(ctx) / "frames" / f"{material.material_id}_f{n:03d}.jpg"


@contextlib.contextmanager
def _quiet_stderr():
    """Mute native stderr (fd 2) while OpenCV's FFmpeg backend decodes.

    Screen recordings and HLS segments make the h264 decoder print hundreds of harmless lines
    ("co located POCs unavailable", "mmco: unref short failure", "reference picture missing").
    Neither cv2.utils.logging nor OPENCV_FFMPEG_LOGLEVEL set from inside Python silences them
    (the env var only works when exported before the process starts), so fd 2 is redirected to
    os.devnull for the duration of the decode. Python-level errors are unaffected: exceptions are
    raised after stderr is restored. Set FAKECOLLECTOR_VIDEO_LOGS=1 to see decoder output.
    """
    if os.environ.get("FAKECOLLECTOR_VIDEO_LOGS", "").strip() in ("1", "true", "yes"):
        yield
        return
    try:
        sys.stderr.flush()
        saved = os.dup(2)
        null = os.open(os.devnull, os.O_WRONLY)
    except OSError:              # no real fd 2 (e.g. some embedded consoles): just decode
        yield
        return
    os.dup2(null, 2)
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(null)
        os.close(saved)


def sample_video(material: Material, ctx: Context | None) -> tuple[list[Unit], list[str]]:
    """Sample up to `video.max_frames` frames, at least `video.every_s` seconds apart.

    Frames are spread over the whole video (step = max(every_s, duration / max_frames)),
    read by seeking with OpenCV, so a 300+ MB recording is never loaded in full.
    Frames are cached as JPEG in data/interim/frames/ and reused by the next module.
    """
    import cv2  # local import: keeps module importable without OpenCV

    errors: list[str] = []
    path = resolve_path(material, ctx)
    max_frames = int(setting(ctx, "video.max_frames", 12))
    every_s = float(setting(ctx, "video.every_s", 5))
    frames_dir = interim_dir(ctx) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Reuse cached frames if a previous module already sampled this video.
    cached = sorted(frames_dir.glob(f"{material.material_id}_f*.jpg"))
    meta_cache = frames_dir / f"{material.material_id}.times.txt"
    if cached and meta_cache.exists():
        times = [float(x) for x in meta_cache.read_text().split()]
        units = []
        for i, fp in enumerate(cached):
            try:
                units.append(Unit(f"{material.material_id}#f{i}", load_image(fp),
                                  {"frame_index": i, "t_s": times[i] if i < len(times) else None,
                                   "frame_path": str(fp), "video_material_id": material.material_id}))
            except Exception as exc:
                errors.append(f"frame cache read failed: {exc}")
        if units:
            return units, errors

    with _quiet_stderr():  # decoder noise only; see _quiet_stderr
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return [], [f"video: cannot open {path.name}"]
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            n_total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            duration = n_total / fps if fps > 0 and n_total > 0 else 0.0
            if duration > 0:
                step = max(every_s, duration / max_frames)
                # sample mid-points of each step so the first frame is not a black intro
                targets = [min(duration - 0.05, step * (i + 0.5)) for i in range(max_frames)]
                targets = [t for t in targets if t >= 0][:max_frames]
                if duration < step:
                    targets = [duration / 2]
            else:
                targets = [every_s * i for i in range(max_frames)]

            units: list[Unit] = []
            times: list[float] = []
            for t in targets:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    if duration <= 0:
                        break           # unknown duration: stop at end of stream
                    continue
                img = to_rgb(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                n = len(units)
                fp = _frame_cache_path(ctx, material, n)
                try:
                    img.save(fp, "JPEG", quality=90)
                except Exception as exc:
                    errors.append(f"frame save failed: {exc}")
                units.append(Unit(f"{material.material_id}#f{n}", img,
                                  {"frame_index": n, "t_s": round(t, 2), "frame_path": str(fp),
                                   "video_material_id": material.material_id,
                                   "video_duration_s": round(duration, 2)}))
                times.append(round(t, 2))
            if units:
                meta_cache.write_text(" ".join(str(x) for x in times))
            else:
                errors.append("video: no frames decoded")
            return units, errors
        finally:
            cap.release()


def units_for(material: Material, ctx: Context | None) -> tuple[list[Unit], list[str]]:
    """Return analysable pictures for a material (1 for images, N for videos, 0 if skipped)."""
    reason = selection_reason(material, ctx)
    if reason is not None:
        return [], [reason]
    path = resolve_path(material, ctx)
    if material.kind == "video" or is_video_path(path):
        try:
            return sample_video(material, ctx)
        except Exception as exc:
            return [], [f"video: {type(exc).__name__}: {exc}"]
    try:
        img = load_image(path)
    except Exception as exc:
        return [], [f"image: {type(exc).__name__}: {exc}"]
    return [Unit(material.material_id, img, {"width": img.width, "height": img.height})], []


def stable_id(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def iter_files(root: Path) -> Iterator[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def pil_to_bgr(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img.convert("RGB"))
    return arr[:, :, ::-1].copy()
