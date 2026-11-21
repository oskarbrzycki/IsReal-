"""Leak check: does anything from the organizer's data sit in git? (owner W4)

R1: the NASK material may be used for the challenge only and must not be
published. This script builds an in-memory list of "sensitive tokens" from the
LOCAL data and searches every git-tracked file (and, with --commits, every
commit message) for them.

Sensitive tokens (never written anywhere, only held in memory):
  domain  - full hosts and eTLD+1 from data/features/infra.parquet and
            html_struct.parquet (stop-listed / generic networks excluded)
  id      - pixel / tag / ad-account / ad_id / page_id numbers, 8+ digits
  title   - page titles of 15+ characters (html_struct, incidents.jsonl)
  file    - distinctive file names from data/raw/nask/ (generic ones excluded)

Masked forms are fine and are not reported: "domain[.]tld", values cut with
"…" (or "..."), N-patterns like "IMG_N.PNG". Images cannot be searched, so they
are listed for manual review.

Usage:
    python scripts/leak_check.py                 # working tree, print findings
    python scripts/leak_check.py --ref origin/main --commits
    python scripts/leak_check.py --redact        # mask tokens in the output (safe to paste)

Exit code: 0 = clean, 1 = something found, 2 = no local data to build tokens from.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fakecollector.features import infra  # noqa: E402  (eTLD+1, stoplist, adtech list)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg", ".tif", ".tiff"}
BINARY_EXT = {".parquet", ".sqlite", ".zip", ".gz", ".pdf", ".mp4", ".onnx", ".bin", ".npz", ".pt"}
ELLIPSES = ("…", "...")

#: File names that say nothing about a campaign (case-insensitive, matched on the stem).
GENERIC_STEMS = re.compile(
    r"^(index|page|dom|main|style|styles|script|scripts|app|bundle|vendor|manifest|screenshot"
    r"|logo|favicon|icon|icons|avatar|banner|hero|image|img|photo|video|output|segment|seg\d*"
    r"|saved_resource(\(\d+\))?|jquery.*|fbevents.*|bootstrap.*|swiper.*|lazysizes.*|gtm.*"
    r"|analytics.*|all\.min|font-awesome.*|cleardot|loading|search|close|arrow.*|back-nav"
    r"|element|css2?|vt(\(\d+\))?|m=.*|\d{1,3}x\d{1,4}(\(\d+\))?|img_\d+|\d+|[0-9a-f]{6,}"
    r"|.*\.(min)|reklama_\d+|strona_\d+|news\d*|ava-coment\d*|education.*|\.?har)$",
    re.IGNORECASE,
)
GENERIC_SUFFIXES = (".pobrane", ".pobierz")
MIN_FILE_STEM = 10
MIN_TITLE = 15
MIN_ID_DIGITS = 8
TITLE_PREFIX = 30  # a quoted prefix this long is already a leak unless it ends in "…"


@dataclass(frozen=True)
class Finding:
    where: str          # path:line or commit:<sha>
    token: str
    kind: str


# ----------------------------------------------------------------------------- tokens

def _as_list(value) -> list:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [value]
        except ValueError:
            return [value]
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _host(url: str) -> str | None:
    match = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#:\s]+)", str(url).strip(), re.IGNORECASE)
    return match.group(1).lower().strip(".") if match else None


def _generic(domain: str, stop: dict) -> bool:
    return infra._is_generic_domain(domain, stop) or infra._is_adtech(domain)


def collect_tokens(repo_root: Path) -> dict[str, str]:
    """{token: kind} built from local data only. Never persisted."""
    import pandas as pd

    stop = infra._load_stoplist(None)
    tokens: dict[str, str] = {}
    features = repo_root / "data" / "features"

    def add_domain(raw: str | None) -> None:
        if not raw:
            return
        raw = str(raw).strip().lower().strip(".")
        host = _host(raw) or raw
        if "." not in host or " " in host or len(host) < 4:
            return
        for candidate in {host, infra._etld1(host) or ""}:
            if candidate and "." in candidate and not _generic(candidate, stop):
                tokens.setdefault(candidate, "domain")

    def add_ids(text: str | None) -> None:
        for digits in re.findall(rf"(?<!\d)\d{{{MIN_ID_DIGITS},}}(?!\d)", str(text or "")):
            tokens.setdefault(digits, "id")

    def add_title(text: str | None) -> None:
        title = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(title) >= MIN_TITLE:
            tokens.setdefault(title, "title")

    infra_path = features / "infra.parquet"
    if infra_path.is_file():
        df = pd.read_parquet(infra_path)
        for col in ("landing_domains", "har_domains", "redirect_chain", "streams", "cert_san"):
            if col in df:
                for value in df[col]:
                    for item in _as_list(value):
                        add_domain(item)
        for col in ("har_tracker_ids", "ad_account_ids", "ad_params"):
            if col in df:
                for value in df[col]:
                    for item in _as_list(value):
                        add_ids(item)
        if "page_title" in df:
            for value in df["page_title"].dropna():
                add_title(value)

    html_path = features / "html_struct.parquet"
    if html_path.is_file():
        df = pd.read_parquet(html_path)
        for col in ("original_url",):
            if col in df:
                for value in df[col].dropna():
                    add_domain(value)
                    add_ids(value)
        for col in ("external_domains", "script_srcs", "form_actions"):
            if col in df:
                for value in df[col]:
                    for item in _as_list(value):
                        add_domain(item)
        if "tracker_ids" in df:
            for value in df["tracker_ids"]:
                for item in _as_list(value):
                    add_ids(item)
        if "title" in df:
            for value in df["title"].dropna():
                add_title(value)

    incidents = repo_root / "data" / "interim" / "incidents.jsonl"
    if incidents.is_file():
        for line in incidents.read_text(encoding="utf-8").splitlines():
            try:
                inc = json.loads(line)
            except ValueError:
                continue
            for url in (inc.get("meta") or {}).get("landing_urls") or []:
                add_domain(url)
                add_ids(url)
            for mat in inc.get("materials") or []:
                add_domain(mat.get("original_url"))
                add_ids(mat.get("original_url"))
                title = (mat.get("meta") or {}).get("title")
                add_title(title)

    raw = repo_root / "data" / "raw" / "nask"
    if raw.is_dir():
        for _dirpath, _dirs, files in os.walk(raw):
            for name in files:
                stem = name
                for suffix in GENERIC_SUFFIXES:
                    if stem.lower().endswith(suffix):
                        stem = stem[: -len(suffix)]
                if stem.lower().endswith(".har") and len(stem) > 4:
                    add_domain(stem[:-4])           # HAR named after the scam domain
                    continue
                stem = Path(stem).stem if "." in stem[1:] else stem
                add_ids(stem)
                if len(stem) >= MIN_FILE_STEM and not GENERIC_STEMS.match(stem):
                    tokens.setdefault(stem, "file")
    return tokens


# ----------------------------------------------------------------------------- search

def _patterns(tokens: dict[str, str]) -> list[tuple[re.Pattern, str, str]]:
    out = []
    for token, kind in tokens.items():
        if kind == "id":
            pattern = rf"(?<!\d){re.escape(token)}(?!\d)"
        elif kind == "domain":
            pattern = rf"(?<![A-Za-z0-9-]){re.escape(token)}(?![A-Za-z0-9-])"
        elif kind == "title":
            # Whitespace-tolerant; a prefix is checked separately in _title_hits.
            pattern = r"\s+".join(re.escape(p) for p in token.split(" "))
        else:
            pattern = re.escape(token)
        out.append((re.compile(pattern, re.IGNORECASE), token, kind))
    return out


def _title_hits(text: str, title: str) -> bool:
    """A title prefix counts unless the quoted part is cut with an ellipsis."""
    prefix = title[:TITLE_PREFIX]
    if len(prefix) < TITLE_PREFIX:
        return False
    low_text, low_title = text.lower(), title.lower()
    start = low_text.find(prefix.lower())
    while start != -1:
        end = start + len(prefix)
        # extend as long as the text keeps following the title
        while end < len(low_text) and end - start < len(low_title) and low_text[end] == low_title[end - start]:
            end += 1
        if end - start >= len(low_title):
            return True                               # the full title is there
        if not low_text.startswith(ELLIPSES, end):
            return True                               # long unmasked prefix
        start = low_text.find(prefix.lower(), end)
    return False


def scan_text(where: str, text: str, patterns) -> list[Finding]:
    findings: list[Finding] = []
    titles = [(t, k) for _p, t, k in patterns if k == "title"]
    for lineno, line in enumerate(text.splitlines(), start=1):
        for regex, token, kind in patterns:
            if kind == "title":
                continue
            if regex.search(line):
                findings.append(Finding(f"{where}:{lineno}", token, kind))
        for title, kind in titles:
            if _title_hits(line, title):
                findings.append(Finding(f"{where}:{lineno}", title, kind))
    return findings


def _git(args: list[str], repo_root: Path) -> bytes:
    return subprocess.run(["git", *args], cwd=repo_root, check=True,
                          capture_output=True).stdout


def resolve_ref(repo_root: Path, ref: str) -> str | None:
    """`main` may exist only as origin/main on a feature-branch checkout."""
    for candidate in (ref, f"origin/{ref}"):
        result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{tree}}"],
                                cwd=repo_root, capture_output=True)
        if result.returncode == 0:
            return candidate
    return None


def tracked_files(repo_root: Path, ref: str | None) -> list[str]:
    if ref:
        raw = _git(["ls-tree", "-r", "-z", "--name-only", ref], repo_root)
    else:
        raw = _git(["ls-files", "-z"], repo_root)
    return [p for p in raw.decode("utf-8").split("\0") if p]


def read_file(repo_root: Path, path: str, ref: str | None) -> bytes:
    if ref:
        return _git(["cat-file", "blob", f"{ref}:{path}"], repo_root)
    return (repo_root / path).read_bytes()


def redact(token: str) -> str:
    if len(token) <= 6:
        return token[0] + "…"
    return f"{token[:3]}…{token[-2:]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Search git for organizer data (R1).")
    parser.add_argument("--ref", default=None, help="scan a git ref (e.g. origin/main) instead of the working tree")
    parser.add_argument("--commits", action="store_true", help="also scan commit messages of the ref / HEAD")
    parser.add_argument("--redact", action="store_true", help="mask tokens in the output")
    parser.add_argument("--summary", action="store_true", help="counts per file and type only, no tokens")
    args = parser.parse_args()

    if args.ref:
        resolved = resolve_ref(REPO_ROOT, args.ref)
        if resolved is None:
            print(f"leak_check: unknown git ref '{args.ref}' (also tried origin/{args.ref}); "
                  f"run `git fetch` first")
            return 2
        if resolved != args.ref:
            print(f"leak_check: '{args.ref}' is not a local branch, using {resolved}")
        args.ref = resolved

    tokens = collect_tokens(REPO_ROOT)
    if not tokens:
        print("leak_check: no local data (data/features, data/interim, data/raw/nask) - nothing to check against.")
        return 2
    kinds: dict[str, int] = {}
    for kind in tokens.values():
        kinds[kind] = kinds.get(kind, 0) + 1
    patterns = _patterns(tokens)

    findings: list[Finding] = []
    images: list[str] = []
    skipped_binary: list[str] = []
    files = tracked_files(REPO_ROOT, args.ref)
    this_file = "scripts/leak_check.py"
    for path in files:
        ext = Path(path).suffix.lower()
        if ext in IMAGE_EXT and ext != ".svg":
            images.append(path)
            continue
        try:
            data = read_file(REPO_ROOT, path, args.ref)
        except (OSError, subprocess.CalledProcessError):
            continue
        if ext in BINARY_EXT or b"\0" in data[:8192]:
            skipped_binary.append(path)
            continue
        text = data.decode("utf-8", errors="replace")
        hits = scan_text(path, text, patterns)
        if path == this_file:
            hits = [h for h in hits if h.kind != "file"]  # regex literals, not data
        findings.extend(hits)

    if args.commits:
        log = _git(["log", "--format=%H%x1f%B%x1e", args.ref or "HEAD"], REPO_ROOT).decode("utf-8", "replace")
        for entry in log.split("\x1e"):
            if "\x1f" not in entry:
                continue
            sha, body = entry.strip().split("\x1f", 1)
            for f in scan_text(f"commit:{sha[:9]}", body, patterns):
                findings.append(f)

    target = args.ref or "working tree"
    print(f"leak_check: {len(tokens)} tokens from local data "
          f"({', '.join(f'{k}={v}' for k, v in sorted(kinds.items()))}); "
          f"{len(files)} tracked files in {target}"
          + ("; commit messages included" if args.commits else ""))

    unique = sorted(set(findings), key=lambda f: (f.where.split(":")[0], int(f.where.rsplit(":", 1)[1]) if f.where.rsplit(":", 1)[1].isdigit() else 0, f.token))
    if args.summary:
        per_file: dict[str, dict[str, int]] = {}
        for f in unique:
            name = f.where.rsplit(":", 1)[0] if not f.where.startswith("commit:") else "(commit messages)"
            per_file.setdefault(name, {}).setdefault(f.kind, 0)
            per_file[name][f.kind] += 1
        for name, counts in sorted(per_file.items()):
            print(f"  {name}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    else:
        for f in unique:
            shown = redact(f.token) if args.redact else f.token
            print(f"{f.where}: {shown} ({f.kind})")

    if images:
        print(f"\nimages to review by hand ({len(images)}):")
        for path in images:
            print(f"  {path}")
    if skipped_binary:
        print(f"\nother binary files not searched ({len(skipped_binary)}): {', '.join(skipped_binary)}")

    files_hit = {f.where.rsplit(':', 1)[0] for f in unique}
    print(f"\nRESULT: {len(unique)} finding(s) in {len(files_hit)} place(s)"
          + (" - LEAK" if unique else " - clean"))
    return 1 if unique else 0


if __name__ == "__main__":
    raise SystemExit(main())
