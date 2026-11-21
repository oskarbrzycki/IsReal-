"""Command line interface: `python -m fakecollector <command>` (CONTRACTS §7). Owner: W1.

Engine commands (correlate / analyze / evaluate) delegate to W5's fakecollector.engine.api
when it exists; otherwise they say so and exit with code 2.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import logging
import runpy
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fakecollector.ingest.util import REPO_ROOT

log = logging.getLogger("fakecollector")


def _config_path(key: str) -> Path:
    """Default location for paths.<key> from config (DATA_DIR / MODELS_DIR aware, see core.config)."""
    from fakecollector.core.config import make_context, resolve_path

    return resolve_path(make_context(REPO_ROOT), key)


def _print_json(obj: Any) -> None:
    if is_dataclass(obj):
        obj = asdict(obj)
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_inventory(args: argparse.Namespace) -> int:
    script = REPO_ROOT / "scripts" / "inventory.py"
    # default output is gitignored, so running the README command never dirties docs/DATA_INVENTORY.md
    out = args.out or str(_config_path("interim") / "DATA_INVENTORY.md")
    data = args.data or str(_config_path("raw"))
    argv = [str(script), data, "--out", out]
    old = sys.argv
    try:
        sys.argv = argv
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = old
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from fakecollector.ingest.loader import load_incidents, load_upload, write_jsonl

    data = Path(args.data) if args.data else _config_path("raw")      # explicit argument wins over config
    if data.is_dir() and not args.upload:
        incidents = load_incidents(data, source=args.source)
    else:  # single folder / file / zip -> one "upload" incident
        from fakecollector.core.config import make_context

        incidents = [load_upload(data, data_dir=make_context(REPO_ROOT).data_dir)]   # uploads under DATA_DIR too
    out = Path(args.out) if args.out else _config_path("interim") / "incidents.jsonl"
    write_jsonl(incidents, out)
    n_mat = sum(len(i.materials) for i in incidents)
    n_err = sum(1 for i in incidents if i.meta.get("errors"))
    print(f"ingest: {len(incidents)} incidents, {n_mat} materials, {n_err} with errors -> {out}")
    return 0


def cmd_features(args: argparse.Namespace) -> int:
    from fakecollector.features.runner import ALL_MODULES, make_context, run_modules

    ctx = make_context(offline=not args.online)
    names = ALL_MODULES if args.module == "all" else [m.strip() for m in args.module.split(",") if m.strip()]
    results = []
    for i, name in enumerate(names, 1):
        # live progress: one line when a module starts and one when it finishes
        print(f"[{i}/{len(names)}] {name}: start", flush=True)
        r = run_modules([name], ctx)[0]
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    # failure only if every requested module failed / was missing
    ok = any("records" in r for r in results)
    return 0 if ok else 1


def _engine_call(func_name: str, *args: Any) -> int:
    """Call fakecollector.engine.api.<func_name>, passing a Context if the function accepts one."""
    try:
        api = importlib.import_module("fakecollector.engine.api")
        func = getattr(api, func_name)
    except (ImportError, AttributeError):
        print(f"{func_name}: not available yet (W5: fakecollector.engine.api.{func_name})", file=sys.stderr)
        return 2
    from fakecollector.features.runner import make_context

    params = list(inspect.signature(func).parameters)
    call_args = list(args)
    if "ctx" in params or len(params) > len(call_args):
        call_args.append(make_context())
    result = func(*call_args[: len(params)] if params else [])
    if result is not None:
        _print_json(result)
    return 0


def cmd_correlate(args: argparse.Namespace) -> int:
    return _engine_call("correlate")


def cmd_analyze(args: argparse.Namespace) -> int:
    return _engine_call("analyze", args.path)


def cmd_evaluate(args: argparse.Namespace) -> int:
    return _engine_call("evaluate")


def cmd_monitor(args: argparse.Namespace) -> int:
    # W4 module; imported lazily so the CLI never depends on it.
    from fakecollector.monitor import main as monitor_main
    return monitor_main(online=bool(args.online))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m fakecollector", description="Kolekcjoner fejkow / Follow the Fake")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inventory", help="static inventory report of a data folder")
    p.add_argument("--data", default=None, help="dataset root (default: paths.raw from config, DATA_DIR aware)")
    p.add_argument("--out", default=None, help="markdown output (default: <paths.interim>/DATA_INVENTORY.md; pass docs/DATA_INVENTORY.md to update the tracked copy)")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("ingest", help="folders/files -> <paths.interim>/incidents.jsonl")
    p.add_argument("--data", default=None,
                   help="dataset root, or a single folder/file/zip (default: paths.raw from config, DATA_DIR aware)")
    p.add_argument("--source", default="nask")
    p.add_argument("--upload", action="store_true", help="treat --data as ONE new incident (source=upload)")
    p.add_argument("--out", default=None, help="default: <paths.interim>/incidents.jsonl (DATA_DIR aware)")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("features", help="run feature modules -> data/features/<module>.parquet")
    p.add_argument("--module", default="all", help="all | html_struct | text | visual | faces | infra (comma list ok)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", default=True, help="no network, cache only (default)")
    mode.add_argument("--online", action="store_true", help="allow OSINT lookups (RDAP/DNS/crt.sh) where modules support it")
    p.set_defaults(func=cmd_features)

    p = sub.add_parser("correlate", help="edges + clusters (W5)")
    p.set_defaults(func=cmd_correlate)
    p = sub.add_parser("analyze", help="new material -> Assignment JSON (W5)")
    p.add_argument("path")
    p.set_defaults(func=cmd_analyze)
    p = sub.add_parser("evaluate", help="evaluation report (W5)")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("monitor", help="re-check RDAP/DNS of known campaign domains, report changes (W4)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", default=True, help="cache only, no network (default)")
    mode.add_argument("--online", action="store_true", help="ask RDAP/DNS again (public services only)")
    p.set_defaults(func=cmd_monitor)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    return int(args.func(args) or 0)
