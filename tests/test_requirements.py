"""Integration rules for requirements/*.txt (owner W4, environment integrator).

Every package is pinned with "==" in exactly one file, so
`pip install -r requirements.txt` can never hit a version conflict again
(it did once: pytest 8.3.3 in core.txt vs 8.3.4 in ingest.txt).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQ_DIR = REPO_ROOT / "requirements"
LINE_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|>=|<=|~=|!=|>|<)?\s*([^\s#;]*)")


def _canon(name: str) -> str:
    """PEP 503 normalisation: Pillow == pillow, open_clip_torch == open-clip-torch."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins() -> dict[str, list[tuple[str, str, str]]]:
    found: dict[str, list[tuple[str, str, str]]] = {}
    for path in sorted(REQ_DIR.glob("*.txt")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            match = LINE_RE.match(line)
            assert match, f"{path.name}: cannot parse {raw!r}"
            name, op, version = match.groups()
            found.setdefault(_canon(name), []).append((path.name, op or "", version))
    return found


def test_every_package_is_pinned_exactly() -> None:
    for name, entries in _pins().items():
        for file, op, version in entries:
            assert op == "==" and version, f"{name} in {file} must be pinned with ==, got {op}{version}"


def test_every_package_lives_in_one_file() -> None:
    dupes = {n: [e[0] for e in entries] for n, entries in _pins().items() if len(entries) > 1}
    assert not dupes, f"packages pinned in more than one file: {dupes}"


def test_torch_only_in_visual_and_sklearn_only_in_core() -> None:
    pins = _pins()
    assert [e[0] for e in pins["torch"]] == ["visual.txt"]
    assert [e[0] for e in pins["torchvision"]] == ["visual.txt"]
    assert [e[0] for e in pins["scikit-learn"]] == ["core.txt"]


def test_pytest_is_dev_only() -> None:
    assert [e[0] for e in _pins()["pytest"]] == ["dev.txt"]
    root = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "dev.txt" not in root.split("#")[0], "dev.txt must not be part of the runtime install"


def test_root_file_includes_every_runtime_module() -> None:
    root = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    included = set(re.findall(r"^-r\s+requirements/(\S+)", root, re.MULTILINE))
    runtime = {p.name for p in REQ_DIR.glob("*.txt")} - {"dev.txt"}
    assert included == runtime, f"requirements.txt missing {runtime - included}, extra {included - runtime}"
