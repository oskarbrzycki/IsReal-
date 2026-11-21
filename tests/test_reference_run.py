"""Tests for env path overrides (core/config.py) and scripts/reference_run.py helpers (W5)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fakecollector.core.config import make_context, resolve_path

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ MODELS_DIR / DATA_DIR
def test_default_models_path(monkeypatch):
    monkeypatch.delenv("MODELS_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    ctx = make_context(ROOT)
    assert resolve_path(ctx, "models") == ROOT / "data" / "models"
    assert resolve_path(ctx, "features") == ROOT / "data" / "features"


def test_models_dir_env_overrides_paths_models(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "m"))
    ctx = make_context(ROOT)
    assert ctx.settings["paths"]["models"] == str(tmp_path / "m")
    assert resolve_path(ctx, "features") == ROOT / "data" / "features"      # others untouched


def test_data_dir_env_relocates_all_data_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("MODELS_DIR", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    ctx = make_context(ROOT)
    for key, sub in (("raw", "raw/nask"), ("interim", "interim"), ("features", "features"),
                     ("graph", "graph"), ("cache", "cache"), ("models", "models")):
        assert resolve_path(ctx, key) == tmp_path / "d" / sub
    assert ctx.data_dir == tmp_path / "d"


def test_models_dir_wins_over_data_dir_and_overrides_win_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path / "baked"))
    ctx = make_context(ROOT)
    assert resolve_path(ctx, "models") == tmp_path / "baked"
    ctx = make_context(ROOT, overrides={"paths": {"features": str(tmp_path / "f"), "models": str(tmp_path / "mm")}})
    assert resolve_path(ctx, "features") == tmp_path / "f"                  # explicit argument beats env
    assert resolve_path(ctx, "models") == tmp_path / "mm"
    assert resolve_path(ctx, "graph") == tmp_path / "d" / "graph"


def test_relative_env_paths_resolve_against_repo_root(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("MODELS_DIR", "weights")
    assert resolve_path(make_context(ROOT), "models") == ROOT / "weights"


def test_empty_env_values_are_ignored(monkeypatch):
    monkeypatch.setenv("MODELS_DIR", "")
    monkeypatch.setenv("DATA_DIR", "")
    assert resolve_path(make_context(ROOT), "models") == ROOT / "data" / "models"


# ------------------------------------------------------------------ reference_run helpers
def _load_script():
    spec = importlib.util.spec_from_file_location("reference_run", ROOT / "scripts" / "reference_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SUMMARY = {
    "n_incidents": 10,
    "campaign": {"precision": 1.0, "recall": 0.5, "f1": 0.6667, "ari": 0.6457, "n_clusters": 8, "fp": 0, "fn": 2, "tp": 2},
    "family": {"precision": 1.0, "recall": 1.0, "f1": 1.0, "ari": 1.0, "n": 10},
    "ablation": [{"variant": "all signals", "f1": 0.67, "ari": 0.65, "fam_f1": 1.0, "fam_ari": 1.0},
                 {"variant": "without identical-file signals (shared_assets, same_material)", "f1": 0.4, "ari": 0.38,
                  "fam_f1": 0.57, "fam_ari": 0.51}],
    "pseudo_variants": {"n_split_incidents": 9, "n_pseudo_incidents": 24, "sibling_recall": 0.7826, "f1": 0.6753},
    "dropout": {"p": 0.3, "trials": 20, "f1_mean": 0.56, "f1_min": 0.0},
    "open_set": {"loco_new_rate": 1.0, "loco_n": 5, "loco_family_hit_rate": 0.8, "loco_family_n": 5,
                 "loo_assign_accuracy": 0.8, "loo_assign_n": 5, "loo_singleton_new_rate": 1.0, "loo_singleton_n": 5},
}


def test_parse_ingest_and_features_output():
    rr = _load_script()
    assert rr.parse_ingest("ingest: 10 incidents, 313 materials, 0 with errors -> /x/incidents.jsonl") == \
        {"incidents": 10, "materials": 313, "errors": 0}
    assert rr.parse_ingest("garbage") == {}
    out = ('INFO something\n{"module": "infra", "records": 25, "with_errors": 0, "skipped": 0, "seconds": 1.3, "out": "x"}\n'
           '{"module": "visual", "records": 179, "with_errors": 179, "skipped": 142, "seconds": 15.0, "out": "y"}\nnot json\n')
    rows = rr.parse_features(out)
    assert [r["module"] for r in rows] == ["infra", "visual"] and rows[1]["with_errors"] == 179


def test_render_summary_table():
    rr = _load_script()
    steps = [{"name": "ingest", "ok": True, "seconds": 1.2, "returncode": 0},
             {"name": "evaluate", "ok": False, "seconds": 3.0, "returncode": 1}]
    feats = [{"module": "visual", "records": 179, "with_errors": 179, "skipped": 142, "seconds": 15.0}]
    text = rr.render(steps, {"ingest": "10 incydentów"}, feats, SUMMARY, "2026-11-21 18:00", online=False)
    for needle in ("Przebieg referencyjny", "BŁĄD (kod 1)", "Moduły z błędami na rekordach: visual",
                   "Kampanie: precyzja / recall", "1.00 / 0.50", "Rodziny: F1 / ARI", "80%", "0.57", "0.56 / 0.00"):
        assert needle in text, needle
    assert "Brak" in rr.render(steps, {}, [], None, "x", online=False)      # no summary -> clear message


# ------------------------------------------------------------------ CLI ingest defaults honour DATA_DIR (W5, W1's cli.py)
def _cli(monkeypatch, tmp_path, *argv, data_dir=True):
    import json

    from fakecollector import cli

    for var in ("MODELS_DIR", "DATA_DIR"):
        monkeypatch.delenv(var, raising=False)
    if data_dir:
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
        folder = tmp_path / "d" / "raw" / "nask" / "7"
        folder.mkdir(parents=True)
        (folder / "page.txt").write_text("hello", encoding="utf-8")
    rc = cli.main(["ingest", *argv])
    return rc, json


def test_ingest_default_paths_follow_data_dir(monkeypatch, tmp_path, capsys):
    rc, _ = _cli(monkeypatch, tmp_path, "--source", "nask")
    assert rc == 0
    out = tmp_path / "d" / "interim" / "incidents.jsonl"
    assert out.exists() and "nask:7" in out.read_text(encoding="utf-8")
    assert str(out) in capsys.readouterr().out


def test_ingest_explicit_args_win_over_data_dir(monkeypatch, tmp_path):
    src = tmp_path / "other" / "9"
    src.mkdir(parents=True)
    (src / "page.txt").write_text("x", encoding="utf-8")
    explicit_out = tmp_path / "custom.jsonl"
    rc, _ = _cli(monkeypatch, tmp_path, "--data", str(tmp_path / "other"), "--out", str(explicit_out))
    assert rc == 0
    text = explicit_out.read_text(encoding="utf-8")
    assert "nask:9" in text and "nask:7" not in text
    assert not (tmp_path / "d" / "interim" / "incidents.jsonl").exists()


def test_ingest_default_without_env_is_repo_data(monkeypatch, tmp_path):
    from fakecollector import cli

    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("MODELS_DIR", raising=False)
    assert cli._config_path("raw") == ROOT / "data" / "raw" / "nask"
    assert cli._config_path("interim") == ROOT / "data" / "interim"
