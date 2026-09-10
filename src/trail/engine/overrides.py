"""User corrections (SPEC 10.10).

When the engine guesses an identity wrong, the user fixes it here — never by editing
the raw logs, which stay append-only (ADR 0001). Applied after resolution, so a
rebuild always reproduces the same corrected result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trail.engine.identity import Identity


@dataclass
class Overrides:
    renames: dict[str, str] = field(default_factory=dict)
    merges: list[list[str]] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    unhidden: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "renames": self.renames,
            "merges": self.merges,
            "hidden": self.hidden,
            "unhidden": self.unhidden,
        }


def load(path: Path) -> Overrides:
    if not path.is_file():
        return Overrides()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Overrides()
    return Overrides(
        renames=dict(data.get("renames") or {}),
        merges=[list(pair) for pair in data.get("merges") or []],
        hidden=list(data.get("hidden") or []),
        unhidden=list(data.get("unhidden") or []),
    )


def save(path: Path, overrides: Overrides) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides.to_json(), indent=2) + "\n", encoding="utf-8")


def apply(identities: dict[str, Identity], overrides: Overrides) -> dict[str, Identity]:
    """Rename, merge and hide. Raw logs are untouched; this is pure interpretation."""
    result = dict(identities)

    for source, target in overrides.merges:
        if source not in result:
            continue
        merged = result.pop(source)
        into = result.get(target)
        if into is None:
            merged.key = target
            result[target] = merged
            continue
        into.runs = sorted(into.runs + merged.runs, key=lambda r: (r.ts_start, r.seq))
        if merged.runs and (not into.latest_semantic or merged.last_ts > into.last_ts):
            into.latest_semantic = merged.latest_semantic or into.latest_semantic

    for key, name in overrides.renames.items():
        if key in result:
            result[key].name = name

    for key in overrides.hidden:
        if key in result:
            result[key].hidden = True
    for key in overrides.unhidden:
        if key in result:
            result[key].hidden = False

    return result
