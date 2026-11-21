"""Infrastructure and OSINT features (module "infra", owner W4).

See CONTRACTS.md sections 4 and 5.

Offline sources (always available, no network):
  * HAR network logs  -> domains, IPs, redirect chain, tracker IDs, ad params
  * manifest.json / yt-dlp info.json -> ad / page identifiers
  * saved HTML        -> fallback domains and inline tracker IDs

Online sources (optional, behind ctx.offline=False, cached in sqlite):
  * RDAP, DNS, crt.sh, ASN -- see infra_osint.py

SAFETY: this module never contacts a domain found in the samples. It only
parses files statically. Optional lookups go to neutral public OSINT services.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from fakecollector.core.models import Context, FeatureRecord, Incident, Material

MODULE = "infra"
LEVEL = "material"
KINDS = ["har", "json", "html"]

#: Similarity signals exposed to the correlation engine (W5).
#: "shared_har_trackers" is deliberately not called "shared_trackers": that name
#: belongs to html_struct, and the engine drops the second module that declares
#: a name it has already seen. The HAR variant also sees pixels that never
#: appear in the saved HTML (fbpx/pxl URL params, the dot-named .har in 61).
SIGNALS = {
    # Strongest evidence: a concrete pixel / tag / ad-account identifier.
    "shared_har_trackers": {
        "type": "set_overlap", "field": "har_tracker_ids",
        "label": "wspólny piksel lub tag reklamowy (z logu HAR)",
    },
    "shared_ad_account": {
        "type": "set_overlap", "field": "ad_account_ids",
        "label": "to samo konto reklamowe lub reklama (ad_id, strona FB)",
    },
    "same_registered_domain": {
        "type": "set_overlap", "field": "landing_domains",
        "label": "ta sama domena strony docelowej",
    },
    "shared_redirector": {
        "type": "set_overlap", "field": "redirect_chain",
        "label": "wspólna domena pośrednia w przekierowaniach",
    },
    "same_favicon": {
        "type": "exact", "field": "favicon_mmh3",
        "label": "identyczna ikona strony (favicon)",
    },
    # Structural. "exact" on the hash, not set_overlap on the key list: a single
    # shared "utm_campaign" key is worthless, only the whole template counts.
    "same_param_template": {
        "type": "exact", "field": "param_template_id",
        "label": "ten sam szablon parametrów linku reklamowego",
    },
    "same_adtech_stack": {
        "type": "set_overlap", "field": "adtech_stack",
        "label": "ten sam zestaw sieci reklamowych na stronie",
    },
    "shared_server_stack": {
        "type": "set_overlap", "field": "server_headers",
        "label": "ta sama technologia serwera",
    },
    # Online-only (None when never fetched).
    "shared_ip_asn": {
        "type": "set_overlap", "field": "asn",
        "label": "ta sama sieć hostingowa (ASN, bez CDN)",
    },
    "shared_ns": {
        "type": "set_overlap", "field": "dns_ns",
        "label": "te same serwery nazw (DNS)",
    },
    # Days since epoch; tol=3 -> score falls linearly to 0 at a 3-day gap.
    # (The engine's default tol is 30 *in field units*, which on seconds would
    # only match domains registered within half a minute of each other.)
    # The label says "date" only: a single-field signal cannot also enforce the
    # same registrar (in A, 1<->3 share the day but not the registrar).
    "shared_registrar_and_date": {
        "type": "numeric_close", "field": "rdap_created_days", "tol": 3.0,
        "label": "domeny zarejestrowane w odstępie do 3 dni",
    },
    "cert_san_overlap": {
        "type": "set_overlap", "field": "cert_san",
        "label": "wspólne nazwy w certyfikacie SSL",
    },
}

#: Two-level grouping (CONTRACTS.md v0.4 s.6, coordinator decision 14:20).
#: campaign = identifies one concrete campaign; family = shared kit / actor.
SIGNAL_CLASS = {
    "shared_har_trackers": "campaign",
    "shared_ad_account": "campaign",
    "same_registered_domain": "campaign",
    "shared_registrar_and_date": "campaign",
    "cert_san_overlap": "campaign",
    "same_favicon": "campaign",
    "same_param_template": "family",
    "same_adtech_stack": "family",
    "shared_server_stack": "family",
    "shared_ip_asn": "family",
    "shared_ns": "family",
    "shared_redirector": "family",
}

# --------------------------------------------------------------------------
# Tracker identifier patterns. A *specific* ID is a strong link between
# incidents, so these are never stop-listed (CONTRACTS.md 9a).
# --------------------------------------------------------------------------
TRACKER_PATTERNS: list[tuple[str, str]] = [
    (r"facebook\.com/tr/?\?(?:[^#]*&)?id=(\d{8,20})", "fb_pixel"),
    (r"/signals/config/(\d{8,20})", "fb_pixel"),
    (r"[?&]fbpx=(\d{8,20})", "fb_pixel"),
    (r"[?&]pxl=(\d{8,20})", "fb_pixel"),
    (r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{8,20})['\"]", "fb_pixel"),
    (r"[?&]id=(GTM-[A-Z0-9]{4,10})", "gtm"),
    (r"[?&]id=(AW-\d{6,15})", "google_ads"),
    (r"/pagead/\w+-conversion/(\d{6,15})", "google_ads"),
    (r"[?&]id=(G-[A-Z0-9]{6,12})", "ga4"),
    (r"[?&]tid=(UA-\d{4,12}-\d{1,4}|G-[A-Z0-9]{6,12})", "ga"),
    (r"gtag\(\s*['\"]config['\"]\s*,\s*['\"]((?:AW|G|GT)-[A-Z0-9-]{4,15})['\"]", "gtag"),
    (r"analytics\.tiktok\.com/i18n/pixel/events\.js\?sdkid=([A-Z0-9]{10,25})", "tiktok"),
    (r"[?&]sdkid=([A-Z0-9]{10,25})", "tiktok"),
]

#: URL query keys that identify the ad / ad account rather than the landing page.
AD_PARAM_KEYS = {
    "ad_id", "adset_name", "ad_name", "adset_id", "campaign_id", "campaign",
    "acc", "account", "land_id", "lpkey", "key", "clickid", "trafficsource",
    "placement", "media_type", "geo", "country_code", "user_id", "_camp_id",
    "_trk", "pxl", "fbpx", "fbclid", "gclid", "ttclid",
}

#: Keys whose *value* names an advertising account / page / campaign owner.
AD_ACCOUNT_KEYS = ("ad_id", "adset_id", "campaign_id", "_camp_id", "acc", "account")

#: Query keys that are per-click noise -- part of the template, never an ID.
#: utm_visit/utm_id carry a fresh random token per visit; pixel_fb/key are
#: opaque encrypted blobs, not identifiers (checked against the samples).
VOLATILE_PARAM_KEYS = {
    "fbclid", "gclid", "ttclid", "clickid", "access_token", "_fbp", "_fbc",
    "utm_visit", "pixel_fb", "key", "lpkey", "user_id", "_trk",
}

#: Ad / analytics networks whose *presence* is distinctive.
#: Facebook, GTM, GA and Doubleclick are deliberately NOT here: almost every
#: sample loads them, so they would link unrelated incidents. Their concrete
#: pixel ID is already a much stronger signal (har_tracker_ids).
ADTECH_NETWORKS = {
    "ads-twitter.com", "bing.net", "bat.bing.com", "taboola.com", "outbrain.com",
    "criteo.com", "criteo.net", "clarity.ms", "hotjar.com", "analytics.tiktok.com",
    "tiktok.com", "snapchat.com", "sc-static.net", "pinterest.com", "mc.yandex.ru",
    "yandex.ru", "quantserve.com", "scorecardresearch.com", "adroll.com",
    "rtbhouse.com", "smartadserver.com", "pubmatic.com", "rubiconproject.com",
}

_SAFE_HEADERS = ("server", "x-powered-by", "x-generator")

#: Server banners shared by a large share of the web: no evidence of a link.
_GENERIC_SERVER_VALUES = {
    "cloudflare", "cloudflare-nginx", "nginx", "apache", "netlify", "vercel",
    "openresty", "litespeed", "microsoft-iis", "awselb/2.0", "gws", "esf",
    "sffe", "cafe", "istio-envoy", "envoy",
}

_HAR_MAX_BYTES = 64 * 1024 * 1024  # refuse absurd files instead of exhausting RAM


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

_extractor = None


def _etld1(host: str) -> str | None:
    """Registered domain (eTLD+1) using tldextract's bundled snapshot (offline)."""
    global _extractor
    if not host:
        return None
    host = host.strip().strip(".").lower()
    if not host or host in ("localhost", "delivered"):
        return None
    try:
        import tldextract
    except ImportError:
        # Degrade gracefully: naive last-two-labels fallback.
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else None
    if _extractor is None:
        # suffix_list_urls=() keeps this fully offline; uses the packaged snapshot.
        # Private PSL entries are included on purpose: scammers host assets on
        # free subdomains (<name>.netlify.app), and the subdomain is the
        # distinctive part, not "netlify.app".
        _extractor = tldextract.TLDExtract(
            suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True
        )
    res = _extractor(host)
    if not res.domain or not res.suffix:
        return None
    return f"{res.domain}.{res.suffix}"


