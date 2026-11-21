"""Load per-module feature tables and aggregate them to incident level (CONTRACTS section 4).

The aggregated structure is signal-oriented:  {incident_id: {signal_name: aggregated_value}}.
A signal that cannot be computed for an incident (no data) is simply absent -> "unavailable".

Aggregation rules (per signal type):
  cosine           -> list of float32 vectors (similarity = max over pairs)
  jaccard_minhash  -> {"sigs": [uint64 arrays], "set": frozenset} (max over pairs)
  set_overlap      -> union of elements
  exact            -> union of scalar values (similarity 1 if the sets intersect)
  hamming_hash     -> list of ints (max over pairs)
  numeric_close    -> list of floats (min distance over pairs)
"""
from __future__ import annotations

import importlib
import logging
import math
import pkgutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

log = logging.getLogger("fakecollector.engine")

SIGNAL_CLASSES = {"campaign", "family"}
SIGNAL_TYPES = {"cosine", "jaccard_minhash", "set_overlap", "exact", "hamming_hash", "numeric_close"}
_MASK64 = 0xFFFFFFFFFFFFFFFF


# --------------------------------------------------------------------------- value helpers
def is_missing(v: Any) -> bool:
    """True for None/NaN/empty containers - everything a module uses for 'unavailable'."""
    if v is None or v is pd.NA or v is pd.NaT:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, (str, bytes)):
        return len(v.strip()) == 0
    if isinstance(v, (list, tuple, set, frozenset, dict)):
        return len(v) == 0
    if isinstance(v, np.ndarray):
        return v.size == 0
    return False


