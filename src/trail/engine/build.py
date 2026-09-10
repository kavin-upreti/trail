"""Turning raw logs into `derived/versions.json` (SPEC 10.8).

Everything here is derived and disposable — delete the file and it rebuilds
identically from the append-only logs (ADR 0001). That determinism is what makes it
safe to keep improving the grouping heuristics after a lecture is recorded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trail._version import __version__
from trail.capture.schema import utc_now
from trail.common.paths import ProjectPaths
from trail.engine import identity as identity_mod
from trail.engine import overrides as overrides_mod
from trail.engine import steps as steps_mod
from trail.engine.grouping import DEFAULT_MINOR_MAX_CHARS, Version, group
from trail.engine.loader import LoadedProject, Run, load

SCHEMA_VERSION = 1


@dataclass
class EngineConfig:
    minor_max_chars: int = DEFAULT_MINOR_MAX_CHARS
    fuzzy_threshold: float = identity_mod.DEFAULT_FUZZY_THRESHOLD
    extra_metric_patterns: list[str] = field(default_factory=list)


@dataclass
class Cell:
    key: str
    name: str
    hidden: bool
    versions: list[Version]
    first_ts: str = ""
    last_ts: str = ""


@dataclass
class Build:
    project: str
    cells: list[Cell] = field(default_factory=list)
    steps: list[steps_mod.Step] = field(default_factory=list)
    loaded: LoadedProject = field(default_factory=LoadedProject)
    warnings: list[str] = field(default_factory=list)
    identity_of: dict[int, str] = field(default_factory=dict)

    @property
    def runs(self) -> list[Run]:
        return self.loaded.runs

    def cell(self, key_or_name: str) -> Cell | None:
        for cell in self.cells:
            if key_or_name in (cell.key, cell.name):
                return cell
        # Allow a bare tag name, e.g. "train" for "tag:train".
        for cell in self.cells:
            if cell.key.split(":", 1)[-1] == key_or_name:
                return cell
        return None

    def step(self, key: str) -> steps_mod.Step | None:
        return next((s for s in self.steps if s.key == key), None)


def build(paths: ProjectPaths, config: EngineConfig | None = None) -> Build:
    """Load, resolve identities, group into versions, find steps."""
    config = config or EngineConfig()
    loaded = load(paths)
    result = Build(project=paths.project, loaded=loaded)
    result.warnings.extend(loaded.warnings)

    identities, warnings = identity_mod.resolve(loaded.runs, config.fuzzy_threshold)
    result.warnings.extend(warnings)
    identities = overrides_mod.apply(identities, overrides_mod.load(paths.overrides))

    for key, identity in identities.items():
        for run in identity.runs:
            result.identity_of[id(run)] = key

    for key, identity in identities.items():
        versions = group(
            identity, config.minor_max_chars, config.extra_metric_patterns, loaded.runs
        )
        if not versions:
            continue
        cell = Cell(
            key=key,
            name=identity.name,
            hidden=identity.hidden,
            versions=versions,
            first_ts=identity.first_ts,
            last_ts=identity.last_ts,
        )
        result.cells.append(cell)

        found, step_warnings = steps_mod.find(key, versions)
        result.steps.extend(found)
        result.warnings.extend(step_warnings)

    result.cells.sort(key=lambda c: c.first_ts)
    result.steps = steps_mod.story_order(result.steps)
    return result


# -- serialisation ----------------------------------------------------------


def _version_json(version: Version) -> dict[str, Any]:
    return {
        "n": version.n,
        "code": version.code,
        "code_hash": version.code_hash,
        "semantic_hash": version.semantic_hash,
        "minor": version.minor,
        "runs": [[r.session, r.seq] for r in version.runs],
        "failed_runs": [[r.session, r.seq] for r in version.failed_runs],
        "attempts": [
            {"ref": [a.run.session, a.run.seq], "error_type": a.error_type}
            for a in version.attempts
        ],
        "replaced_code": version.replaced_code,
        "metrics": version.metrics,
        "loss_std": version.loss_std,
        "run_finals": version.run_finals,
        "marked": version.marked,
        "note": version.note,
        "first_ts": version.first_ts,
        "last_ts": version.last_ts,
    }


def to_json(result: Build, analysis_state: dict[str, str] | None = None) -> dict[str, Any]:
    analysis_state = analysis_state or {}
    return {
        "project": result.project,
        "built_at": utc_now(),
        "trail_version": __version__,
        "schema": SCHEMA_VERSION,
        "sessions": [
            {
                "id": s.id,
                "start": s.start,
                "end": s.end,
                "clean": s.clean,
                "frontend": s.frontend,
                "notebook": s.notebook,
            }
            for s in sorted(result.loaded.sessions.values(), key=lambda s: s.start)
        ],
        "cells": [
            {
                "identity": cell.key,
                "name": cell.name,
                "hidden": cell.hidden,
                "first_ts": cell.first_ts,
                "last_ts": cell.last_ts,
                "versions": [_version_json(v) for v in cell.versions],
            }
            for cell in result.cells
        ],
        "steps": [
            {
                "key": step.key,
                "identity": step.identity,
                "start_n": step.start_n,
                "end_n": step.end_n,
                "note": step.note,
                "analysis": analysis_state.get(step.key, "missing"),
                "ts": step.ts,
            }
            for step in result.steps
        ],
        "warnings": result.warnings,
    }


# -- caching ----------------------------------------------------------------


def _fingerprint(paths: ProjectPaths) -> dict[str, list[float]]:
    """Sizes and mtimes of everything a build depends on."""
    inputs: dict[str, list[float]] = {}
    if paths.runs.is_dir():
        for path in sorted(paths.runs.glob("*.jsonl")):
            stat = path.stat()
            inputs[path.name] = [stat.st_size, stat.st_mtime]
    if paths.overrides.is_file():
        stat = paths.overrides.stat()
        inputs["overrides.json"] = [stat.st_size, stat.st_mtime]
    return inputs


def is_fresh(paths: ProjectPaths) -> bool:
    cache = paths.derived / "build-cache.json"
    if not cache.is_file() or not (paths.derived / "versions.json").is_file():
        return False
    try:
        stored = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return stored.get("inputs") == _fingerprint(paths)


def write(paths: ProjectPaths, result: Build, analysis_state: dict[str, str] | None = None) -> Path:
    paths.derived.mkdir(parents=True, exist_ok=True)
    target = paths.derived / "versions.json"
    target.write_text(
        json.dumps(to_json(result, analysis_state), indent=1) + "\n", encoding="utf-8"
    )
    (paths.derived / "build-cache.json").write_text(
        json.dumps({"inputs": _fingerprint(paths)}, indent=1) + "\n", encoding="utf-8"
    )
    return target


def build_cached(
    paths: ProjectPaths, config: EngineConfig | None = None, force: bool = False
) -> Build:
    """Build, writing versions.json unless nothing has changed since last time."""
    result = build(paths, config)
    if force or not is_fresh(paths):
        write(paths, result)
    return result