def _host_of(url: str) -> str | None:
    try:
        return (urlparse(url).hostname or "").lower() or None
    except (ValueError, AttributeError):
        return None


_stoplist_cache: dict[str, Any] | None = None


def _load_stoplist(ctx: Context | None) -> dict[str, set[str]]:
    """Load config/stoplist.yaml once. Generic CDNs must not create links."""
    global _stoplist_cache
    if _stoplist_cache is not None:
        return _stoplist_cache
    data: dict[str, Any] = {}
    root = getattr(ctx, "repo_root", None) if ctx else None
    candidates = []
    if root:
        candidates.append(Path(root) / "config" / "stoplist.yaml")
    candidates.append(Path(__file__).resolve().parents[2] / "config" / "stoplist.yaml")
    for path in candidates:
        try:
            if path.is_file():
                import yaml

                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                break
        except Exception:  # noqa: BLE001 - a broken stoplist must not kill the run
            data = {}
    _stoplist_cache = {
        "domains": {str(d).lower() for d in (data.get("domains") or [])},
        "filenames": {str(f).lower() for f in (data.get("filenames") or [])},
        "sha1": {str(s).lower() for s in (data.get("sha1") or [])},
    }
    return _stoplist_cache


def _is_adtech(domain: str | None) -> bool:
    """True if the domain (or a parent) is a distinctive ad/analytics network."""
    if not domain:
        return False
    labels = domain.lower().split(".")
    return any(
        ".".join(labels[i:]) in ADTECH_NETWORKS for i in range(len(labels) - 1)
    )


