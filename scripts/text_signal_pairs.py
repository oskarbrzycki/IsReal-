#!/usr/bin/env python3
"""Pairwise check of text signals before weights are set (owner: W2).

Reads data/features/text.parquet, aggregates material rows to incidents the same way
the engine does (CONTRACTS §4: sets = union, vectors = max over material pairs,
scalars = first non-empty) and prints, for every text signal, which incident pairs
it links and with what similarity. A signal that links (almost) every pair is noise
and needs a higher floor or a different type.

Output contains only incident ids, signal names and numbers - no page content.

Usage:
    python scripts/text_signal_pairs.py [--parquet data/features/text.parquet] [--out data/interim/text/signal_pairs.md]
                                        [--only all|page|ocr]   # ocr = records built from W3 OCR text
"""
from __future__ import annotations

import argparse
import itertools
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fakecollector.features.text import SIGNAL_CLASS, SIGNALS  # noqa: E402

LINK_SHARE_WARN = 0.5  # signal linking more than this share of all pairs -> flagged


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, (list, tuple, np.ndarray)):
        return len(v) == 0
    return v == ""


def aggregate(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    """incident_id -> {field: aggregated value}; vectors kept as a list of vectors."""
    out: dict[str, dict[str, object]] = {}
    for inc, g in df.groupby("incident_id"):
        agg: dict[str, object] = {}
        for sig in SIGNALS.values():
            field, typ = sig["field"], sig["type"]
            vals = [v for v in g[field].tolist() if not _is_empty(v)] if field in g else []
            if typ in ("cosine", "jaccard_minhash"):
                agg[field] = [np.asarray(v) for v in vals]
            elif typ == "set_overlap":
                agg[field] = set().union(*[set(v) for v in vals]) if vals else set()
            else:
                agg[field] = vals[0] if vals else None
        out[str(inc)] = agg
    return out


def similarity(typ: str, a, b) -> float | None:
    if typ == "cosine":
        if not a or not b:
            return None
        return max(float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-12)) for x in a for y in b)
    if typ == "jaccard_minhash":
        if not a or not b:
            return None
        return max(float(np.mean(x == y)) for x in a for y in b if len(x) == len(y))
    if typ == "set_overlap":
        if not a or not b:
            return None
        return len(a & b) / len(a | b)
    if typ == "exact":
        if a is None or b is None:
            return None
        return 1.0 if a == b else 0.0
    return None


def incident_table(df: pd.DataFrame) -> str:
    """incident -> materials, top entities, platform names, narrative types (no page content)."""
    lines = ["| incydent | rekordy | top encje | platform_name | narrative_type |", "|---|---:|---|---|---|"]
    for inc, g in sorted(df.groupby("incident_id"), key=lambda kv: (len(str(kv[0])), str(kv[0]))):
        ents = Counter(e for v in g["entities"] if not _is_empty(v) for e in v)
        plat = Counter(p for p in g["platform_name"] if not _is_empty(p))
        narr = Counter(n for n in g["narrative_type"] if not _is_empty(n))
        lines.append(f"| {inc} | {len(g)} | {', '.join(e for e, _ in ents.most_common(4)) or '—'} | "
                     f"{', '.join(p for p, _ in plat.most_common(2)) or '—'} | "
                     f"{', '.join(n for n, _ in narr.most_common(2)) or '—'} |")
    return "\n".join(lines)


def build_report(df: pd.DataFrame) -> str:
    inc = aggregate(df)
    ids = sorted(inc, key=lambda s: (len(s), s))
    pairs = list(itertools.combinations(ids, 2))
    none = {c: int(df[c].map(_is_empty).sum()) for c in ("text_emb", "minhash", "entities", "platform_name")
            if c in df.columns}
    lines = [f"# Text features - {len(df)} records, {len(ids)} incidents, {len(pairs)} pairs", "",
             "Empty values: " + ", ".join(f"{k}={v}" for k, v in none.items()), "",
             incident_table(df), "", "## Signals", ""]
    summary = ["| signal | class | type | floor | pairs with data | linked raw (>0) | linked after floor | "
               "share after floor | raw min / median / max |",
               "|---|---|---|---:|---:|---:|---:|---:|---|"]
    details = []
    for name, sig in SIGNALS.items():
        vals = []
        for a, b in pairs:
            s = similarity(sig["type"], inc[a][sig["field"]], inc[b][sig["field"]])
            if s is not None:
                vals.append((a, b, s))
        floor = float(sig.get("floor", 0.0))
        linked_raw = [v for v in vals if v[2] > 0]
        floored = [(a, b, max(0.0, (s - floor) / (1 - floor)) if floor else s) for a, b, s in vals]
        linked = [v for v in floored if v[2] > 0]
        share = len(linked) / len(pairs) if pairs else 0.0
        arr = np.array([v[2] for v in vals]) if vals else np.array([])
        stats = f"{arr.min():.2f} / {np.median(arr):.2f} / {arr.max():.2f}" if arr.size else "—"
        flag = " ⚠" if share > LINK_SHARE_WARN else ""
        summary.append(f"| {name}{flag} | {SIGNAL_CLASS.get(name, '?')} | {sig['type']} | {floor or '—'} | "
                       f"{len(vals)} | {len(linked_raw)} | {len(linked)} | {share:.0%} | {stats} |")
        details.append(f"## {name} ({sig['type']}, field `{sig['field']}`, floor {floor or '—'})")
        details.append("")
        if not vals:
            details.append("brak danych")
        else:
            raw = {(a, b): s for a, b, s in vals}
            top = sorted(floored, key=lambda v: (-v[2], -raw[(v[0], v[1])]))
            details.append(", ".join(f"{a}–{b}: {s:.2f} (raw {raw[(a, b)]:.2f})" for a, b, s in top if s > 0)
                           or "żadna para > 0 po floor")
        details.append("")
    return "\n".join(lines + summary + [""] + details)


def is_ocr_row(prov) -> bool:
    """Records built from W3 OCR carry an `ocr_text` provenance key."""
    if isinstance(prov, dict):
        return "ocr_text" in prov
    return isinstance(prov, str) and '"ocr_text"' in prov


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--parquet", default="data/features/text.parquet")
    ap.add_argument("--out", default="data/interim/text/signal_pairs.md")
    ap.add_argument("--only", choices=["all", "page", "ocr"], default="all")
    args = ap.parse_args(argv)
    df = pd.read_parquet(args.parquet)
    if args.only != "all" and "provenance" in df.columns:
        mask = df["provenance"].map(is_ocr_row)
        df = df[mask] if args.only == "ocr" else df[~mask]
        if df.empty:
            print(f"no {args.only} records in {args.parquet}", file=sys.stderr)
            return 1
    if "incident_id" not in df.columns:
        print("text.parquet has no incident_id column", file=sys.stderr)
        return 1
    report = build_report(df)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
