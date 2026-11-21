"""Download every model into the image at build time (owner W4).

Runs once during `docker build`, so the running container never needs the
network for models and works with OFFLINE=true. It calls the feature modules'
own loaders, which guarantees the files land exactly where the code later
looks for them (paths.models for YuNet/SFace and CLIP, HF_HOME for e5).

Exit code is non-zero if a model fails, so a broken image never ships silently.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def step(name: str, fn) -> bool:
    started = time.time()
    try:
        detail = fn()
        print(f"[models] OK   {name:28s} {time.time() - started:6.1f}s  {detail or ''}", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 - report every failure, then fail the build
        print(f"[models] FAIL {name:28s} {type(exc).__name__}: {exc}", flush=True)
        return False


def main() -> int:
    from fakecollector.core.config import make_context

    ctx = make_context()
    models_dir = Path(ctx.repo_root) / ctx.settings.get("paths", {}).get("models", "data/models")
    print(f"[models] paths.models -> {models_dir}", flush=True)
    print(f"[models] HF_HOME      -> {os.environ.get('HF_HOME', '(default ~/.cache)')}", flush=True)

    def faces():
        from fakecollector.features import faces as faces_mod

        det, rec = faces_mod.ensure_models(ctx, download=True)
        return f"{det.name}, {rec.name}"

    def clip():
        from fakecollector.features import visual

        loaded = visual._load_clip(ctx)
        return loaded.get("name", "")

    def e5():
        from sentence_transformers import SentenceTransformer

        from fakecollector.features import text

        model = SentenceTransformer(text.EMB_MODEL_DEFAULT, device="cpu")
        dim = model.get_sentence_embedding_dimension()
        return f"{text.EMB_MODEL_DEFAULT} dim={dim}"

    results = [
        step("faces: YuNet + SFace", faces),
        step("visual: CLIP ViT-B-32", clip),
        step("text: multilingual-e5-small", e5),
    ]
    if not all(results):
        print("[models] at least one model failed - aborting the build", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
