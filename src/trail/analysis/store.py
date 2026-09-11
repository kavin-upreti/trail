"""Where analyses live, and whether they're still current (SPEC 11.1, 10.6).

A step's key is derived from the code at both ends plus the note, so editing the
cell afterwards changes the key. The old analysis isn't deleted — it's marked
**stale**, because it still described something real, and silently discarding a
paid-for explanation would be worse than showing it with a warning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trail.common.paths import ProjectPaths
from trail.engine.steps import Step

FRESH, STALE, MISSING = "fresh", "stale", "missing"


def slug(identity: str) -> str:
    return identity.replace(":", "-").replace("/", "-")


def analysis_path(paths: ProjectPaths, step: Step, suffix: str = ".json") -> Path:
    return paths.analyses / slug(step.identity) / f"{step.key}{suffix}"


def state(paths: ProjectPaths, step: Step) -> str:
    return FRESH if analysis_path(paths, step).is_file() else MISSING


def states(paths: ProjectPaths, steps: list[Step]) -> dict[str, str]:
    return {step.key: state(paths, step) for step in steps}


def stale_files(paths: ProjectPaths, steps: list[Step]) -> list[Path]:
    """Saved analyses whose step no longer exists — the code moved on."""
    if not paths.analyses.is_dir():
        return []
    live = {step.key for step in steps}
    return [p for p in paths.analyses.rglob("*.json") if p.stem not in live]


@dataclass
class Saved:
    analysis: dict[str, Any]
    meta: dict[str, Any]


def save(paths: ProjectPaths, step: Step, analysis: dict[str, Any], meta: dict[str, Any]) -> Path:
    target = analysis_path(paths, step)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "step": {
            "key": step.key,
            "identity": step.identity,
            "start_n": step.start_n,
            "end_n": step.end_n,
            "note": step.note,
        },
        "analysis": analysis,
        "meta": meta,
    }
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return target


def load(paths: ProjectPaths, step: Step) -> Saved | None:
    path = analysis_path(paths, step)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Saved(data.get("analysis") or {}, data.get("meta") or {})
