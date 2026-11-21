"""Tests for fakecollector.features.faces (W3). Real-data tests are skipped if data/ is absent."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fakecollector.core.models import Context, Material
from fakecollector.features import _media, faces

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "nask"
MODELS = REPO / "data" / "models"
have_models = (MODELS / faces.YUNET_FILE).exists() and (MODELS / faces.SFACE_FILE).exists()


@pytest.fixture
def ctx(tmp_path):
    return Context(repo_root=REPO, data_dir=tmp_path, settings={
        "paths": {"interim": str(tmp_path / "interim"), "models": str(MODELS)},
        "faces": {"no_download": True},
    })


def _mat(path: Path, kind: str = "image") -> Material:
    return Material(material_id=_media.stable_id(str(path).encode()), incident_id="test:1", kind=kind,
                    path=str(path), size_bytes=path.stat().st_size if path.exists() else 0)


def test_missing_file_does_not_raise(ctx, tmp_path):
    assert faces.extract(_mat(tmp_path / "nope.jpg"), ctx) == []


def test_corrupt_file_does_not_raise(ctx, tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)
    assert faces.extract(_mat(p), ctx) == []


def test_missing_models_gives_error_not_exception(tmp_path):
    ctx = Context(repo_root=REPO, data_dir=tmp_path, settings={
        "paths": {"interim": str(tmp_path / "i"), "models": str(tmp_path / "no_models")},
        "faces": {"no_download": True}})
    p = tmp_path / "a.png"
    Image.fromarray(np.full((200, 200, 3), 128, dtype=np.uint8)).save(p)
    saved = dict(faces._models)
    faces._models.clear()
    try:
        recs = faces.extract(_mat(p), ctx)
    finally:
        faces._models.clear()
        faces._models.update(saved)
    assert len(recs) == 1 and recs[0].features["faces"] is None and recs[0].errors


@pytest.mark.skipif(not have_models, reason="YuNet/SFace models not downloaded")
def test_no_face_on_flat_image(ctx, tmp_path):
    p = tmp_path / "flat.png"
    Image.fromarray(np.full((300, 300, 3), 200, dtype=np.uint8)).save(p)
    recs = faces.extract(_mat(p), ctx)
    assert recs[0].features["face_count"] == 0 and recs[0].features["faces"] is None


def test_signals_declared():
    assert faces.SIGNALS["face_match"]["field"] == "faces.emb"
    assert faces.SIGNALS["same_identity"]["field"] == "faces.identity"


@pytest.mark.skipif(not have_models or not (RAW / "1").exists() or not (RAW / "48").exists(),
                    reason="NASK data or models not present")
@pytest.mark.parametrize("folder", ["1", "48"])
def test_real_incident_has_faces(ctx, folder):
    from fakecollector.ingest.loader import load_incidents
    inc = [i for i in load_incidents(RAW) if i.incident_id.endswith(f":{folder}")][0]
    recs = [r for m in inc.materials if m.kind != "video" for r in faces.extract(m, ctx)]
    assert recs
    total = sum(r.features["face_count"] or 0 for r in recs)
    assert total >= 1
    for r in recs:
        for f in r.features["faces"] or []:
            assert 0.0 <= f["quality"] <= 1.0
            if f["emb"] is not None:
                assert len(f["emb"]) == 128


def test_identity_rules_noise_singleton_named():
    saved = dict(faces._ref)
    try:
        faces._ref.clear()
        faces._ref.update(centroids=np.eye(4, dtype=np.float32), cluster_ids=["P001", "P002", "P003", "P004"],
                          sizes=[3, 1, 2, 5], names={"P003": "noise", "P004": "Jan Testowy"})
        e = np.eye(4, dtype=np.float32)
        assert faces.identify(e[0], None)[0] == "face:P001"      # unnamed cluster
        assert faces.identify(e[1], None)[0] is None             # single-face cluster
        assert faces.identify(e[2], None)[0] is None             # noise
        assert faces.identify(e[3], None)[0] == "Jan Testowy"    # named
    finally:
        faces._ref.clear()
        faces._ref.update(saved)


def test_rebuild_keeps_previous_ids():
    from fakecollector.features.face_ref import match_previous_ids
    old = np.eye(3, dtype=np.float32)
    new = np.array([[0, 0.99, 0.14], [0.98, 0.2, 0], [0, 0, -1]], dtype=np.float32)
    new /= np.linalg.norm(new, axis=1, keepdims=True)
    assert match_previous_ids(new, old, ["P001", "P002", "P003"]) == ["P002", "P001", None]
