"""Checkpoints into steps (SPEC 10.6).

A *step* is the unit Claude explains: everything that changed between one checkpoint
and the next. The subtle rule is anchoring — while you're iterating on the same idea
you keep the same `# trail: cp` note, and all those versions belong to *one* step,
anchored at the last of them (where the idea ended up). Changing or removing the note
closes the step.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from trail.engine.grouping import Version

#: A note left unchanged for this many versions is probably forgotten, not deliberate.
STALE_NOTE_VERSIONS = 5


@dataclass
class Step:
    key: str
    identity: str
    start_n: int
    end_n: int
    note: str
    ts: str

    @property
    def span(self) -> int:
        return self.end_n - self.start_n + 1


def _key(start: Version, end: Version, note: str) -> str:
    raw = f"{start.code_hash}{end.code_hash}{note}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def find(identity_key: str, versions: list[Version]) -> tuple[list[Step], list[str]]:
    """Collapse marked versions into steps. Returns steps + warnings."""
    steps: list[Step] = []
    warnings: list[str] = []
    if not versions:
        return steps, warnings

    # Group consecutive marked versions that share a note; anchor on the last.
    anchors: list[tuple[Version, str]] = []
    run_start: Version | None = None
    run_note: str | None = None
    run_len = 0

    def close(last: Version) -> None:
        nonlocal run_start, run_note, run_len
        if run_start is not None and run_note is not None:
            anchors.append((last, run_note))
            if run_len > STALE_NOTE_VERSIONS:
                warnings.append(
                    f"`{identity_key}`: the checkpoint note {run_note!r} has stayed the "
                    f"same for {run_len} versions — did you forget to change or remove it?"
                )
        run_start, run_note, run_len = None, None, 0

    previous: Version | None = None
    for version in versions:
        if version.marked:
            note = version.note
            if run_note is not None and note == run_note:
                run_len += 1
            else:
                if previous is not None and run_note is not None:
                    close(previous)
                run_start, run_note, run_len = version, note, 1
        elif run_note is not None and previous is not None:
            close(previous)
        previous = version
    if run_note is not None and previous is not None:
        close(previous)

    by_n = {v.n: v for v in versions}
    previous_anchor_n = versions[0].n
    for anchor, note in anchors:
        start = by_n.get(previous_anchor_n, versions[0])
        steps.append(
            Step(
                key=_key(start, anchor, note),
                identity=identity_key,
                start_n=start.n,
                end_n=anchor.n,
                note=note,
                ts=anchor.last_ts,
            )
        )
        previous_anchor_n = anchor.n

    return steps, warnings


def story_order(steps: list[Step]) -> list[Step]:
    """Chronological across the whole project — the order the lecture happened in."""
    return sorted(steps, key=lambda s: s.ts)
