from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.kernel_driver import Kernel

SETUP = 'import trail; trail.start("{project}")'


@pytest.fixture
def logs_root(tmp_path: Path) -> Path:
    # why: hard rule 8 — Google Drive's "My Drive" has a space, so every test path does.
    root = tmp_path / "My Drive" / "trail logs"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def kernel(logs_root: Path):
    with Kernel(env={"TRAIL_ROOT": str(logs_root)}) as k:
        yield k


def read_runs(logs_root: Path, project: str) -> list[dict]:
    """Every `run` record on disk for a project, in file order."""
    records = []
    for path in sorted((logs_root / project / "runs").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return [r for r in records if r.get("type") == "run"]


def read_all(logs_root: Path, project: str) -> list[dict]:
    records = []
    for path in sorted((logs_root / project / "runs").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records
