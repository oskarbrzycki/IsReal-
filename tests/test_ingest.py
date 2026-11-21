"""Tests for loader + runner (W1). Real-data tests are skipped when data/raw/nask is absent."""
from __future__ import annotations

import sys
import types
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from fakecollector.core.models import Context, FeatureRecord
from fakecollector.features.runner import extract_for_path, run_module
from fakecollector.ingest.loader import build_incident, load_incidents, load_upload, read_jsonl, write_jsonl
from fakecollector.ingest.util import REPO_ROOT

RAW = REPO_ROOT / "data" / "raw" / "nask"
needs_data = pytest.mark.skipif(not (RAW / "1").is_dir(), reason="NASK data not present locally")


def _ctx(tmp_path: Path) -> Context:
    return Context(repo_root=REPO_ROOT, data_dir=tmp_path,
                   settings={"paths": {"interim": str(tmp_path / "interim"), "features": str(tmp_path / "features")}})


# ------------------------------------------------------------------ real data

@needs_data
def test_real_incident_1_structure():
    inc = build_incident(RAW / "1", "nask:1", "nask")
    kinds = {m.kind for m in inc.materials}
    assert {"html", "asset", "har", "image"} <= kinds
    page = next(m for m in inc.materials if m.kind == "html")
    # expectation read from the data itself (no real domains in tests): page URL host == HAR host
    har = next(m for m in inc.materials if m.kind == "har")
    assert page.original_url and page.original_url.startswith("https://")
    assert urlsplit(page.original_url).hostname == urlsplit(har.original_url).hostname
    assets = [m for m in inc.materials if m.kind == "asset"]
    assert assets and all(a.parent_html == page.material_id for a in assets)
    assert any(a.is_common_lib for a in assets)          # fbevents.js
    assert all(len(m.material_id) == 16 for m in inc.materials)


@needs_data
def test_real_incident_61_chain():
    inc = build_incident(RAW / "61", "nask:61", "nask")
    pages = sorted((m for m in inc.materials if m.kind == "html"), key=lambda m: m.meta["chain_index"])
    assert [m.meta["chain_index"] for m in pages] == [1, 2, 3]
    # each asset points to the page of its own strona_N directory
    by_id = {m.material_id: m for m in pages}
    for a in (m for m in inc.materials if m.kind == "asset"):
        parent = by_id[a.parent_html]
        assert a.meta["rel_path"].split("/")[0] == parent.meta["rel_path"].split("/")[0]


@needs_data
def test_real_dataset_roundtrip(tmp_path):
    incs = load_incidents(RAW)
    assert [i.incident_id for i in incs][:3] == ["nask:1", "nask:2", "nask:3"]
    assert len(incs) == 10
    out = write_jsonl(incs, tmp_path / "incidents.jsonl")
    back = read_jsonl(out)
    assert [i.incident_id for i in back] == [i.incident_id for i in incs]
    assert sum(len(i.materials) for i in back) == sum(len(i.materials) for i in incs)
    inc5 = next(i for i in back if i.incident_id == "nask:5")
    assert inc5.meta["has_landing"] is False


# ------------------------------------------------------------------ synthetic / broken input

def _make_saved_page(d: Path) -> None:
    (d / "Page_files").mkdir(parents=True)
    (d / "Page.html").write_text(
        '<!-- saved from url=(0024)https://scam.example.com/ -->\n<html><head><title>T</title></head></html>',
        encoding="utf-8")
    (d / "Page_files" / "jquery.min.js.pobrane").write_text("/* jquery */", encoding="utf-8")
    (d / "Page_files" / "app.js.pobrane").write_text("var a=1;", encoding="utf-8")
    (d / "Page_files" / "copy.js").write_text("var a=1;", encoding="utf-8")  # duplicate bytes of app.js


def test_synthetic_saved_page(tmp_path):
    _make_saved_page(tmp_path / "7")
    inc = build_incident(tmp_path / "7", "nask:7", "nask")
    page = next(m for m in inc.materials if m.kind == "html")
    assert page.original_url == "https://scam.example.com/"
    assets = {m.meta["name"]: m for m in inc.materials if m.kind == "asset"}
    assert assets["jquery.min.js.pobrane"].is_common_lib
    assert assets["jquery.min.js.pobrane"].mime == "text/javascript" or assets["jquery.min.js.pobrane"].mime
    # exact duplicate collapsed into one material
    assert len(assets) == 2
    dup = assets["app.js.pobrane"]
    assert dup.meta["duplicate_paths"] == ["Page_files/copy.js"]


