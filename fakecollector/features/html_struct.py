"""html_struct: static structure fingerprint of saved landing pages (CONTRACTS §5). Owner: W1.

SAFETY: BeautifulSoup static parse only. No rendering, no JS execution, no network.
Inline scripts are only scanned with regexes for tracker IDs.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Comment

from fakecollector.core.models import Context, FeatureRecord, Material
from fakecollector.ingest.loader import resolve_path
from fakecollector.ingest.util import (
    domain_is_stoplisted,
    etld1,
    host_of,
    load_stoplist,
    name_is_stoplisted,
    normalize_resource_name,
    sha1_file,
    sha1_is_stoplisted,
)

MODULE = "html_struct"
LEVEL = "material"
KINDS = ["html", "mhtml"]

SIGNALS = {
    "dom_template": {"type": "hamming_hash", "field": "dom_simhash", "bits": 64,
                     "label": "podobny szablon strony (DOM)"},
    "shared_assets": {"type": "set_overlap", "field": "asset_hashes",
                      "label": "identyczne pliki strony (sha1)"},
    "shared_trackers": {"type": "set_overlap", "field": "tracker_ids",
                        "label": "wspólny identyfikator śledzący (piksel FB / GA / GTM / TikTok)"},
    "shared_scripts": {"type": "set_overlap", "field": "script_srcs",
                       "label": "te same nietypowe skrypty"},
    "shared_form_endpoint": {"type": "set_overlap", "field": "form_actions",
                             "label": "ten sam adres wysyłki formularza"},
    "hidden_text_sim": {"type": "set_overlap", "field": "hidden_text_shingles",
                        "label": "podobny ukryty tekst"},
}

# CONTRACTS v0.4: campaign = concrete campaign identifier, family = shared kit / actor
SIGNAL_CLASS = {
    "shared_assets": "campaign",
    "shared_trackers": "campaign",
    "shared_form_endpoint": "campaign",
    "dom_template": "family",
    "shared_scripts": "family",
    "hidden_text_sim": "family",
}

FEATURE_KEYS = [
    "original_url", "title", "meta", "generator", "lang", "dom_simhash", "dom_size",
    "css_classes", "script_srcs", "asset_hashes", "tracker_ids", "form_actions", "form_fields",
    "external_domains", "hidden_text", "hidden_text_shingles", "hidden_text_count", "hidden_reasons",
    "html_comments", "custom_fonts", "n_forms", "n_inputs", "n_iframes", "n_inline_scripts",
]

MAX_LIST = 500
MAX_HIDDEN_CHARS = 5000

# ------------------------------------------------------------------ tracker patterns
TRACKER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("fb", re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"]?(\d{10,20})")),
    ("fb", re.compile(r"facebook\.com/tr/?\?[^\"'\s<>]*?\bid=(\d{10,20})")),
    ("fb", re.compile(r"/signals/config/(\d{10,20})")),
    ("ga", re.compile(r"\b(UA-\d{4,10}-\d{1,4})\b")),
    ("ga4", re.compile(r"(?<=['\"=/?&\s])(G-[A-Z0-9]{8,12})\b")),
    ("gtm", re.compile(r"\b(GTM-[A-Z0-9]{4,9})\b")),
    ("gads", re.compile(r"\b(AW-\d{6,12})\b")),
    ("tiktok", re.compile(r"ttq\.load\(\s*['\"]([A-Z0-9]{15,25})['\"]")),
    ("tiktok", re.compile(r"tiktok\.com/i18n/pixel/events\.js\?[^\"'\s<>]*?sdkid=([A-Z0-9]{15,25})")),
    ("ym", re.compile(r"\bym\(\s*(\d{5,12})\s*,\s*['\"]init")),
    ("ym", re.compile(r"mc\.yandex\.ru/watch/(\d{5,12})")),
]
# FB pixel id carried in landing URLs (e.g. ?pxl=<15-16 digits>) or saved as a bare-number file
URL_PIXEL_PARAMS = ("pxl", "pixel", "pixel_id", "fbpixel", "fb_pixel")
PIXEL_FILE_RE = re.compile(r"^\d{15,17}$")
# Script names too generic to link two sites by name alone (bytes still compared via asset_hashes)
GENERIC_SCRIPT_NAMES = {
    "main.js", "app.js", "index.js", "script.js", "scripts.js", "common.js", "bundle.js", "custom.js",
    "functions.js", "init.js", "vendor.js", "vendors.js", "runtime.js", "polyfills.js", "core.js", "util.js",
    "utils.js", "site.js", "global.js", "plugins.js", "theme.js", "js", "",
}

# ------------------------------------------------------------------ hidden text heuristics
HIDDEN_CLASS_NAMES = {"hidden", "d-none", "hide", "invisible", "sr-only", "visually-hidden", "screen-reader-text"}
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "head", "meta", "link", "svg"}
# Form widgets (country pickers etc.) are hidden by design and identical across unrelated pages
FORM_WIDGET_TAGS = {"select", "option", "optgroup", "datalist"}
PHONE_CODE_RE = re.compile(r"\+\d{1,4}\b")
MIN_PHONE_CODES = 20      # a block with this many "+NN" codes is a country/phone-code list
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*?font-family\s*:\s*['\"]?([^;'\"}]+)", re.I)
WORD_RE = re.compile(r"\w+", re.U)


def _norm_style(style: str) -> str:
    return re.sub(r"\s+", "", style.lower())


def _style_hidden_reasons(style: str) -> list[str]:
    """Reasons why an inline style / CSS declaration block hides its text."""
    s = _norm_style(style)
    if not s:
        return []
    out = []
    if "display:none" in s:
        out.append("display:none")
    if "visibility:hidden" in s:
        out.append("visibility:hidden")
    if re.search(r"(?:^|;)opacity:0(?:\.0+)?(?:;|!|$)", s):
        out.append("opacity:0")
    fs = re.search(r"font-size:(\d*\.?\d+)(px|pt|em|rem|%)?", s)
    if fs:
        val, unit = float(fs.group(1)), fs.group(2) or "px"
        if val == 0 or (unit in ("px", "pt") and val <= 1) or (unit in ("em", "rem") and val <= 0.1):
            out.append("font-size:0")
    if "color:transparent" in s:
        out.append("color:transparent")
    color = re.search(r"(?:^|;)color:([^;!]+)", s)
    bg = re.search(r"background(?:-color)?:([^;!]+)", s)
    if color and bg and color.group(1) == bg.group(1).split()[0]:
        out.append("color=background")
    if re.search(r"(?:left|top|text-indent):-\d{3,}(?:px|em)", s):
        out.append("offscreen")
    if "clip:rect(0" in s or "clip-path:inset(50%" in s:
        out.append("clipped")
    return out


def _hidden_selectors(css_text: str) -> dict[str, list[str]]:
    """Simple '.class' / '#id' selectors whose declarations hide content."""
    found: dict[str, list[str]] = {}
    for selectors, decl in CSS_RULE_RE.findall(css_text):
        reasons = _style_hidden_reasons(decl)
        if not reasons:
            continue
        for sel in selectors.split(","):
            sel = sel.strip()
            if re.fullmatch(r"[.#][\w-]+", sel):
                found[sel] = reasons
    return found


def _drop_phone_code_lists(tag) -> None:
    """Remove the innermost descendants holding >= MIN_PHONE_CODES '+NN' codes (country dial-code lists)."""
    for el in list(tag.find_all(True)):
        if el.parent is None:          # already removed with an ancestor
            continue
        if len(PHONE_CODE_RE.findall(el.get_text(" "))) < MIN_PHONE_CODES:
            continue
        if any(len(PHONE_CODE_RE.findall(c.get_text(" "))) >= MIN_PHONE_CODES
               for c in el.find_all(True, recursive=False)):
            continue                   # a child holds the list: remove that one instead
        el.extract()


def _shingles(text: str, n: int = 3) -> list[str]:
    words = [w.lower() for w in WORD_RE.findall(text)]
    if len(words) < n:
        return [" ".join(words)] if words else []
    return sorted({" ".join(words[i:i + n]) for i in range(len(words) - n + 1)})[:MAX_LIST]


# ------------------------------------------------------------------ DOM simhash

def simhash64(tokens: Counter) -> str | None:
    if not tokens:
        return None
    v = [0] * 64
    for tok, w in tokens.items():
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return f"{out:016x}"


def dom_tokens(soup: BeautifulSoup) -> Counter:
    """Tag-path tokens (last 4 ancestors) + document-order tag 3-grams. Text and attributes ignored."""
    tokens: Counter = Counter()
    seq: list[str] = []
    root = soup.find("html") or soup
    stack: list[tuple[Any, tuple[str, ...]]] = [(root, ())]
    while stack:
        node, path = stack.pop()
        name = getattr(node, "name", None)
        if not name:
            continue
        p = (path + (name,))[-4:]
        tokens["p:" + "/".join(p)] += 1
        seq.append(name)
        children = [c for c in getattr(node, "contents", []) if getattr(c, "name", None)]
        for c in reversed(children):
            stack.append((c, p))
    for i in range(len(seq) - 2):
        tokens["s:" + ">".join(seq[i:i + 3])] += 1
    return tokens


# ------------------------------------------------------------------ input reading

def _resource_dirs(page: Path) -> list[Path]:
    cands = [page.parent / f"{page.stem}_files", page.parent / "resources"]
    return [d for d in cands if d.is_dir()]


def _read_page(material: Material, ctx: Context) -> tuple[bytes | str, list[tuple[str, bytes | Path]]]:
    """(html content, [(resource name, bytes-or-path)]) for html or mhtml materials."""
    path = resolve_path(material, ctx.repo_root)
    if material.kind == "mhtml":
        with path.open("rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
        html: str | None = None
        resources: list[tuple[str, bytes | Path]] = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = part.get_content_type()
            loc = str(part.get("Content-Location") or "")
            if ctype == "text/html" and html is None:
                html = part.get_content()
                continue
            payload = part.get_payload(decode=True) or b""
            name = urlsplit(loc).path.rsplit("/", 1)[-1] if loc else ""
            resources.append((name, payload))
        if html is None:
            raise ValueError("mhtml without text/html part")
        return html, resources
    raw = path.read_bytes()
    resources = []
    for d in _resource_dirs(path):
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.name.lower() != ".ds_store":
                resources.append((f.name, f))
    return raw, resources


# ------------------------------------------------------------------ helpers

def _norm_action(action: str) -> str | None:
    a = (action or "").strip()
    if not a or a.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return None
    host = host_of(a)
    path = urlsplit(a if host else "x://h/" + a.lstrip("./")).path or "/"
    path = re.sub(r"/{2,}", "/", path)
    return f"{host}{path}" if host else path.lower()


def _url_pixels(url: str | None) -> list[str]:
    if not url:
        return []
    try:
        q = parse_qs(urlsplit(url).query)
    except ValueError:
        return []
    out = []
    for key in URL_PIXEL_PARAMS:
        for v in q.get(key, []):
            if re.fullmatch(r"\d{10,20}", v):
                out.append(f"fb:{v}")
    return out


def _reg_domain(host: str | None) -> str | None:
    """eTLD+1, or the bare host when the suffix is unknown to the PSL snapshot."""
    return etld1(host) or host if host else None


def _limit(values, n: int = MAX_LIST) -> list:
    return sorted(set(v for v in values if v))[:n]


# ------------------------------------------------------------------ main

def analyze_html(content: bytes | str, resources: list[tuple[str, bytes | Path]],
                 original_url: str | None, stop: dict[str, set[str]]) -> dict[str, Any]:
    """Pure function: html + its resources -> feature dict (no I/O besides hashing resource files)."""
    try:
        soup = BeautifulSoup(content, "lxml")
    except Exception:
        soup = BeautifulSoup(content, "html.parser")
    raw_text = content if isinstance(content, str) else content.decode(
        soup.original_encoding or "utf-8", errors="replace")

    title = soup.title.get_text(" ", strip=True)[:300] if soup.title else None
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").strip().lower()
        val = (tag.get("content") or "").strip()
        if val and (key.startswith("og:") or key in ("description", "keywords", "generator", "author", "robots")):
            meta.setdefault(key, val[:300])
    html_tag = soup.find("html")
    lang = (html_tag.get("lang") or "").strip().lower() or None if html_tag else None

    tokens = dom_tokens(soup)

    css_classes: set[str] = set()
    for tag in soup.find_all(class_=True):
        cls = tag.get("class")
        css_classes.update(cls if isinstance(cls, list) else str(cls).split())

    script_srcs, external = set(), set()
    for tag in soup.find_all("script", src=True):
        src = tag["src"]
        name = normalize_resource_name(urlsplit(src).path.rsplit("/", 1)[-1] if "/" in src else src)
        if (name and name not in GENERIC_SCRIPT_NAMES and not PIXEL_FILE_RE.match(name)
                and not name_is_stoplisted(name, stop)):
            script_srcs.add(name)
    for tag_name, attr in (("a", "href"), ("script", "src"), ("img", "src"), ("iframe", "src"),
                           ("link", "href"), ("form", "action"), ("source", "src"), ("video", "src")):
        for tag in soup.find_all(tag_name):
            dom = _reg_domain(host_of(tag.get(attr)))
            if dom and not domain_is_stoplisted(dom, stop):
                external.add(dom)

    # trackers: inline scripts + noscript + raw markup (attributes), plus landing URL params and pixel files
    trackers: set[str] = set()
    for prefix, rx in TRACKER_PATTERNS:
        for m in rx.finditer(raw_text):
            trackers.add(f"{prefix}:{m.group(1)}")
    trackers.update(_url_pixels(original_url))

    # resources: hashes (minus stoplist) and pixel config files saved under their numeric id
    asset_hashes: set[str] = set()
    for name, src in resources:
        if PIXEL_FILE_RE.match(name or ""):
            trackers.add(f"fb:{name}")
        if name and name_is_stoplisted(name, stop):
            continue
        if isinstance(src, Path):
            if src.stat().st_size == 0:
                continue
            sha1 = sha1_file(src)
        else:
            if not src:
                continue
            sha1 = hashlib.sha1(src).hexdigest()
        if not sha1_is_stoplisted(sha1, stop):
            asset_hashes.add(sha1[:16])

    forms = soup.find_all("form")
    form_actions = set()
    for f in forms:
        act = _norm_action(f.get("action", ""))
        host = act.split("/")[0] if act and not act.startswith("/") and "." in act.split("/")[0] else None
        if act and not (host and domain_is_stoplisted(_reg_domain(host), stop)):
            form_actions.add(act)
    fields = set()
    inputs = soup.find_all(["input", "select", "textarea"])
    for tag in inputs:
        if (tag.get("type") or "").lower() in ("submit", "button", "image", "reset"):
            continue
        name = (tag.get("name") or tag.get("id") or "").strip().lower()
        if name:
            fields.add(name[:60])

    # hidden text
    css_text = "\n".join(s.get_text() for s in soup.find_all("style"))
    hidden_sel = _hidden_selectors(css_text)
    custom_fonts = {f.strip() for f in FONT_FACE_RE.findall(css_text)}
    snippets, reasons_all = [], set()
    flagged: set[int] = set()
    body = soup.body or soup
    for tag in body.find_all(True):
        if tag.name in SKIP_TEXT_TAGS or tag.name in FORM_WIDGET_TAGS:
            continue
        reasons = _style_hidden_reasons(tag.get("style") or "")
        if tag.has_attr("hidden"):
            reasons.append("hidden-attr")
        classes = tag.get("class") or []
        for c in classes:
            if c.lower() in HIDDEN_CLASS_NAMES:
                reasons.append(f"class:{c}")
            if f".{c}" in hidden_sel:
                reasons += hidden_sel[f".{c}"]
        if tag.get("id") and f"#{tag['id']}" in hidden_sel:
            reasons += hidden_sel[f"#{tag['id']}"]
        if not reasons:
            continue
        if any(id(p) in flagged for p in tag.parents):
            continue  # already covered by a hidden ancestor
        flagged.add(id(tag))
        for junk in tag.find_all(SKIP_TEXT_TAGS | FORM_WIDGET_TAGS):
            junk.extract()
        _drop_phone_code_lists(tag)
        text = tag.get_text(" ", strip=True)
        if text and len(PHONE_CODE_RE.findall(text)) < MIN_PHONE_CODES:
            snippets.append(text)
            reasons_all.update(reasons)
    hidden_text = " | ".join(snippets)[:MAX_HIDDEN_CHARS] if snippets else None

    comments = []
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        t = " ".join(str(c).split())
        if t and not t.lower().startswith("saved from url"):
            comments.append(t[:120])

    return {
        "original_url": original_url,
        "title": title,
        "meta": meta,
        "generator": meta.get("generator"),
        "lang": lang,
        "dom_simhash": simhash64(tokens),
        "dom_size": sum(v for k, v in tokens.items() if k.startswith("p:")),
        "css_classes": _limit(css_classes),
        "script_srcs": _limit(script_srcs),
        "asset_hashes": _limit(asset_hashes, 2000),
        "tracker_ids": _limit(trackers),
        "form_actions": _limit(form_actions),
        "form_fields": _limit(fields, 200),
        "external_domains": _limit(external),
        "hidden_text": hidden_text,
        "hidden_text_shingles": _shingles(hidden_text) if hidden_text else [],
        "hidden_text_count": len(snippets),
        "hidden_reasons": sorted(reasons_all),
        "html_comments": list(dict.fromkeys(comments))[:30],
        "custom_fonts": _limit(custom_fonts, 50),
        "n_forms": len(forms),
        "n_inputs": len(inputs),
        "n_iframes": len(soup.find_all("iframe")),
        "n_inline_scripts": sum(1 for s in soup.find_all("script") if not s.get("src")),
    }


def extract(item: Material, ctx: Context) -> FeatureRecord:
    """Contract entry point. Never raises: failures go to errors, features become None."""
    stop = load_stoplist(ctx.settings, ctx.repo_root)
    prov = {"html_struct": f"bs4+lxml static parse; parsed_at={time.strftime('%Y-%m-%dT%H:%M:%S')}"}
    try:
        content, resources = _read_page(item, ctx)
        feats = analyze_html(content, resources, item.original_url, stop)
        errors: list[str] = []
    except Exception as exc:
        feats = {k: None for k in FEATURE_KEYS}
        feats["meta"] = {}  # keep the flattened meta.* columns consistent across rows
        errors = [f"html_struct: {type(exc).__name__}: {exc}"]
    return FeatureRecord(entity_id=item.material_id, level="material", module=MODULE, features=feats,
                         provenance=prov, errors=errors, incident_id=item.incident_id)
