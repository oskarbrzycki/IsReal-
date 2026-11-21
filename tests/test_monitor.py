"""Offline tests for `python -m fakecollector monitor` (owner W4).

Synthetic domains only (R1: nothing from the organizer's data), seeded OSINT
cache, previous state on disk, and any network call fails the test.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from fakecollector import monitor
from fakecollector.core.models import Context
from fakecollector.features import infra_osint

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
A, B, C = "example-alpha.com", "example-beta.org", "example-gamma.net"


def _ctx(root: Path) -> Context:
    settings = {"paths": {"features": "data/features", "graph": "data/graph", "cache": "data/cache"}}
    return Context(repo_root=root, data_dir=root / "data", settings=settings, offline=True)


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    def no_network(*_a, **_k):
        raise AssertionError("network call in offline mode")

    monkeypatch.setattr(infra_osint, "_http_get", no_network)
    monkeypatch.setattr(infra_osint, "_http_json", no_network)
    monkeypatch.setattr(infra_osint, "_dns_records", no_network)
    monkeypatch.setattr(infra_osint, "_rdap_domain", no_network)

    ctx = _ctx(tmp_path)
    (tmp_path / "data" / "features").mkdir(parents=True)
    (tmp_path / "data" / "graph").mkdir(parents=True)
    pd.DataFrame({
        "incident_id": ["t:1", "t:2", "t:3"],
        "landing_domains": [[A], [B], [C]],
    }).to_parquet(tmp_path / "data" / "features" / "infra.parquet")
    (tmp_path / "data" / "graph" / "clusters.json").write_text(json.dumps({"clusters": [
        {"campaign_id": "C001", "members": ["t:1", "t:2"]},
        {"campaign_id": "C002", "members": ["t:3"]},
    ]}), encoding="utf-8")

    conn = infra_osint._connect(infra_osint._cache_path(ctx))
    # A: moved to new name servers and a new IP
    infra_osint._cache_put(conn, "rdap", A, {"registrar": "r", "ns": [], "status": ["active"],
                                             "expires": "2027-01-01T00:00:00Z"})
    infra_osint._cache_put(conn, "dns", A, {"a": ["203.0.113.9"], "ns": ["ns1.new.test"], "mx": [],
                                            "nxdomain": False})
    # B: put on hold by the registry and already expired
    infra_osint._cache_put(conn, "rdap", B, {"registrar": "r", "ns": [], "status": ["client hold"],
                                             "expires": "2026-11-01T00:00:00Z"})
    infra_osint._cache_put(conn, "dns", B, {"a": [], "ns": [], "mx": [], "nxdomain": True})
    # C: unchanged
    infra_osint._cache_put(conn, "rdap", C, {"registrar": "r", "ns": [], "status": ["active"],
                                             "expires": "2027-06-01T00:00:00Z"})
    infra_osint._cache_put(conn, "dns", C, {"a": ["203.0.113.5"], "ns": ["ns1.same.test"], "mx": [],
                                            "nxdomain": False})
    conn.close()
    return ctx


def _write_previous(ctx: Context) -> None:
    state = {"domains": {
        A: {"rdap": {"registrar": "r", "status": ["active"], "expires": "2027-01-01T00:00:00Z"},
            "dns": {"a": ["203.0.113.1"], "ns": ["ns1.old.test"], "mx": [], "nxdomain": False}},
        B: {"rdap": {"registrar": "r", "status": ["active"], "expires": "2026-11-01T00:00:00Z"},
            "dns": {"a": ["203.0.113.2"], "ns": ["ns1.b.test"], "mx": [], "nxdomain": False}},
        C: {"rdap": {"registrar": "r", "status": ["active"], "expires": "2027-06-01T00:00:00Z"},
            "dns": {"a": ["203.0.113.5"], "ns": ["ns1.same.test"], "mx": [], "nxdomain": False}},
    }}
    path = Path(ctx.repo_root) / "data" / "cache" / "monitor_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")


def test_domains_come_from_campaigns(world: Context) -> None:
    assert monitor.known_campaign_domains(world) == {A: ["C001"], B: ["C001"], C: ["C002"]}


def test_first_run_is_a_baseline(world: Context) -> None:
    report = monitor.run(world, online=False, now=NOW)
    assert report["previous_run"] is False
    assert report["domains_checked"] == 3
    assert report["domains_with_changes"] == 0            # nothing to compare with yet
    state = json.loads((Path(world.repo_root) / "data/cache/monitor_state.json").read_text("utf-8"))
    assert set(state["domains"]) == {A, B, C}


def test_changes_and_alerts_against_previous_state(world: Context) -> None:
    _write_previous(world)
    report = monitor.run(world, online=False, now=NOW)
    by = {r["domain"]: r for r in report["results"]}

    kinds_a = {c["kind"] for c in by[A]["changes"]}
    assert kinds_a == {"ns_changed", "ip_changed"}
    ns = next(c for c in by[A]["changes"] if c["kind"] == "ns_changed")
    assert ns["added"] == ["ns1.new.test"] and ns["removed"] == ["ns1.old.test"]

    kinds_b = {c["kind"] for c in by[B]["changes"]}
    assert {"status_changed", "stopped_resolving"} <= kinds_b
    alerts_b = {a["kind"] for a in by[B]["alerts"]}
    assert {"suspended", "expired", "nxdomain"} <= alerts_b

    assert by[C]["changes"] == [] and by[C]["alerts"] == []
    assert report["domains_with_changes"] == 2
    assert all(r["source"] == {"rdap": "cache", "dns": "cache"} for r in report["results"])


def test_report_is_written_under_graph(world: Context) -> None:
    report = monitor.run(world, online=False, now=NOW)
    path = Path(report["report_path"])
    assert path.parent == Path(world.repo_root) / "data" / "graph"
    assert path.name == "monitor_20261121T120000Z.json"
    assert json.loads(path.read_text("utf-8"))["domains_checked"] == 3


def test_no_features_means_nothing_to_check(tmp_path: Path) -> None:
    assert monitor.known_campaign_domains(_ctx(tmp_path)) == {}


def test_cli_registers_monitor() -> None:
    from fakecollector.cli import build_parser

    args = build_parser().parse_args(["monitor"])
    assert args.func.__name__ == "cmd_monitor" and args.online is False
    assert build_parser().parse_args(["monitor", "--online"]).online is True
