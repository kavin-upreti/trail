"""Which cell is this? (SPEC 10.3)

Three ways to answer, best first:

1. A ``# trail: cell <name>`` tag. Explicit, stable, survives anything.
2. The frontend's ``cell_id``. Free when available.
3. Fuzzy matching on the code itself.

ADR 0004 promoted (3) from a fallback to *the* mechanism on Colab, which sends no
cell ids at all. So it has to be good: an incrementally edited cell must keep its
identity, while a genuinely new cell must not steal one.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from trail.engine.loader import Run

DEFAULT_FUZZY_THRESHOLD = 0.5

#: How many recent identities to compare against. Beyond this it's both slow and
#: meaningless — a cell you last touched 50 cells ago isn't what you just edited.
MAX_CANDIDATES = 50

_SETUP_PREFIXES = ("%", "!", "import ", "from ", "trail.", "drive.mount")


@dataclass
class Identity:
    key: str
    name: str
    hidden: bool = False
    runs: list[Run] = field(default_factory=list)
    latest_semantic: str = ""

    @property
    def first_ts(self) -> str:
        return self.runs[0].ts_start if self.runs else ""

    @property
    def last_ts(self) -> str:
        return self.runs[-1].ts_start if self.runs else ""


def display_name(run: Run) -> str:
    """Name an untagged cell after its first line of real code."""
    for line in run.norm.semantic.split("\n"):
        text = line.strip()
        if text:
            return text[:40] + ("…" if len(text) > 40 else "")
    return "(empty cell)"


def is_setup(semantic: str) -> bool:
    """Setup cells are still recorded, just collapsed in the UI (SPEC 10.4)."""
    lines = [line.strip() for line in semantic.split("\n") if line.strip()]
    if not lines:
        return False
    return all(line.startswith(_SETUP_PREFIXES) for line in lines)


def _best_fuzzy_match(
    run: Run, identities: dict[str, Identity], order: list[str], threshold: float
) -> str | None:
    """Closest recently-seen identity by line similarity, if any clears the bar."""
    target = run.norm.semantic.split("\n")
    if not any(line.strip() for line in target):
        return None

    best_key: str | None = None
    best_ratio = 0.0
    for key in reversed(order[-MAX_CANDIDATES:]):  # most recently run first
        identity = identities[key]
        if not identity.latest_semantic:
            continue
        matcher = difflib.SequenceMatcher(None, identity.latest_semantic.split("\n"), target)
        # why: real_quick_ratio is a cheap upper bound — skip hopeless pairs before
        # paying for the full diff, which matters on a lecture with hundreds of runs.
        if matcher.real_quick_ratio() < best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_key, best_ratio = key, ratio

    return best_key if best_ratio >= threshold else None


def resolve(
    runs: list[Run], threshold: float = DEFAULT_FUZZY_THRESHOLD
) -> tuple[dict[str, Identity], list[str]]:
    """Assign every run an identity, in global order. Returns identities + warnings."""
    identities: dict[str, Identity] = {}
    order: list[str] = []
    warnings: list[str] = []
    cell_id_to_key: dict[str, str] = {}
    tag_cell_ids: dict[str, set[str]] = {}
    auto_counter = 0

    def touch(key: str, run: Run, name: str | None = None) -> None:
        identity = identities.get(key)
        if identity is None:
            identity = Identity(key, name or display_name(run))
            identities[key] = identity
        identity.runs.append(run)
        if run.ok:
            identity.latest_semantic = run.norm.semantic
        if key in order:
            order.remove(key)
        order.append(key)

    for run in runs:
        if run.skipped:
            continue

        if run.tags.cell:
            key = f"tag:{run.tags.cell}"
            if run.cell_id:
                # Remember it, so later untagged runs of the same cell stay linked.
                cell_id_to_key[run.cell_id] = key
                tag_cell_ids.setdefault(run.tags.cell, set()).add(run.cell_id)
            touch(key, run, name=run.tags.cell)
            continue

        if run.cell_id:
            key = cell_id_to_key.get(run.cell_id, f"id:{run.cell_id}")
            touch(key, run)
            continue

        match = _best_fuzzy_match(run, identities, order, threshold)
        if match is not None:
            touch(match, run)
            continue

        auto_counter += 1
        touch(f"auto:{auto_counter}", run)

    for slug, ids in tag_cell_ids.items():
        if len(ids) > 1:
            warnings.append(
                f"Tag `{slug}` seems to be on {len(ids)} different cells (maybe a duplicated cell)."
            )

    for identity in identities.values():
        if identity.runs:
            latest = identity.latest_semantic or identity.runs[-1].norm.semantic
            identity.hidden = is_setup(latest)

    return identities, warnings
