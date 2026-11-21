#!/usr/bin/env python3
"""Import a sample of PhreshPhish phishing pages as incidents for an external test (owner: W3).

Dataset: phreshphish/phreshphish on Hugging Face, licence CC BY 4.0, for anti-phishing research.
See docs/EXTERNAL_TEST.md for citation, method and results.

  python scripts/import_phreshphish.py [--n 300] [--max-brands 30] [--per-brand 30] [--out data_ext]

What it does (static only - pages are never rendered, no URL from the dataset is ever requested):
  1. downloads parquet shards of the *test* split one by one (data/test-000.parquet, -001, ...)
     into <out>/hf/ via huggingface_hub, reading first only the metadata columns (no HTML);
  2. keeps rows with label == "phish" and a real brand in `target` (generic labels such as
     "other", "generic*" are dropped: they are not brands and would distort brand purity);
     duplicates by `sha256` are dropped;
  3. picks the `--max-brands` most frequent brands and takes pages round-robin (one per brand per
     round, at most `--per-brand` each) until `--n`, so the sample covers as many brands as possible;
  4. writes each page as one incident:  <out>/raw/nask/<k>/page.html
     and its metadata OUTSIDE the incident folder: <out>/meta/<k>.json  {target, date, lang, url}.
     Keeping meta.json out of the folder matters: the loader would ingest it as a `json` material and
     the text module would read the brand label (`target`) -> label leakage into the features.

Use the result only with DATA_DIR=<out> in the current shell session, e.g. (PowerShell)
  $env:DATA_DIR="data_ext"
  python -m fakecollector ingest --data data_ext/raw/nask --source phreshphish --out data_ext/interim/incidents.jsonl
`ingest` does not follow DATA_DIR for its defaults, so --data and --out must be given explicitly.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASET = "phreshphish/phreshphish"
META_COLS = ["sha256", "label", "target", "date", "lang"]
GENERIC_TARGETS = {"", "other", "unknown", "none", "null", "n/a"}


def is_brand(target: str) -> bool:
    t = (target or "").strip().lower()
    return t not in GENERIC_TARGETS and not t.startswith("generic")


def shard_names() -> list[str]:
    from huggingface_hub import HfApi
    info = HfApi().dataset_info(DATASET)
    return sorted(s.rfilename for s in info.siblings
                  if s.rfilename.startswith("data/test-") and s.rfilename.endswith(".parquet"))


def fetch(name: str, out: Path) -> Path:
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(DATASET, name, repo_type="dataset", local_dir=str(out / "hf")))


def candidates(path: Path) -> list[dict]:
    import pyarrow.parquet as pq
    t = pq.read_table(path, columns=META_COLS).to_pylist()
    rows = []
    for i, r in enumerate(t):
        if str(r.get("label", "")).strip().lower() == "phish" and is_brand(str(r.get("target") or "")):
            rows.append({**r, "target": str(r["target"]).strip(), "_shard": path, "_row": i})
    return rows


def select(rows: list[dict], n: int, max_brands: int, per_brand: int) -> list[dict]:
    seen, uniq = set(), []
    for r in rows:
        if r["sha256"] in seen:
            continue
        seen.add(r["sha256"])
        uniq.append(r)
    top = [b for b, _ in Counter(r["target"] for r in uniq).most_common(max_brands)]
    queues = {b: [r for r in uniq if r["target"] == b][:per_brand] for b in top}
    picked: list[dict] = []
    while len(picked) < n and any(queues.values()):     # round-robin: as many brands as possible
        for b in top:
            if queues[b] and len(picked) < n:
                picked.append(queues[b].pop(0))
    return picked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--max-brands", type=int, default=30)
    ap.add_argument("--per-brand", type=int, default=30)
    ap.add_argument("--out", default=str(REPO / "data_ext"))
    ap.add_argument("--max-shards", type=int, default=4, help="safety limit on downloaded test shards")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    if out == (REPO / "data").resolve() or (REPO / "data").resolve() in out.parents:
        print("refusing to write into data/ (NASK data); use a separate folder such as data_ext/", file=sys.stderr)
        return 2

    rows: list[dict] = []
    used = []
    for name in shard_names()[: args.max_shards]:
        path = fetch(name, out)
        used.append(name)
        rows += candidates(path)
        if len(select(rows, args.n, args.max_brands, args.per_brand)) >= args.n:
            break
    picked = select(rows, args.n, args.max_brands, args.per_brand)
    if not picked:
        print("no phishing rows with a brand target found", file=sys.stderr)
        return 1

    raw, meta_dir = out / "raw" / "nask", out / "meta"
    for d in (raw, meta_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    import pyarrow.parquet as pq
    by_shard: dict[Path, list[tuple[int, dict]]] = {}
    for k, r in enumerate(picked, start=1):
        by_shard.setdefault(r["_shard"], []).append((k, r))
    for shard, items in by_shard.items():
        table = pq.read_table(shard, columns=["html", "url"])
        html_col, url_col = table.column("html"), table.column("url")
        for k, r in items:
            folder = raw / str(k)
            folder.mkdir()
            (folder / "page.html").write_text(html_col[r["_row"]].as_py() or "", encoding="utf-8")
            meta = {"target": r["target"], "date": str(r["date"]) if r.get("date") else None,
                    "lang": r.get("lang"), "url": url_col[r["_row"]].as_py(),
                    "source": f"{DATASET} ({shard.name}, row {r['_row']})", "license": "CC BY 4.0"}
            (meta_dir / f"{k}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    brands = Counter(r["target"] for r in picked)
    summary = {"incidents": len(picked), "brands": len(brands), "shards": used,
               "candidates_after_filter": len(rows), "per_brand": dict(brands.most_common())}
    (out / "import_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_brand"}, ensure_ascii=False))
    print("brands:", ", ".join(f"{b}={c}" for b, c in brands.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
