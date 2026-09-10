"""Layout of a logs root and a project folder (SPEC 6).

One place that knows where everything lives, so capture and the engine can never
disagree. Paths routinely contain spaces (Google Drive's "My Drive") — hard rule 8 —
so everything here is a ``pathlib.Path``, never a string that gets concatenated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT_MARKER = ".trail-root"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProjectPaths:
    """Every path inside one project's folder."""

    root: Path
    project: str

    @property
    def dir(self) -> Path:
        return self.root / self.project

    @property
    def runs(self) -> Path:
        return self.dir / "runs"

    @property
    def blobs(self) -> Path:
        return self.dir / "blobs"

    @property
    def derived(self) -> Path:
        return self.dir / "derived"

    @property
    def analyses(self) -> Path:
        return self.dir / "analyses"

    @property
    def qa(self) -> Path:
        return self.dir / "qa"

    @property
    def fallback_imported(self) -> Path:
        return self.dir / "fallback-imported"

    @property
    def overrides(self) -> Path:
        return self.dir / "overrides.json"

    @property
    def errors_log(self) -> Path:
        return self.dir / "trail-errors.log"

    @property
    def claude_md(self) -> Path:
        return self.dir / "CLAUDE.md"

    def session_file(self, session_id: str) -> Path:
        return self.runs / f"{session_id}.jsonl"

    def blob(self, sha: str, ext: str) -> Path:
        return self.blobs / f"{sha}.{ext}"

    def ensure(self) -> None:
        """Create the directories capture writes into."""
        for path in (self.runs, self.blobs):
            path.mkdir(parents=True, exist_ok=True)


def ensure_root(root: Path) -> Path:
    """Create the logs root and its marker file if missing."""
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ROOT_MARKER
    if not marker.exists():
        from trail.capture.schema import utc_now

        marker.write_text(
            json.dumps({"created": utc_now(), "schema": SCHEMA_VERSION}), encoding="utf-8"
        )
    return root


def is_root(path: Path) -> bool:
    return (path / ROOT_MARKER).is_file()


def projects(root: Path) -> list[str]:
    """Project folder names inside a logs root, newest activity last."""
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "runs").is_dir())
