"""Feature runner (CONTRACTS §4). Owner: W1.

run_module(name, ctx): import fakecollector.features.<name>, feed it the matching materials
from data/interim/incidents.jsonl, write data/features/<name>.parquet.
A failing record never stops the run: it becomes a row with errors and no features.
"""
from __future__ import annotations

import importlib
import json
import logging
import time
import traceback
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from fakecollector.core.models import Context, FeatureRecord, Incident
from fakecollector.ingest.loader import read_jsonl
from fakecollector.ingest.util import REPO_ROOT, load_stoplist

log = logging.getLogger(__name__)

# Default order (CONTRACTS §4): text last, it may read visual.parquet (ocr_text).
ALL_MODULES = ["html_struct", "infra", "visual", "faces", "text"]
BASE_COLUMNS = ["entity_id", "incident_id", "level", "module", "errors", "provenance"]


# ------------------------------------------------------------------ context

def make_context(offline: bool = True, repo_root: Path | None = None) -> Context:
    """Runtime context from W5's core.config.make_context (settings + stoplist + .env)."""
    from fakecollector.core.config import make_context as _make_context

    return _make_context(repo_root=repo_root, offline=offline)


def _paths(ctx: Context) -> tuple[Path, Path]:
    p = (ctx.settings or {}).get("paths", {})
    interim = Path(p.get("interim", "data/interim"))
    features = Path(p.get("features", "data/features"))
    root = ctx.repo_root
    return (interim if interim.is_absolute() else root / interim,
            features if features.is_absolute() else root / features)


# ------------------------------------------------------------------ flattening

def _to_plain(v: Any) -> Any:
    """Make a value parquet-friendly: sets/tuples -> sorted lists, numpy -> python."""
    try:
        import numpy as np
        if isinstance(v, np.ndarray):
            return v.astype("float32").tolist() if v.dtype.kind == "f" else v.tolist()
        if isinstance(v, np.generic):
            return v.item()
    except ImportError:  # pragma: no cover
        pass
    if isinstance(v, (set, frozenset)):
        try:
            return sorted(v)
        except TypeError:
            return list(v)
    if isinstance(v, tuple):
        return [_to_plain(x) for x in v]
    if isinstance(v, list):
        return [_to_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_plain(x) for k, x in v.items()}
    return v


def flatten_features(features: dict[str, Any] | None) -> dict[str, Any]:
    """One level of dict nesting -> 'parent.child' columns; deeper dicts stay as values."""
    out: dict[str, Any] = {}
    for k, v in (features or {}).items():
        v = _to_plain(v)
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


def _record_row(rec: FeatureRecord) -> dict[str, Any]:
    row = {
        "entity_id": rec.entity_id,
        "incident_id": rec.incident_id,
        "level": rec.level,
        "module": rec.module,
        "errors": list(rec.errors or []),
        "provenance": json.dumps(rec.provenance or {}, ensure_ascii=False),
    }
    for k, v in flatten_features(rec.features).items():
        if k in row:
            k = f"f_{k}"
        row[k] = v
    return row


def _write_parquet(rows: list[dict[str, Any]], out: Path) -> None:
    """Write rows; any column pyarrow cannot type (mixed types) is stored as JSON text."""
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=BASE_COLUMNS)
    for col in BASE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    arrays, names = [], []
    for col in df.columns:
        values = df[col].tolist()
        values = [None if (isinstance(x, float) and x != x) else x for x in values]  # NaN -> None
        try:
            arr = pa.array(values)
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError):
            arr = pa.array([None if x is None else json.dumps(_to_plain(x), ensure_ascii=False, default=str)
                            for x in values], type=pa.string())
            log.warning("column %s stored as JSON text (mixed types)", col)
        if pa.types.is_null(arr.type) and col == "errors":
            arr = pa.array(values, type=pa.list_(pa.string()))
        arrays.append(arr)
        names.append(str(col))
    tmp = out.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_arrays(arrays, names=names), tmp)
    tmp.replace(out)


# ------------------------------------------------------------------ running

def _error_record(mod, entity_id: str, incident_id: str, level: str, msg: str) -> FeatureRecord:
    return FeatureRecord(entity_id=entity_id, level=level, module=getattr(mod, "MODULE", "?"),
                         features={}, provenance={}, errors=[msg], incident_id=incident_id)


