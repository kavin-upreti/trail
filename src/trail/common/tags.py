"""Comment tags (SPEC 9.2).

A tag is a whole line that is only a comment, e.g. ``# @cell: mlp-init``. Because
they are ordinary comments the notebook still runs fine without Trail installed.

This module is shared by capture and the engine, so it must stay dependency-free
and must never raise on weird input — capture calls it on every cell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A tag owns the whole line: "# @name", "# @name value" or "# @name: value".
TAG_RE = re.compile(r"^\s*#\s*@(\w+)(?:[:\s]\s*(.*))?$")

KNOWN = frozenset({"cell", "cp", "checkpoint", "fix", "keep", "skip"})

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Turn arbitrary text into a project/cell slug, or "" if nothing survives."""
    slug = _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")[:64].strip("-")
    # why: the grammar requires the first character to be alphanumeric, and a
    # leading digit is fine, so only a fully-empty result is unusable.
    return slug if SLUG_RE.match(slug) else ""


@dataclass(frozen=True)
class Tags:
    """Every tag found in one cell's source."""

    cell: str | None = None
    checkpoint: bool = False
    checkpoint_note: str = ""
    fix: bool = False
    keep: bool = False
    skip: bool = False
    unknown: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(
            self.cell or self.checkpoint or self.fix or self.keep or self.skip or self.unknown
        )


def parse(code: str) -> Tags:
    """Read the tags out of a cell's source. Never raises."""
    cell: str | None = None
    checkpoint = False
    note = ""
    fix = keep = skip = False
    unknown: list[str] = []

    try:
        lines = code.splitlines()
    except Exception:
        return Tags()

    for line in lines:
        match = TAG_RE.match(line)
        if match is None:
            continue
        name = match.group(1).lower()
        value = (match.group(2) or "").strip()

        if name == "cell":
            slug = slugify(value)
            # why: an unusable @cell value is worse than none — falling back to
            # cell_id/fuzzy matching beats inventing a bogus identity.
            if slug:
                cell = slug
        elif name in ("cp", "checkpoint"):
            checkpoint = True
            if value:
                note = value
        elif name == "fix":
            fix = True
        elif name == "keep":
            keep = True
        elif name == "skip":
            skip = True
        else:
            unknown.append(name)

    return Tags(cell, checkpoint, note, fix, keep, skip, tuple(unknown))


def tag_lines(code: str) -> list[int]:
    """Indices of lines that are tags — the engine strips these when normalising."""
    try:
        return [i for i, line in enumerate(code.splitlines()) if TAG_RE.match(line)]
    except Exception:
        return []
