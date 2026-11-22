"""Dataset loader: folders/files/zips -> Incident + Material records (CONTRACTS §2).

Owner: W1. Output: data/interim/incidents.jsonl (one Incident per line, dataclasses.asdict).

SAFETY: purely static. Files are hashed and sniffed; HTML is only scanned with regexes
for its source URL. Nothing is rendered, executed or fetched.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from fakecollector.core.models import Incident, Material
from fakecollector.ingest.util import (
    ASSET_DIR_RE,
    HTML_EXT,
    IGNORED_NAMES,
    IMAGE_EXT,
    REPO_ROOT,
    VIDEO_EXT,
    host_of,
    load_stoplist,
    name_is_stoplisted,
    real_ext,
    sha1_file,
    sha1_is_stoplisted,
    sniff_mime,
)

log = logging.getLogger(__name__)

SAVED_FROM_RE = re.compile(r"saved from url=\(\d+\)(\S+?)\s*-->", re.I)
OG_URL_RE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*[\"']og:url[\"'][^>]*content\s*=\s*[\"']([^\"']+)"
    r"|<meta[^>]+content\s*=\s*[\"']([^\"']+)[\"'][^>]*(?:property|name)\s*=\s*[\"']og:url",
    re.I,
)
CANONICAL_RE = re.compile(
    r"<link[^>]+rel\s*=\s*[\"']canonical[\"'][^>]*href\s*=\s*[\"']([^\"']+)"
    r"|<link[^>]+href\s*=\s*[\"']([^\"']+)[\"'][^>]*rel\s*=\s*[\"']canonical",
    re.I,
)
MHTML_LOC_RE = re.compile(rb"Snapshot-Content-Location:\s*(\S+)", re.I)
# "strona_2", "page-3", "step 1", "krok_2" -> chain position
CHAIN_DIR_RE = re.compile(r"(?:strona|page|step|krok|etap|landing)[ _\-]?(\d{1,3})$", re.I)

MAX_HTML_SCAN = 2_000_000          # bytes read when looking for the source URL
MAX_HAR_PARSE = 60_000_000         # do not json-parse bigger HAR files for URL extraction
MAX_ZIP_TOTAL = 2_000_000_000      # zip-bomb guard (uncompressed bytes)


# ------------------------------------------------------------------ classification

def _in_asset_dir(rel_parts: tuple[str, ...]) -> int | None:
    """Index of the first resource directory (X_files/ or resources/) in the path, else None."""
    for i, part in enumerate(rel_parts[:-1]):
        if ASSET_DIR_RE.search(part):
            return i
    return None


def classify(path: Path, mime: str | None, in_asset_dir: bool) -> str:
    """Material.kind per CONTRACTS §2."""
    if in_asset_dir:
        return "asset"
    ext = real_ext(path.name)
    m = mime or ""
    if ext == ".mhtml" or ext == ".mht" or m == "multipart/related":
        return "mhtml"
    if ext in HTML_EXT or m == "text/html":
        return "html"
    if ext == ".har":
        return "har"
    if ext in VIDEO_EXT or m.startswith("video/") or m == "application/vnd.apple.mpegurl":
        return "video"
    if ext in IMAGE_EXT or m.startswith("image/"):
        return "image"
    if ext == ".json" or m == "application/json":
        return "json"
    return "other"


# ------------------------------------------------------------------ original URL

def _first(match: re.Match | None) -> str | None:
    if not match:
        return None
    return next((g for g in match.groups() if g), None)


def url_from_html(path: Path) -> tuple[str | None, str | None]:
    """(url, how) from 'saved from url' comment, og:url or canonical."""
    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_HTML_SCAN)
    except OSError:
        return None, None
    text = raw.decode("utf-8", errors="replace")
    for how, rx in (("saved_from", SAVED_FROM_RE), ("og_url", OG_URL_RE), ("canonical", CANONICAL_RE)):
        url = _first(rx.search(text))
        if url and url.lower().startswith(("http://", "https://")):
            return url.strip(), how
    return None, None


def url_from_mhtml(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            head = fh.read(8192)
    except OSError:
        return None
    m = MHTML_LOC_RE.search(head)
    return m.group(1).decode("utf-8", errors="replace") if m else None


def url_from_json(path: Path) -> str | None:
    """page-capture manifest ('page_url') or yt-dlp info.json ('webpage_url')."""
    try:
        if path.stat().st_size > 20_000_000:
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        for key in ("page_url", "webpage_url", "original_url", "url"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith(("http://", "https://")):
                return val
    return None


def har_summary(path: Path) -> tuple[str | None, str | None]:
    """(first page URL, capture start time) of a HAR log. Ignores file:// and bogus hosts."""
    try:
        if path.stat().st_size > MAX_HAR_PARSE:
            return None, None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        log_ = data.get("log", {})
        pages = log_.get("pages") or []
        entries = log_.get("entries") or []
        started = (pages[0].get("startedDateTime") if pages else None) or \
                  (entries[0].get("startedDateTime") if entries else None)
        candidates = [pg.get("title") for pg in pages] + [(e.get("request") or {}).get("url") for e in entries]
        url = next((u for u in candidates if isinstance(u, str) and host_of(u)), None)
        return url, started
    except (OSError, ValueError, AttributeError, IndexError):
        return None, None


