#!/usr/bin/env python3
"""Pairwise check of visual/faces signals before weights are set (owner: W3).

Uses the engine's own aggregation and similarity (fakecollector.engine.features / .similarity),
so the numbers are exactly what the correlator will see. For every signal of `visual` and
`faces` it prints which incident pairs it links, raw similarity (before `floor`) and the
rescaled score, split into pairs from the same working campaign (eval/labels.yaml) and pairs
from different campaigns. A signal that links (almost) every pair, or scores cross-campaign
pairs as high as same-campaign ones, needs a higher floor.

Variant "no shared files": records whose entity_id (sha1 of bytes) occurs in more than one
incident are dropped first, so identical copied files do not make the check circular
(CONTRACTS section 9).

Output: incident ids, signal names and numbers only - no content.

Usage:
  python scripts/visual_signal_pairs.py [--features data/features] [--out data/interim/visual/signal_pairs.md]
                                        [--floor visual_style=0.85 ...]
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fakecollector.engine.features import aggregate_incidents, collect_signals, load_feature_tables  # noqa: E402
from fakecollector.engine.similarity import compute  # noqa: E402
from fakecollector.features import faces as faces_mod  # noqa: E402
from fakecollector.features import visual as visual_mod  # noqa: E402

MODULES = ["visual", "faces"]
SIGNAL_CLASS = {**visual_mod.SIGNAL_CLASS, **faces_mod.SIGNAL_CLASS}
LINK_SHARE_WARN = 0.5


def load_labels(path: Path) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    out: dict[str, str] = {}
    for cid, members in (raw.get("campaigns") or {}).items():
        for m in members:
            out[str(m)] = str(cid)
    for m in raw.get("singletons") or []:
        out[str(m)] = f"single:{m}"
    return out


def drop_shared_files(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    for name, df in tables.items():
        base = df["entity_id"].astype(str).str.split("#").str[0]
        n_inc = df.assign(_b=base).groupby("_b")["incident_id"].nunique()
        shared = set(n_inc[n_inc > 1].index)
        out[name] = df[~base.isin(shared)].reset_index(drop=True)
    return out


def pair_rows(agg: dict, signals: dict, labels: dict[str, str]) -> list[dict]:
    ids = sorted(agg, key=lambda s: (len(s), s))
    rows = []
    for a, b in itertools.combinations(ids, 2):
        same = labels.get(a) is not None and labels.get(a) == labels.get(b)
        for name, spec in signals.items():
            score, ev = compute(spec, agg[a].get(name), agg[b].get(name))
            if score is None:
                continue
            rows.append({"signal": name, "a": a, "b": b, "same": same, "score": float(score),
                         "raw": float(ev.get("raw", score)), "shared": ev.get("shared")})
    return rows


def _stats(vals: list[float]) -> str:
    if not vals:
        return "—"
    arr = np.asarray(vals)
    return f"{arr.min():.2f} / {np.median(arr):.2f} / {arr.max():.2f}"


def summarize(rows: list[dict], signals: dict, n_pairs: int, title: str) -> list[str]:
    lines = [f"### {title}", "",
             "| signal | class | type | floor | pairs w/ data | linked (>0) | share of all | "
             "same-camp linked | cross-camp linked | raw same: min/med/max | raw cross: min/med/max |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for name, spec in signals.items():
        r = [x for x in rows if x["signal"] == name]
        linked = [x for x in r if x["score"] > 0]
        share = len(linked) / n_pairs if n_pairs else 0.0
        same = [x for x in r if x["same"]]
        cross = [x for x in r if not x["same"]]
        flag = " ⚠" if share > LINK_SHARE_WARN else ""
        lines.append(
            f"| {name}{flag} | {SIGNAL_CLASS.get(name, 'campaign')} | {spec['type']} | {spec.get('floor', '—')} | "
            f"{len(r)} | {len(linked)} | {share:.0%} | {sum(x['score'] > 0 for x in same)}/{len(same)} | "
            f"{sum(x['score'] > 0 for x in cross)}/{len(cross)} | {_stats([x['raw'] for x in same])} | "
            f"{_stats([x['raw'] for x in cross])} |")
    lines.append("")
    return lines


def details(rows: list[dict], signals: dict) -> list[str]:
    out = []
    for name, spec in signals.items():
        r = sorted([x for x in rows if x["signal"] == name and x["score"] > 0], key=lambda x: -x["score"])
        out.append(f"#### {name} (`{spec['field']}`, {spec['type']}, floor {spec.get('floor', '—')})")
        out.append("")
        if not r:
            out.append("żadna para > 0")
        else:
            out.append(", ".join(
                f"{x['a'].split(':')[-1]}–{x['b'].split(':')[-1]}{'' if x['same'] else '✗'}: "
                f"{x['score']:.2f} (raw {x['raw']:.2f})" for x in r))
        out.append("")
    out.append("✗ = para z różnych kampanii roboczych (eval/labels.yaml)")
    return out


def build_report(features_dir: Path, labels_path: Path, floors: dict[str, float]) -> str:
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
    params = dict((settings.get("engine") or {}).get("signal_params") or {})
    for k, v in floors.items():
        params.setdefault(k, {})
        params[k] = {**params[k], "floor": v}
    signals = collect_signals(params, only_modules=MODULES)
    tables = load_feature_tables(features_dir, MODULES)
    labels = load_labels(labels_path)
    lines = [f"# Visual + faces signals - incident pairs", "",
             f"Tables: {', '.join(f'{k} ({len(v)} rows)' for k, v in tables.items())}. "
             f"Floors overridden: {floors or 'none'}.", ""]
    det = []
    for title, tabs in (("all records", tables), ("no shared files (identical sha1 across incidents dropped)",
                                                  drop_shared_files(tables))):
        agg = aggregate_incidents(tabs, signals)
        n = len(agg)
        rows = pair_rows(agg, signals, labels)
        lines += summarize(rows, signals, n * (n - 1) // 2, f"{title}: {n} incidents, {n * (n - 1) // 2} pairs")
        if not det:
            det = details(rows, signals)
    return "\n".join(lines + ["## Linked pairs (all records)", ""] + det)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--features", default=str(ROOT / "data" / "features"))
    ap.add_argument("--labels", default=str(ROOT / "eval" / "labels.yaml"))
    ap.add_argument("--out", default=str(ROOT / "data" / "interim" / "visual" / "signal_pairs.md"))
    ap.add_argument("--floor", action="append", default=[], help="signal=value, overrides floor")
    args = ap.parse_args(argv)
    floors = {k: float(v) for k, v in (x.split("=", 1) for x in args.floor)}
    report = build_report(Path(args.features), Path(args.labels), floors)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
