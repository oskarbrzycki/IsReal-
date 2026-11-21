#!/usr/bin/env python3
"""Reference run: ingest -> features all -> correlate -> evaluate, with timing, errors and a summary table.

    python scripts/reference_run.py                 # offline, data/raw/nask
    python scripts/reference_run.py --online        # allow OSINT lookups (RDAP/DNS/crt.sh) in `features`
    python scripts/reference_run.py --skip-ingest   # reuse data/interim/incidents.jsonl

Each step runs as the normal CLI (`python -m fakecollector ...`), so what is measured is exactly what a
user would run. The summary (campaign P/R/F1/ARI, family F1/ARI, open-set, pseudo-variants, robustness)
is printed and saved as reports/reference_run_<timestamp>.md (numbers only, safe for the repo).
The official numbers for RESULTS_SUMMARY.md come from running this on the reference machine (full
feature set: CLIP + OCR).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- running steps
def run_step(name: str, cmd: list[str], env: dict[str, str]) -> dict[str, Any]:
    """Run one CLI step; returns {name, ok, seconds, returncode, output}."""
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    return {"name": name, "ok": proc.returncode == 0, "returncode": proc.returncode,
            "seconds": round(time.time() - t0, 1), "output": (proc.stdout or "") + (proc.stderr or "")}


def parse_ingest(text: str) -> dict[str, Any]:
    """'ingest: 10 incidents, 313 materials, 0 with errors -> ...'"""
    m = re.search(r"ingest:\s*(\d+)\s+incidents?,\s*(\d+)\s+materials?,\s*(\d+)\s+with errors", text)
    return {"incidents": int(m[1]), "materials": int(m[2]), "errors": int(m[3])} if m else {}


def parse_features(text: str) -> list[dict[str, Any]]:
    """One JSON object per module is printed by `features` (module, records, with_errors, seconds...)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and '"module"' in line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def newest_eval_json(since: float) -> Path | None:
    files = [p for p in (REPO / "reports").glob("eval_*.json") if p.stat().st_mtime >= since]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


