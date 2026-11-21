"""Domain rotation monitor (owner W4): `python -m fakecollector monitor [--online]`.

Re-checks RDAP and DNS for the landing domains of every known campaign,
compares the answers with the previous run and reports what changed:
new name servers or IPs, a domain on hold / in redemption, an expired or
deleted domain, a name that no longer resolves.

Read-only with respect to the pipeline: it reads data/graph/clusters.json and
data/features/infra.parquet, touches nothing in the engine, and writes only
  data/cache/monitor_state.json      previous answers, for the next comparison
  data/graph/monitor_<ts>.json       this run's report

SAFETY: like infra_osint, it asks only neutral public services (rdap.org,
public DNS resolvers), never the scam hosts. --offline (default) reads the
OSINT cache only and sends nothing over the network.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fakecollector.core.models import Context
from fakecollector.features import infra_osint

log = logging.getLogger(__name__)

#: EPP status fragments that mean the site is (being) taken down.
SUSPENDED = ("hold",)                                    # clientHold / serverHold
DELETING = ("redemption", "pending delete", "pendingdelete")


# ----------------------------------------------------------------------------- paths

def _path(ctx: Context, key: str, default: str) -> Path:
    raw = ((ctx.settings or {}).get("paths") or {}).get(key, default)
    p = Path(str(raw))
    return p if p.is_absolute() else Path(ctx.repo_root) / p


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [value]
    return [str(v) for v in value] if isinstance(value, (list, tuple, set)) else [str(value)]


# ----------------------------------------------------------------------------- inputs

def known_campaign_domains(ctx: Context) -> dict[str, list[str]]:
    """{landing domain: [campaign ids]} from clusters.json + infra.parquet."""
    import pandas as pd

    features = _path(ctx, "features", "data/features") / "infra.parquet"
    if not features.is_file():
        return {}
    df = pd.read_parquet(features, columns=["incident_id", "landing_domains"])
    by_incident: dict[str, set[str]] = {}
    for inc, value in zip(df["incident_id"], df["landing_domains"]):
        by_incident.setdefault(str(inc), set()).update(_as_list(value))

    campaign_of: dict[str, str] = {}
    clusters = _path(ctx, "graph", "data/graph") / "clusters.json"
    if clusters.is_file():
        try:
            data = json.loads(clusters.read_text(encoding="utf-8"))
            for cluster in data.get("clusters") or []:
                for member in cluster.get("members") or []:
                    campaign_of[str(member)] = str(cluster.get("campaign_id"))
        except (ValueError, OSError) as exc:
            log.warning("monitor: cannot read clusters.json: %s", exc)

    out: dict[str, set[str]] = {}
    for inc, domains in by_incident.items():
        label = campaign_of.get(inc, inc)          # before `correlate`: the incident itself
        for domain in domains:
            if domain:
                out.setdefault(domain, set()).add(label)
    return {d: sorted(c) for d, c in sorted(out.items())}


# ----------------------------------------------------------------------------- snapshots

def snapshot(domain: str, conn, online: bool) -> dict[str, Any]:
    """Current RDAP + DNS view of one domain.

    online: ask the services again (fresh answer, cache refreshed); on a network
    failure fall back to the cached answer and say so. offline: cache only.
    """
    out: dict[str, Any] = {"rdap": None, "dns": None, "source": {}}
    for source, fetch in (("rdap", infra_osint._rdap_domain), ("dns", infra_osint._dns_records)):
        value = None
        if online:
            value = fetch(domain)
            if value is not None:
                infra_osint._cache_put(conn, source, domain, value)
                out["source"][source] = "live"
        if value is None:
            row = conn.execute(
                "SELECT payload FROM osint WHERE source=? AND key=?", (source, domain)
            ).fetchone()
            if row:
                try:
                    value = json.loads(row[0])
                    out["source"][source] = "cache"
                except ValueError:
                    value = None
        out[source] = value
        if value is None:
            out["source"][source] = "none"
    return out


def _set(snap: dict | None, part: str, key: str) -> set[str]:
    section = (snap or {}).get(part) or {}
    return {str(x) for x in (section.get(key) or [])}


def _value(snap: dict | None, part: str, key: str) -> Any:
    return ((snap or {}).get(part) or {}).get(key)


def diff(prev: dict | None, cur: dict) -> list[dict[str, Any]]:
    """Changes between two snapshots of one domain (empty on the first run)."""
    if not prev:
        return []
    changes: list[dict[str, Any]] = []

    def set_change(kind: str, part: str, key: str, label: str) -> None:
        # only compare when both runs actually had an answer for this part
        if (prev.get(part) is None) or (cur.get(part) is None):
            return
        before, after = _set(prev, part, key), _set(cur, part, key)
        if before != after:
            changes.append({"kind": kind, "added": sorted(after - before),
                            "removed": sorted(before - after),
                            "detail": f"{label}: +{sorted(after - before)} -{sorted(before - after)}"})

    set_change("ns_changed", "dns", "ns", "zmiana serwerów nazw (DNS)")
    set_change("ip_changed", "dns", "a", "zmiana adresów IP (rekord A)")
    set_change("mx_changed", "dns", "mx", "zmiana serwerów poczty (MX)")
    set_change("status_changed", "rdap", "status", "zmiana statusu w rejestrze")

    for key, kind, label in (("registrar", "registrar_changed", "zmiana rejestratora"),
                             ("expires", "expiry_changed", "zmiana daty wygaśnięcia (odnowienie?)")):
        if prev.get("rdap") is not None and cur.get("rdap") is not None:
            before, after = _value(prev, "rdap", key), _value(cur, "rdap", key)
            if before != after and (before or after):
                changes.append({"kind": kind, "before": before, "after": after,
                                "detail": f"{label}: {before} -> {after}"})

    if prev.get("dns") is not None and cur.get("dns") is not None:
        was, now = bool(_value(prev, "dns", "nxdomain")), bool(_value(cur, "dns", "nxdomain"))
        if now and not was:
            changes.append({"kind": "stopped_resolving", "detail": "domena przestała istnieć w DNS (NXDOMAIN)"})
        elif was and not now:
            changes.append({"kind": "resolving_again", "detail": "domena znów istnieje w DNS"})

    if prev.get("rdap") is not None and cur.get("rdap") is not None:
        if _value(cur, "rdap", "not_found") and not _value(prev, "rdap", "not_found"):
            changes.append({"kind": "gone_from_registry",
                            "detail": "domena zniknęła z RDAP (usunięta lub wygasła)"})
    return changes


def alerts(cur: dict, now: datetime) -> list[dict[str, Any]]:
    """Problems visible in the current snapshot alone (no history needed)."""
    out: list[dict[str, Any]] = []
    status = " ".join(_set(cur, "rdap", "status"))
    if any(s in status for s in SUSPENDED):
        out.append({"kind": "suspended", "detail": f"domena zawieszona w rejestrze ({status})"})
    if any(s in status for s in DELETING):
        out.append({"kind": "being_deleted", "detail": f"domena w trakcie usuwania ({status})"})
    expires = _value(cur, "rdap", "expires")
    if expires:
        try:
            when = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < now:
                out.append({"kind": "expired", "detail": f"domena wygasła {when.date().isoformat()}"})
        except ValueError:
            pass
    if _value(cur, "dns", "nxdomain"):
        out.append({"kind": "nxdomain", "detail": "domena nie istnieje w DNS (NXDOMAIN)"})
    elif cur.get("dns") is not None and not _set(cur, "dns", "a"):
        out.append({"kind": "no_a_record", "detail": "brak rekordu A - strona prawdopodobnie martwa"})
    if _value(cur, "rdap", "not_found"):
        out.append({"kind": "not_in_registry", "detail": "brak domeny w RDAP (usunięta albo TLD bez RDAP)"})
    return out


# ----------------------------------------------------------------------------- run

def run(ctx: Context, online: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    domains = known_campaign_domains(ctx)
    state_path = _path(ctx, "cache", "data/cache") / "monitor_state.json"
    previous: dict[str, Any] = {}
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8")).get("domains") or {}
        except (ValueError, OSError):
            previous = {}

    conn = infra_osint._connect(infra_osint._cache_path(ctx))
    results: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    try:
        for domain, campaigns in domains.items():
            snap = snapshot(domain, conn, online)
            current[domain] = snap
            results.append({
                "domain": domain,
                "campaigns": campaigns,
                "source": snap["source"],
                "first_seen_by_monitor": domain not in previous,
                "changes": diff(previous.get(domain), snap),
                "alerts": alerts(snap, now),
            })
    finally:
        conn.close()

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "mode": "online" if online else "offline (cache only)",
        "previous_run": bool(previous),
        "domains_checked": len(results),
        "domains_with_changes": sum(1 for r in results if r["changes"]),
        "domains_with_alerts": sum(1 for r in results if r["alerts"]),
        "results": results,
    }
    graph_dir = _path(ctx, "graph", "data/graph")
    graph_dir.mkdir(parents=True, exist_ok=True)
    report_path = graph_dir / f"monitor_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Keep the previous answer for a domain we could not check this time.
    merged = {**previous, **{d: s for d, s in current.items()
                             if s.get("rdap") is not None or s.get("dns") is not None}}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"updated_at": report["generated_at"], "domains": merged},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def print_summary(report: dict[str, Any]) -> None:
    print(f"monitor ({report['mode']}): {report['domains_checked']} domen, "
          f"zmiany: {report['domains_with_changes']}, alerty: {report['domains_with_alerts']}"
          + ("" if report["previous_run"] else "  [pierwszy przebieg - stan bazowy zapisany]"))
    for r in report["results"]:
        lines = [c["detail"] for c in r["changes"]] + [a["detail"] for a in r["alerts"]]
        if lines:
            print(f"  {r['domain']}  [{', '.join(r['campaigns'])}]")
            for line in lines:
                print(f"    - {line}")
    print(f"raport: {report['report_path']}")


def main(online: bool = False) -> int:
    from fakecollector.core.config import make_context

    ctx = make_context(offline=not online)
    report = run(ctx, online=online)
    if not report["domains_checked"]:
        print("monitor: brak domen kampanii - uruchom najpierw `features --module infra` (i `correlate`).")
        return 2
    print_summary(report)
    return 0
