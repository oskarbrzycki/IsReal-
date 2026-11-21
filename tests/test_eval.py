"""Evaluation tests on synthetic data (W5). Run: pytest tests/test_eval.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from fakecollector.core.config import make_context
from fakecollector.engine import correlate as co
from fakecollector.engine.features import aggregate_incidents, normalize_signals
from fakecollector.eval import experiments as ex
from fakecollector.eval.metrics import load_labels, pairwise_prf
from fakecollector.eval.run import evaluate
from tests.fixtures.synthetic import STOPLIST, SYNTH_SIGNALS, make_synthetic, write_synthetic

ROOT = Path(__file__).resolve().parents[1]


def test_pairwise_metrics():
    truth = {"a": "X", "b": "X", "c": "Y", "d": "Z"}
    perfect = pairwise_prf(truth, {"a": "1", "b": "1", "c": "2", "d": "3"})
    assert perfect["f1"] == 1.0 and perfect["ari"] == 1.0
    merged = pairwise_prf(truth, {"a": "1", "b": "1", "c": "1", "d": "3"})
    assert merged["precision"] < 1.0 and merged["recall"] == 1.0
    split = pairwise_prf(truth, {"a": "1", "b": "2", "c": "3", "d": "4"})
    assert split["recall"] == 0.0


def test_load_labels_real_file():
    from fakecollector.eval.metrics import load_family_labels
    truth = load_labels(ROOT / "eval" / "labels.yaml")
    assert truth["nask:1"] == truth["nask:3"] == "A"
    assert truth["nask:5"] != truth["nask:10"]            # singletons are separate campaigns
    fam = load_family_labels(ROOT / "eval" / "labels.yaml", truth)
    assert fam["nask:1"] == fam["nask:48"] == fam["nask:61"]       # family hypothesis (W4)
    assert fam["nask:5"] != fam["nask:10"] and fam["nask:5"] != fam["nask:1"]


@pytest.fixture(scope="module")
def synth():
    ctx = make_context(ROOT)
    cfg = co.engine_cfg(ctx.settings)
    signals = normalize_signals(SYNTH_SIGNALS, cfg["signal_params"], cfg["signal_class"])
    tables, truth = make_synthetic()
    feats = aggregate_incidents(tables, signals, STOPLIST)
    return cfg, signals, tables, truth, feats


def test_experiments(synth):
    cfg, signals, tables, truth, feats = synth
    ftruth = {i: ("F:K23" if t in ("K2", "K3") else f"F:{t}") for i, t in truth.items()}
    rows = ex.ablation(feats, signals, cfg, truth, ftruth)
    assert "fam_f1" in rows[0]
    assert rows[0]["variant"] == "all signals" and rows[0]["f1"] >= 0.9
    assert any(r["variant"].startswith("without module") for r in rows)
    pv = ex.pseudo_variants(tables, signals, STOPLIST, cfg, truth)
    assert pv["n_split_incidents"] == 3 and pv["sibling_recall"] is not None
    d = ex.dropout(feats, signals, cfg, truth, p=0.3, trials=3)
    assert 0.0 <= d["f1_mean"] <= 1.0
    o = ex.open_set(feats, signals, cfg, truth, ftruth)
    assert o["loco_new_rate"] == 1.0 and o["loo_assign_accuracy"] >= 0.8


def test_evaluate_writes_report(tmp_path):
    write_synthetic(tmp_path / "data" / "features", tmp_path / "labels.yaml")
    ctx = make_context(ROOT, overrides={"paths": {k: str(tmp_path / "data" / k) for k in
                                                  ("features", "interim", "graph", "cache")}})
    ctx.settings["stoplist"] = STOPLIST
    path = evaluate(ctx, labels_path=tmp_path / "labels.yaml", signals=SYNTH_SIGNALS,
                    out_dir=tmp_path / "reports", dropout_trials=2)
    text = path.read_text(encoding="utf-8")
    for section in ("Wynik bazowy", "Poziom rodzin", "Ablacja", "Pseudo-warianty", "Open-set", "Odporność"):
        assert section in text


def test_evaluate_without_data_does_not_crash(tmp_path):
    ctx = make_context(ROOT, overrides={"paths": {k: str(tmp_path / k) for k in
                                                  ("features", "interim", "graph", "cache")}})
    path = evaluate(ctx, signals=SYNTH_SIGNALS, out_dir=tmp_path / "reports")
    assert "Za mało danych" in path.read_text(encoding="utf-8")


def test_dropout_is_reproducible_regardless_of_dict_order(synth):
    """Same seed -> same numbers, even if the incidents arrive in a different order (hash randomization)."""
    import random
    cfg, signals, _, truth, feats = synth
    keys = list(feats)
    random.Random(3).shuffle(keys)
    shuffled = {k: feats[k] for k in keys}
    a = ex.dropout(feats, signals, cfg, truth, p=0.3, trials=5, seed=0)
    b = ex.dropout(shuffled, signals, cfg, truth, p=0.3, trials=5, seed=0)
    assert a == b and a["seed"] == 0


def test_aggregate_incidents_has_sorted_ids(synth):
    _, _, _, _, feats = synth
    assert list(feats) == sorted(feats)


def test_family_variant_check_structure(synth):
    cfg, signals, _, truth, feats = synth
    ftruth = {i: ("F:K23" if t in ("K2", "K3") else f"F:{t}") for i, t in truth.items()}
    fv = ex.family_variant_check(feats, signals, cfg, truth, ftruth)
    assert set(fv["conditions"]) == {"family_precision_1.0", "open_set_new_rate_100%", "singletons_100%",
                                     "no_new_false_family_edges", "campaign_edges_unchanged"}
    assert fv["conditions"]["campaign_edges_unchanged"] is True             # the variant never touches campaigns
    assert fv["current"]["family_precision"] is not None and "campaign_edges" not in fv["current"]
    assert isinstance(fv["conditions_met"], bool)