def _is_generic_domain(domain: str | None, stop: dict[str, set[str]]) -> bool:
    """True if the domain, or any parent of it, is stop-listed.

    The parent check matters because the public-suffix list splits some
    provider subdomains into their own registered domain
    (translate-pa.googleapis.com), and stop-listing every one by hand
    would be endless.
    """
    if not domain:
        return True
    domain = domain.lower()
    labels = domain.split(".")
    for i in range(len(labels) - 1):
        if ".".join(labels[i:]) in stop["domains"]:
            return True
    return False


def _iso_to_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _normalise_tracker(kind: str, value: str) -> str:
    """Collapse the spellings of one ID so set_overlap does not double-count.

    The same Google Ads tag appears as "AW-<id>" in gtag/GTM URLs and as
    a bare "<id>" in /pagead/1p-conversion/ calls.
    """
    value = value.strip()
    if kind == "gtag":
        upper = value.upper()
        if upper.startswith("AW-"):
            kind = "google_ads"
        elif upper.startswith(("G-", "GT-")):
            kind = "ga4"
        else:
            kind = "gtag"
    if kind == "google_ads":
        value = re.sub(r"^AW-", "", value, flags=re.IGNORECASE)
    if kind in ("ga4", "gtm", "ga", "google_ads"):
        value = value.upper()
    return f"{kind}:{value}"


def _find_trackers(text: str) -> set[str]:
    """Return {"<kind>:<id>"} for every tracker identifier found in text."""
    out: set[str] = set()
    for pattern, kind in TRACKER_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1)
            if value:
                out.add(_normalise_tracker(kind, value))
    return out


def _split_params(url: str) -> list[tuple[str, str]]:
    try:
        return parse_qsl(urlparse(url).query, keep_blank_values=True)
    except (ValueError, AttributeError):
        return []


