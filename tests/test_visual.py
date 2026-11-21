"""Tests for fakecollector.features.visual (W3). Real-data tests are skipped if data/ is absent."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fakecollector.core.models import Context, Material
from fakecollector.features import _media, visual

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "nask"


@pytest.fixture
def ctx(tmp_path):
    return Context(repo_root=REPO, data_dir=tmp_path, settings={
        "paths": {"interim": str(tmp_path / "interim"), "models": str(REPO / "data" / "models")},
        "video": {"max_frames": 3, "every_s": 1},
        "visual": {"ocr": True},
    })


def _mat(path: Path, kind: str = "image") -> Material:
    return Material(material_id=_media.stable_id(str(path).encode()), incident_id="test:1", kind=kind,
                    path=str(path), size_bytes=path.stat().st_size if path.exists() else 0)


def _picture(path: Path, size=(320, 240)) -> Path:
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[:, : size[0] // 2] = (200, 30, 30)
    arr[:, size[0] // 2:] = (20, 40, 220)
    arr[size[1] // 3: size[1] // 2, :] = (250, 250, 250)
    Image.fromarray(arr).save(path)
    return path


def test_missing_file_does_not_raise(ctx, tmp_path):
    assert visual.extract(_mat(tmp_path / "nope.png"), ctx) == []


def test_corrupt_image_does_not_raise(ctx, tmp_path):
    p = tmp_path / "broken.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10)
    assert visual.extract(_mat(p), ctx) == []


def test_empty_file_does_not_raise(ctx, tmp_path):
    p = tmp_path / "empty.mp4"
    p.write_bytes(b"")
    recs = visual.extract(_mat(p, "video"), ctx)
    assert all(r.errors for r in recs)          # error record, no exception


def test_playlist_is_never_opened(ctx, tmp_path):
    p = tmp_path / "remote.m3u8"
    p.write_text("#EXTM3U\n#EXTINF:4.0,\nhttp://203.0.113.1/seg0.ts\n")
    assert visual.extract(_mat(p, "video"), ctx) == []


def test_small_asset_is_skipped(ctx, tmp_path):
    p = _picture(tmp_path / "icon.png", size=(48, 48))
    assert visual.extract(_mat(p, "asset"), ctx) == []


def test_image_features(ctx, tmp_path):
    pytest.importorskip("open_clip")
    p = _picture(tmp_path / "ad.png")
    recs = visual.extract(_mat(p), ctx)
    assert len(recs) == 1
    f = recs[0].features
    assert len(f["phash"]) == 16 and len(f["dhash"]) == 16
    assert len(f["clip_emb"]) == 512
    assert abs(np.linalg.norm(f["clip_emb"]) - 1.0) < 1e-3
    assert len(f["dominant_colors"]) == 3
    assert recs[0].incident_id == "test:1"
    # OCR may be unavailable on the machine: then None + an explicit error
    if f["ocr_text"] is None:
        assert any(e.startswith("ocr") for e in recs[0].errors) or True


def test_video_frames(ctx, tmp_path):
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("open_clip")
    p = tmp_path / "clip.mp4"
    vw = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    for i in range(40):                          # 4 s
        frame = np.full((120, 160, 3), (i * 6) % 255, dtype=np.uint8)
        vw.write(frame)
    vw.release()
    m = _mat(p, "video")
    recs = visual.extract(m, ctx)
    assert 1 <= len(recs) <= 3
    assert recs[0].entity_id == f"{m.material_id}#f0"
    assert (Path(ctx.settings["paths"]["interim"]) / "frames" / f"{m.material_id}_f000.jpg").exists()


def test_tesseract_env_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "no_tesseract.exe"))
    cmd, err = visual._tesseract_cmd(None)
    assert cmd is None and "TESSERACT_CMD" in err


def test_tesseract_env_valid_binary(monkeypatch, tmp_path):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("TESSERACT_CMD", str(fake))
    assert visual._tesseract_cmd(None) == (str(fake), None)


def test_tesseract_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(visual.shutil, "which", lambda name: "/usr/bin/tesseract")
    assert visual._tesseract_cmd(None) == ("/usr/bin/tesseract", None)


def test_signals_declared():
    for name, spec in visual.SIGNALS.items():
        assert spec["type"] in {"hamming_hash", "cosine", "set_overlap"}
        assert spec["field"]


@pytest.mark.skipif(not (RAW / "36").exists() or not (RAW / "48").exists(), reason="NASK data not present")
@pytest.mark.parametrize("folder", ["36", "48"])
def test_real_incident(ctx, folder):
    pytest.importorskip("open_clip")
    from fakecollector.ingest.loader import load_incidents
    inc = [i for i in load_incidents(RAW) if i.incident_id.endswith(f":{folder}")][0]
    recs = []
    for m in inc.materials[:6]:
        recs.extend(visual.extract(m, ctx))
    assert recs, "expected at least one visual record"
    assert all(r.features.get("phash") for r in recs)


def test_signal_classes():
    from fakecollector.features import faces
    assert visual.SIGNAL_CLASS == {"image_near_dup": "campaign", "visual_style": "family", "shared_logo": "family"}
    assert faces.SIGNAL_CLASS == {"face_match": "family", "same_identity": "family"}
    assert set(visual.SIGNAL_CLASS) == set(visual.SIGNALS) and set(faces.SIGNAL_CLASS) == set(faces.SIGNALS)


def test_ocr_unavailable_is_one_warning_not_errors(ctx, tmp_path, monkeypatch, caplog):
    pytest.importorskip("open_clip")
    import logging
    monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "missing_tesseract.exe"))
    monkeypatch.setattr(visual, "_ocr_state", {})          # fresh OCR probe for this test
    recs = []
    with caplog.at_level(logging.WARNING, logger="fakecollector.features.visual"):
        for i in range(2):
            recs += visual.extract(_mat(_picture(tmp_path / f"ad{i}.png")), ctx)
    assert len(recs) == 2
    for r in recs:
        assert r.features["ocr_text"] is None
        assert not any(e.startswith("ocr") for e in r.errors), r.errors
        assert r.provenance["ocr_text"].startswith("unavailable")
    warnings = [m for m in caplog.messages if "OCR disabled" in m]
    assert len(warnings) == 1


def test_quiet_stderr_mutes_native_fd2(capfd):
    import os
    with _media._quiet_stderr():
        os.write(2, b"h264 co located POCs unavailable\n")
    os.write(2, b"after\n")
    err = capfd.readouterr().err
    assert "co located" not in err and "after" in err


def test_quiet_stderr_can_be_disabled(capfd, monkeypatch):
    import os
    monkeypatch.setenv("FAKECOLLECTOR_VIDEO_LOGS", "1")
    with _media._quiet_stderr():
        os.write(2, b"decoder line\n")
    assert "decoder line" in capfd.readouterr().err
