"""Tests for html_struct (W1). Real-data tests are skipped when data/raw/nask is absent."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from fakecollector.core.models import Context, Material
from fakecollector.features import html_struct
from fakecollector.features.html_struct import SIGNALS, analyze_html, extract, simhash64
from fakecollector.ingest.loader import build_incident
from fakecollector.ingest.util import REPO_ROOT, load_stoplist

RAW = REPO_ROOT / "data" / "raw" / "nask"
needs_data = pytest.mark.skipif(not (RAW / "1").is_dir(), reason="NASK data not present locally")
CTX = Context(repo_root=REPO_ROOT, data_dir=REPO_ROOT / "data", settings={})


def _pages(folder: str):
    inc = build_incident(RAW / folder, f"nask:{folder}", "nask")
    return [m for m in inc.materials if m.kind in html_struct.KINDS]


def _ham(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def test_module_contract():
    assert html_struct.MODULE == "html_struct" and html_struct.LEVEL == "material"
    assert set(html_struct.KINDS) == {"html", "mhtml"}
    assert set(SIGNALS) == {"dom_template", "shared_assets", "shared_trackers", "shared_scripts",
                            "shared_form_endpoint", "hidden_text_sim"}
    for spec in SIGNALS.values():
        assert spec["type"] in {"cosine", "jaccard_minhash", "set_overlap", "exact", "hamming_hash", "numeric_close"}


@needs_data
def test_real_incidents_1_and_2_share_pixel_and_template():
    r1 = extract(_pages("1")[0], CTX)
    r2 = extract(_pages("2")[0], CTX)
    assert not r1.errors and not r2.errors
    f1, f2 = r1.features, r2.features
    # 1 and 2 share a Facebook pixel; the id itself is read from the data, never written in tests
    shared = {t for t in set(f1["tracker_ids"]) & set(f2["tracker_ids"]) if t.startswith("fb:")}
    assert shared
    assert _ham(f1["dom_simhash"], f2["dom_simhash"]) <= 3
    assert len(set(f1["asset_hashes"]) & set(f2["asset_hashes"])) >= 10
    assert f1["lang"] == "pl" and f1["title"]
    assert not any("fbevents" in s for s in f1["script_srcs"])   # stoplisted


@needs_data
def test_real_incident_14_html_and_mhtml():
    recs = [extract(m, CTX) for m in _pages("14")]
    assert len(recs) == 3 and all(not r.errors for r in recs)
    assert {m.kind for m in _pages("14")} == {"html", "mhtml"}
    for r in recs:  # pixel id comes from the landing URL (?pxl=...)
        # pixel id from the landing URL (?pxl=...) of this very capture
        pxl = parse_qs(urlsplit(r.features["original_url"]).query)["pxl"][0]
        assert f"fb:{pxl}" in r.features["tracker_ids"]
        assert r.features["n_inputs"] > 0


def test_synthetic_trackers_forms_hidden_text():
    html = b"""<!-- saved from url=(0020)https://x.example/ -->
    <html lang="PL"><head><title> Oferta </title>
    <meta property="og:url" content="https://x.example/"><meta name="generator" content="WordPress 6.1">
    <style>.ghost{font-size:0} #secret { display : none }</style>
    <script>fbq('init', '123456789012345'); gtag('config', 'G-ABCDEFGH12');</script>
    <script src="./Oferta_files/landing-core.js.pobrane"></script>
    <script src="./Oferta_files/jquery.min.js.pobrane"></script>
    <script src="./Oferta_files/main.js.pobrane"></script>
    <!-- template v2 -->
    </head><body class="page home">
      <p>Zarob <span class="ghost">xx</span> duzo</p>
      <div id="secret">ukryty tekst numer jeden</div>
      <div style="color:#fff;background-color:#fff">bialy na bialym</div>
      <form action="https://api.leadcrm.example/send.php?x=1"><input name="Imie"><input name="phone">
        <input type="submit" name="go"></form>
      <a href="https://cdn.facebook.net/x">fb</a><a href="https://sub.scamhost.co.uk/a">x</a>
      <noscript><img src="https://www.facebook.com/tr?id=999999999999999&ev=PageView"></noscript>
    </body></html>"""
    f = analyze_html(html, [], "https://x.example/?pxl=111122223333444", load_stoplist())
    assert {"fb:123456789012345", "fb:999999999999999", "fb:111122223333444", "ga4:G-ABCDEFGH12"} <= set(f["tracker_ids"])
    assert f["script_srcs"] == ["landing-core.js"]           # jquery stoplisted, main.js generic
    assert f["form_actions"] == ["api.leadcrm.example/send.php"]
    assert f["form_fields"] == ["imie", "phone"]
    assert f["external_domains"] == ["api.leadcrm.example", "scamhost.co.uk"]  # unknown TLD -> host; facebook.net stoplisted
    assert f["lang"] == "pl" and f["title"] == "Oferta" and f["generator"] == "WordPress 6.1"
    assert f["hidden_text_count"] == 3
    assert {"font-size:0", "display:none", "color=background"} <= set(f["hidden_reasons"])
    assert "ukryty tekst numer jeden" in f["hidden_text"] and f["hidden_text_shingles"]
    assert f["html_comments"] == ["template v2"]
    assert {"page", "home"} <= set(f["css_classes"])


def test_resource_hashes_skip_stoplist_and_empty(tmp_path):
    files = tmp_path / "P_files"
    files.mkdir()
    (files / "logo.webp").write_bytes(b"RIFF....WEBPdata")
    (files / "saved_resource.html").write_bytes(b"<html></html>")
    (files / "empty.css").write_bytes(b"")
    (files / "555566667777888").write_bytes(b"pixel config")   # synthetic pixel id
    res = [(p.name, p) for p in files.iterdir()]
    f = analyze_html(b"<html><body></body></html>", res, None, load_stoplist())
    assert len(f["asset_hashes"]) == 2                     # logo + pixel file
    assert "fb:555566667777888" in f["tracker_ids"]


def test_simhash_stable_and_sensitive():
    a = analyze_html(b"<html><body><div><p>a</p><p>b</p></div></body></html>", [], None, load_stoplist())
    b = analyze_html(b"<html><body><div><p>zzz</p><p>yyy</p></div></body></html>", [], None, load_stoplist())
    c = analyze_html(b"<html><body><table><tr><td>1</td></tr></table><ul><li>x</li></ul></body></html>",
                     [], None, load_stoplist())
    assert a["dom_simhash"] == b["dom_simhash"]            # text does not matter
    assert _ham(a["dom_simhash"], c["dom_simhash"]) > 8
    assert simhash64({}) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("content", [b"", b"\x00\xff\xfe\x00garbage", b"<html><head><title>x"])
def test_empty_or_broken_html_never_raises(tmp_path, content):
    p = tmp_path / "broken.html"
    p.write_bytes(content)
    m = Material(material_id="0" * 16, incident_id="t:1", kind="html", path=str(p))
    rec = extract(m, CTX)
    assert rec.module == "html_struct" and rec.incident_id == "t:1"
    assert isinstance(rec.features, dict)


def test_missing_file_goes_to_errors(tmp_path):
    m = Material(material_id="1" * 16, incident_id="t:2", kind="mhtml", path=str(tmp_path / "nope.mhtml"))
    rec = extract(m, CTX)
    assert rec.errors and rec.features["dom_simhash"] is None


def test_hidden_text_ignores_form_widgets_and_phone_code_lists():
    """Country pickers (select/option, '+NN' dial-code lists) are identical everywhere -> no hidden_text_sim."""
    codes = "".join(f"<li><span>Kraj {i}</span> <span>+{i + 1}</span></li>" for i in range(40))
    html = f"""<html><body>
      <div style="display:none">
        <p>prawdziwy ukryty tekst oferty</p>
        <ul class="iti__country-list">{codes}</ul>
      </div>
      <select style="display:none" name="cc"><option>Polska +48</option><option>Niemcy +49</option></select>
      <div class="hidden"><ul>{codes}</ul></div>
    </body></html>""".encode()
    f = analyze_html(html, [], None, load_stoplist())
    assert f["hidden_text"] == "prawdziwy ukryty tekst oferty"
    assert f["hidden_text_count"] == 1
    assert "+48" not in f["hidden_text"]


def test_signals_have_polish_labels_and_classes():
    for name, spec in SIGNALS.items():
        assert spec.get("label"), name
    assert set(html_struct.SIGNAL_CLASS) == set(SIGNALS)
    assert set(html_struct.SIGNAL_CLASS.values()) <= {"campaign", "family"}