def to_py(v: Any) -> Any:
    """Convert numpy/pandas containers read from parquet into plain python lists/scalars."""
    if isinstance(v, np.ndarray):
        return [to_py(x) for x in v.tolist()] if v.dtype == object else v.tolist()
    if isinstance(v, (list, tuple)):
        return [to_py(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    return v


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not (isinstance(x, float) and math.isnan(x))


def _is_number_seq(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(_is_number(x) for x in v)


def _iter_tokens(v: Any) -> Iterable[Any]:
    v = to_py(v)
    if isinstance(v, dict):
        for x in v.values():
            yield from _iter_tokens(x)
    elif isinstance(v, (list, tuple, set, frozenset)):
        for x in v:
            yield from _iter_tokens(x)
    elif not is_missing(v):
        yield v


# --------------------------------------------------------------------------- stoplist
class Stoplist:
    """Drops generic elements (CDNs, jQuery, ...) so they never create 'shared element' links."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.filenames = [str(x).lower() for x in cfg.get("filenames") or []]
        self.sha1 = {str(x).lower() for x in cfg.get("sha1") or []}
        self.domains = [str(x).lower() for x in cfg.get("domains") or []]

    def is_stopped(self, token: str) -> bool:
        t = token.strip().lower()
        if not t:
            return True
        if t in self.sha1:
            return True
        host = t.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        for d in self.domains:
            if host == d or host.endswith("." + d):
                return True
        return any(f in t for f in self.filenames) and ("/" in t or "." in t)


# --------------------------------------------------------------------------- aggregation
def _to_int_hash(x: Any) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x & _MASK64
    if isinstance(x, float) and x.is_integer():
        return int(x) & _MASK64
    if isinstance(x, str):
        s = x.strip().lower().removeprefix("0x")
        if s and all(c in "0123456789abcdef" for c in s):
            return int(s, 16) & _MASK64
    return None


def _to_number(x: Any) -> float | None:
    if _is_number(x):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        try:
            return float(s)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() / 86400.0  # days since epoch
        except ValueError:
            return None
    return None


def _as_vectors(v: Any) -> list[np.ndarray]:
    v = to_py(v)
    if _is_number_seq(v):
        return [np.asarray(v, dtype=np.float32)]
    out: list[np.ndarray] = []
    if isinstance(v, list):
        for item in v:
            out.extend(_as_vectors(item))
    return out


def aggregate_values(spec: dict[str, Any], values: list[Any], stop: Stoplist | None = None) -> Any:
    """Aggregate raw per-record values of one signal to one incident-level value (or None)."""
    stype = spec["type"]
    stop = stop or Stoplist()
    if stype == "cosine":
        vecs = [x for raw in values for x in _as_vectors(raw) if float(np.linalg.norm(x)) > 0]
        return vecs or None
    if stype == "jaccard_minhash":
        sigs: list[np.ndarray] = []
        toks: set[str] = set()
        for raw in values:
            v = to_py(raw)
            if _is_number_seq(v):
                sigs.append(np.array([int(x) & _MASK64 for x in v], dtype=np.uint64))
            elif isinstance(v, list) and v and all(_is_number_seq(x) for x in v):
                sigs.extend(np.array([int(y) & _MASK64 for y in x], dtype=np.uint64) for x in v)
            else:
                toks.update(str(t) for t in _iter_tokens(v))
        if not sigs and not toks:
            return None
        return {"sigs": sigs, "set": frozenset(toks)}
    if stype in ("set_overlap", "exact"):
        toks = {str(t) for raw in values for t in _iter_tokens(raw)}
        toks = {t for t in toks if not stop.is_stopped(t)}
        return frozenset(toks) if toks else None
    if stype == "hamming_hash":
        hashes: list[int] = []
        for raw in values:
            v = to_py(raw)
            if isinstance(v, list) and len(v) >= 16 and all(x in (0, 1) for x in v):  # bit vector
                hashes.append(int("".join(str(int(b)) for b in v), 2) & _MASK64)
                continue
            for tok in _iter_tokens(v):
                h = _to_int_hash(tok)
                if h is not None:
                    hashes.append(h)
        return hashes or None
    if stype == "numeric_close":
        nums = [n for raw in values for t in _iter_tokens(raw) if (n := _to_number(t)) is not None]
        return nums or None
    raise ValueError(f"unknown signal type: {stype}")


def sources_of(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Value sources of a signal; specs not passed through normalize_signals have just one."""
    return spec.get("sources") or [{"module": spec.get("module"), "field": spec["field"]}]


def _get_field(rec: dict[str, Any], field: str, columns: set[str]) -> Any:
    """Read `field` from a record; supports 'faces.emb' = key `emb` of every dict in list `faces`."""
    if field in columns:
        return rec.get(field)
    head, _, rest = field.partition(".")
    if not rest or head not in columns:
        return None
    base = to_py(rec.get(head))
    if isinstance(base, dict):
        return base.get(rest)
    if isinstance(base, list):
        return [item.get(rest) for item in base if isinstance(item, dict)]
    return None


# --------------------------------------------------------------------------- signal registry
def normalize_signals(signals: dict[str, dict[str, Any]],
                      params: dict[str, dict[str, Any]] | None = None,
                      classes: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Validate signal specs; merge `engine.signal_params`; set `class` and `sources`.

    class:   "campaign" (default) or "family" (CONTRACTS 4: SIGNAL_CLASS in the module);
             `engine.signal_class` in settings.yaml overrides what a module declares.
    sources: list of {"module", "field"}; a signal declared by several modules (e.g. shared_trackers
             in html_struct and infra) reads the values of all of them.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, spec in signals.items():
        if spec.get("type") not in SIGNAL_TYPES:
            log.warning("signal %s skipped: unknown type %r", name, spec.get("type"))
            continue
        merged = dict(spec)
        merged.update((params or {}).get(name, {}))
        cls = (classes or {}).get(name) or merged.get("class") or "campaign"
        if cls not in SIGNAL_CLASSES:
            log.warning("signal %s: unknown class %r, using campaign", name, cls)
            cls = "campaign"
        merged["class"] = cls
        if not merged.get("sources"):
            merged["sources"] = [{"module": merged.get("module"), "field": merged["field"]}]
        out[name] = merged
    return out


def collect_signals(params: dict[str, dict[str, Any]] | None = None,
                    only_modules: Iterable[str] | None = None,
                    classes: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Collect `SIGNALS` (+ optional `SIGNAL_CLASS`) from every module in `fakecollector.features`.

    Missing/broken modules are skipped. A signal name declared by two modules is a hard error.
    """
    signals: dict[str, dict[str, Any]] = {}
    try:
        pkg = importlib.import_module("fakecollector.features")
    except ImportError:
        return signals
    wanted = set(only_modules) if only_modules else None
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name == "runner" or info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"fakecollector.features.{info.name}")
        except Exception as exc:  # a broken feature module must never break the engine
            log.warning("feature module %s not importable: %s", info.name, exc)
            continue
        mod_signals = getattr(mod, "SIGNALS", None)
        if not mod_signals:
            continue
        mname = getattr(mod, "MODULE", info.name)
        if wanted is not None and mname not in wanted:
            continue
        mod_classes = getattr(mod, "SIGNAL_CLASS", None) or {}
        for sname, spec in mod_signals.items():
            if sname in signals:
                raise ValueError(
                    f"duplicate signal name {sname!r}: declared by modules {signals[sname]['module']!r} and "
                    f"{mname!r} - rename one (CONTRACTS: signal names are unique)")
            signals[sname] = {**spec, "module": mname, "class": mod_classes.get(sname, "campaign")}
    return normalize_signals(signals, params, classes)


# --------------------------------------------------------------------------- tables
def load_feature_tables(features_dir: Path, modules: Iterable[str] | None = None) -> dict[str, pd.DataFrame]:
    """Read data/features/*.parquet -> {module: DataFrame}. Unreadable files are skipped."""
    tables: dict[str, pd.DataFrame] = {}
    wanted = set(modules) if modules else None
    if not Path(features_dir).exists():
        return tables
    for path in sorted(Path(features_dir).glob("*.parquet")):
        if wanted is not None and path.stem not in wanted:
            continue
        try:
            tables[path.stem] = pd.read_parquet(path)
        except Exception as exc:
            log.warning("cannot read %s: %s", path, exc)
    return tables


def _group_of(rec: dict[str, Any], material_map: dict[str, str] | None,
              group_fn: Callable[[dict[str, Any]], str | None] | None) -> str | None:
    inc = rec.get("incident_id")
    if is_missing(inc):
        entity = rec.get("entity_id")
        inc = entity if rec.get("level") == "incident" else (material_map or {}).get(entity)
    if is_missing(inc):
        return None
    if group_fn is not None:
        rec = {**rec, "incident_id": inc}
        return group_fn(rec)
    return str(inc)


def aggregate_incidents(
    tables: dict[str, pd.DataFrame],
    signals: dict[str, dict[str, Any]],
    stoplist: dict[str, Any] | None = None,
    material_map: dict[str, str] | None = None,
    group_fn: Callable[[dict[str, Any]], str | None] | None = None,
    extra_ids: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Aggregate feature tables to {incident_id: {signal: value}}.

    material_map: material_id -> incident_id, used only when a table lacks `incident_id`.
    group_fn:     optional record -> group id; used by evaluation to build pseudo-incidents
                  (return None to drop the record).
    extra_ids:    incident ids that must appear even if they have no features at all.
    """
    stop = Stoplist(stoplist)
    buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
    ids: set[str] = {str(i) for i in extra_ids}
    for module, df in tables.items():
        module_signals = [(n, src["field"]) for n, s in signals.items()
                          for src in sources_of(s) if src["module"] == module]
        columns = set(df.columns)
        for rec in df.to_dict("records"):
            inc = _group_of(rec, material_map, group_fn)
            if inc is None:
                continue
            ids.add(inc)
            for name, field_name in module_signals:
                raw = _get_field(rec, field_name, columns)
                if not is_missing(raw):
                    buckets[(inc, name)].append(raw)
    out: dict[str, dict[str, Any]] = {i: {} for i in sorted(ids)}      # fixed order = reproducible runs
    for (inc, name), vals in sorted(buckets.items(), key=lambda kv: kv[0]):
        try:
            agg = aggregate_values(signals[name], vals, stop)
        except Exception as exc:
            log.warning("aggregation failed for %s/%s: %s", inc, name, exc)
            continue
        if agg is not None:
            out[inc][name] = agg
    return out


def aggregate_records(
    records: list[dict[str, Any]],
    signals: dict[str, dict[str, Any]],
    stoplist: dict[str, Any] | None = None,
    incident_id: str = "upload:new",
) -> dict[str, Any]:
    """Aggregate FeatureRecord-like dicts of ONE incident (e.g. a freshly analysed upload).

    Each record needs: `module` and a `features` dict (the FeatureRecord shape).
    """
    stop = Stoplist(stoplist)
    buckets: dict[str, list[Any]] = defaultdict(list)
    for rec in records:
        feats = rec.get("features") or {}
        columns = set(feats)
        for name, spec in signals.items():
            for src in sources_of(spec):
                if src["module"] != rec.get("module"):
                    continue
                raw = _get_field(feats, src["field"], columns)
                if not is_missing(raw):
                    buckets[name].append(raw)
    out: dict[str, Any] = {}
    for name, vals in buckets.items():
        agg = aggregate_values(signals[name], vals, stop)
        if agg is not None:
            out[name] = agg
    return out
