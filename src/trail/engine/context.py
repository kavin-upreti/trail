"""What else was going on between two runs (SPEC 10.9).

The most common way to fool yourself about a result: you changed the cell, but you
*also* changed the learning rate two cells up, restarted the kernel, or moved from
CPU to GPU. This module gathers those confounders so an analysis can warn about them
instead of confidently crediting the wrong change.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from trail.capture.fingerprint import diff as diff_vars
from trail.engine.loader import Run

MAX_OTHER_CELL_DIFF_LINES = 40


@dataclass
class Context:
    var_changes: dict[str, Any] = field(default_factory=dict)
    other_cells: list[dict[str, Any]] = field(default_factory=list)
    restarts: int = 0
    seed_note: str = ""
    device_changed: bool = False
    same_session: bool = True

    @property
    def has_warnings(self) -> bool:
        return bool(
            self.other_cells or self.restarts or self.device_changed or not self.same_session
        )


def _vars_before(run: Run, all_runs: list[Run]) -> dict[str, Any]:
    """The namespace as it was *entering* this run = the fingerprint after the last one."""
    previous: dict[str, Any] = {}
    for other in all_runs:
        if other is run:
            break
        if other.session == run.session and not other.skipped:
            previous = other.vars
    return previous


def _seed_note(before: Run, after: Run) -> str:
    def literals(run: Run) -> list[int]:
        seed = run.raw.get("seed") or {}
        return list(seed.get("manual_seed_literals") or [])

    a, b = literals(before), literals(after)
    if not a and not b:
        return "neither run set a manual seed, so some of any difference is chance"
    if a == b:
        return f"both runs seeded with {a[0]}" if a else ""
    return (
        f"different seeds ({a or 'none'} vs {b or 'none'}), so results aren't directly comparable"
    )


def between(before: Run, after: Run, all_runs: list[Run], identity_of: dict[str, str]) -> Context:
    """Everything that changed between two runs, beyond the cell itself."""
    context = Context()
    context.same_session = before.session == after.session
    context.var_changes = diff_vars(_vars_before(before, all_runs), _vars_before(after, all_runs))
    context.seed_note = _seed_note(before, after)
    context.device_changed = before.raw.get("device") != after.raw.get("device")

    window = [
        run
        for run in all_runs
        if before.ts_start < run.ts_start <= after.ts_start and not run.skipped
    ]
    context.restarts = len({run.session for run in window} - {before.session}) if window else 0

    # Other cells that changed in the window — the real confounders.
    own = identity_of.get(id(after)) or identity_of.get(id(before))
    latest_by_identity: dict[str, list[Run]] = {}
    for run in window:
        key = identity_of.get(id(run))
        if key is None or key == own:
            continue
        latest_by_identity.setdefault(key, []).append(run)

    budget = MAX_OTHER_CELL_DIFF_LINES
    for key, runs in latest_by_identity.items():
        first, last = runs[0], runs[-1]
        if first.norm.semantic_hash == last.norm.semantic_hash and len(runs) == 1:
            continue
        lines = list(
            difflib.unified_diff(
                first.norm.semantic.split("\n"),
                last.norm.semantic.split("\n"),
                lineterm="",
                n=1,
            )
        )[2:]
        if not lines:
            continue
        clipped = lines[:budget]
        budget -= len(clipped)
        context.other_cells.append({"identity": key, "diff": clipped, "runs": len(runs)})
        if budget <= 0:
            break

    return context