def _collect_ad_params(url: str, bag: dict[str, str], template: set[str]) -> None:
    """Record ad-related query params and the *shape* of the query string."""
    for key, value in _split_params(url):
        low = key.lower()
        template.add(low)
        if low.startswith("utm_") or low in AD_PARAM_KEYS:
            if low in VOLATILE_PARAM_KEYS:
                continue  # per-click value: useless as an identifier
            if value and len(value) <= 120:
                bag.setdefault(low, value)


def _template_id(keys: set[str]) -> str | None:
    """Stable short id for a URL query-key template.

    None for trivial templates (fewer than 3 keys): a lone "id" or "utm_source"
    says nothing about who built the page.
    """
    meaningful = sorted(k for k in keys if k)
    if len(meaningful) < 3:
        return None
    joined = "|".join(meaningful)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def _resolve_path(ctx: Context | None, rel_path: str) -> Path:
    """Material.path is relative to the repo root (CONTRACTS.md section 3)."""
    path = Path(rel_path)
    if path.is_absolute():
        return path
    root = getattr(ctx, "repo_root", None) if ctx else None
    return (Path(root) / path) if root else path


def _empty_features() -> dict[str, Any]:
    """Every field the module can produce, defaulted to None/empty."""
    return {
        "har_domains": [],
        "har_ips": [],
        "landing_domains": [],
        "redirect_chain": [],
        "har_tracker_ids": [],
        "ad_params": [],
        "ad_account_ids": [],
        "param_template": [],
        "param_template_id": None,
        "adtech_stack": [],
        "server_headers": [],
        "streams": [],
        "first_seen": None,
        "first_seen_ts": None,
        "page_title": None,
        "capture_tool": None,
        "favicon_mmh3": None,
        "n_requests": None,
        # Online-only fields, filled by infra_osint when ctx.offline is False.
        "rdap_registrar": None,
        "rdap_created": None,
        "rdap_created_ts": None,
        "rdap_created_days": None,
        "rdap_ns": [],
        "dns_a": [],
        "dns_ns": [],
        "dns_mx": [],
        "asn": [],
        "cert_issuer": [],
        "cert_san": [],
        "cert_first_seen": None,
    }


# --------------------------------------------------------------------------
# HAR
# --------------------------------------------------------------------------

