"""Shared static helpers for ingest and html_struct (owner: W1).

SAFETY: nothing here renders HTML, executes JS or touches the network.
tldextract is used with its bundled Public Suffix List snapshot only.
"""
from __future__ import annotations

import hashlib
import mimetypes
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# Browser "save page as" (Polish locale) appends ".pobrane" to scripts; some use ".pobierz"/".download".
BROWSER_SUFFIXES = (".pobrane", ".pobierz", ".download")
# Directories that hold a saved page's resources: "X_files/" (browser) or "resources/" (page-capture tool).
ASSET_DIR_RE = re.compile(r"(_files|^resources)$", re.I)
HTML_EXT = {".html", ".htm", ".xhtml", ".shtml"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".svg", ".ico", ".heic", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi", ".ts", ".m3u8"}
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
# page-capture appends an 8-hex content hash before the extension: "jquery-3.6.0.min_ff1523fb.js"
CAPTURE_HASH_RE = re.compile(r"_[0-9a-f]{8}(?=\.[a-z0-9]+$)", re.I)
# Browser de-duplicates saved names as "name(1).ext"
COPY_SUFFIX_RE = re.compile(r"\(\d+\)(?=\.[a-z0-9]+$|$)", re.I)


def strip_browser_suffix(name: str) -> str:
    """'main.js.pobrane' -> 'main.js'."""
    low = name.lower()
    for suf in BROWSER_SUFFIXES:
        if low.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)]
    return name


def real_ext(name: str) -> str:
    """Lowercase extension after removing browser suffixes; '.har' dotfile counts as '.har'."""
    name = strip_browser_suffix(name)
    if name.startswith(".") and name.count(".") == 1:
        return name.lower()
    ext = Path(name).suffix.lower()
    if len(ext) > 6 or not ext[1:].isalnum():
        return ""
    return ext


def normalize_resource_name(name: str) -> str:
    """Canonical resource file name used for cross-site matching (lowercase, no suffix/hash/copy marks)."""
    name = strip_browser_suffix(name.split("?")[0].split("#")[0])
    name = CAPTURE_HASH_RE.sub("", name)
    name = COPY_SUFFIX_RE.sub("", name)
    return name.strip().lower()


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sniff_mime(path: Path) -> str | None:
    """Content-based MIME type from magic bytes, falling back to the (suffix-stripped) extension."""
    try:
        with path.open("rb") as fh:
            head = fh.read(512)
    except OSError:
        return None
    return sniff_bytes(head, path.name)


def sniff_bytes(head: bytes, name: str = "") -> str | None:
    if not head:
        return "application/x-empty"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image/heic"
    if head[4:8] == b"ftyp":
        return "video/quicktime" if head[8:10] == b"qt" else "video/mp4"
    if head[:1] == b"\x47" and len(head) > 188 and head[188:189] == b"\x47":
        return "video/mp2t"
    if head.startswith(b"#EXTM3U"):
        return "application/vnd.apple.mpegurl"
    if head[:4] == b"wOF2":
        return "font/woff2"
    if head[:4] == b"wOFF":
        return "font/woff"
    if head[:2] == b"PK":
        return "application/zip"
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if head.startswith(b"%PDF"):
        return "application/pdf"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith(b"from:") or b"mime-version:" in text[:400]:
        return "multipart/related"
    if text.startswith((b"<!doctype html", b"<html", b"<!-- saved from", b"<head", b"<meta")):
        return "text/html"
    if text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in text):
        return "image/svg+xml"
    guess, _ = mimetypes.guess_type(strip_browser_suffix(name))
    if guess:
        return guess
    if text.startswith((b"{", b"[")):
        return "application/json"
    return None


def host_of(url: str | None) -> str | None:
    """Lowercase hostname of an absolute (or protocol-relative) http(s) URL, else None."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or "." not in host:
        return None
    return host.lower().rstrip(".")


@lru_cache(maxsize=1)
def _extractor():
    import tldextract

    # Empty suffix_list_urls + no cache dir = bundled PSL snapshot, never fetched over the network.
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def etld1(host_or_url: str | None) -> str | None:
    """Registered domain (eTLD+1), e.g. 'cdn.foo.co.uk' -> 'foo.co.uk'. None for IPs/invalid."""
    if not host_or_url:
        return None
    host = host_of(host_or_url) if "/" in host_or_url else host_or_url.lower().strip(".")
    if not host:
        return None
    ext = _extractor()(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return None


# ------------------------------------------------------------------ stoplist

@lru_cache(maxsize=8)
def _load_stoplist_file(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError:
        data = {}
    return data


def load_stoplist(settings: dict[str, Any] | None = None, repo_root: Path | None = None) -> dict[str, set[str]]:
    """Stoplist as lowercase sets. Uses settings['stoplist'] if the context already loaded it."""
    raw: dict[str, Any] | None = None
    if settings and isinstance(settings.get("stoplist"), dict):
        raw = settings["stoplist"]
    if raw is None:
        raw = _load_stoplist_file(str((repo_root or REPO_ROOT) / "config" / "stoplist.yaml"))
    return {
        "filenames": {str(x).lower() for x in raw.get("filenames") or []},
        "sha1": {str(x).lower() for x in raw.get("sha1") or []},
        "domains": {str(x).lower().strip(".") for x in raw.get("domains") or []},
    }


def name_is_stoplisted(name: str, stop: dict[str, set[str]]) -> bool:
    n = normalize_resource_name(name)
    return any(pat in n for pat in stop["filenames"])


def sha1_is_stoplisted(sha1: str | None, stop: dict[str, set[str]]) -> bool:
    if not sha1:
        return False
    s = sha1.lower()
    # stoplist may hold full sha1 or a prefix (e.g. material_id = sha1[:16])
    return any(s.startswith(x) for x in stop["sha1"] if len(x) >= 8)


def domain_is_stoplisted(domain: str | None, stop: dict[str, set[str]]) -> bool:
    if not domain:
        return True
    d = domain.lower().strip(".")
    return any(d == x or d.endswith("." + x) for x in stop["domains"])