# ------------------------------------------------------------------ incident builder

def _iter_files(folder: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        dirnames[:] = [d for d in dirnames if d != "__MACOSX"]
        for fn in sorted(filenames):
            if fn.lower() in IGNORED_NAMES or fn.startswith("._"):
                continue
            p = Path(dirpath) / fn
            if p.is_file() and not p.is_symlink():
                yield p


def _store_path(p: Path) -> str:
    """Path relative to repo root when possible (CONTRACTS: path under data/), else absolute."""
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def _find_page_for_asset(asset_dir: Path, pages_by_dir: dict[Path, list[tuple[Path, str]]]) -> str | None:
    """material_id of the page that owns resource dir `asset_dir` ('X_files' -> 'X.html')."""
    siblings = pages_by_dir.get(asset_dir.parent, [])
    if not siblings:
        return None
    name = asset_dir.name
    if name.lower().endswith("_files"):
        stem = name[: -len("_files")]
        for page_path, mid in siblings:
            if page_path.stem == stem:
                return mid
    # page-capture layout (resources/ + dom.html) or unmatched stem: prefer html, then mhtml
    for page_path, mid in siblings:
        if page_path.suffix.lower() in HTML_EXT:
            return mid
    return siblings[0][1]


def _chain_index(rel_parts: tuple[str, ...]) -> int | None:
    for part in reversed(rel_parts[:-1]):
        m = CHAIN_DIR_RE.search(part.strip())
        if m:
            return int(m.group(1))
    return None


def build_incident(folder: Path, incident_id: str, source: str, stop: dict[str, set[str]] | None = None) -> Incident:
    """Turn one folder into an Incident. Never raises on a single bad file."""
    stop = stop or load_stoplist()
    t0 = time.time()
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    for p in _iter_files(folder):
        rel = p.relative_to(folder)
        try:
            sha1 = sha1_file(p)
            mime = sniff_mime(p)
            ad_idx = _in_asset_dir(rel.parts)
            kind = classify(p, mime, ad_idx is not None)
            rows.append({"p": p, "rel": rel, "sha1": sha1, "mime": mime, "kind": kind, "ad_idx": ad_idx,
                         "size": p.stat().st_size})
        except OSError as exc:
            errors.append(f"{rel.as_posix()}: {exc}")

    # pages (html/mhtml outside resource dirs) indexed by directory, for asset -> parent mapping
    pages_by_dir: dict[Path, list[tuple[Path, str]]] = {}
    for r in rows:
        if r["kind"] in ("html", "mhtml"):
            pages_by_dir.setdefault(r["p"].parent, []).append((r["p"], r["sha1"][:16]))

    materials: list[Material] = []
    seen: dict[str, Material] = {}
    for r in rows:
        p, rel, sha1, kind = r["p"], r["rel"], r["sha1"], r["kind"]
        mid = sha1[:16]
        parent = None
        if kind == "asset":
            asset_dir = folder.joinpath(*rel.parts[: r["ad_idx"] + 1])
            parent = _find_page_for_asset(asset_dir, pages_by_dir)

        if mid in seen:  # exact duplicate inside one incident -> keep one material, remember the copy
            first = seen[mid]
            first.meta.setdefault("duplicate_paths", []).append(rel.as_posix())
            if parent and parent != first.parent_html:
                parents = first.meta.setdefault("also_parent_html", [])
                if parent not in parents:
                    parents.append(parent)
            continue

        meta: dict[str, Any] = {"sha1": sha1, "rel_path": rel.as_posix(), "name": p.name}
        original_url = None
        try:
            if kind == "html":
                original_url, how = url_from_html(p)
                if how:
                    meta["url_source"] = how
            elif kind == "mhtml":
                original_url = url_from_mhtml(p)
            elif kind == "json":
                original_url = url_from_json(p)
            elif kind == "har":
                original_url, started = har_summary(p)
                if started:
                    meta["har_started"] = started
        except Exception as exc:  # defensive: URL extraction must never break ingest
            errors.append(f"{rel.as_posix()}: url extraction failed: {exc}")

        if kind in ("html", "mhtml", "har", "json"):
            ci = _chain_index(rel.parts)
            if ci is not None:
                meta["chain_index"] = ci
            meta["page_dir"] = rel.parent.as_posix()

        common = name_is_stoplisted(p.name, stop) or sha1_is_stoplisted(sha1, stop) or r["size"] == 0
        m = Material(
            material_id=mid,
            incident_id=incident_id,
            kind=kind,  # type: ignore[arg-type]
            path=_store_path(p),
            original_url=original_url,
            mime=r["mime"],
            size_bytes=r["size"],
            is_common_lib=common,
            parent_html=parent,
            meta=meta,
        )
        seen[mid] = m
        materials.append(m)

    # pages without their own URL inherit it from a capture manifest / mhtml in the same directory
    for m in materials:
        if m.kind == "html" and not m.original_url:
            donor = next((o for o in materials if o.kind in ("json", "mhtml") and o.original_url
                          and o.meta.get("page_dir") == m.meta.get("page_dir")), None)
            if donor:
                m.original_url = donor.original_url
                m.meta["url_source"] = f"sibling_{donor.kind}"

    # chain index only makes sense when there are several pages
    pages = [m for m in materials if m.kind in ("html", "mhtml")]
    if len({m.meta.get("chain_index") for m in pages}) <= 1:
        for m in materials:
            m.meta.pop("chain_index", None)

    kinds: dict[str, int] = {}
    for m in materials:
        kinds[m.kind] = kinds.get(m.kind, 0) + 1
    if not any(m.kind != "other" and m.size_bytes > 0 for m in materials):
        shown = ", ".join(r["rel"].as_posix() for r in rows[:3]) or "(pusty folder)"
        log.warning("ingest: %s: brak rozpoznanych materiałów (HTML/HAR/obraz/wideo/JSON), plik(i) pominięte "
                    "w analizie: %s", folder.name, shown)
    landing_urls = sorted({m.original_url for m in materials if m.original_url and m.kind in ("html", "mhtml")})
    meta = {
        "folder": folder.name,
        "n_materials": len(materials),
        "n_files": len(rows),
        "kinds": kinds,
        "n_pages": len(pages),
        "has_landing": bool(pages),
        "landing_urls": landing_urls,
        "ingest_s": round(time.time() - t0, 3),
    }
    if errors:
        meta["errors"] = errors
    return Incident(incident_id=incident_id, source=source, materials=materials, meta=meta)


def _folder_sort_key(name: str):
    return (0, int(name), "") if name.isdigit() else (1, 0, name.lower())


def load_incidents(root: Path, source: str = "nask", stop: dict[str, set[str]] | None = None) -> list[Incident]:
    """Each top-level folder of `root` is one Incident ('<source>:<folder>')."""
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"data folder not found: {root}")
    stop = stop or load_stoplist()
    folders = sorted((d for d in root.iterdir() if d.is_dir() and not d.name.startswith((".", "__"))),
                     key=lambda d: _folder_sort_key(d.name))
    out = []
    for d in folders:
        try:
            out.append(build_incident(d, f"{source}:{d.name}", source, stop))
        except Exception as exc:  # one broken folder must not stop the dataset
            log.exception("incident %s failed", d)
            out.append(Incident(incident_id=f"{source}:{d.name}", source=source, materials=[],
                                meta={"folder": d.name, "errors": [f"ingest failed: {exc}"]}))
    return out