# --------------------------------------------------------------------------- rendering
def table(rows: list[list[Any]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def pct(x: Any) -> str:
    return "-" if x is None else f"{100 * float(x):.0f}%"


def num(x: Any) -> str:
    return "-" if x is None else f"{float(x):.2f}"


def render_metrics(s: dict[str, Any]) -> str:
    """The summary table from the evaluation numbers (eval_*.json)."""
    c, f = s["campaign"], s["family"]
    pv, dr, os_ = s.get("pseudo_variants", {}), s.get("dropout", {}), s.get("open_set", {})
    no_ident = next((r for r in s.get("ablation", []) if r["variant"].startswith("without identical-file")), None)
    rows = [
        ["Kampanie: precyzja / recall", f"{num(c['precision'])} / {num(c['recall'])}", f"fałszywe połączenia: {c['fp']}"],
        ["Kampanie: F1 / ARI", f"{num(c['f1'])} / {num(c['ari'])}", f"{s['n_incidents']} incydentów, {c['n_clusters']} kampanii"],
        ["Rodziny: F1 / ARI", f"{num(f['f1'])} / {num(f['ari'])}", f"precyzja {num(f['precision'])}, recall {num(f['recall'])}"],
    ]
    if no_ident:
        rows.append(["Bez sygnałów „identyczne pliki”: F1 kampanii / rodzin", f"{num(no_ident['f1'])} / {num(no_ident['fam_f1'])}",
                     "wynik bez błędnego koła z etykietami"])
    rows += [
        ["Open-set: kampania spoza bazy rozpoznana jako nowa", pct(os_.get("loco_new_rate")), f"n={os_.get('loco_n')}"],
        ["Open-set: nowa kampania przypisana do właściwej rodziny", pct(os_.get("loco_family_hit_rate")), f"n={os_.get('loco_family_n')}"],
        ["Przypisanie incydentu do znanej kampanii (leave-one-out)", pct(os_.get("loo_assign_accuracy")), f"n={os_.get('loo_assign_n')}"],
        ["Singletony rozpoznane jako nowe", pct(os_.get("loo_singleton_new_rate")), f"n={os_.get('loo_singleton_n')}"],
        ["Pseudo-warianty: pary z jednego incydentu wracają razem", pct(pv.get("sibling_recall")),
         f"{pv.get('n_pseudo_incidents', '-')} części z {pv.get('n_split_incidents', '-')} incydentów; F1 {num(pv.get('f1'))}"],
        ["Odporność na braki (30% modalności): F1 średnio / minimum", f"{num(dr.get('f1_mean'))} / {num(dr.get('f1_min'))}",
         f"{dr.get('trials')} prób"],
    ]
    fv = s.get("family_variant")
    if fv:
        cur, pos = fv["current"], fv["positive_only"]
        rows += [
            ["Wariant „family tylko na plus”: precyzja / recall rodzin (obecny → wariant)",
             f"{num(cur['family_precision'])} / {num(cur['family_recall'])} → {num(pos['family_precision'])} / {num(pos['family_recall'])}",
             f"fałszywe krawędzie rodzin: {len(cur['false_family_edges'])} → {len(pos['false_family_edges'])}"],
            ["Wariant: nowa kampania → właściwa rodzina (obecny → wariant)",
             f"{pct(cur['loco_family_hit_rate'])} → {pct(pos['loco_family_hit_rate'])}",
             f"warunki przyjęcia spełnione: {'TAK' if fv['conditions_met'] else 'NIE: ' + ', '.join(k for k, v in fv['conditions'].items() if not v)}"],
        ]
    return table(rows, ["Metryka", "Wartość", "Uwagi"])


def render(steps: list[dict[str, Any]], notes: dict[str, Any], features: list[dict[str, Any]],
           summary: dict[str, Any] | None, stamp: str, online: bool) -> str:
    srows = []
    for st in steps:
        srows.append([st["name"], "OK" if st["ok"] else f"BŁĄD (kod {st['returncode']})", f"{st['seconds']} s",
                      notes.get(st["name"], "")])
    parts = [f"# Przebieg referencyjny ({stamp})\n",
             f"Tryb: {'online (OSINT)' if online else 'offline'}. Python {sys.version.split()[0]}.\n",
             "## Kroki\n", table(srows, ["Krok", "Status", "Czas", "Uwagi"]) + "\n"]
    if features:
        frows = [[r.get("module"), r.get("records"), r.get("with_errors"), r.get("skipped", ""), r.get("seconds")]
                 for r in features]
        parts += ["## Moduły cech\n", table(frows, ["Moduł", "Rekordy", "Z błędami", "Pominięte", "Czas [s]"]) + "\n"]
        bad = [r["module"] for r in features if r.get("with_errors")]
        if bad:
            parts.append(f"Moduły z błędami na rekordach: {', '.join(bad)} (np. brak CLIP/OCR na tej maszynie).\n")
    if summary:
        parts += ["## Wyniki\n", render_metrics(summary) + "\n"]
    else:
        parts.append("## Wyniki\n\nBrak (ewaluacja nie zakończyła się albo wcześniejszy krok się nie powiódł).\n")
    return "\n".join(parts)


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/raw/nask", help="dataset root for ingest")
    ap.add_argument("--online", action="store_true", help="allow OSINT lookups in the features step")
    ap.add_argument("--skip-ingest", action="store_true", help="reuse data/interim/incidents.jsonl")
    ap.add_argument("--no-save", action="store_true", help="print only, do not write reports/reference_run_*.md")
    args = ap.parse_args(argv)

    env = dict(os.environ)
    py = sys.executable
    started = time.time()
    plan = []
    if not args.skip_ingest:
        plan.append(("ingest", [py, "-m", "fakecollector", "ingest", "--data", args.data]))
    plan += [("features", [py, "-m", "fakecollector", "features", "--module", "all",
                           "--online" if args.online else "--offline"]),
             ("correlate", [py, "-m", "fakecollector", "correlate"]),
             ("evaluate", [py, "-m", "fakecollector", "evaluate"])]

    steps, notes, features = [], {}, []
    for name, cmd in plan:
        print(f"[{name}] ...", flush=True)
        st = run_step(name, cmd, env)
        steps.append(st)
        if name == "ingest":
            info = parse_ingest(st["output"])
            notes[name] = f"{info.get('incidents', '?')} incydentów, {info.get('materials', '?')} plików, {info.get('errors', '?')} z błędami" if info else ""
        elif name == "features":
            features = parse_features(st["output"])
            n_err = sum(int(r.get("with_errors") or 0) for r in features)
            notes[name] = f"{len(features)} modułów, {n_err} rekordów z błędami"
        print(f"[{name}] {'OK' if st['ok'] else 'BŁĄD'} ({st['seconds']} s)", flush=True)
        if not st["ok"]:
            print(st["output"][-1500:], file=sys.stderr)
            break

    ej = newest_eval_json(started - 1) if all(s["ok"] for s in steps) else None
    summary = json.loads(ej.read_text(encoding="utf-8")) if ej else None
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = render(steps, notes, features, summary, stamp, args.online)
    print("\n" + text)
    if not args.no_save:
        out = REPO / "reports" / f"reference_run_{datetime.now():%Y%m%d_%H%M%S}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"\nZapisano: {out.relative_to(REPO)}")
    return 0 if all(s["ok"] for s in steps) and summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