def test_empty_folder_and_garbage(tmp_path):
    root = tmp_path / "root"
    (root / "empty").mkdir(parents=True)
    (root / "junk").mkdir()
    (root / "junk" / "broken.html").write_bytes(b"\x00\xff\xfe<html")
    (root / "junk" / "zero.png").write_bytes(b"")
    (root / "junk" / ".DS_Store").write_bytes(b"x")
    incs = load_incidents(root)
    assert [i.incident_id for i in incs] == ["nask:empty", "nask:junk"]
    assert incs[0].materials == [] and incs[0].meta["has_landing"] is False
    names = {m.meta["name"] for m in incs[1].materials}
    assert names == {"broken.html", "zero.png"}
    assert next(m for m in incs[1].materials if m.meta["name"] == "zero.png").is_common_lib  # empty file


def test_missing_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_incidents(tmp_path / "nope")


def test_upload_single_file_folder_and_zip(tmp_path):
    data_dir = tmp_path / "data"
    f = tmp_path / "ad.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    inc = load_upload(f, data_dir=data_dir, incident_id="upload:a")
    assert inc.source == "upload" and inc.materials[0].kind == "image"

    _make_saved_page(tmp_path / "case")
    inc = load_upload(tmp_path / "case", data_dir=data_dir, incident_id="upload:b")
    assert {m.kind for m in inc.materials} == {"html", "asset"}

    z = tmp_path / "case.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in (tmp_path / "case").rglob("*"):
            if p.is_file():
                zf.write(p, Path("case") / p.relative_to(tmp_path / "case"))
    inc = load_upload(z, data_dir=data_dir, incident_id="upload:c")
    assert any(m.kind == "html" and m.original_url for m in inc.materials)


def test_upload_zip_slip_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    with pytest.raises(ValueError):
        load_upload(z, data_dir=tmp_path / "data", incident_id="upload:evil")
    assert not (tmp_path / "evil.txt").exists()


# ------------------------------------------------------------------ runner

def test_runner_isolates_errors(tmp_path, monkeypatch):
    _make_saved_page(tmp_path / "raw" / "1")
    _make_saved_page(tmp_path / "raw" / "2")
    incs = load_incidents(tmp_path / "raw")

    mod = types.ModuleType("fakecollector.features._dummy")
    mod.MODULE, mod.LEVEL, mod.KINDS = "_dummy", "material", ["html", "asset"]

    def extract(m, ctx):
        if m.incident_id == "nask:2" and m.kind == "html":
            raise RuntimeError("boom")
        return FeatureRecord(entity_id=m.material_id, level="material", module="_dummy",
                             features={"n": 1, "tags": {"b", "a"}, "meta": {"x": "y"}, "vec": (0.5, 1.0)},
                             incident_id=m.incident_id)

    mod.extract = extract
    monkeypatch.setitem(sys.modules, "fakecollector.features._dummy", mod)
    stats = run_module("_dummy", _ctx(tmp_path), incidents=incs)
    df = pd.read_parquet(stats["out"])
    # common libs (jquery) are skipped: per incident 1 html + 1 asset
    assert stats["records"] == 4 and stats["with_errors"] == 1
    assert {"entity_id", "incident_id", "level", "module", "errors", "n", "tags", "meta.x", "vec"} <= set(df.columns)
    ok = df[df["errors"].map(len) == 0].iloc[0]
    assert list(ok["tags"]) == ["a", "b"]
    bad = df[df["errors"].map(len) > 0].iloc[0]
    assert "boom" in bad["errors"][0] and pd.isna(bad["n"])


def test_runner_empty_input(tmp_path, monkeypatch):
    mod = types.ModuleType("fakecollector.features._dummy2")
    mod.MODULE, mod.KINDS = "_dummy2", ["html"]
    mod.extract = lambda m, ctx: None
    monkeypatch.setitem(sys.modules, "fakecollector.features._dummy2", mod)
    stats = run_module("_dummy2", _ctx(tmp_path), incidents=[])
    df = pd.read_parquet(stats["out"])
    assert len(df) == 0 and "entity_id" in df.columns


# ------------------------------------------------------------------ regression (round 2)