# ------------------------------------------------------------------ uploads (UI "new material")

def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract a zip with zip-slip and zip-bomb protection."""
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_ZIP_TOTAL:
            raise ValueError(f"zip too large when unpacked ({total} bytes)")
        for info in zf.infolist():
            name = info.filename
            # macOS zips sometimes store UTF-8 names without the flag -> fix mojibake
            if not info.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest) + os.sep) and target != dest:
                raise ValueError(f"unsafe path in zip: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def load_upload(path: Path, data_dir: Path | None = None, incident_id: str | None = None,
                stop: dict[str, set[str]] | None = None) -> Incident:
    """Single new material for the UI: a folder, a single HTML/image/video file or a zip.

    Files are copied to data/interim/uploads/<id>/ so the original location does not matter.
    A zip that contains exactly one top-level folder is treated as that folder.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    data_dir = Path(data_dir) if data_dir else REPO_ROOT / "data"
    ts = time.strftime("%Y%m%dT%H%M%S")
    incident_id = incident_id or f"upload:{ts}"
    work = data_dir / "interim" / "uploads" / incident_id.replace(":", "_")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    if path.is_dir():
        shutil.copytree(path, work / path.name)
        folder = work / path.name
    elif zipfile.is_zipfile(path):
        _safe_extract(path, work)
        entries = [e for e in work.iterdir() if e.name not in ("__MACOSX",) and not e.name.startswith(".")]
        folder = entries[0] if len(entries) == 1 and entries[0].is_dir() else work
    else:
        shutil.copy2(path, work / path.name)
        folder = work
    inc = build_incident(folder, incident_id, "upload", stop)
    inc.meta["upload_name"] = path.name
    return inc


# ------------------------------------------------------------------ jsonl io

def write_jsonl(incidents: list[Incident], out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for inc in incidents:
            fh.write(json.dumps(asdict(inc), ensure_ascii=False) + "\n")
    tmp.replace(out)
    return out


def read_jsonl(path: Path) -> list[Incident]:
    """Inverse of write_jsonl: rebuild Incident/Material dataclasses."""
    out: list[Incident] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            mats = [Material(**m) for m in d.pop("materials", [])]
            out.append(Incident(materials=mats, **d))
    return out


def resolve_path(material: Material, repo_root: Path | None = None) -> Path:
    """Absolute path of a material file (Material.path is repo-relative when possible)."""
    p = Path(material.path)
    return p if p.is_absolute() else (repo_root or REPO_ROOT) / p
