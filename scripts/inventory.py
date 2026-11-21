#!/usr/bin/env python3
"""Static inventory of the NASK "Kolekcjoner fejkow" data package.

Usage:
    python scripts/inventory.py data/raw/nask [--out data/interim/DATA_INVENTORY.md] [--json data/interim/inventory.json]

The curated report in docs/DATA_INVENTORY.md is only rewritten when passed explicitly via --out.

SAFETY: the data contains live scam pages. This script never renders HTML,
never executes JS and never performs any network request. All parsing is
static (stdlib html.parser / json / email). Only domains, counts and short
metadata are written to the Markdown report - no page text, no ad copy.
"""
from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import json
import mimetypes
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

try:  # optional dependency
    from PIL import Image  # type: ignore

    Image.MAX_IMAGE_PIXELS = None
except Exception:  # pragma: no cover
    Image = None

# Browser "save page as" in Polish locale appends ".pobrane" ("downloaded")
# to script files; a few files are saved as "pobierz" ("download").
BROWSER_SUFFIXES = {".pobrane", ".download", ".pobierz"}
HTML_EXT = {".html", ".htm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".svg", ".ico"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".ts", ".m3u8"}
SAVED_FROM_RE = re.compile(r"saved from url=\(\d+\)(\S+)", re.I)
FB_PIXEL_RE = re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{6,20})['\"]")
# Pixel IDs in network URLs: connect.facebook.net/signals/config/<id>, facebook.com/tr?id=<id>
FB_PIXEL_URL_RE = re.compile(r"(?:/signals/config/|facebook\.com/tr/?\?(?:[^\s\"']*&)?id=)(\d{12,20})")
# Browser "save page" stores the pixel config script under its bare numeric ID.
FB_PIXEL_FILE_RE = re.compile(r"^\d{15,17}$")
DIGITS_RE = re.compile(r"\d+")
MANUAL_MARKER = "<!-- MANUAL: hand-written section below is preserved by inventory.py -->"
HASHLIKE_RE = re.compile(r"[0-9a-f]{8,}", re.I)


# ---------------------------------------------------------------- helpers

def host_of(url: str | None) -> str | None:
    """Return lowercase hostname of an absolute http(s) URL, else None."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        return None
    return parts.hostname.lower().rstrip(".")


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_ext(path: Path) -> str:
    """Extension with browser download suffixes folded, e.g. 'x.js.pobrane' -> '.js(+pobrane)'."""
    name = path.name
    if name.startswith(".") and name.count(".") == 1:  # dotfile such as '.har'
        return name.lower()
    suffixes = [s.lower() for s in path.suffixes]
    if not suffixes:
        return "(none)"
    last = suffixes[-1]
    if last in BROWSER_SUFFIXES:
        inner = suffixes[-2] if len(suffixes) > 1 and len(suffixes[-2]) <= 6 else ""
        return f"{inner or '(none)'}(+{last[1:]})"
    if len(last) > 6 or not last[1:].replace("@", "").isalnum():
        return "(none)"  # e.g. 'vt(3)', long hashes, 'js@latest'
    return last


def sniff(path: Path) -> str:
    """Content-based type from magic bytes; falls back to mimetypes."""
    try:
        with path.open("rb") as fh:
            head = fh.read(512)
    except OSError:
        return "unreadable"
    if not head:
        return "empty"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return "video/mp4"
    if head[:1] == b"\x47" and len(head) > 188 and head[188:189] == b"\x47":
        return "video/mp2t"
    if head.startswith(b"#EXTM3U"):
        return "application/vnd.apple.mpegurl"
    if head[:4] == b"wOF2" or head[:4] == b"wOFF":
        return "font/woff2" if head[:4] == b"wOF2" else "font/woff"
    if head[:2] == b"PK":
        return "application/zip"
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith(b"from:") or b"mime-version:" in text[:300]:
        return "multipart/related (mhtml)"
    if text.startswith((b"<!doctype html", b"<html", b"<!-- saved from")):
        return "text/html"
    if text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in text):
        return "image/svg+xml"
    if text.startswith((b"{", b"[")):
        return "application/json"
    guess, _ = mimetypes.guess_type(path.name)
    if guess:
        return guess
    if b"function" in text or b"var " in text or b"!function" in text or b"use strict" in text:
        return "application/javascript (guess)"
    if b"@font-face" in text or b"{" in text and b":" in text and b";" in text:
        return "text/css (guess)"
    return "application/octet-stream"


def name_pattern(name: str) -> str:
    """Generalise a filename: digits -> N, long hex -> H."""
    stem = HASHLIKE_RE.sub("H", name)
    return DIGITS_RE.sub("N", stem)


# ---------------------------------------------------------------- HTML

class _StaticHTML(HTMLParser):
    """Collects structural facts only. Never touches the network."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self._in_title = False
        self._in_script = False
        self.saved_from: str | None = None
        self.og_url: str | None = None
        self.canonical: str | None = None
        self.script_src = 0
        self.script_inline = 0
        self.img = 0
        self.forms = 0
        self.inputs = 0
        self.iframes = 0
        self.a_domains: Counter[str] = Counter()
        self.src_domains: Counter[str] = Counter()
        self.fb_pixels: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "script":
            if a.get("src"):
                self.script_src += 1
                if h := host_of(a["src"]):
                    self.src_domains[h] += 1
            else:
                self.script_inline += 1
                self._in_script = True
        elif tag == "img":
            self.img += 1
            if h := host_of(a.get("src")):
                self.src_domains[h] += 1
        elif tag == "a":
            if h := host_of(a.get("href")):
                self.a_domains[h] += 1
        elif tag == "form":
            self.forms += 1
            if h := host_of(a.get("action")):
                self.a_domains[h] += 1
        elif tag in ("input", "select", "textarea"):
            self.inputs += 1
        elif tag == "iframe":
            self.iframes += 1
            if h := host_of(a.get("src")):
                self.src_domains[h] += 1
        elif tag == "meta":
            if a.get("property", "").lower() == "og:url" and a.get("content"):
                self.og_url = a["content"]
        elif tag == "link":
            if "canonical" in a.get("rel", "").lower() and a.get("href"):
                self.canonical = a["href"]

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_script:
            self.fb_pixels.update(FB_PIXEL_RE.findall(data))

    def handle_comment(self, data):
        if self.saved_from is None:
            m = SAVED_FROM_RE.search(data)
            if m:
                self.saved_from = m.group(1)


def parse_html(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    p = _StaticHTML()
    try:
        p.feed(text)
        p.close()
    except Exception as exc:  # malformed markup should not kill the run
        return {"error": repr(exc)}
    title = " ".join("".join(p.title_parts).split())
    return {
        "title": title,
        "saved_from": p.saved_from,
        "saved_from_host": host_of(p.saved_from),
        "og_url_host": host_of(p.og_url),
        "canonical_host": host_of(p.canonical),
        "script_src": p.script_src,
        "script_inline": p.script_inline,
        "img": p.img,
        "forms": p.forms,
        "inputs": p.inputs,
        "iframes": p.iframes,
        "a_domains": dict(p.a_domains),
        "src_domains": dict(p.src_domains),
        "fb_pixels": sorted(p.fb_pixels),
    }


# ---------------------------------------------------------------- other formats

def parse_har(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        log = data["log"]
    except Exception as exc:
        return {"error": repr(exc)}
    entries = log.get("entries", [])
    hosts: Counter[str] = Counter()
    ips: set[str] = set()
    statuses: Counter[int] = Counter()
    redirects = 0
    pixels: set[str] = set()
    for e in entries:
        pixels.update(FB_PIXEL_URL_RE.findall(e.get("request", {}).get("url", "")))
        if h := host_of(e.get("request", {}).get("url")):
            hosts[h] += 1
        if ip := e.get("serverIPAddress"):
            ips.add(ip.strip("[]"))
        st = e.get("response", {}).get("status", 0)
        statuses[st] += 1
        if 300 <= st < 400:
            redirects += 1
    pages = log.get("pages", [])
    first_host = host_of(entries[0]["request"]["url"]) if entries else None
    return {
        "creator": (log.get("creator") or {}).get("name"),
        "pages": len(pages),
        "entries": len(entries),
        "first_request_host": first_host,
        "hosts": dict(hosts),
        "server_ips": sorted(ips),
        "redirects_3xx": redirects,
        "statuses": {str(k): v for k, v in sorted(statuses.items())},
        "fb_pixels": sorted(pixels),
    }


def parse_mhtml(path: Path) -> dict:
    with path.open("rb") as fh:
        head = fh.read(4096)
    msg = email.message_from_bytes(head, policy=email.policy.compat32)
    loc = msg.get("Snapshot-Content-Location") or msg.get("Content-Location")
    return {"snapshot_host": host_of(loc), "subject_present": bool(msg.get("Subject"))}


def parse_json_meta(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return {"error": repr(exc)}
    out: dict = {"top_keys": sorted(data)[:40] if isinstance(data, dict) else f"list[{len(data)}]"}
    if isinstance(data, dict):
        if "extractor" in data:  # yt-dlp metadata
            out["kind"] = "yt-dlp info.json"
            out["extractor"] = data.get("extractor")
            out["webpage_host"] = host_of(data.get("webpage_url"))
        elif "page_url" in data:  # page-capture manifest
            out["kind"] = "page-capture manifest"
            out["tool"] = data.get("tool")
            out["captured_at"] = data.get("captured_at")
            out["page_host"] = host_of(data.get("page_url"))
            q = urlsplit(data.get("page_url") or "").query
            out["page_url_query_keys"] = sorted({kv.split("=")[0] for kv in q.split("&") if kv})
    return out


def image_dims(path: Path) -> tuple[int, int] | None:
    if Image is None or path.suffix.lower() == ".svg":
        return None
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


# ---------------------------------------------------------------- walk

@dataclass
class FileRec:
    rel: str
    top: str
    size: int
    ext: str
    mime: str
    sha1: str
    depth: int
    in_files_dir: bool
    extra: dict = field(default_factory=dict)


def classify(rec: FileRec) -> str:
    """Coarse material category used in summary tables."""
    m, e = rec.mime, rec.ext
    if rec.in_files_dir:
        return "page asset (_files/)"
    if m == "text/html" or e in HTML_EXT:
        return "html page"
    if "mhtml" in m or e == ".mhtml":
        return "mhtml"
    if e == ".har":
        return "har log"
    if m.startswith("image/"):
        return "image"
    if m.startswith("video/") or e in VIDEO_EXT:
        return "video"
    if e == ".json" or m == "application/json":
        return "json metadata"
    return "other"


def walk(root: Path) -> list[FileRec]:
    recs: list[FileRec] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            rel = p.relative_to(root)
            parts = rel.parts
            top = parts[0] if len(parts) > 1 else "(root)"
            in_files = any(part.endswith("_files") or part == "resources" for part in parts[1:-1])
            rec = FileRec(
                rel=rel.as_posix(),
                top=top,
                size=p.stat().st_size,
                ext=norm_ext(p),
                mime=sniff(p),
                sha1=sha1_file(p),
                depth=len(parts) - 1,
                in_files_dir=in_files,
            )
            if rec.mime == "text/html" or rec.ext in HTML_EXT:
                rec.extra = parse_html(p)
            elif rec.ext == ".har":
                rec.extra = parse_har(p)
            elif rec.ext == ".mhtml" or "mhtml" in rec.mime:
                rec.extra = parse_mhtml(p)
            elif rec.ext == ".json":
                rec.extra = parse_json_meta(p)
            if rec.in_files_dir and FB_PIXEL_FILE_RE.match(fn):
                rec.extra["fb_pixels"] = [fn]
            if rec.mime.startswith("image/"):
                if dims := image_dims(p):
                    rec.extra["dims"] = dims
            recs.append(rec)
    recs.sort(key=lambda r: (folder_key(r.top), r.rel))
    return recs


def saved_page_pairs(root: Path, top: str) -> list[dict]:
    """For every X.html anywhere in folder `top`, check whether sibling X_files/ exists."""
    out = []
    for dirpath, _dirs, files in os.walk(root / top):
        d = Path(dirpath)
        if any(part.endswith("_files") for part in d.relative_to(root).parts):
            continue
        for fn in files:
            if Path(fn).suffix.lower() in HTML_EXT:
                stem = Path(fn).stem
                fdir = d / f"{stem}_files"
                out.append({
                    "html": (d / fn).relative_to(root).as_posix(),
                    "has_files_dir": fdir.is_dir(),
                    "files_in_dir": sum(1 for _ in fdir.rglob("*") if _.is_file()) if fdir.is_dir() else 0,
                })
    return out


def tree(root: Path, top: str, levels: int = 2, max_items: int = 12) -> list[str]:
    """ASCII tree of folder `top`, `levels` deep, collapsing long listings."""
    lines = [f"{top}/"]

    def rec(d: Path, prefix: str, level: int) -> None:
        kids = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        shown = kids[:max_items]
        for i, k in enumerate(shown):
            last = i == len(shown) - 1 and len(kids) <= max_items
            branch = "└── " if last else "├── "
            if k.is_dir():
                n = sum(1 for f in k.rglob("*") if f.is_file())
                lines.append(f"{prefix}{branch}{shorten(k.name)}/  ({n} files)")
                if level < levels:
                    rec(k, prefix + ("    " if last else "│   "), level + 1)
            else:
                lines.append(f"{prefix}{branch}{shorten(k.name)}  [{human(k.stat().st_size)}]")
        if len(kids) > max_items:
            lines.append(f"{prefix}└── … (+{len(kids) - max_items} more)")

    rec(root / top, "", 1)
    return lines


def shorten(s: str, n: int = 60) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def folder_key(name: str):
    return (0, int(name)) if name.isdigit() else (1, name)


# ---------------------------------------------------------------- report

def build_report(root: Path, recs: list[FileRec]) -> tuple[str, dict]:
    by_top: dict[str, list[FileRec]] = defaultdict(list)
    for r in recs:
        by_top[r.top].append(r)
    tops = sorted(by_top, key=folder_key)
    pairs = {t: saved_page_pairs(root, t) for t in tops if t != "(root)"}

    md: list[str] = []
    w = md.append
    w("# DATA_INVENTORY — paczka NASK (`data/raw/nask/`)\n")
    w("> Wygenerowano automatycznie: `python scripts/inventory.py data/raw/nask`. "
      "Parsowanie wyłącznie statyczne (bez renderowania, bez JS, bez sieci). "
      "Raport zawiera tylko liczby, typy, domeny i skrócone tytuły — bez treści stron i reklam.\n")

    # 1. summary
    total = sum(r.size for r in recs)
    w("## 1. Podsumowanie\n")
    w(f"- Folderów najwyższego poziomu: **{len(tops)}** ({', '.join(tops)})")
    w(f"- Plików: **{len(recs)}**, łączny rozmiar: **{human(total)}**")
    cats = Counter(classify(r) for r in recs)
    w("- Kategorie materiałów: " + ", ".join(f"{k}: {v}" for k, v in cats.most_common()))
    w("")

    # 2. per-folder table
    w("## 2. Foldery × kategorie\n")
    cat_cols = ["html page", "page asset (_files/)", "har log", "image", "video", "mhtml", "json metadata", "other"]
    w("| folder | pliki | rozmiar | głęb. | " + " | ".join(cat_cols) + " | X.html+X_files |")
    w("|---|---:|---:|---:|" + "---:|" * len(cat_cols) + "---|")
    for t in tops:
        rs = by_top[t]
        c = Counter(classify(r) for r in rs)
        pr = pairs.get(t, [])
        pr_s = f"{sum(p['has_files_dir'] for p in pr)}/{len(pr)}" if pr else "—"
        w(f"| {t} | {len(rs)} | {human(sum(r.size for r in rs))} | {max(r.depth for r in rs)} | "
          + " | ".join(str(c.get(k, 0)) for k in cat_cols) + f" | {pr_s} |")
    w("")
    w("`X.html+X_files` = liczba stron HTML (poza `_files/`), które mają obok folder `X_files/` / wszystkie takie strony.\n")

    # 3. extensions and MIME
    w("## 3. Rozszerzenia i typy MIME (sniffing po magic bytes)\n")
    ext_by_top = {t: Counter(r.ext for r in by_top[t]) for t in tops}
    all_ext = Counter(r.ext for r in recs)
    w("| rozszerzenie | razem | " + " | ".join(tops) + " |")
    w("|---|---:|" + "---:|" * len(tops))
    for e, n in all_ext.most_common():
        w(f"| `{e}` | {n} | " + " | ".join(str(ext_by_top[t].get(e, 0) or "") for t in tops) + " |")
    w("")
    mime_by_top = {t: Counter(r.mime for r in by_top[t]) for t in tops}
    all_mime = Counter(r.mime for r in recs)
    w("| MIME (sniff) | razem | " + " | ".join(tops) + " |")
    w("|---|---:|" + "---:|" * len(tops))
    for m, n in all_mime.most_common():
        w(f"| {m} | {n} | " + " | ".join(str(mime_by_top[t].get(m, 0) or "") for t in tops) + " |")
    w("")
    w("Uwaga: `.js(+pobrane)` itp. to skrypty zapisane przez przeglądarkę w polskiej wersji językowej "
      "(sufiks „.pobrane”). `(none)` = brak rozszerzenia (np. `vt(3)`, `css2`, numeryczne ID pikseli FB).\n")

    # 4. top-level files and name patterns
    w("## 4. Pliki na poziomie folderu (poza `_files/`) i wzorce nazw\n")
    w("| folder | plik (wzorzec nazwy) | kategoria | rozmiar | wymiary |")
    w("|---|---|---|---:|---|")
    for t in tops:
        for r in by_top[t]:
            if r.in_files_dir:
                continue
            dims = r.extra.get("dims")
            name = r.rel.split("/", 1)[1] if "/" in r.rel else r.rel
            cat = classify(r)
            # HTML file names equal page titles -> show only pattern, not the text
            shown = "«tytuł strony».html" if cat == "html page" and "/" not in name else (
                "/".join(name.split("/")[:-1] + ["«tytuł strony».html"]) if cat == "html page" else name_pattern(name))
            w(f"| {t} | `{shorten(shown, 70)}` | {cat} | {human(r.size)} | {f'{dims[0]}×{dims[1]}' if dims else ''} |")
    w("")
    pat = Counter(name_pattern(Path(r.rel).name) for r in recs if not r.in_files_dir and classify(r) != "html page")
    w("Najczęstsze wzorce nazw (N = cyfry, H = hash hex): " + ", ".join(f"`{p}`×{n}" for p, n in pat.most_common(12)) + "\n")

    # 5. example trees
    w("## 5. Przykładowe drzewa folderów (2 poziomy)\n")
    for t in [x for x in ("1", "14", "61") if x in by_top]:
        w("```")
        md.extend(tree(root, t))
        w("```")
    w("")

    # 6. HTML pages
    w("## 6. Strony HTML (parsowanie statyczne)\n")
    w("| folder | plik | tytuł (skrót) | saved from | og:url / canonical | script src | inline script | img | form | input | iframe | domeny w <a> | piksele FB |")
    w("|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in recs:
        if classify(r) not in ("html page",) and not (r.in_files_dir and r.mime == "text/html"):
            continue
        x = r.extra
        if "error" in x:
            w(f"| {r.top} | {shorten(Path(r.rel).name, 30)} | parse error | | | | | | | | | | |")
            continue
        fname = "(w _files/) " + Path(r.rel).name if r.in_files_dir else (
            Path(r.rel).name if Path(r.rel).stem.lower() in ("dom", "index", "page") else "«tytuł».html")
        og = x.get("og_url_host") or x.get("canonical_host") or ""
        w(f"| {r.top} | {shorten(fname, 40)} | {shorten(x.get('title') or '', 45)} | {x.get('saved_from_host') or ''} | {og} | "
          f"{x['script_src']} | {x['script_inline']} | {x['img']} | {x['forms']} | {x['inputs']} | {x['iframes']} | "
          f"{len(x['a_domains'])} | {len(x['fb_pixels'])} |")
    w("")

    # 7. HAR
    w("## 7. Logi HAR\n")
    w("| folder | plik | narzędzie | requesty | unikalne hosty | IP serwerów | 3xx | pierwszy host |")
    w("|---|---|---|---:|---:|---:|---:|---|")
    for r in recs:
        if r.ext != ".har":
            continue
        x = r.extra
        if "error" in x:
            w(f"| {r.top} | {Path(r.rel).name} | parse error | | | | | |")
            continue
        w(f"| {r.top} | `{r.rel.split('/', 1)[1]}` | {x['creator']} | {x['entries']} | {len(x['hosts'])} | "
          f"{len(x['server_ips'])} | {x['redirects_3xx']} | {x['first_request_host'] or ''} |")
    w("")

    # 8. metadata files
    w("## 8. Metadane (JSON / MHTML)\n")
    for r in recs:
        if classify(r) in ("json metadata", "mhtml") and not r.in_files_dir:
            x = {k: v for k, v in r.extra.items() if k != "top_keys"}
            w(f"- `{r.top}/…/{Path(r.rel).name if classify(r) != 'json metadata' or r.top != '5' else '«tytuł».info.json'}` — "
              + ", ".join(f"{k}: {v}" for k, v in x.items()))
    w("")

    # 9. domains
    w("## 9. Domeny\n")
    link_dom: dict[str, set[str]] = defaultdict(set)
    page_dom: dict[str, set[str]] = defaultdict(set)
    har_dom: dict[str, set[str]] = defaultdict(set)
    pixels: dict[str, set[str]] = defaultdict(set)
    for r in recs:
        x = r.extra
        for px in x.get("fb_pixels", []):
            pixels[px].add(r.top)
        if "a_domains" in x:
            for d in x["a_domains"]:
                link_dom[d].add(r.top)
            for k in ("saved_from_host", "og_url_host", "canonical_host"):
                if x.get(k):
                    page_dom[x[k]].add(r.top)
        if "hosts" in x:
            for d in x["hosts"]:
                har_dom[d].add(r.top)
        for k in ("snapshot_host", "page_host", "webpage_host"):
            if x.get(k):
                page_dom[x[k]].add(r.top)

    def dom_table(title: str, dmap: dict[str, set[str]]) -> None:
        w(f"### {title} ({len(dmap)})\n")
        w("| domena | foldery |")
        w("|---|---|")
        for d in sorted(dmap, key=lambda d: (-len(dmap[d]), d)):
            w(f"| {d} | {', '.join(sorted(dmap[d], key=folder_key))} |")
        w("")

    dom_table("Domeny stron (saved from / og:url / canonical / manifest / mhtml)", page_dom)
    dom_table("Domeny w linkach `<a href>` / `<form action>`", link_dom)
    dom_table("Hosty z logów HAR", har_dom)
    w("### Identyfikatory pikseli Facebook (`fbq('init', …)`, URL-e `signals/config/<id>` / `tr?id=` w HAR, pliki `<id>` w `_files/`)\n")
    w("| pixel ID | foldery |")
    w("|---|---|")
    for px in sorted(pixels, key=lambda p: (-len(pixels[p]), p)):
        w(f"| {px} | {', '.join(sorted(pixels[px], key=folder_key))} |")
    w("")

    # 10. duplicates
    w("## 10. Duplikaty dokładne (sha1)\n")
    groups: dict[str, list[FileRec]] = defaultdict(list)
    for r in recs:
        groups[r.sha1].append(r)
    dups = {h: g for h, g in groups.items() if len(g) > 1}
    redundant = sum(len(g) - 1 for g in dups.values())
    cross = {h: g for h, g in dups.items() if len({r.top for r in g}) > 1}
    w(f"- Grup duplikatów: **{len(dups)}**, nadmiarowych kopii: **{redundant}** "
      f"({human(sum((len(g) - 1) * g[0].size for g in dups.values()))})")
    w(f"- Grup obejmujących >1 folder: **{len(cross)}**\n")
    pair_ct: Counter[tuple[str, ...]] = Counter()
    for g in cross.values():
        pair_ct[tuple(sorted({r.top for r in g}, key=folder_key))] += 1
    if pair_ct:
        w("| foldery dzielące identyczne pliki | liczba wspólnych plików |")
        w("|---|---:|")
        for k, n in pair_ct.most_common():
            w(f"| {', '.join(k)} | {n} |")
        w("")
    w("| sha1[:12] | kopie | rozmiar | kategoria | foldery |")
    w("|---|---:|---:|---|---|")
    for h, g in sorted(dups.items(), key=lambda kv: (-len({r.top for r in kv[1]}), -kv[1][0].size))[:40]:
        w(f"| {h[:12]} | {len(g)} | {human(g[0].size)} | {classify(g[0])} | "
          f"{', '.join(sorted({r.top for r in g}, key=folder_key))} |")
    if len(dups) > 40:
        w(f"| … | | | | (+{len(dups) - 40} grup) |")
    w("")

    data = {
        "root": str(root),
        "files": [r.__dict__ for r in recs],
        "saved_page_pairs": pairs,
        "duplicates": {h: [r.rel for r in g] for h, g in dups.items()},
    }
    return "\n".join(md) + "\n", data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, help="root of the NASK package, e.g. data/raw/nask")
    ap.add_argument("--out", type=Path, default=Path("data/interim/DATA_INVENTORY.md"),
                    help="markdown report (default keeps the tracked docs/ copy untouched)")
    ap.add_argument("--json", type=Path, default=Path("data/interim/inventory.json"),
                    help="full per-file details (stays in gitignored data/)")
    args = ap.parse_args(argv)
    if not args.data.is_dir():
        print(f"not a directory: {args.data}", file=sys.stderr)
        return 2
    recs = walk(args.data)
    md, data = build_report(args.data, recs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Keep the hand-written analysis (everything from MANUAL_MARKER on) across regenerations.
    if args.out.exists():
        old = args.out.read_text(encoding="utf-8")
        if MANUAL_MARKER in old:
            md += "\n" + old[old.index(MANUAL_MARKER):]
    args.out.write_text(md, encoding="utf-8")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    print(f"{len(recs)} files inventoried -> {args.out} (+ details in {args.json})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
