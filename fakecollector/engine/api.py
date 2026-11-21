"""Engine entry points for the CLI (W1): `correlate()`, `evaluate()`, `analyze(path)`.

    python -m fakecollector correlate   -> fakecollector.engine.api.correlate()
    python -m fakecollector evaluate    -> fakecollector.engine.api.evaluate()
    python -m fakecollector analyze <p> -> fakecollector.engine.api.analyze(p)
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from fakecollector.core.config import make_context
from fakecollector.core.models import Assignment, Context
from fakecollector.engine import assign as assign_mod
from fakecollector.engine import correlate as co
from fakecollector.engine.features import aggregate_records
from fakecollector.engine.pipeline import Result, load_state, run_from_disk

log = logging.getLogger("fakecollector.engine")


def correlate(ctx: Context | None = None, method: str | None = None) -> Result:
    """Score all incident pairs, cluster them, write data/graph/edges.parquet + clusters.json."""
    return run_from_disk(ctx, method=method, write=True)


def evaluate(ctx: Context | None = None, **kwargs: Any) -> Path:
    """Run all experiments, write reports/eval_<ts>.md and return its path."""
    from fakecollector.eval.run import evaluate as _evaluate
    return _evaluate(ctx, **kwargs)


def analyze_records(records: list[dict[str, Any]], incident_id: str = "upload:new",
                    ctx: Context | None = None, state: Result | None = None,
                    exclude_incidents: list[str] | None = None) -> assign_mod.FamilyAssignment:
    """Assign a new incident given its FeatureRecords (dicts with `module` + `features`).

    exclude_incidents: ids ("nask:47" or "47") removed from the base in memory before comparing.
    """
    ctx = ctx or make_context()
    state = state or load_state(ctx, exclude=exclude_incidents)
    new = aggregate_records(records, state.signals, ctx.settings.get("stoplist"), incident_id)
    return assign_mod.assign(new, state.features, state.clusters, state.signals, state.cfg, incident_id,
                             state.family_of)


def analyze(path: str | Path, ctx: Context | None = None,
            exclude_incidents: list[str] | None = None) -> assign_mod.FamilyAssignment:
    """Analyse a NEW material (folder/file) against the processed corpus.

    Needs W1's ingest+runner to turn `path` into FeatureRecords. Expected hook (to agree with W1):
    `fakecollector.features.runner.extract_for_path(path, ctx) -> list[FeatureRecord | dict]`.

    exclude_incidents: build the comparison base WITHOUT these incidents (in memory, nothing written),
    e.g. ["nask:47"], to demo a "new campaign" without a separate database. ~0.2 s for 10 incidents.
    """
    ctx = ctx or make_context()
    try:
        runner = importlib.import_module("fakecollector.features.runner")
        extract_for_path = runner.extract_for_path
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "analyze() needs fakecollector.features.runner.extract_for_path(path, ctx) from W1; "
            "use analyze_records() with FeatureRecords until it exists") from exc
    records = [r if isinstance(r, dict) else r.__dict__ for r in extract_for_path(Path(path), ctx)]
    return analyze_records(records, incident_id=f"upload:{Path(path).name}", ctx=ctx,
                           exclude_incidents=exclude_incidents)