def test_bare_dotfile_har_is_detected(tmp_path):
    """61/strona_1/.har: a file named exactly '.har' must be a har material (globs skip dotfiles)."""
    d = tmp_path / "61" / "strona_1"
    d.mkdir(parents=True)
    (d / ".har").write_text('{"log": {"pages": [], "entries": [{"startedDateTime": "2026-10-20T11:55:07Z",'
                            ' "request": {"url": "https://scam.example.org/x"}}]}}', encoding="utf-8")
    (d / "._junk").write_bytes(b"x")  # macOS resource fork, must be ignored
    inc = build_incident(tmp_path / "61", "nask:61", "nask")
    hars = [m for m in inc.materials if m.kind == "har"]
    assert len(hars) == 1 and hars[0].meta["name"] == ".har"
    assert hars[0].original_url == "https://scam.example.org/x"
    assert hars[0].meta["har_started"].startswith("2026-10-20")
    assert len(inc.materials) == 1


@needs_data
def test_real_61_has_three_har_files():
    inc = build_incident(RAW / "61", "nask:61", "nask")
    names = sorted(m.meta["rel_path"] for m in inc.materials if m.kind == "har")
    assert "strona_1/.har" in names and len(names) == 3


def _list_module(monkeypatch, name: str):
    mod = types.ModuleType(f"fakecollector.features.{name}")
    mod.MODULE, mod.LEVEL, mod.KINDS = name, "material", ["html", "asset"]

    def extract(m, ctx):
        if m.kind == "asset":
            return []                                    # skipped, not an error
        return [FeatureRecord(entity_id=f"{m.material_id}#f{i}", level="material", module=name,
                              features={"i": i}) for i in range(3)]

    mod.extract = extract
    monkeypatch.setitem(sys.modules, f"fakecollector.features.{name}", mod)
    return mod


def test_runner_accepts_list_and_empty_list(tmp_path, monkeypatch):
    _make_saved_page(tmp_path / "raw" / "1")
    incs = load_incidents(tmp_path / "raw")
    _list_module(monkeypatch, "_listmod")
    stats = run_module("_listmod", _ctx(tmp_path), incidents=incs)
    df = pd.read_parquet(stats["out"])
    assert stats["records"] == 3 and stats["with_errors"] == 0 and stats["skipped"] == 1
    assert sorted(df["i"]) == [0, 1, 2]
    assert all(df["incident_id"] == "nask:1") and all(df["entity_id"].str.contains("#f"))


def test_runner_rejects_wrong_return_type(tmp_path, monkeypatch):
    _make_saved_page(tmp_path / "raw" / "1")
    incs = load_incidents(tmp_path / "raw")
    mod = types.ModuleType("fakecollector.features._badmod")
    mod.MODULE, mod.KINDS = "_badmod", ["html"]
    mod.extract = lambda m, ctx: [{"not": "a record"}]
    monkeypatch.setitem(sys.modules, "fakecollector.features._badmod", mod)
    stats = run_module("_badmod", _ctx(tmp_path), incidents=incs)
    df = pd.read_parquet(stats["out"])
    assert stats["with_errors"] == 1 and "TypeError" in df["errors"].iloc[0][0]


def test_extract_for_path_single_upload(tmp_path, monkeypatch):
    _make_saved_page(tmp_path / "case")
    _list_module(monkeypatch, "_listmod2")
    ctx = _ctx(tmp_path)
    recs = extract_for_path(tmp_path / "case", ctx, modules=["_listmod2", "html_struct", "_does_not_exist"])
    mods = {r.module for r in recs}
    assert mods == {"_listmod2", "html_struct"}
    assert all(r.incident_id == "upload:case" for r in recs)
    page = next(r for r in recs if r.module == "html_struct")
    assert page.features["original_url"] == "https://scam.example.com/"
    assert not (tmp_path / "features").exists()          # in-memory only, no parquet written


def test_cli_inventory_does_not_touch_tracked_docs(tmp_path):
    """README command `inventory` must not rewrite the tracked docs/DATA_INVENTORY.md."""
    from fakecollector.cli import main

    _make_saved_page(tmp_path / "raw" / "1")
    docs = REPO_ROOT / "docs" / "DATA_INVENTORY.md"
    before = docs.read_bytes() if docs.exists() else None
    assert main(["inventory", "--data", str(tmp_path / "raw")]) == 0
    assert (docs.read_bytes() if docs.exists() else None) == before
    assert (REPO_ROOT / "data" / "interim" / "DATA_INVENTORY.md").exists()
