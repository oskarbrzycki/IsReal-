#!/usr/bin/env python3
"""Prepare the three live-demo "new material" cases in data/demo/ (owner: W3).

  python scripts/demo_cases.py [--raw data/raw/nask] [--out data/demo] [--holdout 47] [--no-base]

Creates (all under data/, never committed):
  data/demo/folder2_bez_har.zip          copy of incident 2 without *.har  -> expected: campaign C001 {1,2}
                                         (docs/DEMO_SCRIPT.md: demo mode "exclude nask:2")
  data/demo/folder47.zip                 incident 47 as a whole            -> expected: "nowa kampania"
                                         (UI demo mode "exclude nask:47", or the base below)
  data/demo/case_c_reklama48.zip         only the ad screenshot of 48      -> expected: campaign B {48,61}
                                         or at least its family (face/visual signals)
  data/demo/base_bez_47/                 the dataset without the hold-out folder, made of hard links
                                         (no extra disk space; falls back to copies)

Alternative for case (b) without the UI demo mode, a base without 47:
  python -m fakecollector ingest --data data/demo/base_bez_47
  python -m fakecollector features --module all
  python -m fakecollector correlate
  python -m fakecollector analyze data/demo/folder47.zip
File names and zip layout match docs/DEMO_SCRIPT.md (top-level folder "2" / "47"), which
`load_upload` treats as one incident. Files are only copied, never opened or executed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def zip_folder(src: Path, out: Path, arc_root: str, skip=lambda p: False) -> int:
    """Zip `src` recursively under the top-level folder `arc_root`. Returns number of files."""
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file() and not skip(p):
                zf.write(p, f"{arc_root}/{p.relative_to(src).as_posix()}")
                n += 1
    return n


def ad_screenshot(folder: Path) -> Path:
    """The ad image of an incident: a top-level raster file (not inside a *_files page folder)."""
    cands = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT]
    if not cands:
        raise FileNotFoundError(f"no top-level ad image in {folder}")
    return max(cands, key=lambda p: p.stat().st_size)


def link_tree(src: Path, dst: Path) -> str:
    """Mirror `src` into `dst` with hard links (same volume), falling back to copies."""
    mode = "hardlink"
    for p in src.rglob("*"):
        target = dst / p.relative_to(src)
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        try:
            os.link(p, target)
        except OSError:
            shutil.copy2(p, target)
            mode = "copy"
    return mode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw" / "nask"))
    ap.add_argument("--out", default=str(ROOT / "data" / "demo"))
    ap.add_argument("--holdout", default="47", help="folder used as the 'new campaign' case")
    ap.add_argument("--no-base", action="store_true", help="do not build base_bez_<holdout>/")
    args = ap.parse_args(argv)
    raw, out = Path(args.raw), Path(args.out)
    for f in ("2", "48", args.holdout):
        if not (raw / f).is_dir():
            print(f"missing folder {raw / f}", file=sys.stderr)
            return 1
    out.mkdir(parents=True, exist_ok=True)

    n_a = zip_folder(raw / "2", out / "folder2_bez_har.zip", "2",
                     skip=lambda p: p.suffix.lower() == ".har")
    n_b = zip_folder(raw / args.holdout, out / f"folder{args.holdout}.zip", args.holdout)
    ad = ad_screenshot(raw / "48")
    c_out = out / "case_c_reklama48.zip"
    with zipfile.ZipFile(c_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(ad, f"case_c_reklama48/reklama{ad.suffix.lower()}")
    print(f"case a: {out / 'folder2_bez_har.zip'} ({n_a} files, HAR removed)")
    print(f"case b: {out / f'folder{args.holdout}.zip'} ({n_b} files)")
    print(f"case c: {c_out} (1 file: ad screenshot of 48)")

    if not args.no_base:
        base = out / f"base_bez_{args.holdout}"
        modes = {link_tree(d, base / d.name) for d in sorted(raw.iterdir())
                 if d.is_dir() and d.name != args.holdout}
        print(f"base without {args.holdout}: {base} ({', '.join(sorted(modes))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