def _parse_har(path: Path, feats: dict[str, Any], stop: dict[str, set[str]],
               errors: list[str]) -> None:
    size = path.stat().st_size
    if size > _HAR_MAX_BYTES:
        errors.append(f"har_too_large:{size}")
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        log = json.load(fh).get("log", {})

    entries = log.get("entries") or []
    feats["n_requests"] = len(entries)
    creator = log.get("creator") or {}
    if creator.get("name"):
        feats["capture_tool"] = str(creator["name"])[:60]

    domains: set[str] = set()
    landing: set[str] = set()
    ips: set[str] = set()
    trackers: set[str] = set()
    adtech: set[str] = set()
    headers: set[str] = set()
    redirects: list[str] = []
    ad_bag: dict[str, str] = {}
    template: set[str] = set()
    earliest: float | None = None

    # log.pages[].title often holds the full navigation URL with ad parameters.
    for page in log.get("pages") or []:
        title = page.get("title")
        if isinstance(title, str) and title.startswith(("http://", "https://")):
            trackers |= _find_trackers(title)
            host = _host_of(title)
            dom = _etld1(host) if host else None
            if dom and not _is_generic_domain(dom, stop):
                landing.add(dom)
                domains.add(dom)
                _collect_ad_params(title, ad_bag, template)
        elif isinstance(title, str) and title and not title.startswith("file:///"):
            feats["page_title"] = feats["page_title"] or title[:200]
        ts = _iso_to_ts(page.get("startedDateTime"))
        if ts is not None and (earliest is None or ts < earliest):
            earliest = ts

    for entry in entries:
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url = request.get("url") or ""
        if not url:
            continue

        ts = _iso_to_ts(entry.get("startedDateTime"))
        if ts is not None and (earliest is None or ts < earliest):
            earliest = ts

        host = _host_of(url)
        domain = _etld1(host) if host else None
        generic = _is_generic_domain(domain, stop)
        if domain and not generic:
            domains.add(domain)
        if _is_adtech(domain):
            adtech.add(domain)

        # Tracker IDs matter even on stop-listed hosts (facebook.com/tr?id=...).
        trackers |= _find_trackers(url)

        resource_type = (entry.get("_resourceType") or "").lower()
        status = response.get("status") or 0
        mime = ((response.get("content") or {}).get("mimeType") or "").lower()
        is_document = resource_type == "document" or mime.startswith("text/html")

        # Only the scam's own documents define the campaign's URL template.
        # Google/Doubleclick conversion beacons are documents too and would
        # otherwise flood param_template with their own query keys.
        if is_document and 200 <= status < 400 and domain and not generic:
            _collect_ad_params(url, ad_bag, template)
            landing.add(domain)

        server_ip = entry.get("serverIPAddress")
        if server_ip and not generic:
            ips.add(str(server_ip))

        if 300 <= status < 400:
            location = response.get("redirectURL") or ""
            if not location:
                for header in response.get("headers") or []:
                    if (header.get("name") or "").lower() == "location":
                        location = header.get("value") or ""
                        break
            src = _etld1(host) if host else None
            dst_host = _host_of(location) if location else None
            dst = _etld1(dst_host) if dst_host else None
            for hop in (src, dst):
                if hop and not _is_generic_domain(hop, stop) and hop not in redirects:
                    redirects.append(hop)

        if not generic:
            for header in response.get("headers") or []:
                name = (header.get("name") or "").lower()
                if name not in _SAFE_HEADERS:
                    continue
                value = (header.get("value") or "").strip()
                if not value or len(value) > 80:
                    continue
                # "server: cloudflare" is on most of the web -- no evidence.
                if value.lower() in _GENERIC_SERVER_VALUES:
                    continue
                headers.add(f"{name}:{value}")

    feats["har_domains"] = sorted(domains)
    feats["landing_domains"] = sorted(landing)
    feats["har_ips"] = sorted(ips)
    feats["har_tracker_ids"] = sorted(trackers)
    feats["redirect_chain"] = redirects
    feats["server_headers"] = sorted(headers)
    feats["adtech_stack"] = sorted(adtech)
    feats["param_template"] = sorted(template)
    feats["param_template_id"] = _template_id(template)
    feats["ad_params"] = sorted(f"{k}={v}" for k, v in ad_bag.items())
    feats["ad_account_ids"] = sorted(
        f"{k}:{ad_bag[k]}" for k in AD_ACCOUNT_KEYS if ad_bag.get(k)
    )
    if earliest is not None:
        feats["first_seen_ts"] = earliest
        feats["first_seen"] = datetime.fromtimestamp(earliest, timezone.utc).isoformat()


# --------------------------------------------------------------------------
# JSON metadata: page-capture manifest.json and yt-dlp info.json
# --------------------------------------------------------------------------

def _parse_json_meta(path: Path, feats: dict[str, Any], stop: dict[str, set[str]],
                     errors: list[str]) -> None:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        errors.append("json_not_object")
        return

    ad_bag: dict[str, str] = {}
    template: set[str] = set()
    trackers: set[str] = set()
    domains: set[str] = set()
    landing: set[str] = set()

    extractor = str(data.get("extractor") or "")
    tool = str(data.get("tool") or "")

    if tool:  # page-capture manifest.json
        feats["capture_tool"] = tool[:60]
        page_url = data.get("page_url")
        if isinstance(page_url, str):
            _collect_ad_params(page_url, ad_bag, template)
            trackers |= _find_trackers(page_url)
            dom = _etld1(_host_of(page_url) or "")
            if dom and not _is_generic_domain(dom, stop):
                domains.add(dom)
                landing.add(dom)
        if data.get("title"):
            feats["page_title"] = str(data["title"])[:200]
        feats["first_seen"] = data.get("captured_at") or feats["first_seen"]
        feats["first_seen_ts"] = _iso_to_ts(feats["first_seen"])
        streams = data.get("streams")
        if isinstance(streams, list):
            stream_domains = set()
            for item in streams:
                dom = _etld1(_host_of(str(item)) or "")
                if dom and not _is_generic_domain(dom, stop):
                    stream_domains.add(dom)
                    domains.add(dom)
            feats["streams"] = sorted(stream_domains)

    if extractor.startswith("facebook"):  # yt-dlp info.json (FB Ad Library)
        feats["capture_tool"] = f"yt-dlp:{extractor}"[:60]
        for key, label in (
            ("playlist_id", "fb_ad_id"),
            ("playlist_uploader_id", "fb_page_id"),
            ("id", "fb_ad_variant"),
        ):
            value = data.get(key)
            if value:
                ad_bag[label] = str(value)[:120]
        uploader = data.get("playlist_uploader")
        if uploader:
            ad_bag["fb_page_name"] = str(uploader)[:120]
        if data.get("title"):
            feats["page_title"] = str(data["title"])[:200]
        epoch = data.get("epoch")
        if isinstance(epoch, (int, float)):
            feats["first_seen_ts"] = float(epoch)
            feats["first_seen"] = datetime.fromtimestamp(
                float(epoch), timezone.utc
            ).isoformat()
        # The ad lives on facebook.com: a generic host, so it is not a landing domain.
        for key in ("webpage_url", "playlist_webpage_url"):
            url = data.get(key)
            if isinstance(url, str):
                _collect_ad_params(url, ad_bag, template)

    if not tool and not extractor:
        errors.append("json_unknown_kind")
        return

    feats["ad_params"] = sorted(f"{k}={v}" for k, v in ad_bag.items())
    account_keys = AD_ACCOUNT_KEYS + ("fb_ad_id", "fb_page_id")
    feats["ad_account_ids"] = sorted(
        f"{k}:{ad_bag[k]}" for k in account_keys if ad_bag.get(k)
    )
    feats["param_template"] = sorted(template)
    feats["param_template_id"] = _template_id(template)
    feats["har_tracker_ids"] = sorted(trackers)
    feats["har_domains"] = sorted(domains)
    feats["landing_domains"] = sorted(landing)


