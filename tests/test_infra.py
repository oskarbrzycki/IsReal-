"""Tests for the "infra" feature module (owner W4).

Covers: two real incidents, a missing file, a corrupted file, an empty file,
an unsupported kind and the wrong entity level. All offline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakecollector.core.models import Context, Incident, Material
from fakecollector.features import infra

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "data" / "raw" / "nask"


@pytest.fixture()
def ctx(tmp_path: Path) -> Context:
    # data_dir points at a temp dir so the OSINT cache never touches real data.
    return Context(repo_root=REPO_ROOT, data_dir=tmp_path, settings={}, offline=True)


def _material(path: Path, kind: str, incident_id: str = "nask:test") -> Material:
    return Material(
        material_id="t" * 16,
        incident_id=incident_id,
        kind=kind,  # type: ignore[arg-type]
        path=str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if path.is_relative_to(REPO_ROOT)
        else str(path),
        size_bytes=path.stat().st_size if path.exists() else 0,
    )


def _find(pattern: str) -> Path | None:
    if not RAW.is_dir():
        return None
    matches = sorted(RAW.glob(pattern))
    return matches[0] if matches else None


needs_data = pytest.mark.skipif(not RAW.is_dir(), reason="NASK data not present")


# ---------------------------------------------------------------- real data
# R1: no value from the organizer's data is written here. Expectations are
# derived from the files themselves (in this set a HAR is named after the
# scam's domain), so the tests prove the behaviour without leaking IDs.

def _har(folder: str) -> Path | None:
    hars = sorted(p for p in RAW.glob(f"{folder}/*.har") if p.name != ".har") if RAW.is_dir() else []
    return hars[0] if hars else None


@needs_data
def test_har_incident_1_has_pixel_and_domain(ctx: Context) -> None:
    """Incident 1: HAR must yield the landing domain and an FB pixel."""
    path = _har("1")
    if path is None:
        pytest.skip("incident 1 HAR not found")
    record = infra.extract(_material(path, "har", "nask:1"), ctx)

    assert record.module == "infra"
    assert record.level == "material"
    assert record.incident_id == "nask:1"
    assert record.errors == []
    assert path.stem.lower() in record.features["landing_domains"]
    assert any(t.startswith("fb_pixel:") for t in record.features["har_tracker_ids"])
    assert record.features["n_requests"] > 0
    assert record.features["first_seen"] is not None
    # Generic CDNs must not leak into the landing domains.
    assert not any(
        d.endswith(("facebook.com", "facebook.net", "gstatic.com"))
        for d in record.features["landing_domains"]
    )


@needs_data
def test_incidents_1_and_2_share_a_pixel(ctx: Context) -> None:
    """The campaign evidence itself: 1 and 2 carry the same concrete pixel ID."""
    pixels = {}
    for folder in ("1", "2"):
        hars = sorted(p for p in RAW.glob(f"{folder}/*.har"))
        if not hars:
            pytest.skip(f"no HAR in incident {folder}")
        pixels[folder] = {
            t for p in hars
            for t in infra.extract(_material(p, "har", f"nask:{folder}"), ctx).features["har_tracker_ids"]
            if t.startswith("fb_pixel:")
        }
    assert pixels["1"] & pixels["2"]


@needs_data
def test_har_incident_36_ad_params(ctx: Context) -> None:
    """Incident 36: ad_id comes from the navigation URL, pixel from fbpx."""
    path = _har("36")
    if path is None:
        pytest.skip("incident 36 HAR not found")
    record = infra.extract(_material(path, "har", "nask:36"), ctx)

    assert record.errors == []
    assert path.stem.lower() in record.features["landing_domains"]
    assert any(x.startswith("ad_id:") for x in record.features["ad_account_ids"])
    assert any(t.startswith("fb_pixel:") for t in record.features["har_tracker_ids"])
    # Per-click junk must never become an identifier.
    assert not any(p.startswith("fbclid=") for p in record.features["ad_params"])
    assert not any(p.startswith("access_token=") for p in record.features["ad_params"])


@needs_data
def test_yt_dlp_info_json_gives_ad_account(ctx: Context) -> None:
    """Incident 5 has no landing page, only a Facebook Ad Library video."""
    path = _find("**/5/*.info.json")
    if path is None:
        pytest.skip("incident 5 info.json not found")
    record = infra.extract(_material(path, "json", "nask:5"), ctx)

    assert record.errors == []
    ids = record.features["ad_account_ids"]
    assert any(x.startswith("fb_ad_id:") for x in ids)
    assert any(x.startswith("fb_page_id:") for x in ids)
    # facebook.com is generic: it is not this incident's landing domain.
    assert record.features["landing_domains"] == []


@needs_data
def test_dot_named_har_is_parsed(ctx: Context) -> None:
    """Incident 61 ships a HAR literally named ".har" - glob "*.har" misses it."""
    path = _find("**/61/strona_1/.har")
    if path is None:
        pytest.skip("dot-named HAR not found")
    record = infra.extract(_material(path, "har", "nask:61"), ctx)
    assert record.errors == []
    assert record.features["n_requests"] > 0
    # the only tracker of incident 61 lives in this file
    assert any(t.startswith("google_ads:") for t in record.features["har_tracker_ids"])


# ------------------------------------------------------- failure resilience

def test_missing_file_does_not_raise(ctx: Context) -> None:
    material = Material(
        material_id="m" * 16, incident_id="nask:x", kind="har",
        path="data/raw/nask/does-not-exist.har",
    )
    record = infra.extract(material, ctx)
    assert record.errors == ["file_not_found"]
    assert record.features["har_domains"] == []
    assert record.features["favicon_mmh3"] is None


def test_corrupted_har_is_reported_not_raised(tmp_path: Path, ctx: Context) -> None:
    broken = tmp_path / "broken.har"
    broken.write_text('{"log": {"entries": [ this is not json', encoding="utf-8")
    record = infra.extract(_material(broken, "har"), ctx)
    assert record.errors and any("json_decode_error" in e for e in record.errors)
    assert record.features["har_tracker_ids"] == []


def test_empty_har_yields_empty_features(tmp_path: Path, ctx: Context) -> None:
    empty = tmp_path / "empty.har"
    empty.write_text(json.dumps({"log": {"entries": [], "pages": []}}), encoding="utf-8")
    record = infra.extract(_material(empty, "har"), ctx)
    assert record.errors == []
    assert record.features["n_requests"] == 0
    assert record.features["landing_domains"] == []
    assert record.features["first_seen"] is None


def test_zero_byte_file(tmp_path: Path, ctx: Context) -> None:
    empty = tmp_path / "zero.har"
    empty.write_bytes(b"")
    record = infra.extract(_material(empty, "har"), ctx)
    assert record.errors  # decode error, but no exception
    assert record.features["har_domains"] == []


def test_unknown_json_kind(tmp_path: Path, ctx: Context) -> None:
    path = tmp_path / "random.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    record = infra.extract(_material(path, "json"), ctx)
    assert "json_unknown_kind" in record.errors


def test_incident_level_input_is_rejected_cleanly(ctx: Context) -> None:
    incident = Incident(incident_id="nask:1", source="nask", materials=[])
    record = infra.extract(incident, ctx)
    assert record.errors == ["unsupported_level:expected_material"]
    assert record.entity_id == "nask:1"


def test_extract_without_context(tmp_path: Path) -> None:
    """ctx is optional: the module must still work (and stay offline)."""
    path = tmp_path / "x.har"
    path.write_text(json.dumps({"log": {"entries": []}}), encoding="utf-8")
    material = Material(
        material_id="z" * 16, incident_id="nask:y", kind="har", path=str(path),
    )
    record = infra.extract(material, None)
    assert record.module == "infra"
    assert record.errors == []


# ------------------------------------------------------------ unit helpers

def test_tracker_id_spellings_collapse() -> None:
    """AW-123 and the bare 123 conversion ID must become one value."""
    found = infra._find_trackers(
        "https://www.googletagmanager.com/gtag/js?id=AW-1234567890 "
        "https://www.google.com/pagead/1p-conversion/1234567890/?x=1"
    )
    assert found == {"google_ads:1234567890"}


def test_stoplist_matches_parent_domain() -> None:
    stop = {"domains": {"googleapis.com"}, "filenames": set(), "sha1": set()}
    assert infra._is_generic_domain("translate-pa.googleapis.com", stop)
    assert infra._is_generic_domain("googleapis.com", stop)
    assert not infra._is_generic_domain("example-landing.com", stop)


def test_etld1_basic() -> None:
    assert infra._etld1("www.example-landing.com") == "example-landing.com"
    assert infra._etld1("") is None
    assert infra._etld1("localhost") is None


def test_param_template_id_ignores_trivial_templates() -> None:
    assert infra._template_id(set()) is None
    assert infra._template_id({"id"}) is None
    assert infra._template_id({"utm_source", "utm_id"}) is None
    full = {"utm_id", "utm_medium", "utm_campaign", "utm_content", "utm_visit"}
    assert infra._template_id(full) == infra._template_id(set(full))  # order-free
    assert infra._template_id(full) != infra._template_id(full | {"clickid"})


def test_adtech_networks_exclude_the_ubiquitous_ones() -> None:
    """A Facebook pixel is on nearly every sample: it must not be a "stack"."""
    assert infra._is_adtech("static.ads-twitter.com")
    assert infra._is_adtech("bat.bing.net")
    assert not infra._is_adtech("connect.facebook.net")
    assert not infra._is_adtech("www.googletagmanager.com")
    assert not infra._is_adtech("example-landing.com")


def test_generic_server_banner_is_dropped(tmp_path: Path, ctx: Context) -> None:
    har = {
        "log": {
            "entries": [
                {
                    "startedDateTime": "2026-10-01T00:00:00.000Z",
                    "_resourceType": "document",
                    "request": {"url": "https://example-scam-test.pro/a?x=1"},
                    "response": {
                        "status": 200,
                        "content": {"mimeType": "text/html"},
                        "headers": [
                            {"name": "Server", "value": "cloudflare"},
                            {"name": "X-Powered-By", "value": "PHP/8.1.0"},
                        ],
                    },
                }
            ]
        }
    }
    path = tmp_path / "s.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    record = infra.extract(_material(path, "har"), ctx)
    assert record.features["server_headers"] == ["x-powered-by:PHP/8.1.0"]


@needs_data
def test_adtech_stack_links_48_and_61(ctx: Context) -> None:
    """48 and 61 embed the same unusual Twitter+Bing pixel pair."""
    stacks = {}
    for incident, pattern in (("48", "**/48/*.html"), ("61", "**/61/strona_1/*.html")):
        path = _find(pattern)
        if path is None:
            pytest.skip(f"landing HTML of {incident} not found")
        record = infra.extract(_material(path, "html", f"nask:{incident}"), ctx)
        stacks[incident] = set(record.features["adtech_stack"])
    assert stacks["48"], "48 should load at least one distinctive ad network"
    assert stacks["48"] & stacks["61"], "expected a shared adtech network"


def test_every_signal_has_a_short_label() -> None:
    """Each spec carries a short Polish "label" shown in the UI explanations."""
    for name, spec in infra.SIGNALS.items():
        label = spec.get("label")
        assert isinstance(label, str) and label.strip(), f"{name} has no label"
        assert len(label) <= 60, f"{name} label too long for the UI: {label!r}"
        assert label != name, f"{name} label is just the raw signal name"


def test_every_signal_has_a_valid_class() -> None:
    """CONTRACTS.md v0.4: each signal is "campaign" or "family"."""
    assert set(infra.SIGNAL_CLASS) == set(infra.SIGNALS)
    assert set(infra.SIGNAL_CLASS.values()) <= {"campaign", "family"}


def test_signal_names_do_not_collide_with_other_modules() -> None:
    """The engine silently drops a duplicate signal name from the later module.

    "shared_trackers" was lost exactly this way, so guard against a repeat.
    """
    import importlib

    for other in ("html_struct", "text", "visual", "faces"):
        try:
            mod = importlib.import_module(f"fakecollector.features.{other}")
        except Exception:  # noqa: BLE001 - optional deps (PIL, torch) may be absent
            continue
        clash = set(getattr(mod, "SIGNALS", {}) or {}) & set(infra.SIGNALS)
        assert not clash, f"signal name clash with {other}: {sorted(clash)}"


def test_cdn_ips_are_not_evidence() -> None:
    from fakecollector.features import infra_osint

    assert infra_osint.is_cdn_ip("188.114.97.1")    # Cloudflare edge ranges
    assert infra_osint.is_cdn_ip("104.16.0.1")
    assert not infra_osint.is_cdn_ip("203.0.113.7")  # TEST-NET-3 (RFC 5737)
    assert not infra_osint.is_cdn_ip("not-an-ip")


def test_registrar_spellings_collapse() -> None:
    from fakecollector.features import infra_osint

    norm = infra_osint.normalise_registrar
    assert norm("NameCheap, Inc.") == norm("Namecheap Inc.") == "namecheap"
    assert norm("NameSilo, LLC") == "namesilo"
    assert norm(None) is None


def test_offline_mode_reads_cache_and_never_touches_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo runs offline: answers come from the sqlite cache only."""
    from fakecollector.features import infra_osint

    def no_network(*_args, **_kwargs):
        raise AssertionError("network call in offline mode")

    monkeypatch.setattr(infra_osint, "_http_json", no_network)
    monkeypatch.setattr(infra_osint, "_dns_records", no_network)

    ctx = Context(repo_root=REPO_ROOT, data_dir=tmp_path, settings={}, offline=True)
    conn = infra_osint._connect(infra_osint._cache_path(ctx))
    infra_osint._cache_put(conn, "rdap", "example-a.live", {
        "registrar": "Example Registrar Inc", "created": "2026-01-02T03:04:05Z", "ns": ["ns1.x.net"],
    })
    conn.close()

    features = infra._empty_features()
    features["landing_domains"] = ["example-a.live", "uncached.example"]
    provenance: dict[str, str] = {}
    errors: list[str] = []
    infra_osint.enrich(features, ctx, offline=True, provenance=provenance, errors=errors)

    assert errors == []
    assert features["rdap_registrar"] == "example registrar"
    from datetime import datetime, timezone

    expected = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp() / 86400
    assert features["rdap_created_days"] == pytest.approx(expected, abs=1e-3)
    assert features["rdap_ns"] == ["ns1.x.net"]
    assert "rdap:cache" in provenance["osint"]


def test_crtsh_empty_answer_differs_from_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from fakecollector.features import infra_osint

    monkeypatch.setattr(infra_osint, "_http_json", lambda _url: [])
    empty = infra_osint._crtsh("example.test")
    assert empty is not None and empty["empty"] is True and empty["san"] == []

    monkeypatch.setattr(infra_osint, "_http_json", lambda _url: None)
    assert infra_osint._crtsh("example.test") is None  # error -> not cached


def test_registration_date_signal_uses_days() -> None:
    spec = infra.SIGNALS["shared_registrar_and_date"]
    assert spec["field"] == "rdap_created_days"
    assert spec["tol"] == 3.0


def test_signals_reference_existing_fields() -> None:
    """Every SIGNALS field must exist in the feature schema (engine contract)."""
    schema = infra._empty_features()
    for name, spec in infra.SIGNALS.items():
        assert spec["field"] in schema, f"signal {name} points at unknown field"
