"""Runs into versions (SPEC 10.5).

The heart of the thing. Twenty runs of one cell become four versions you'd actually
want to read, with the typos folded away rather than deleted:

- a run that **failed** becomes an *attempt* attached to whatever version fixed it
- a run whose code is semantically identical just joins the current version
- a comment-only edit updates the version's text without creating a new one
- a genuinely new state starts a new version, flagged *minor* if the change is tiny
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from trail.engine.identity import Identity
from trail.engine.loader import Run
from trail.engine.metrics import extract, noise_estimate, primary_name

DEFAULT_MINOR_MAX_CHARS = 12


@dataclass
class Attempt:
    run: Run
    error_type: str | None


@dataclass
class Version:
    n: int
    code: str
    code_hash: str
    semantic_hash: str
    minor: bool = False
    runs: list[Run] = field(default_factory=list)
    failed_runs: list[Run] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    replaced_code: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    loss_std: float | None = None
    #: The primary metric's final value for each ok run, oldest first. Identical code
    #: can still produce very different numbers when another cell changed in between,
    #: and showing only the latest would hide exactly that.
    run_finals: list[float] = field(default_factory=list)

    @property
    def first_ts(self) -> str:
        return self.runs[0].ts_start if self.runs else ""

    @property
    def last_ts(self) -> str:
        return self.runs[-1].ts_start if self.runs else ""

    @property
    def latest_ok(self) -> Run | None:
        for run in reversed(self.runs):
            if run.ok:
                return run
        return self.runs[-1] if self.runs else None

    @property
    def marked(self) -> bool:
        return any(run.marked for run in self.runs)

    @property
    def note(self) -> str:
        """The most recent non-empty checkpoint note among this version's runs."""
        for run in reversed(self.runs):
            if run.marked and run.checkpoint_note:
                return run.checkpoint_note
        return ""


def is_minor(previous: str, current: str, max_chars: int = DEFAULT_MINOR_MAX_CHARS) -> bool:
    """A change so small it shouldn't clutter the timeline, e.g. ``0.1`` → ``0.01``.

    Two conditions, both required (SPEC 10.5): at most one line differs, and the
    character-level edit is at most ``max_chars`` long. Minor versions are still kept
    and numbered — they're just collapsed in the UI as "3 small edits".
    """
    before, after = previous.split("\n"), current.split("\n")
    changed_lines = sum(
        max(i2 - i1, j2 - j1)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, before, after).get_opcodes()
        if op != "equal"
    )
    if changed_lines > 1:
        return False

    changed_chars = sum(
        (i2 - i1) + (j2 - j1)
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, previous, current).get_opcodes()
        if op != "equal"
    )
    return changed_chars <= max_chars


def group(
    identity: Identity,
    minor_max_chars: int = DEFAULT_MINOR_MAX_CHARS,
    extra_patterns: list[str] | None = None,
    all_runs: list[Run] | None = None,
) -> list[Version]:
    """Fold one cell's runs into its versions, in order."""
    versions: list[Version] = []
    current: Version | None = None
    pending: list[Attempt] = []

    def start(run: Run, minor: bool = False) -> Version:
        version = Version(
            n=len(versions) + 1,
            code=run.code,
            code_hash=run.norm.code_hash,
            semantic_hash=run.norm.semantic_hash,
            minor=minor,
            runs=[run],
        )
        versions.append(version)
        return version

    for run in identity.runs:
        if run.skipped:
            continue

        if not run.ok:
            if current is not None and run.norm.semantic_hash == current.semantic_hash:
                # Same code, now failing: that's state, not an edit.
                current.failed_runs.append(run)
            else:
                pending.append(Attempt(run, run.error_type))
            continue

        if current is None:
            current = start(run)
        elif run.tags.fix:
            # "That version was wrong even though it ran" — overwrite, don't branch.
            current.replaced_code.append(current.code)
            current.code = run.code
            current.code_hash = run.norm.code_hash
            current.semantic_hash = run.norm.semantic_hash
            current.runs.append(run)
        elif run.norm.semantic_hash == current.semantic_hash:
            current.runs.append(run)
            current.code = run.code  # comment-only edits update the text in place
            current.code_hash = run.norm.code_hash
        else:
            previous_semantic = current.runs[-1].norm.semantic
            minor = is_minor(previous_semantic, run.norm.semantic, minor_max_chars)
            current = start(run, minor=minor and not run.tags.keep)

        current.attempts.extend(pending)
        pending = []

    if pending and versions:
        versions[-1].attempts.extend(pending)
    elif pending:
        # Every run of this cell failed; keep them visible rather than dropping them.
        orphan = Version(n=1, code=pending[0].run.code, code_hash="", semantic_hash="")
        orphan.attempts.extend(pending)
        versions.append(orphan)

    own = {id(run) for run in identity.runs}
    for version in versions:
        _attach_metrics(version, extra_patterns, all_runs, own)
    return versions


def _clean_rerun_blocks(
    version: Version, all_runs: list[Run] | None, own: set[int]
) -> list[list[Run]]:
    """Split a version's runs into stretches with nothing else running in between.

    why: a "noise estimate" is only meaningful across genuinely identical conditions.
    If another cell ran between two executions — a new learning rate, a reshaped
    tensor — the spread between them is not noise, it is that change. Reporting it as
    noise would be worse than reporting nothing.
    """
    ok_runs = [run for run in version.runs if run.ok]
    if all_runs is None or len(ok_runs) < 2:
        return [ok_runs] if len(ok_runs) >= 2 else []

    blocks: list[list[Run]] = [[ok_runs[0]]]
    for previous, current in zip(ok_runs, ok_runs[1:], strict=False):
        interrupted = any(
            id(other) not in own
            and not other.skipped
            and previous.ts_start < other.ts_start <= current.ts_start
            for other in all_runs
        )
        if interrupted:
            blocks.append([current])
        else:
            blocks[-1].append(current)
    return [block for block in blocks if len(block) >= 2]


def _attach_metrics(
    version: Version,
    extra_patterns: list[str] | None,
    all_runs: list[Run] | None = None,
    own: set[int] | None = None,
) -> None:
    latest = version.latest_ok
    version.metrics = extract(latest, extra_patterns) if latest is not None else {}

    # Identical re-runs give a free noise estimate: how much does this number move
    # when nothing changed? Without it, "3.31 → 3.28" looks like progress.
    name = primary_name(version.metrics)
    if not name or name == "duration_s":
        return

    version.run_finals = []
    for run in version.runs:
        if not run.ok:
            continue
        value = extract(run, extra_patterns).get(name, {}).get("final")
        if isinstance(value, (int, float)):
            version.run_finals.append(float(value))

    best: float | None = None
    for block in _clean_rerun_blocks(version, all_runs, own or set()):
        finals = []
        for run in block:
            value = extract(run, extra_patterns).get(name, {}).get("final")
            if isinstance(value, (int, float)):
                finals.append(float(value))
        spread = noise_estimate(finals)
        if spread is not None and (best is None or spread > best):
            best = spread
    version.loss_std = best
