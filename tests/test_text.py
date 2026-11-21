"""Tests for the text module (W2).

Synthetic fixtures only (no organizer data in the repo). The real-data test runs
only when data/raw/nask/ exists locally and is skipped otherwise.
Embeddings are disabled here (no model download in CI); see test_embedding_optional.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ["TEXT_EMB_DISABLED"] = "1"

from fakecollector.features import text as T  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO / "data" / "raw" / "nask"

SCAM_HTML = """<html><head><meta charset="utf-8">
<title>Sensacyjny wywiad – Rafał Brzoska ujawnia sekret</title>
<script>var hidden = 'skrypt';</script><style>.x{color:red}</style></head>
<body><div style="display:none">UKRYTY TEKST</div>
<h1>Rafał Brzoska w rozmowie z redakcją Gazeta.pl zdradził sekret swojego bogactwa</h1>
<p>Prezes InPost przyznał na antenie TVN24, że korzysta z platformy inwestycyjnej Quantum Zysk.
Dzięki niej zarabia 1 200 zł dziennie. Minimalna wpłata to 250 PLN. Banki chcą zablokować ten algorytm!</p>
<p>Autor: Jan Nowak. Komentarze (25)</p>
<a href="#">Przejdź na oficjalną stronę Quantum Zysk</a> <button>Zarejestruj się teraz</button>
<input type="hidden" value="secret"><span hidden>HIDDEN2</span><p aria-hidden="true">ARIA</p>
</body></html>"""

PRODUCT_HTML = """<html><head><title>Metabo RX</title></head><body>
<h2>Naturalny suplement na metabolizm</h2><p>Kapsułki wspierają odchudzanie i zdrowie. Skład: 12 składników.
Lekarz dr. Kowalska poleca. Dawkowanie: 2 kapsułki dziennie. Cena 147 zł zamiast 294 zł.</p>
<button>Zamów Metabo RX</button></body></html>"""


def _write(tmp_path: Path, name: str, content: str | bytes) -> Path:
    p = tmp_path / name
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


# ---------------------------------------------------------------- unit: parsing

def test_visible_text_drops_hidden_and_scripts():
    doc = T.parse_html(SCAM_HTML)
    assert doc["title"].startswith("Sensacyjny wywiad")
    for bad in ("UKRYTY", "HIDDEN2", "ARIA", "skrypt", "color:red", "secret"):
        assert bad not in doc["text"]
    assert "Quantum Zysk" in doc["text"]
    assert "Zarejestruj się teraz" in doc["cta_texts"]


def test_text_features_scam_article():
    doc = T.parse_html(SCAM_HTML)
    errs: list[str] = []
    f = T.text_features(doc["text"], title=doc["title"], cta_texts=doc["cta_texts"], embed=False, errors=errs)
    assert errs == []
    assert set(f) == set(T.FEATURE_KEYS)
    assert {"Rafał Brzoska", "InPost", "Gazeta.pl", "TVN24"} <= set(f["entities"])
    assert f["persons"] == ["Rafał Brzoska"]
    assert f["platform_name"] == "quantum zysk"
    assert f["narrative_type"] in ("celebrity_interview", "investment_platform")
    assert "investment_platform" in f["narrative_tags"]
    assert "1200 PLN/day" in f["promised_amounts"] and "250 PLN" in f["promised_amounts"]
    assert f["earnings_claim"] is True
    assert "zarejestruj sie teraz" in f["cta_phrases"]
    assert len(f["visible_text"]) <= T.SNIPPET_CHARS
    assert len(f["minhash"]) == T.MINHASH_PERM and all(isinstance(x, int) for x in f["minhash"])
    assert 0 < len(f["keywords"]) <= T.TOP_KEYWORDS
    assert f["text_emb"] is None  # disabled in tests


def test_product_page_platform_from_title_and_narrative():
    doc = T.parse_html(PRODUCT_HTML)
    f = T.text_features(doc["text"], title=doc["title"], cta_texts=doc["cta_texts"], embed=False)
    assert f["platform_name"] == "metabo rx"
    assert f["narrative_type"] == "health_product"
    assert "147 PLN" in f["promised_amounts"]


def test_entity_inflection_and_exact_acronyms():
    ents = T.find_entities("Wywiad z Rafałem Brzoską i Robertem Lewandowskim. Konto w ING i PKO BP.")
    assert {"Rafał Brzoska", "Robert Lewandowski"} <= set(ents["entities"])
    assert {"ING", "PKO BP"} <= set(ents["brands"])
    assert "ING" not in ents["entities"]  # banks are generic (payment-method lists)
    # lowercase "ing" inside English words must not match the bank
    assert "ING" not in T.find_entities("trading and investing are amazing")["brands"]


def test_platform_title_with_store_prefix():
    name, cands = T.guess_platform_name("Zagraj teraz i wygraj bonus!", title="App Store – Słodka Bonanza")
    assert name == "słodka bonanza"
    assert "Słodka Bonanza" in cands


@pytest.mark.parametrize("text,expected", [
    ("Zarabiaj 500 € dziennie", "500 EUR/day"),
    ("tylko $250 na start", "250 USD"),
    ("nawet 10 tys. zł miesięcznie", "10000 PLN/month"),
    ("kwota 1.250,50 zł", "1250.5 PLN"),
])
def test_promised_amounts(text, expected):
    amounts, _ = T.promised_amounts(text)
    assert expected in amounts


def test_minhash_near_duplicate_vs_different():
    base = " ".join(f"słowo{i}" for i in range(80))
    variant = base.replace("słowo40", "inne40")
    other = " ".join(f"tekst{i}" for i in range(80))
    a, b, c = (T.minhash_signature(x) for x in (base, variant, other))
    assert T.minhash_jaccard(a, b) > 0.8
    assert T.minhash_jaccard(a, c) < 0.1


def test_keywords_use_corpus_idf():
    idf = T.build_idf(["platforma inwestycja zysk", "platforma suplement zdrowie", "platforma kasyno bonus"])
    kws = T.keywords("platforma suplement", idf)
    assert kws[0] == "suplement"  # common corpus word "platforma" ranks lower


def test_signals_reference_emitted_fields():
    for sig in T.SIGNALS.values():
        assert sig["field"] in T.FEATURE_KEYS
        assert sig["type"] in {"cosine", "jaccard_minhash", "set_overlap", "exact", "hamming_hash", "numeric_close"}


# ---------------------------------------------------------------- file readers

def test_extract_dict_html_writes_full_text(tmp_path):
    p = _write(tmp_path, "page.html", SCAM_HTML)
    d = T.extract_dict(p, kind="html", data_dir=tmp_path / "data")
    assert d["module"] == "text" and d["level"] == "material" and len(d["entity_id"]) == 16
    assert d["errors"] == []
    assert d["features"]["platform_name"] == "quantum zysk"
    full = tmp_path / "data" / "interim" / "text" / f"{d['entity_id']}.txt"
    assert full.exists() and "Quantum Zysk" in full.read_text(encoding="utf-8")


def test_extract_dict_mhtml(tmp_path):
    mhtml = (
        "From: <Saved by test>\r\nSubject: Metabo RX\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/related; type="text/html"; boundary="BOUND"\r\n\r\n'
        "--BOUND\r\nContent-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: quoted-printable\r\n"
        "Content-Location: https://example.invalid/\r\n\r\n"
        + PRODUCT_HTML.replace("=", "=3D").replace("ł", "=C5=82").replace("ó", "=C3=B3").replace("ą", "=C4=85")
        .replace("ę", "=C4=99").replace("ś", "=C5=9B")
        + "\r\n--BOUND--\r\n"
    )
    p = _write(tmp_path, "page.mhtml", mhtml.encode("ascii"))
    d = T.extract_dict(p, kind="mhtml", data_dir=tmp_path / "data")
    assert d["errors"] == []
    assert d["features"]["platform_name"] == "metabo rx"
    assert d["features"]["narrative_type"] == "health_product"


def test_extract_dict_json_metadata(tmp_path):
    info = {
        "extractor": "facebook:ads", "title": "Czytać", "description": "Rafał Brzoska: nowa platforma Quantum Zysk "
        "pozwala zarabiać 800 zł dziennie. Zarejestruj się!",
        "formats": [{"url": "https://cdn.example.invalid/v.mp4"}],
        "webpage_url": "https://landing.example.invalid/?utm_campaign=brzoska_pl&ad_name=quantum+zysk+v2",
    }
    p = _write(tmp_path, "x.info.json", json.dumps(info, ensure_ascii=False))
    d = T.extract_dict(p, kind="json", data_dir=tmp_path / "data")
    f = d["features"]
    assert "Rafał Brzoska" in f["entities"]
    assert f["platform_name"] == "quantum zysk"
    assert "800 PLN/day" in f["promised_amounts"]


# ---------------------------------------------------------------- robustness

@pytest.mark.parametrize("name,content", ids=["empty", "blank", "garbage", "badjson", "badmhtml", "png"], argvalues=[
    ("empty.html", ""),
    ("blank.html", "<html><body>   </body></html>"),
    ("garbage.html", bytes(range(256)) * 20),
    ("broken.json", "{not json"),
    ("empty.mhtml", "not a mime archive"),
    ("image.png", b"\x89PNG\r\n\x1a\n"),
])
def test_empty_or_corrupt_input_never_raises(tmp_path, name, content):
    p = _write(tmp_path, name, content)
    kind = {".html": "html", ".json": "json", ".mhtml": "mhtml", ".png": "image"}[p.suffix]
    d = T.extract_dict(p, kind=kind, data_dir=tmp_path / "data")
    assert d["module"] == "text"
    assert set(d["features"]) == set(T.FEATURE_KEYS)
    if name != "garbage.html":  # random bytes decode to some "text"; only no-crash is required
        assert d["errors"]  # error recorded, not raised
        assert d["features"]["minhash"] is None and d["features"]["text_emb"] is None


def test_missing_file_never_raises(tmp_path):
    d = T.extract_dict(tmp_path / "nope.html", entity_id="x", kind="html", data_dir=tmp_path)
    assert d["entity_id"] == "x" and d["errors"]


def test_text_features_empty_string():
    errs: list[str] = []
    f = T.text_features("", embed=False, errors=errs)
    assert f["text_len"] == 0 and f["entities"] is None and errs


def test_embedding_optional(monkeypatch):
    """If the model cannot be loaded, text_emb is None and an error is recorded."""
    monkeypatch.setattr(T, "embed_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no model")))
    errs: list[str] = []
    f = T.text_features("Rafał Brzoska poleca platformę Quantum Zysk.", embed=True, errors=errs)
    assert f["text_emb"] is None and any("text_emb" in e for e in errs)
    assert f["minhash"] is not None


def test_extract_feature_record_interface(tmp_path):
    from fakecollector.core.models import Context, FeatureRecord, Material

    (tmp_path / "data" / "raw").mkdir(parents=True)
    _write(tmp_path / "data" / "raw", "page.html", SCAM_HTML)
    ctx = Context(repo_root=tmp_path, data_dir=tmp_path / "data", settings={})
    mat = Material(material_id="abc123", incident_id="nask:test", kind="html", path="data/raw/page.html")
    rec = T.extract(mat, ctx)
    assert isinstance(rec, FeatureRecord)
    assert rec.entity_id == "abc123" and rec.module == "text" and rec.errors == []
    assert rec.incident_id == "nask:test"
    assert rec.features["platform_name"] == "quantum zysk"


def test_extract_rejects_kind_outside_kinds(tmp_path):
    from fakecollector.core.models import Context, Material

    _write(tmp_path, "x.har", b"{}")
    ctx = Context(repo_root=tmp_path, data_dir=tmp_path / "data", settings={})
    rec = T.extract(Material(material_id="m1", incident_id="nask:1", kind="har", path="x.har"), ctx)
    assert rec.errors and rec.features["entities"] is None and rec.incident_id == "nask:1"


def test_signal_class_covers_signals():
    assert set(T.SIGNAL_CLASS) == set(T.SIGNALS)
    assert T.SIGNAL_CLASS["text_near_dup"] == "campaign" and T.SIGNAL_CLASS["same_platform_name"] == "campaign"
    assert {T.SIGNAL_CLASS[s] for s in ("text_semantic", "same_narrative", "shared_entities")} == {"family"}


def test_generic_brands_not_in_entities():
    ents = T.find_entities("Skomentuj na Facebook. Rafał Brzoska i Google.")
    assert "Facebook" in ents["brands"] and "Facebook" not in ents["entities"]
    assert "Rafał Brzoska" in ents["entities"]


def test_signal_pairs_script(tmp_path):
    import importlib.util

    root = tmp_path / "raw"
    for inc, html in (("1", SCAM_HTML), ("2", SCAM_HTML.replace("Nowak", "Kowal")), ("3", PRODUCT_HTML)):
        (root / inc).mkdir(parents=True)
        _write(root / inc, "p.html", html)
    out = tmp_path / "data" / "features" / "text.parquet"
    T.run_batch(root, out, tmp_path / "data")
    spec = importlib.util.spec_from_file_location("tsp", REPO / "scripts" / "text_signal_pairs.py")
    tsp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tsp)
    import pandas as pd

    rep = tsp.build_report(pd.read_parquet(out))
    assert "nask:1–nask:2" in rep and "text_near_dup" in rep


def test_ocr_records_from_visual_parquet(tmp_path):
    pd = pytest.importorskip("pandas")
    from fakecollector.core.models import Context, Material

    feats = tmp_path / "data" / "features"
    feats.mkdir(parents=True)
    pd.DataFrame({
        "entity_id": ["img1", "vid1#f0", "vid1#f1", "img2"],
        "ocr_text": ["Rafał Brzoska poleca platformę Quantum Zysk", "Zarabiaj 500 zł dziennie", None, ""],
    }).to_parquet(feats / "visual.parquet")
    ctx = Context(repo_root=tmp_path, data_dir=tmp_path / "data", settings={})
    recs = T.extract(Material(material_id="img1", incident_id="nask:1", kind="image", path="x.png"), ctx)
    assert len(recs) == 1 and recs[0].entity_id == "img1" and recs[0].incident_id == "nask:1"
    assert "Rafał Brzoska" in recs[0].features["entities"]
    vid = T.extract(Material(material_id="vid1", incident_id="nask:5", kind="video", path="v.mp4"), ctx)
    assert [r.entity_id for r in vid] == ["vid1#f0"]
    assert "500 PLN/day" in vid[0].features["promised_amounts"]
    assert T.extract(Material(material_id="img2", incident_id="nask:1", kind="image", path="y.png"), ctx) == []
    for r in recs + vid:  # OCR: only text_near_dup and shared_entities stay active
        assert r.features["text_emb"] is None
        assert r.features["narrative_key"] is None and r.features["platform_name"] is None
        assert r.features["minhash"] is not None and r.features["entities"] is not None
        assert "ocr_text" in r.provenance


def test_narrative_other_is_not_a_match():
    f = T.text_features("Lorem ipsum dolor sit amet, consectetur adipiscing elit.", embed=False)
    assert f["narrative_type"] == "other" and f["narrative_key"] is None
    doc = T.parse_html(PRODUCT_HTML)
    g = T.text_features(doc["text"], title=doc["title"], embed=False)
    assert g["narrative_key"] == g["narrative_type"] == "health_product"
    assert T.SIGNALS["same_narrative"]["field"] == "narrative_key"


def test_corpus_idf_from_incidents_jsonl(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    _write(raw, "a.html", SCAM_HTML)
    _write(raw, "b.html", PRODUCT_HTML)
    inc = tmp_path / "data" / "interim"
    inc.mkdir(parents=True)
    lines = [json.dumps({"incident_id": f"nask:{i}", "materials": [
        {"material_id": f"m{i}", "kind": "html", "path": f"data/raw/{n}", "is_common_lib": False}]})
        for i, n in ((1, "a.html"), (2, "b.html"))]
    (inc / "incidents.jsonl").write_text("\n".join(lines), encoding="utf-8")
    idf = T.corpus_idf(tmp_path / "data", tmp_path)
    assert idf["n_docs"] == 2 and "quantum" in idf["idf"]


def test_signal_pairs_script(tmp_path):
    import importlib.util

    pd = pytest.importorskip("pandas")
    rows = []
    for inc, html in (("nask:1", SCAM_HTML), ("nask:2", SCAM_HTML.replace("Nowak", "Kowal")), ("nask:3", PRODUCT_HTML)):
        p = _write(tmp_path, inc.replace(":", "_") + ".html", html)
        d = T.extract_dict(p, kind="html", data_dir=tmp_path / "data", write_full_text=False)
        rows.append({"incident_id": inc, "entity_id": d["entity_id"], **d["features"]})
    spec = importlib.util.spec_from_file_location("tsp", REPO / "scripts" / "text_signal_pairs.py")
    tsp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tsp)
    rep = tsp.build_report(pd.DataFrame(rows))
    assert "nask:1–nask:2" in rep and "text_near_dup" in rep and "| nask:3 |" in rep


# ---------------------------------------------------------------- real data (local only)

@pytest.mark.skipif(not DATA_ROOT.exists(), reason="organizer data not available (data/raw/nask)")
@pytest.mark.parametrize("folder", ["1", "48"])
def test_real_incident(folder, tmp_path):
    pages = [p for p in (DATA_ROOT / folder).rglob("*.html") if not any(x.endswith("_files") for x in p.parts)]
    assert pages, f"no html pages in folder {folder}"
    for p in pages:
        d = T.extract_dict(p, kind="html", data_dir=tmp_path, write_full_text=False)
        f = d["features"]
        assert d["errors"] == []
        assert f["text_len"] and f["text_len"] > 100
        assert f["minhash"] is not None
        assert f["narrative_type"] in T.NARRATIVE_TYPES