# --------------------------------------------------------------------------
# HTML fallback (used when an incident has no HAR)
# --------------------------------------------------------------------------

_SAVED_FROM_RE = re.compile(r"saved from url=\(\d+\)(\S+)", re.IGNORECASE)
_HTML_MAX_BYTES = 8 * 1024 * 1024


def _parse_html(path: Path, feats: dict[str, Any], stop: dict[str, set[str]],
                material: Material | None, errors: list[str]) -> None:
    size = path.stat().st_size
    text = path.read_text(encoding="utf-8", errors="replace")
    if size > _HTML_MAX_BYTES:
        text = text[:_HTML_MAX_BYTES]
        errors.append("html_truncated")

    domains: set[str] = set()
    landing: set[str] = set()
    ad_bag: dict[str, str] = {}
    template: set[str] = set()

    # Tracker IDs from inline scripts: fbq('init'), gtag('config'), GTM.
    trackers = _find_trackers(text)

    origin = None
    match = _SAVED_FROM_RE.search(text[:4000])
    if match:
        origin = match.group(1)
    elif material is not None and material.original_url:
        origin = material.original_url
    if origin:
        _collect_ad_params(origin, ad_bag, template)
        dom = _etld1(_host_of(origin) or "")
        if dom and not _is_generic_domain(dom, stop):
            domains.add(dom)
            landing.add(dom)

    adtech: set[str] = set()
    for raw in re.findall(r"""(?:href|action|src)\s*=\s*["']([^"']+)["']""", text):
        if not raw.lower().startswith(("http://", "https://")):
            continue
        dom = _etld1(_host_of(raw) or "")
        if not dom:
            continue
        if _is_adtech(dom):
            adtech.add(dom)
        if not _is_generic_domain(dom, stop):
            domains.add(dom)

    # Ad pixels are often injected from inline JS, not from a src attribute
    # (Taboola, Twitter uwt), so scan every URL in the page text as well.
    for host in re.findall(r"https?://([A-Za-z0-9.-]{4,253})", text):
        dom = _etld1(host)
        if dom and _is_adtech(dom):
            adtech.add(dom)

    title = re.search(r"<title[^>]*>(.{1,200}?)</title>", text, re.IGNORECASE | re.DOTALL)
    if title:
        feats["page_title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:200]

    feats["har_domains"] = sorted(domains)
    feats["landing_domains"] = sorted(landing)
    feats["har_tracker_ids"] = sorted(trackers)
    feats["ad_params"] = sorted(f"{k}={v}" for k, v in ad_bag.items())
    feats["ad_account_ids"] = sorted(
        f"{k}:{ad_bag[k]}" for k in AD_ACCOUNT_KEYS if ad_bag.get(k)
    )
    feats["param_template"] = sorted(template)
    feats["param_template_id"] = _template_id(template)
    feats["adtech_stack"] = sorted(adtech)
    feats["favicon_mmh3"] = _favicon_hash_for_page(path, text)


# --------------------------------------------------------------------------
# Favicon hash (Shodan style: mmh3 of the base64-encoded bytes)
# --------------------------------------------------------------------------

def _favicon_mmh3(raw: bytes) -> int | None:
    try:
        import base64

        import mmh3
    except ImportError:
        return None
    try:
        encoded = base64.encodebytes(raw)
        return int(mmh3.hash(encoded))
    except Exception:  # noqa: BLE001 - hashing must never break a run
        return None


def _favicon_hash_for_page(html_path: Path, text: str) -> int | None:
    """Find a favicon saved next to the page (X_files/) and hash it."""
    assets = html_path.with_name(html_path.stem + "_files")
    names: list[str] = []
    for match in re.finditer(
        r"""<link[^>]+rel\s*=\s*["'][^"']*icon[^"']*["'][^>]*>""", text, re.IGNORECASE
    ):
        href = re.search(r"""href\s*=\s*["']([^"']+)["']""", match.group(0), re.IGNORECASE)
        if href:
            names.append(os.path.basename(urlparse(href.group(1)).path))
    candidates: list[Path] = []
    if assets.is_dir():
        for child in assets.iterdir():
            low = child.name.lower()
            if low in {n.lower() for n in names if n} or "favicon" in low or low.endswith(".ico"):
                candidates.append(child)
    for candidate in candidates:
        try:
            if candidate.is_file() and 0 < candidate.stat().st_size <= 2 * 1024 * 1024:
                return _favicon_mmh3(candidate.read_bytes())
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def extract(item: Material | Incident, ctx: Context | None = None) -> FeatureRecord:
    """Extract infrastructure features from one material.

    Never raises: any failure is recorded in FeatureRecord.errors and the
    affected features stay empty/None (CONTRACTS.md section 4).
    """
    entity_id = getattr(item, "material_id", None) or getattr(item, "incident_id", "")
    incident_id = getattr(item, "incident_id", None)
    features = _empty_features()
    errors: list[str] = []
    provenance: dict[str, str] = {}
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if isinstance(item, Incident) or not hasattr(item, "kind"):
        errors.append("unsupported_level:expected_material")
        return FeatureRecord(
            entity_id=entity_id, level=LEVEL, module=MODULE, features=features,
            provenance=provenance, errors=errors, incident_id=incident_id,
        )

    material: Material = item  # type: ignore[assignment]
    stop = _load_stoplist(ctx)
    path = _resolve_path(ctx, material.path)

    try:
        if not path.is_file():
            errors.append("file_not_found")
        else:
            kind = material.kind
            # A .har file may be registered as "json"; trust the extension too.
            if kind == "har" or path.suffix.lower() == ".har" or path.name.lower() == ".har":
                _parse_har(path, features, stop, errors)
                provenance["har"] = f"static-parse:{path.name}@{fetched_at}"
            elif kind == "json":
                _parse_json_meta(path, features, stop, errors)
                provenance["json"] = f"static-parse:{path.name}@{fetched_at}"
            elif kind in ("html", "mhtml"):
                _parse_html(path, features, stop, material, errors)
                provenance["html"] = f"static-parse:{path.name}@{fetched_at}"
            else:
                errors.append(f"unsupported_kind:{kind}")
    except json.JSONDecodeError as exc:
        errors.append(f"json_decode_error:{exc.lineno}")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"io_error:{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 - contract: never break the run
        errors.append(f"unexpected:{type(exc).__name__}")

    # Optional online enrichment. Offline by default; cache-only when offline.
    offline = True if ctx is None else bool(getattr(ctx, "offline", True))
    try:
        from fakecollector.features import infra_osint

        infra_osint.enrich(features, ctx, offline=offline, provenance=provenance,
                           errors=errors)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        errors.append(f"osint_failed:{type(exc).__name__}")

    return FeatureRecord(
        entity_id=entity_id,
        level=LEVEL,
        module=MODULE,
        features=features,
        provenance=provenance,
        errors=errors,
        incident_id=incident_id,
    )


def material_id_of(path: str | Path) -> str:
    """sha1(bytes)[:16] -- same rule as the loader (CONTRACTS.md section 2)."""
    digest = hashlib.sha1()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]
