"""Configuration loading for FakeCollector: settings.yaml, stoplist.yaml, .env.

Owner: W5. The only entry points other modules need are `load_settings`,
`load_stoplist` and `make_context`.
"""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from fakecollector.core.models import Context

log = logging.getLogger("fakecollector.config")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        log.warning("config file missing: %s", path)
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def deep_update(base: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of `base` with `overrides` merged in recursively."""
    out = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_update(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_settings(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or REPO_ROOT
    return _load_yaml(root / "config" / "settings.yaml")


def load_stoplist(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or REPO_ROOT
    return _load_yaml(root / "config" / "stoplist.yaml")


def load_env(repo_root: Path | None = None) -> None:
    """Load `.env` into os.environ if python-dotenv and the file are available."""
    root = repo_root or REPO_ROOT
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional dependency
        return
    env_file = root / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


def _env_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, root: Path) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_absolute() else root / p


def apply_env_paths(settings: dict[str, Any], root: Path, explicit: set[str]) -> None:
    """Environment overrides for `settings["paths"]` (in place).

    DATA_DIR   relocates every path that lives under `data/` (raw, interim, features, graph, cache,
               models) to DATA_DIR/<same subfolder>. Paths outside `data/` and absolute paths stay.
    MODELS_DIR overrides paths.models (wins over DATA_DIR), e.g. a baked-in model folder in Docker.
    `explicit` = keys given through `overrides=` (tests, callers): those always win over the environment.
    """
    paths = settings.setdefault("paths", {})
    paths.setdefault("models", "data/models")
    data_dir = _env_path("DATA_DIR", root)
    if data_dir is not None:
        for key, rel in list(paths.items()):
            p = Path(str(rel))
            if key not in explicit and not p.is_absolute() and p.parts[:1] == ("data",):
                paths[key] = str(data_dir.joinpath(*p.parts[1:]))
    models_dir = _env_path("MODELS_DIR", root)
    if models_dir is not None and "models" not in explicit:
        paths["models"] = str(models_dir)


def make_context(
    repo_root: Path | None = None,
    offline: bool | None = None,
    overrides: dict[str, Any] | None = None,
) -> Context:
    """Build the runtime Context. Precedence for `offline`: argument > OFFLINE env > settings."""
    root = Path(repo_root) if repo_root else REPO_ROOT
    load_env(root)
    settings = deep_update(load_settings(root), overrides)
    apply_env_paths(settings, root, set(((overrides or {}).get("paths") or {})))
    settings["stoplist"] = load_stoplist(root)

    if offline is None:
        offline = _env_bool(os.environ.get("OFFLINE"))
    if offline is None:
        offline = bool(settings.get("offline", True))

    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return Context(repo_root=root, data_dir=data_dir, settings=settings, offline=offline)


def resolve_path(ctx: Context, key: str) -> Path:
    """Resolve a `paths.<key>` entry of settings.yaml against the repo root."""
    rel = ctx.settings.get("paths", {}).get(key)
    if rel is None:
        raise KeyError(f"settings.paths.{key} is not configured")
    p = Path(rel)
    return p if p.is_absolute() else ctx.repo_root / p
