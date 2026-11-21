"""Smoke tests for the Streamlit UI (W1): every view renders without exceptions; safety helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = Path(__file__).resolve().parents[1] / "ui" / "app.py"


@pytest.mark.parametrize("tab", ["kampanie", "graf", "incydent", "analiza", "metodyka"])
def test_view_renders_without_exceptions(tab):
    at = st_testing.AppTest.from_file(str(APP), default_timeout=180)
    at.query_params["tab"] = tab
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert at.title[0].value.startswith("IsReal?")


def _helpers():
    import importlib.util
    import sys
    from unittest import mock

    # import the module without running main(): patch streamlit page calls
    spec = importlib.util.spec_from_file_location("ui_app_helpers", APP)
    src = APP.read_text(encoding="utf-8").replace("\nmain()\n", "\n")
    mod = importlib.util.module_from_spec(spec)
    with mock.patch("streamlit.set_page_config"):
        exec(compile(src, str(APP), "exec"), mod.__dict__)
    sys.modules.pop("ui_app_helpers", None)
    return mod


def test_defang_and_markdown_safety():
    m = _helpers()
    assert m.defang("https://scam-shop.xyz/a?b=1") == "hxxps://scam-shop[.]xyz/a?b=1"
    assert m.defang("wspólna domena fake-news.live i promo-site.pro") == \
        "wspólna domena fake-news[.]live i promo-site[.]pro"
    assert m.defang("plik main.css, raport eval_1.md, settings.yaml, 0.85") == \
        "plik main.css, raport eval_1.md, settings.yaml, 0.85"
    # every markdown/HTML control char is escaped -> rendered as literal text, never a link or tag
    assert m.md_safe("[kliknij](https://evil.com) <script>") == \
        "\\[kliknij\\]\\(hxxps://evil\\[.\\]com\\) \\<script\\>"
    assert "<" not in m.plain("<b>x</b> & y.com") and "y[.]com" in m.plain("y.com")
    assert m.short_value([0.1] * 512) == "wektor[512]"


def test_campaign_report_masks_ids_and_lists_reasons():
    import pandas as pd

    m = _helpers()
    reasons = [{"signal": "shared_trackers", "score": 1.0, "weight": 3.0,
                "detail": "wspólny identyfikator śledzący: fb:123456789012345"},
               {"signal": "shared_assets", "score": 1.0, "weight": 3.0,
                "detail": "identyczne pliki strony (sha1): abcdef0123456789, 0fedcba987654321"},
               {"signal": "same_registered_domain", "score": 0.0, "weight": 3.0, "detail": "brak: domena"}]
    rule = [{"signal": "image_near_dup", "score": 0.9, "weight": 2.0, "detail": "niemal identyczny obraz (0.90)"},
            {"signal": m.RULE_SIGNAL, "score": 0.0, "weight": 0.0, "detail": m.RULE_TEXT}]
    edges = pd.DataFrame([
        {"level": "campaign", "a": "nask:1", "b": "nask:2", "score": 0.9, "n_signals": 3, "reasons": reasons, "rule": False},
        {"level": "family", "a": "nask:2", "b": "nask:3", "score": 0.4, "n_signals": 2, "reasons": rule, "rule": True},
    ])
    s = {"clusters": {"params": {"tau_campaign": 0.5},
                      "clusters": [{"campaign_id": "C001", "members": ["nask:1", "nask:2"], "label": "fake-news.live",
                                    "top_signals": ["shared_trackers"], "cohesion": 0.9, "family_id": "F001"},
                                   {"campaign_id": "C002", "members": ["nask:3"], "label": "nask:3",
                                    "top_signals": [], "cohesion": 1.0, "family_id": "F001"}],
                      "families": [{"family_id": "F001", "campaigns": ["C001", "C002"],
                                    "members": ["nask:1", "nask:2", "nask:3"], "label": "x", "top_signals": []}]},
         "edges": edges, "labels": {"shared_trackers": "wspólny tracker", "shared_assets": "wspólne pliki"}}
    payload, csv_text = m.build_campaign_report(s)
    c1 = payload["kampanie"][0]
    assert c1["kampania"] == "C001" and c1["rodzina"] == "F001" and c1["incydenty"] == ["nask:1", "nask:2"]
    assert c1["etykieta"] == "fake-news[.]live"
    assert [r["sygnał"] for r in c1["przesłanki_kampanii"]] == ["shared_trackers", "shared_assets"]
    text = str(payload) + csv_text
    assert "123456789012345" not in text and "1234…2345" in text      # pixel id masked
    assert "abcdef0123456789" not in text and "abcdef…89" in text        # file hash masked
    c2 = payload["kampanie"][1]
    assert c2["odrzucone_jako_kampania"] == [{"para": "nask:2 ↔ nask:3", "powód": m.RULE_TEXT}]
    assert csv_text.startswith("﻿kampania;rodzina;")
    assert "nask:1" in csv_text  # incident ids are not masked (short, needed by analysts)


def test_analyze_view_has_demo_exclude_mode():
    at = st_testing.AppTest.from_file(str(APP), default_timeout=180)
    at.query_params["tab"] = "analiza"
    at.run()
    assert not at.exception
    assert any("Tryb demo" in e.label for e in at.expander)
    ms = at.multiselect[0]
    m = _helpers()
    # enabled only when the installed engine supports analyze(..., exclude_incidents=...)
    assert ms.disabled is (not m.engine_supports_exclude())


def test_saved_ids_for_excluded_mode_uses_saved_campaign_of_best_neighbour():
    from types import SimpleNamespace as NS

    m = _helpers()
    s = {"camp_of": {"nask:1": "C001", "nask:2": "C001", "nask:48": "C002"},
         "fam_of_camp": {"C001": "F001", "C002": "F002"}}
    me = "upload:x.zip"
    res = NS(incident_id=me, campaign_id="C002", family_id="F002",          # engine's in-memory numbering
             nearest=[NS(a=me, b="nask:48", score=0.1), NS(a="nask:1", b=me, score=0.88)], family_nearest=[])
    assert m.saved_ids_for(res, s) == ("C001", "F001")
    new_fam = NS(incident_id=me, campaign_id=None, family_id="F009", nearest=[],
                 family_nearest=[NS(a=me, b="nask:48", score=0.6)])
    assert m.saved_ids_for(new_fam, s) == (None, "F002")


def test_public_mode_masks_domains_ids_and_content():
    m = _helpers()
    m.PUBLIC["on"] = True
    try:
        assert m.defang("ta sama domena strony docelowej: promo-site.pro") == \
            "ta sama domena strony docelowej: domena .pro"
        assert m.defang("piksel fb:1234…2345 i fb_pixel:123456789012345") == "piksel fb:…2345 i fb_pixel:…2345"
        assert m.defang("pliki: abcdef0123456789, 16c8…6789") == "pliki: …6789, …6789"
        assert m.defang("biblioteka z connect.facebook.net") == "biblioteka z connect[.]facebook[.]net"
        assert m.public_detail("same_platform_name", "ta sama nazwa platformy: platforma X") == \
            "ta sama nazwa platformy: [ukryte w trybie publicznym]"
        assert m.public_detail("shared_trackers", "wspólny tracker: fb:123456789012345") == "wspólny tracker: fb:…2345"
        assert m.public_label("Marka A / Marka B", "C002") == "C002"
    finally:
        m.PUBLIC["on"] = False
    assert m.public_label("x.com label") == "x[.]com label"


@pytest.mark.parametrize("tab", ["kampanie", "graf", "incydent", "analiza", "metodyka"])
def test_views_render_in_public_mode(tab):
    at = st_testing.AppTest.from_file(str(APP), default_timeout=180)
    at.query_params["tab"] = tab
    at.query_params["public"] = "1"
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]


def test_public_detail_keeps_no_match_lines():
    m = _helpers()
    m.PUBLIC["on"] = True
    try:
        assert m.public_detail("face_match", "brak: podobna twarz") == "brak: podobna twarz"
    finally:
        m.PUBLIC["on"] = False


# ------------------------------------------------------------------ presentation mode / pitch polish
def test_polish_plurals():
    m = _helpers()
    cases = {1: "kampania", 2: "kampanie", 4: "kampanie", 5: "kampanii", 12: "kampanii", 14: "kampanii",
             22: "kampanie", 25: "kampanii", 0: "kampanii", 101: "kampanii", 112: "kampanii"}
    for n, word in cases.items():
        assert m.campaigns_pl(n) == f"{n} {word}", n
    assert m.incidents_pl(1) == "1 incydent" and m.incidents_pl(3) == "3 incydenty" and m.incidents_pl(7) == "7 incydentów"
    assert m.families_pl(1) == "1 rodzina" and m.families_pl(2) == "2 rodziny" and m.families_pl(6) == "6 rodzin"


def test_reasons_frame_hides_missing_rows_on_request():
    m = _helpers()
    rs = [{"signal": "shared_trackers", "detail": "wspólny tracker: fb:…2345", "score": 1.0, "weight": 3.0},
          {"signal": "face_match", "detail": "brak: podobna twarz", "score": 0.0, "weight": 1.0},
          {"signal": "regula_kampanii", "detail": "za mało twardych dowodów na tę samą kampanię", "score": 0, "weight": 0}]
    assert len(m.reasons_frame(rs, hide_missing=False)) == 3
    hidden = m.reasons_frame(rs, hide_missing=True)
    assert len(hidden) == 2 and not any(str(x).startswith("brak:") for x in hidden["przesłanka"])


def test_key_edge_is_rule_message_else_highest_score():
    m = _helpers()
    plain = [{"score": 0.4, "reasons": []}, {"score": 0.7, "reasons": []}, {"score": 0.5, "reasons": []}]
    assert m.key_edge_index(plain) == 1
    with_rule = plain + [{"score": 0.2, "reasons": [{"signal": "regula_kampanii"}]}]
    assert m.key_edge_index(with_rule) == 3


def _res(status, nearest, closest=None, camp=None):
    from types import SimpleNamespace
    return SimpleNamespace(status=status, nearest=nearest, closest_score=closest, campaign_id=camp)


def test_analysis_sentence_known_and_new_campaign():
    m = _helpers()
    edge = {"a": "new", "b": "nask:1", "score": 0.8, "reasons": [
        {"signal": "shared_trackers", "detail": "wspólny tracker: fb:…2345", "score": 1.0, "weight": 3.0},
        {"signal": "shared_assets", "detail": "identyczne pliki: a…1, b…2, c…3 (+14)", "score": 1.0, "weight": 2.0},
        {"signal": "face_match", "detail": "brak: podobna twarz", "score": 0.0, "weight": 1.0}]}
    known = m.analysis_sentence(_res("known_campaign", [edge], camp="C001"), "known_campaign", "C001", None, 0.35)
    assert "C001" in known and "wspólny tracker" in known and "identyczne pliki (17)" in known and "brak" not in known
    new = m.analysis_sentence(_res("new_family", [{"a": "x", "b": "y", "score": 0.23, "reasons": []}], closest=0.23),
                              "new_family", None, None, 0.35)
    assert new == "Nie znaleziono twardych dowodów powiązania. Najbliższe znane zgłoszenie pasuje w 23% (próg 35%)."
    fam = m.analysis_sentence(_res("new_campaign_known_family", [], closest=0.3), "new_campaign_known_family",
                              None, "F001", 0.35)
    assert fam.endswith("Wzorzec pasuje do rodziny F001.")
    assert "Za mało danych" in m.analysis_sentence(_res("insufficient_data", []), "insufficient_data", None, None, 0.35)


@pytest.mark.parametrize("tab", ["kampanie", "graf", "incydent", "analiza", "metodyka"])
def test_views_render_in_presentation_mode(tab):
    at = st_testing.AppTest.from_file(str(APP), default_timeout=180)
    at.query_params["tab"] = tab
    at.query_params["present"] = "1"
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    assert any("Tryb prezentacji" == t.label for t in at.toggle)
