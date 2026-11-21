"""Engine tests on synthetic data (W5). Run: pytest tests/test_engine.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from fakecollector.core.config import make_context
from fakecollector.engine import cluster as cl
from fakecollector.engine import correlate as co
from fakecollector.engine import similarity as sim
from fakecollector.engine.api import analyze_records
from fakecollector.engine.assign import assign
from fakecollector.engine.features import (Stoplist, aggregate_incidents, aggregate_records,
                                           aggregate_values, is_missing, normalize_signals)
from fakecollector.engine.pipeline import run, run_from_disk
from fakecollector.eval.metrics import pairwise_prf
from tests.fixtures.synthetic import STOPLIST, SYNTH_SIGNALS, make_synthetic, write_synthetic

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def setup():
    ctx = make_context(ROOT)
    cfg = co.engine_cfg(ctx.settings)
    signals = normalize_signals(SYNTH_SIGNALS, cfg["signal_params"], cfg["signal_class"])
    tables, truth = make_synthetic()
    feats = aggregate_incidents(tables, signals, STOPLIST)
    return ctx, cfg, signals, tables, truth, feats


# ------------------------------------------------------------------ helpers / similarity
def test_is_missing():
    assert all(is_missing(x) for x in [None, float("nan"), "", "  ", [], np.array([]), {}])
    assert not any(is_missing(x) for x in [0, 0.0, "a", [0], np.array([0])])


def test_similarity_types():
    v = [np.array([1.0, 0.0], dtype=np.float32)]
    assert sim.compute({"type": "cosine"}, v, [np.array([1.0, 0.0], dtype=np.float32)])[0] == pytest.approx(1.0)
    assert sim.compute({"type": "cosine"}, v, [np.array([0.0, 1.0], dtype=np.float32)])[0] == pytest.approx(0.0)
    assert sim.compute({"type": "set_overlap"}, frozenset("ab"), frozenset("bc"))[0] == pytest.approx(1 / 3)
    many, few = frozenset(map(str, range(40))), frozenset(map(str, range(8)))
    assert sim.compute({"type": "set_overlap"}, many, few)[0] == pytest.approx(8 / 40)            # Jaccard
    assert sim.compute({"type": "set_overlap", "metric": "count", "saturate": 4}, many, few)[0] == 1.0
    assert sim.compute({"type": "set_overlap", "metric": "count", "saturate": 4}, many, frozenset("0"))[0] == 0.25
    assert sim.compute({"type": "exact"}, frozenset("a"), frozenset("b"))[0] == 0.0
    assert sim.compute({"type": "hamming_hash", "floor": 0.0}, [0b1111], [0b1111])[0] == 1.0
    assert sim.compute({"type": "numeric_close", "tol": 10}, [0.0], [5.0])[0] == pytest.approx(0.5)
    assert sim.compute({"type": "set_overlap"}, None, frozenset("a"))[0] is None   # missing side


def test_aggregation_rules_and_stoplist():
    stop = Stoplist(STOPLIST)
    s = aggregate_values({"type": "set_overlap"}, [["a.example", "x.cloudflare.com"], np.array(["b"])], stop)
    assert s == frozenset({"a.example", "x.cloudflare.com", "b"})
    s = aggregate_values({"type": "set_overlap"}, [[f"https://{STOPLIST['domains'][0]}/x.js", "ok"]], stop)
    assert s == frozenset({"ok"})                       # stoplisted CDN dropped
    assert aggregate_values({"type": "set_overlap"}, [[f"https://{STOPLIST['domains'][0]}/x.js"]], stop) is None
    vecs = aggregate_values({"type": "cosine"}, [[1.0, 2.0], [[1.0, 0.0], [0.0, 1.0]], [0.0, 0.0]], stop)
    assert len(vecs) == 3                               # zero vector dropped, nested flattened
    assert aggregate_values({"type": "hamming_hash"}, ["ff", 3], stop) == [255, 3]


def test_dotted_field_for_faces():
    tbl = {"faces": pd.DataFrame([{"entity_id": "m1", "level": "material", "module": "faces", "incident_id": "i1",
                                   "faces": [{"emb": [1.0, 0.0]}, {"emb": [0.0, 1.0]}]}])}
    sigs = {"face_match": {"module": "faces", "type": "cosine", "field": "faces.emb"}}
    out = aggregate_incidents(tbl, sigs)
    assert len(out["i1"]["face_match"]) == 2


# ------------------------------------------------------------------ correlation / clustering
def test_campaign_rule_hard_identifier_or_two_signals(setup):
    _, cfg, signals, _, _, feats = setup
    f = feats["syn:K1-1"]
    # one SOFT signal only (near-duplicate image): no campaign edge ...
    soft = {"image_near_dup": f["image_near_dup"]}
    assert co.score_pair("a", "b", soft, soft, signals, cfg, "campaign") is None
    # ... one HARD identifier alone is enough ...
    hard = {"shared_trackers": f["shared_trackers"]}
    e = co.score_pair("a", "b", hard, hard, signals, cfg, "campaign")
    assert e is not None and e.score == 1.0
    # ... and two distinct soft campaign signals are enough as well
    two = {"image_near_dup": f["image_near_dup"], "text_near_dup": f["text_near_dup"]}
    assert co.score_pair("a", "b", two, two, signals, cfg, "campaign") is not None


def test_demoted_pair_goes_to_family_with_explanation(setup):
    """The 3-61 case: the only campaign evidence is a near-duplicate image -> family edge + reason."""
    _, cfg, signals, _, _, feats = setup
    f = feats["syn:K1-1"]
    pair = {"image_near_dup": f["image_near_dup"], "text_semantic": f["text_semantic"]}
    assert co.score_pair("a", "b", pair, pair, signals, cfg, "campaign") is None
    fam = co.score_pair("a", "b", pair, pair, signals, cfg, "family")
    assert fam is not None
    rule = [r for r in fam.reasons if r.signal == co.RULE_SIGNAL]
    assert rule and "za mało twardych dowodów" in rule[0].detail and rule[0].weight == 0.0
    assert any(r.signal == "image_near_dup" for r in fam.reasons)      # demoted, still visible


def test_duplicate_signal_name_is_hard_error(tmp_path, monkeypatch):
    import fakecollector.features as pkg
    from fakecollector.engine.features import collect_signals
    for n in ("zz_dup_a", "zz_dup_b"):
        (tmp_path / f"{n}.py").write_text(
            f'MODULE = "{n}"\nSIGNALS = {{"same_thing": {{"type": "exact", "field": "x"}}}}\n')
    monkeypatch.setattr(pkg, "__path__", list(pkg.__path__) + [str(tmp_path)])
    with pytest.raises(ValueError, match="duplicate signal name"):
        collect_signals()


def test_module_label_beats_fallback_label():
    spec = {"type": "exact", "label": "etykieta z modułu"}
    assert "etykieta z modułu" in sim.describe("same_favicon", spec, 1.0, {"shared": ["x"]})
    assert "ten sam favicon" in sim.describe("same_favicon", {"type": "exact"}, 1.0, {"shared": ["x"]})


def test_visual_style_floor_and_face_match_not_overridden():
    import yaml
    params = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))["engine"]["signal_params"]
    assert params["visual_style"]["floor"] == 0.85
    assert "face_match" not in params          # W3 owns the face_match floor


def test_reasons_are_explained_in_polish(setup):
    _, cfg, signals, _, _, feats = setup
    e = co.score_pair("syn:K1-1", "syn:K1-2", feats["syn:K1-1"], feats["syn:K1-2"], signals, cfg)
    assert e is not None and e.reasons
    assert e.reasons[0].detail and e.reasons[0].weight * e.reasons[0].score >= e.reasons[-1].weight * e.reasons[-1].score
    assert any("wspólne identyfikatory" in r.detail for r in e.reasons)


def test_pipeline_recovers_campaigns(setup):
    _, cfg, signals, _, truth, feats = setup
    res = run(feats, signals, cfg)
    pred = cl.labels_of(res.clusters)
    m = pairwise_prf(truth, pred)
    assert m["f1"] >= 0.9 and m["precision"] == 1.0, m
    # the traps must not merge: K1/K2 share only an ASN, S3 only the stoplisted CDN
    assert pred["syn:K1-1"] != pred["syn:K2-1"]
    assert pred["syn:S3"] != pred["syn:K1-1"]


def test_duplicate_groups_are_contracted(setup):
    _, cfg, signals, _, _, feats = setup
    groups = cl.duplicate_groups(feats, [], 0.95, {"syn:K1-1": {"m1"}, "syn:S1": {"m1"}, "syn:S2": {"m2"}})
    assert groups == [["syn:K1-1", "syn:S1"]]
    res = run(feats, signals, cfg, {"syn:K1-1": {"m1"}, "syn:S1": {"m1"}})
    pred = cl.labels_of(res.clusters)
    assert pred["syn:K1-1"] == pred["syn:S1"]


def test_hdbscan_runs(setup):
    _, cfg, signals, _, truth, feats = setup
    res = run(feats, signals, cfg, method="hdbscan")
    assert len(cl.labels_of(res.clusters)) == len(feats)


def test_deterministic(setup):
    _, cfg, signals, _, _, feats = setup
    a = [c.members for c in run(feats, signals, cfg).clusters]
    b = [c.members for c in run(feats, signals, cfg).clusters]
    assert a == b


# ------------------------------------------------------------------ assignment (open set)
def test_assign_known_variant_and_novel(setup):
    _, cfg, signals, _, truth, feats = setup
    held = "syn:K1-3"
    known = {k: v for k, v in feats.items() if k != held}
    res = run(known, signals, cfg)
    a = assign(feats[held], known, res.clusters, signals, cfg, held)
    k1_cluster = next(c.campaign_id for c in res.clusters if "syn:K1-1" in c.members)
    assert a.campaign_id == k1_cluster and a.nearest and a.confidence > cfg["tau_new"]

    # a campaign nobody has seen: remove all of K3 from the known set
    known = {k: v for k, v in feats.items() if not k.startswith("syn:K3")}
    res = run(known, signals, cfg)
    for m in ("syn:K3-1", "syn:K3-2"):
        assert assign(feats[m], known, res.clusters, signals, cfg, m).campaign_id is None


def test_assign_with_no_comparable_data(setup):
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    a = assign({}, feats, res.clusters, signals, cfg, "upload:empty")
    assert a.campaign_id is None and a.confidence == 0.0 and a.nearest == []


# ------------------------------------------------------------------ disk round trip + api
def test_run_from_disk_and_analyze_records(tmp_path):
    truth = write_synthetic(tmp_path / "data" / "features", tmp_path / "labels.yaml")
    ctx = make_context(ROOT, overrides={"paths": {k: str(tmp_path / "data" / k) for k in
                                                  ("features", "interim", "graph", "cache")}})
    ctx.settings["stoplist"] = STOPLIST
    res = run_from_disk(ctx, signals=SYNTH_SIGNALS)
    assert (tmp_path / "data" / "graph" / "edges.parquet").exists()
    assert (tmp_path / "data" / "graph" / "clusters.json").exists()
    assert pairwise_prf(truth, cl.labels_of(res.clusters))["f1"] >= 0.9
    # re-read edges from disk
    path = tmp_path / "data" / "graph" / "edges.parquet"
    assert len(co.load_edges(path, "campaign")) == len(res.edges)
    assert len(co.load_edges(path, "family")) == len(res.family_edges)
    payload = json.loads((tmp_path / "data" / "graph" / "clusters.json").read_text(encoding="utf-8"))
    assert all("family_id" in c for c in payload["clusters"])

    # analyse a "new" incident given as FeatureRecord dicts (a variant of K2)
    rec = [{"module": "text", "features": {"platform_name": "Platforma K2", "entities": ["Osoba K2"]}},
           {"module": "infra", "features": {"domains": ["k2-invest0.example"], "asn": "AS1"}}]
    from fakecollector.engine.pipeline import load_state
    state = load_state(ctx, SYNTH_SIGNALS)
    a = analyze_records(rec, "upload:x", ctx, state)
    k2 = next(c.campaign_id for c in state.clusters if "syn:K2-1" in c.members)
    assert a.campaign_id == k2 and a.status == "known_campaign" and a.family_id is not None
    assert aggregate_records(rec, state.signals)["same_platform_name"] == frozenset({"Platforma K2"})


# ------------------------------------------------------------------ two levels (campaign / family)
def test_signal_classes_applied(setup):
    _, cfg, signals, *_ = setup
    assert signals["shared_trackers"]["class"] == "campaign"
    assert signals["text_semantic"]["class"] == "family"       # from settings.engine.signal_class
    assert signals["dom_template"]["class"] == "family"


def test_levels_use_only_their_signals(setup):
    _, cfg, signals, _, _, feats = setup
    camp = co.score_pair("a", "b", feats["syn:K1-1"], feats["syn:K1-2"], signals, cfg, "campaign")
    fam = co.score_pair("a", "b", feats["syn:K1-1"], feats["syn:K1-3"], signals, cfg, "family")
    assert all(signals[r.signal]["class"] == "campaign" for r in camp.reasons)
    assert all(signals[r.signal]["class"] == "family" for r in fam.reasons)


def test_families_group_campaigns(setup):
    _, cfg, signals, _, truth, feats = setup
    res = run(feats, signals, cfg)
    assert res.families and all(f.family_id.startswith("F") for f in res.families)
    assert set(res.family_of) == {c.campaign_id for c in res.clusters}   # every campaign in a family
    # a campaign is never split across families
    fam_of_inc = cl.family_labels_of(res.clusters, res.families)
    camp_of_inc = cl.labels_of(res.clusters)
    for cid in {c for c in camp_of_inc.values()}:
        assert len({fam_of_inc[i] for i, c in camp_of_inc.items() if c == cid}) == 1


def test_family_link_needs_family_signals_only(setup):
    """Two campaigns without any family-signal edge must stay in separate families."""
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg, )
    only_camp = {n: s for n, s in signals.items() if s["class"] == "campaign"}
    res2 = run(feats, only_camp, cfg)
    assert len(res2.families) == len(res2.clusters)             # no family signals -> 1 campaign = 1 family


def test_assign_new_campaign_known_family(setup):
    """A new incident sharing only family evidence: no campaign, but family recovered."""
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    k1_cid = next(c.campaign_id for c in res.clusters if "syn:K1-1" in c.members)
    donor = feats["syn:K1-1"]
    new = {k: v for k, v in donor.items() if signals[k]["class"] == "family"}
    new["same_platform_name"] = frozenset({"Zupelnie inna platforma"})       # campaign signal differs
    new["shared_trackers"] = frozenset({"999"})
    new["shared_assets"] = frozenset({"other"})
    a = assign(new, feats, res.clusters, signals, cfg, "upload:rel", res.family_of)
    assert a.campaign_id is None and a.status == "new_campaign_known_family"
    assert a.family_id == res.family_of[k1_cid]


def test_assign_new_family_and_dataclass_compat(setup):
    from fakecollector.core.models import Assignment
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    alien = {"shared_trackers": frozenset({"000"}), "same_platform_name": frozenset({"Alien"}),
             "text_semantic": [np.ones(16, dtype=np.float32) * np.array([(-1) ** i for i in range(16)], dtype=np.float32)]}
    a = assign(alien, feats, res.clusters, signals, cfg, "upload:alien", res.family_of)
    assert isinstance(a, Assignment) and a.campaign_id is None and a.status in ("new_family", "new_campaign_known_family")


def test_multi_source_signal_merges_modules():
    sigs = normalize_signals({"shared_trackers": {"module": "html_struct", "type": "set_overlap", "field": "tracker_ids",
                                                  "sources": [{"module": "html_struct", "field": "tracker_ids"},
                                                              {"module": "infra", "field": "har_tracker_ids"}]}})
    tables = {"html_struct": pd.DataFrame([{"entity_id": "m", "level": "material", "incident_id": "i", "tracker_ids": ["1"]}]),
              "infra": pd.DataFrame([{"entity_id": "m2", "level": "material", "incident_id": "i", "har_tracker_ids": ["2"]}])}
    assert aggregate_incidents(tables, sigs)["i"]["shared_trackers"] == frozenset({"1", "2"})


# ------------------------------------------------------------------ masking of organizer identifiers
def test_mask_value_examples():
    from fakecollector.engine.mask import mask_text, mask_value
    assert mask_value("1234567890123456") == "1234…3456"
    assert mask_value("fb:1234567890123456") == "fb:1234…3456"
    assert mask_value("scam-example.live") == "scam-example[.]live"
    assert mask_value("https://www.scam-example.live/path?x=1") == "www[.]scam-example[.]live"
    assert mask_value("a1b2c3d4e5f60718") == "a1b2…0718"          # file hash
    assert mask_value("investment_platform") == "investment_platform"   # ordinary values untouched
    assert mask_value("AS12345") == "AS12345"                        # short ids stay readable
    assert "1234567890123456" not in mask_text("pixel 1234567890123456 in report")


def test_reasons_and_labels_never_contain_full_identifiers():
    spec = {"type": "set_overlap"}
    d = sim.describe("shared_trackers", spec, 1.0, {"shared": ["fb:1234567890123456", "scam-example.live"]})
    assert "1234567890123456" not in d and "scam-example.live" not in d
    assert "1234…3456" in d and "scam-example[.]live" in d
    from fakecollector.engine.cluster import _top_shared
    feats = {"a": {"shared_trackers": frozenset({"scam-example.live"})}, "b": {"shared_trackers": frozenset({"scam-example.live"})}}
    label = _top_shared(["a", "b"], feats, {"shared_trackers": {"type": "set_overlap"}})
    assert "scam-example.live" not in label


def test_analyze_uses_runner_extract_for_path(tmp_path, monkeypatch):
    """analyze(path) -> W1 runner.extract_for_path -> aggregate -> assign (runner stubbed here)."""
    import fakecollector.features.runner as runner
    from fakecollector.core.models import FeatureRecord
    from fakecollector.engine.api import analyze
    truth = write_synthetic(tmp_path / "data" / "features", tmp_path / "labels.yaml")
    ctx = make_context(ROOT, overrides={"paths": {k: str(tmp_path / "data" / k) for k in
                                                  ("features", "interim", "graph", "cache")}})
    ctx.settings["stoplist"] = STOPLIST
    res = run_from_disk(ctx, signals=SYNTH_SIGNALS)
    seen = {}

    def fake_extract(path, ctx=None, modules=None, incident_id=None):
        seen["path"] = Path(path)
        return [FeatureRecord(entity_id="m", level="material", module="text",
                              features={"platform_name": "Platforma K1", "entities": ["Osoba K1"]}, incident_id="upload:x"),
                FeatureRecord(entity_id="i", level="incident", module="infra",
                              features={"domains": ["k1-invest0.example"], "asn": "AS0"}, incident_id="upload:x")]
    monkeypatch.setattr(runner, "extract_for_path", fake_extract)
    import fakecollector.engine.api as api
    monkeypatch.setattr(api, "load_state", lambda c, exclude=None: __import__("fakecollector.engine.pipeline", fromlist=["x"]).load_state(c, SYNTH_SIGNALS, exclude))
    a = analyze(tmp_path / "new_folder", ctx)
    k1 = next(c.campaign_id for c in res.clusters if "syn:K1-1" in c.members)
    assert seen["path"] == tmp_path / "new_folder" and a.campaign_id == k1 and a.status == "known_campaign"


# ------------------------------------------------------------------ "new campaign" is always explained
def _is_consistent(a):
    return (a.family_id is None) == (a.family_confidence == 0.0)


def test_new_campaign_always_has_neighbours_and_reason(setup):
    """The W3 case: analysed incident has no campaign edge -> nearest must still be filled + a reason."""
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    f = feats["syn:K1-1"]
    # only a family-class match (no hard identifier, no 2 campaign signals): no strict campaign edge exists
    new = {"text_semantic": f["text_semantic"], "dom_template": f["dom_template"], "image_near_dup": f["image_near_dup"]}
    a = assign(new, feats, res.clusters, signals, cfg, "upload:b", res.family_of)
    assert a.campaign_id is None and a.nearest, a
    assert a.reason and a.closest_id in feats and a.closest_score is not None
    assert "próg" in a.reason and all(e.reasons for e in a.nearest)
    assert _is_consistent(a)


def test_family_confidence_matches_family_id(setup):
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    for inc, f in feats.items():
        known = {k: v for k, v in feats.items() if k != inc}
        r = run(known, signals, cfg)
        a = assign(f, known, r.clusters, signals, cfg, inc, r.family_of)
        assert _is_consistent(a), (inc, a.status, a.family_id, a.family_confidence)
        if a.status != "insufficient_data":
            assert a.nearest and a.reason


def test_loose_neighbours_when_no_edge_possible(setup):
    """One soft campaign match only: no strict edge, still the closest incident is named."""
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    new = {"image_near_dup": feats["syn:K2-1"]["image_near_dup"]}
    a = assign(new, feats, res.clusters, signals, cfg, "upload:c", res.family_of)
    assert a.status in ("new_family", "new_campaign_known_family") and a.nearest and a.closest_id


def test_insufficient_data_has_reason(setup):
    _, cfg, signals, _, _, feats = setup
    res = run(feats, signals, cfg)
    a = assign({}, feats, res.clusters, signals, cfg, "upload:none", res.family_of)
    assert a.status == "insufficient_data" and a.reason and _is_consistent(a)


def test_exclude_incidents_builds_base_in_memory(tmp_path):
    from fakecollector.engine.pipeline import load_state
    write_synthetic(tmp_path / "data" / "features", tmp_path / "labels.yaml")
    ctx = make_context(ROOT, overrides={"paths": {k: str(tmp_path / "data" / k) for k in
                                                  ("features", "interim", "graph", "cache")}})
    ctx.settings["stoplist"] = STOPLIST
    cut = load_state(ctx, SYNTH_SIGNALS, exclude=["syn:K3-1", "syn:K3-2", "syn:K3-3", "47"])   # unknown ids are ignored
    assert "syn:K3-1" not in cut.features
    assert not any("K3" in m for c in cut.clusters for m in c.members)
    assert not (tmp_path / "data" / "graph").exists()                # nothing written to disk
    rec = [{"module": "text", "features": {"platform_name": "Platforma K3", "entities": ["Osoba K3"]}},
           {"module": "infra", "features": {"domains": ["k3-invest0.example"], "asn": "AS1"}}]
    from fakecollector.engine.api import analyze_records
    a = analyze_records(rec, "upload:k3", ctx, state=cut)
    assert a.campaign_id is None                                       # K3 is unknown to the reduced base
    run_from_disk(ctx, signals=SYNTH_SIGNALS)                          # now write the full grouping
    full = load_state(ctx, SYNTH_SIGNALS)
    assert "syn:K3-1" in full.features
    b = analyze_records(rec, "upload:k3", ctx, state=full)
    assert b.campaign_id is not None                                   # ... but known in the full one


# ------------------------------------------------------------------ family level: signals below floor = missing
def test_below_floor_is_flagged_in_evidence():
    v = [np.array([1.0, 0.0], dtype=np.float32)]
    low = [np.array([0.0, 1.0], dtype=np.float32)]
    _, ev = sim.compute({"type": "cosine", "floor": 0.5}, v, low)
    assert ev["below_floor"] is True
    _, ev = sim.compute({"type": "cosine", "floor": 0.5}, v, v)
    assert ev["below_floor"] is False
    assert sim.compute({"type": "cosine"}, v, low)[1]["below_floor"] is False       # no floor, never "below"
    s, ev = sim.compute({"type": "set_overlap", "floor": 0.2}, frozenset("abcdef"), frozenset("axyzuv"))
    assert s == 0.0 and ev["below_floor"]                                           # set floor honoured (W2)


def test_family_positive_only_does_not_let_weak_signals_lower_the_score(setup):
    _, cfg, signals, _, _, feats = setup
    f = feats["syn:K1-1"]
    other = feats["syn:K2-1"]
    signals = {**signals, "text_semantic": {**signals["text_semantic"], "floor": 0.5}}   # real module declares its own
    # one strong family signal (same template hash) + one that is below its floor (unrelated embeddings)
    a = {"dom_template": f["dom_template"], "text_semantic": f["text_semantic"]}
    b = {"dom_template": f["dom_template"], "text_semantic": other["text_semantic"]}
    off = co.score_pair("a", "b", a, b, signals, {**cfg, "family_positive_only": False, "min_signals_family": 1}, "family")
    on = co.score_pair("a", "b", a, b, signals, {**cfg, "family_positive_only": True, "min_signals_family": 1}, "family")
    assert on.score > off.score
    assert [r.signal for r in on.reasons] == ["dom_template"]                      # the weak one is simply not used
    assert {r.signal for r in off.reasons} == {"dom_template", "text_semantic"}


def test_positive_only_never_touches_campaign_level(setup):
    _, cfg, signals, _, _, feats = setup
    ids = sorted(feats)
    for a, b in [(x, y) for i, x in enumerate(ids) for y in ids[i + 1:]]:
        e0 = co.score_pair(a, b, feats[a], feats[b], signals, {**cfg, "family_positive_only": False}, "campaign")
        e1 = co.score_pair(a, b, feats[a], feats[b], signals, {**cfg, "family_positive_only": True}, "campaign")
        assert (e0 is None) == (e1 is None) and (e0 is None or e0.score == e1.score)


def test_positive_only_needs_min_signals_family(setup):
    """If the only family evidence is below its floor, the pair has no family edge at all."""
    _, cfg, signals, _, _, feats = setup
    signals = {**signals, "text_semantic": {**signals["text_semantic"], "floor": 0.5}}
    a = {"text_semantic": feats["syn:K1-1"]["text_semantic"]}
    b = {"text_semantic": feats["syn:K2-1"]["text_semantic"]}
    assert co.score_pair("a", "b", a, b, signals, {**cfg, "family_positive_only": True, "min_signals_family": 1}, "family") is None
