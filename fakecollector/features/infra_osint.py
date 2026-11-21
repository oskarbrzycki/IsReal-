"""Optional online OSINT enrichment for the "infra" module (owner W4).

Queries ONLY neutral public services, never a domain taken from the samples:
  * RDAP  (rdap.org bootstrap)      -> registrar, creation date, nameservers
  * DNS   (dnspython, public 1.1.1.1/8.8.8.8) -> A, NS, MX
  * crt.sh JSON                     -> certificate issuer, first seen, SANs
  * RDAP of the RIR for an IP       -> ASN / network handle

Every answer is cached in data/cache/osint.sqlite. With offline=True nothing
leaves the machine: only the cache is read. No API keys are used anywhere.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Generic client name on purpose: no project, team or event details leave the machine.
USER_AGENT = "osint-client/0.1"
TIMEOUT_S = 10
CACHE_TTL_S = 7 * 24 * 3600
MAX_DOMAINS_PER_RECORD = 4

#: Published edge ranges of CDNs/reverse proxies. An IP inside them says
#: nothing about who runs the site (9 of 10 samples sit behind Cloudflare),
#: so these IPs get no ASN lookup and never feed shared_ip_asn.
#: Source: cloudflare.com/ips-v4 (static list, no network needed).
CDN_NETWORKS = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
)]


def is_cdn_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in CDN_NETWORKS)


_REGISTRAR_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|co|corp|corporation|gmbh|sa|sas|bv|plc)\b\.?", re.IGNORECASE
)


def normalise_registrar(name: str | None) -> str | None:
    """'NameCheap, Inc.' and 'Namecheap Inc.' are the same registrar."""
    if not name:
        return None
    text = _REGISTRAR_SUFFIX.sub(" ", str(name).lower())
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return text or None


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def _cache_path(ctx: Any) -> Path:
    data_dir = getattr(ctx, "data_dir", None) if ctx else None
    base = Path(data_dir) if data_dir else Path("data")
    return base / "cache" / "osint.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS osint ("
        " source TEXT NOT NULL, key TEXT NOT NULL, fetched_at REAL NOT NULL,"
        " payload TEXT, PRIMARY KEY (source, key))"
    )
    return conn


def _cache_get(conn: sqlite3.Connection, source: str, key: str) -> Any | None:
    row = conn.execute(
        "SELECT payload, fetched_at FROM osint WHERE source=? AND key=?", (source, key)
    ).fetchone()
    if not row:
        return None
    payload, fetched_at = row
    if time.time() - float(fetched_at) > CACHE_TTL_S:
        return None
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return None


def _cache_put(conn: sqlite3.Connection, source: str, key: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO osint (source, key, fetched_at, payload)"
        " VALUES (?, ?, ?, ?)",
        (source, key, time.time(), json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def _http_get(url: str) -> tuple[int | None, Any | None]:
    """(HTTP status, parsed JSON or None). Status None = network failure."""
    try:
        import requests
    except ImportError:
        return None, None
    try:
        resp = requests.get(
            url, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
    except Exception:  # noqa: BLE001 - network problems must never break a run
        return None, None
    try:
        return resp.status_code, (resp.json() if resp.status_code == 200 else None)
    except ValueError:
        return resp.status_code, None


def _http_json(url: str) -> Any | None:
    _status, data = _http_get(url)
    return data


def _rdap_domain(domain: str) -> dict[str, Any] | None:
    status_code, data = _http_get(f"https://rdap.org/domain/{domain}")
    if status_code == 404:
        # Not in the registry any more (deleted / dropped) - or no RDAP for the TLD.
        return {"registrar": None, "created": None, "ns": [], "status": [],
                "expires": None, "not_found": True}
    if not isinstance(data, dict):
        return None
    registrar = None
    for entity in data.get("entities") or []:
        roles = [str(r).lower() for r in (entity.get("roles") or [])]
        if "registrar" in roles:
            vcard = entity.get("vcardArray")
            if isinstance(vcard, list) and len(vcard) > 1:
                for field in vcard[1]:
                    if isinstance(field, list) and field and field[0] == "fn":
                        registrar = str(field[3])[:120]
                        break
            registrar = registrar or str(entity.get("handle") or "")[:120] or None
            if registrar:
                break
    created = None
    expires = None
    for event in data.get("events") or []:
        action = str(event.get("eventAction", "")).lower()
        if action in ("registration", "created") and created is None:
            created = event.get("eventDate")
        elif action == "expiration" and expires is None:
            expires = event.get("eventDate")
    nameservers = sorted(
        {str(ns.get("ldhName", "")).lower().rstrip(".") for ns in (data.get("nameservers") or [])
         if ns.get("ldhName")}
    )
    # EPP status codes, e.g. "client hold", "server hold", "redemption period".
    status = sorted({str(s).lower() for s in (data.get("status") or [])})
    return {"registrar": registrar, "created": created, "ns": nameservers,
            "status": status, "expires": expires}


def _dns_records(domain: str) -> dict[str, list[str]] | None:
    try:
        import dns.resolver
    except ImportError:
        return None
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = ["1.1.1.1", "8.8.8.8"]
    resolver.lifetime = TIMEOUT_S
    resolver.timeout = TIMEOUT_S
    out: dict[str, Any] = {"a": [], "ns": [], "mx": [], "nxdomain": False}
    for rtype, key in (("A", "a"), ("NS", "ns"), ("MX", "mx")):
        try:
            answers = resolver.resolve(domain, rtype)
            out[key] = sorted({str(r).rstrip(".").lower() for r in answers})
        except dns.resolver.NXDOMAIN:
            out["nxdomain"] = True   # the name does not exist at all
            break
        except Exception:  # noqa: BLE001 - no answer / timeout -> empty list
            out[key] = []
    return out


def _crtsh(domain: str) -> dict[str, Any] | None:
    data = _http_json(f"https://crt.sh/?q={domain}&output=json")
    if not isinstance(data, list):
        return None  # timeout / HTTP error: unknown, retry next online run
    if not data:
        # crt.sh answered and has no certificate for this name. Cache that, so
        # the offline demo can tell "checked, none" apart from "never checked".
        return {"issuer": [], "san": [], "first_seen": None, "empty": True}
    issuers: set[str] = set()
    sans: set[str] = set()
    first_seen = None
    for row in data[:200]:
        if not isinstance(row, dict):
            continue
        issuer = row.get("issuer_name")
        if issuer:
            issuers.add(str(issuer)[:120])
        for name in str(row.get("name_value") or "").splitlines():
            name = name.strip().lstrip("*.").lower()
            if name:
                sans.add(name)
        entry = row.get("not_before")
        if entry and (first_seen is None or str(entry) < str(first_seen)):
            first_seen = str(entry)
    return {
        "issuer": sorted(issuers)[:5],
        "san": sorted(sans)[:200],
        "first_seen": first_seen,
    }


def _asn_of_ip(ip: str) -> str | None:
    for url in (f"https://rdap.org/ip/{ip}", f"https://rdap.db.ripe.net/ip/{ip}"):
        data = _http_json(url)
        if isinstance(data, dict):
            handle = data.get("handle") or data.get("name")
            country = data.get("country")
            if handle:
                return f"{handle}{('/' + str(country)) if country else ''}"[:60]
    return None


def _iso_ts(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s[:10], "%Y-%m-%d"),
    ):
        try:
            dt = parser(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            continue
    return None


# --------------------------------------------------------------------------
# Entry point called by infra.extract
# --------------------------------------------------------------------------

def enrich(features: dict[str, Any], ctx: Any, offline: bool,
           provenance: dict[str, str], errors: list[str]) -> None:
    """Fill the online fields of `features` in place.

    offline=True  -> read the cache only, never touch the network.
    offline=False -> query public OSINT services and cache the answers.
    """
    domains = list(features.get("landing_domains") or [])[:MAX_DOMAINS_PER_RECORD]
    ips = [ip for ip in (features.get("har_ips") or []) if not is_cdn_ip(str(ip))]
    ips = ips[:MAX_DOMAINS_PER_RECORD]
    if not domains and not ips:
        return

    try:
        conn = _connect(_cache_path(ctx))
    except sqlite3.Error as exc:
        errors.append(f"osint_cache_error:{type(exc).__name__}")
        return

    registrars: list[str] = []
    created_dates: list[str] = []
    rdap_ns: set[str] = set()
    dns_a: set[str] = set()
    dns_ns: set[str] = set()
    dns_mx: set[str] = set()
    issuers: set[str] = set()
    sans: set[str] = set()
    cert_first: str | None = None
    asns: set[str] = set()
    used: set[str] = set()

    def lookup(source: str, key: str, fetcher):
        cached = _cache_get(conn, source, key)
        if cached is not None:
            used.add(f"{source}:cache")
            return cached
        if offline:
            return None
        value = fetcher(key)
        if value is not None:
            _cache_put(conn, source, key, value)
            used.add(f"{source}:live")
        return value

    try:
        for domain in domains:
            rdap = lookup("rdap", domain, _rdap_domain)
            if isinstance(rdap, dict):
                if rdap.get("registrar"):
                    registrars.append(str(rdap["registrar"]))
                if rdap.get("created"):
                    created_dates.append(str(rdap["created"]))
                rdap_ns |= {str(x) for x in (rdap.get("ns") or [])}

            dns_data = lookup("dns", domain, _dns_records)
            if isinstance(dns_data, dict):
                dns_a |= set(dns_data.get("a") or [])
                dns_ns |= set(dns_data.get("ns") or [])
                dns_mx |= set(dns_data.get("mx") or [])

            cert = lookup("crtsh", domain, _crtsh)
            if isinstance(cert, dict):
                issuers |= set(cert.get("issuer") or [])
                sans |= set(cert.get("san") or [])
                value = cert.get("first_seen")
                if value and (cert_first is None or str(value) < cert_first):
                    cert_first = str(value)

        for ip in ips:
            asn = lookup("asn", ip, _asn_of_ip)
            if asn:
                asns.add(str(asn))
    finally:
        conn.close()

    if registrars:
        normalised = sorted({normalise_registrar(r) for r in registrars} - {None})
        features["rdap_registrar"] = normalised[0] if normalised else None
    if created_dates:
        # Earliest by actual time, not by string order (formats differ per registry).
        stamped = [(ts, d) for d in created_dates if (ts := _iso_ts(d)) is not None]
        if stamped:
            ts, earliest = min(stamped)
            features["rdap_created"] = earliest
            features["rdap_created_ts"] = ts
            features["rdap_created_days"] = round(ts / 86400.0, 4)
    if rdap_ns:
        features["rdap_ns"] = sorted(rdap_ns)
    if dns_a:
        features["dns_a"] = sorted(dns_a)
    if dns_ns:
        features["dns_ns"] = sorted(dns_ns)
    if dns_mx:
        features["dns_mx"] = sorted(dns_mx)
    if issuers:
        features["cert_issuer"] = sorted(issuers)
    if sans:
        features["cert_san"] = sorted(sans)
    if cert_first:
        features["cert_first_seen"] = cert_first
    if asns:
        features["asn"] = sorted(asns)

    if used:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        provenance["osint"] = f"{','.join(sorted(used))}@{stamp}"