def _safe_extract(mod, item, ctx: Context, entity_id: str, incident_id: str, level: str) -> list[FeatureRecord]:
    """Call extract(); accept FeatureRecord or list[FeatureRecord] (CONTRACTS v0.4).

    [] means "skipped" (no row, no error). Any exception or wrong return type becomes one error row.
    """
    try:
        result = mod.extract(item, ctx)
        recs = result if isinstance(result, list) else [result]
        bad = [type(r).__name__ for r in recs if not isinstance(r, FeatureRecord)]
        if bad:
            raise TypeError(f"extract() returned {', '.join(sorted(set(bad)))}, expected FeatureRecord or list")
        for rec in recs:
            rec.incident_id = rec.incident_id or incident_id
            rec.entity_id = rec.entity_id or entity_id
            rec.module = rec.module or mod.MODULE
            rec.level = rec.level or level
        return recs
    except Exception as exc:  # contract: a record never breaks the run
        tb = traceback.format_exc(limit=3).strip().splitlines()[-1]
        return [_error_record(mod, entity_id, incident_id, level, f"runner: {type(exc).__name__}: {exc} | {tb}")]


def _load_module(name: str):
    mod = importlib.import_module(f"fakecollector.features.{name}")
    for attr in ("MODULE", "KINDS", "extract"):
        if not hasattr(mod, attr):
            raise AttributeError(f"fakecollector.features.{name} has no {attr}")
    return mod


def collect_records(mod, ctx: Context, incidents: list[Incident]) -> tuple[list[FeatureRecord], int, int]:
    """Run one loaded module over incidents in memory -> (records, n_with_errors, n_skipped_items)."""
    level = getattr(mod, "LEVEL", "material")
    kinds = set(mod.KINDS or [])
    records: list[FeatureRecord] = []
    n_err = n_skip = 0
    for inc in incidents:
        if level == "incident":
            items = [(inc, inc.incident_id)]
        else:
            items = [(m, m.material_id) for m in inc.materials if m.kind in kinds and not m.is_common_lib]
        for item, eid in items:
            recs = _safe_extract(mod, item, ctx, eid, inc.incident_id, level)
            if not recs:
                n_skip += 1
            n_err += sum(1 for r in recs if r.errors)
            records.extend(recs)
    return records, n_err, n_skip


def run_module(name: str, ctx: Context, incidents: list[Incident] | None = None,
               out: Path | None = None) -> dict[str, Any]:
    """Run one feature module over all incidents and write its parquet. Returns run stats."""
    t0 = time.time()
    mod = _load_module(name)
    interim, features_dir = _paths(ctx)
    if incidents is None:
        incidents = read_jsonl(interim / "incidents.jsonl")
    records, n_err, n_skip = collect_records(mod, ctx, incidents)
    out = out or features_dir / f"{mod.MODULE}.parquet"
    _write_parquet([_record_row(r) for r in records], out)
    stats = {"module": mod.MODULE, "records": len(records), "with_errors": n_err, "skipped": n_skip,
             "seconds": round(time.time() - t0, 2), "out": str(out)}
    log.info("features %s: %s", name, stats)
    return stats


def run_modules(names: list[str], ctx: Context, incidents: list[Incident] | None = None) -> list[dict[str, Any]]:
    """Run several modules; a module that cannot be imported is reported and skipped."""
    results = []
    for name in names:
        try:
            results.append(run_module(name, ctx, incidents))
        except ModuleNotFoundError as exc:
            results.append({"module": name, "skipped": f"not available: {exc}"})
        except Exception as exc:
            log.exception("module %s failed", name)
            results.append({"module": name, "failed": f"{type(exc).__name__}: {exc}"})
    return results


def extract_for_path(path: Path, ctx: Context | None = None, modules: list[str] | None = None,
                     incident_id: str | None = None) -> list[FeatureRecord]:
    """Ingest ONE new material (folder / file / zip) and run all available modules in memory.

    Used by engine.api.analyze() and the UI "new material" view. Nothing is written to
    data/features/; uploaded files are copied to data/interim/uploads/<id>/.
    """
    from fakecollector.ingest.loader import load_upload

    ctx = ctx or make_context()
    path = Path(path)
    incident = load_upload(path, data_dir=ctx.data_dir, incident_id=incident_id or f"upload:{path.name}",
                           stop=load_stoplist(ctx.settings, ctx.repo_root))
    records: list[FeatureRecord] = []
    for name in modules or ALL_MODULES:
        try:
            mod = _load_module(name)
        except Exception as exc:  # missing optional module / dependency -> skip it
            log.warning("extract_for_path: module %s unavailable: %s", name, exc)
            continue
        recs, _, _ = collect_records(mod, ctx, [incident])
        records.extend(recs)
    return records
