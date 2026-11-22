"""Regression tests for the "foreign juror" run: odd folder names/contents must never crash the pipeline."""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from fakecollector import cli
from fakecollector.ingest.loader import build_incident, load_incidents

ROOT = Path(__file__).resolve().parents[1]


def test_ingest_missing_folder_is_a_clear_message_not_a_traceback(tmp_path, capsys):
    assert cli.main(["ingest", "--data", str(tmp_path / "nie_ma")]) == 2
    assert "nie znaleziono" in capsys.readouterr().err


def test_analyze_missing_path_is_a_clear_message_not_a_traceback(tmp_path, capsys):
    assert cli.main(["analyze", str(tmp_path / "nie_ma.zip")]) == 2
    assert "nie znaleziono" in capsys.readouterr().err


def test_odd_folders_are_ingested_and_unknown_ones_warned(tmp_path, caplog):
    raw = tmp_path / "raw"
    (raw / "zgłoszenie ż ó ł").mkdir(parents=True)
    (raw / "zgłoszenie ż ó ł" / "Zdjęcie śćźż.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    (raw / "pusty_folder").mkdir()
    (raw / "pusty_plik").mkdir()
    (raw / "pusty_plik" / "a.html").write_bytes(b"")
    (raw / "zepsuty_zip").mkdir()
    (raw / "zepsuty_zip" / "p.zip").write_bytes(b"PK\x03\x04 not a zip")
    (raw / "tylko_url").mkdir()
    (raw / "tylko_url" / "link.txt").write_text("https://scam.example/x\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        incidents = load_incidents(raw)
    assert {i.incident_id for i in incidents} == {"nask:zgłoszenie ż ó ł", "nask:pusty_folder", "nask:pusty_plik",
                                                  "nask:zepsuty_zip", "nask:tylko_url"}
    warned = caplog.text
    for name in ("pusty_folder", "pusty_plik", "zepsuty_zip", "tylko_url"):
        assert f"ingest: {name}: brak rozpoznanych materiałów" in warned
    assert "ingest: zgłoszenie ż ó ł:" not in warned          # a real picture is fine


def test_nested_submission_is_one_incident(tmp_path):
    deep = tmp_path / "inne" / "a" / "b" / "zgl"
    deep.mkdir(parents=True)
    (deep / "index.html").write_text("<html><title>x</title></html>", encoding="utf-8")
    inc = build_incident(tmp_path / "inne", "nask:inne", "nask")
    assert any(m.kind == "html" for m in inc.materials)


def test_evaluate_without_labels_says_so(tmp_path):
    from fakecollector.core.config import make_context
    from fakecollector.eval.run import evaluate

    ctx = make_context(ROOT, overrides={"paths": {k: str(tmp_path / k) for k in
                                                  ("features", "interim", "graph", "cache")}})
    text = evaluate(ctx, labels_path=tmp_path / "brak.yaml", out_dir=tmp_path / "reports").read_text(encoding="utf-8")
    assert "Brak etykiet: metryki pominięte" in text


def test_reference_run_default_data_follows_config():
    spec = importlib.util.spec_from_file_location("reference_run", ROOT / "scripts" / "reference_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "--data" not in mod.ingest_command("python", None)
    assert mod.ingest_command("python", "x")[-2:] == ["--data", "x"]


def test_reference_run_without_labels_is_success_with_message():
    spec = importlib.util.spec_from_file_location("reference_run2", ROOT / "scripts" / "reference_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    steps = [{"name": n, "ok": True, "seconds": 0.1} for n in ("ingest", "features", "correlate", "evaluate")]
    text = mod.render(steps, {}, [], None, "2026-01-01 00:00", False)
    assert "Brak etykiet: metryki pominięte" in text
