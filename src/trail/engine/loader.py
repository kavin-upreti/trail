"""Reading raw logs back (SPEC 10.1).

Tolerance is the whole job. These files are written by a background thread inside a
kernel that may be killed at any moment, then synced by Google Drive, which is
happy to leave a half-written last line or drop a second copy named "name (1).jsonl".
None of that is an error; it is the normal shape of the input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trail.common.normalize import Normalized, analyse
from trail.common.paths import ProjectPaths
from trail.common.tags import Tags
from trail.common.tags import parse as parse_tags

SCHEMA_VERSION = 1


@dataclass
class Run:
    """One execution of one cell, with the derived bits the engine needs."""

    raw: dict[str, Any]
    norm: Normalized
    tags: Tags

    @property
    def session(self) -> str:
        return str(self.raw.get("session", ""))

    @property
    def seq(self) -> int:
        return int(self.raw.get("seq", 0))

    @property
    def key(self) -> tuple[str, int]:
        return (self.session, self.seq)

    @property
    def ts_start(self) -> str:
        return str(self.raw.get("ts_start") or self.raw.get("ts") or "")

    @property
    def status(self) -> str:
        return str(self.raw.get("status", "ok"))

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def skipped(self) -> bool:
        return bool(self.raw.get("skipped"))

    @property
    def code(self) -> str:
        return str(self.raw.get("code", ""))

    @property
    def cell_id(self) -> str | None:
        value = self.raw.get("cell_id")
        return str(value) if value else None

    @property
    def duration_s(self) -> float:
        try:
            return float(self.raw.get("duration_s") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def error_type(self) -> str | None:
        error = self.raw.get("error")
        return str(error.get("type")) if isinstance(error, dict) else None

    @property
    def stdout(self) -> str:
        block = self.raw.get("stdout")
        return str(block.get("text", "")) if isinstance(block, dict) else ""

    @property
    def vars(self) -> dict[str, Any]:
        value = self.raw.get("vars")
        return value if isinstance(value, dict) else {}

    @property
    def displays(self) -> list[dict[str, Any]]:
        value = self.raw.get("displays")
        return value if isinstance(value, list) else []

    @property
    def marked(self) -> bool:
        """Did the user flag this run as a checkpoint, by tag or by function call?"""
        return self.tags.checkpoint or bool(self.raw.get("checkpoint_call"))

    @property
    def checkpoint_note(self) -> str:
        call = self.raw.get("checkpoint_call")
        if isinstance(call, str) and call.strip():
            return call.strip()
        return self.tags.checkpoint_note


@dataclass
class Session:
    id: str
    start: str = ""
    end: str = ""
    clean: bool = False
    frontend: str = ""
    notebook: str | None = None
    runs: int = 0


@dataclass
class LoadedProject:
    runs: list[Run] = field(default_factory=list)
    sessions: dict[str, Session] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    markers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _iter_records(path: Path, warnings: list[str]) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"couldn't read {path.name}: {exc}")
        return []

    lines = text.split("\n")
    records: list[dict[str, Any]] = []
    bad_mid_file = 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            # A broken *last* line is a partially synced write, and expected.
            if index >= len(lines) - 2:
                continue
            bad_mid_file += 1
            continue
        if isinstance(record, dict):
            records.append(record)
    if bad_mid_file:
        warnings.append(f"{path.name}: skipped {bad_mid_file} unreadable line(s)")
    return records


def load(paths: ProjectPaths) -> LoadedProject:
    """Read every session file for a project into one ordered list of runs."""
    loaded = LoadedProject()
    if not paths.runs.is_dir():
        return loaded

    seen: set[tuple[str, int]] = set()
    newer_schema = False

    for path in sorted(paths.runs.glob("*.jsonl")):
        for record in _iter_records(path, loaded.warnings):
            kind = record.get("type")
            try:
                if int(record.get("schema", SCHEMA_VERSION)) > SCHEMA_VERSION:
                    newer_schema = True
            except (TypeError, ValueError):
                pass

            if kind == "run":
                run = Run(
                    record, analyse(record.get("code", "")), parse_tags(record.get("code", ""))
                )
                # Drive conflict copies duplicate whole files; (session, seq) is unique.
                if run.key in seen:
                    continue
                seen.add(run.key)
                loaded.runs.append(run)
            elif kind == "session_start":
                session = loaded.sessions.setdefault(
                    str(record.get("session", "")), Session(str(record.get("session", "")))
                )
                session.start = str(record.get("ts", ""))
                session.frontend = str(record.get("frontend", ""))
                session.notebook = record.get("notebook")
            elif kind == "session_end":
                session = loaded.sessions.setdefault(
                    str(record.get("session", "")), Session(str(record.get("session", "")))
                )
                session.end = str(record.get("ts", ""))
                session.clean = bool(record.get("clean"))
                session.runs = int(record.get("runs") or 0)
            elif kind == "note":
                loaded.notes.append(record)
            elif kind == "marker":
                loaded.markers.append(record)
            elif kind is not None:
                loaded.warnings.append(f"ignored unknown record type {kind!r}")

    if newer_schema:
        loaded.warnings.append(
            "These logs were written by a newer Trail; update Trail on this Mac."
        )

    # Global order: wall clock first, then per-session sequence for ties.
    loaded.runs.sort(key=lambda r: (r.ts_start, r.session, r.seq))

    for run in loaded.runs:
        session = loaded.sessions.setdefault(run.session, Session(run.session))
        if not session.start:
            session.start = run.ts_start
        if not session.end or run.ts_start > session.end:
            session.end = run.ts_start

    for session in loaded.sessions.values():
        if not session.clean and session.end:
            # No session_end record: the kernel was restarted or crashed (SPEC 7.3).
            session.runs = session.runs or 0

    unknown_tags = sorted({t for run in loaded.runs for t in run.tags.unknown})
    if unknown_tags:
        loaded.warnings.append(f"unknown tag(s) ignored: {', '.join(unknown_tags)}")

    return loaded
