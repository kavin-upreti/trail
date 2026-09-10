"""Background writer (SPEC 8.7).

The cell hook's only job is to build a dict and put it on a queue; everything that
can block — Google Drive I/O, PNG writes, fsync — happens on one daemon thread.
That is what keeps the main-thread cost of recording a cell under a millisecond.

If the real logs root stops accepting writes (Drive disconnects, permissions change)
we switch to a local fallback folder and keep recording. Losing a lecture because a
sync client hiccupped would be far worse than a warning.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trail.capture.schema import enforce_size
from trail.common.paths import ProjectPaths

#: Per-session cap on image bytes, so a plotting-heavy lecture can't fill Drive.
BLOB_BUDGET_BYTES = 200 * 1024 * 1024

_STOP = object()


class Writer:
    """Serialises records and blobs onto disk from a single background thread."""

    def __init__(
        self,
        paths: ProjectPaths,
        session_id: str,
        fallback: Path,
        warn: Callable[[str], None] | None = None,
    ) -> None:
        self.paths = paths
        self.session_id = session_id
        self.fallback = fallback
        self._warn = warn or (lambda message: None)

        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._dir = paths.dir
        self.using_fallback = False
        self.blob_bytes = 0
        self.records_written = 0
        self.errors = 0
        self._seen_blobs: set[str] = set()
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        try:
            self.paths.ensure()
        except Exception:
            # why: hard rule 1. A logs root that refuses directories (Drive not
            # mounted yet, read-only mount, permissions) must cost a warning, never
            # the user's start() call.
            self._switch_to_fallback()
        self._thread = threading.Thread(target=self._run, name="trail-writer", daemon=True)
        self._thread.start()
        atexit.register(self._atexit)

    def stop(self, timeout: float = 10.0) -> None:
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)
        self._thread = None
        try:
            atexit.unregister(self._atexit)
        except Exception:
            pass

    def _atexit(self) -> None:
        # Best effort on a dying kernel: drain what we can, don't hang the shutdown.
        self.flush(timeout=3.0)

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait for the queue to drain. Returns False on timeout."""
        done = threading.Event()
        self._queue.put(("fsync", done))
        return done.wait(timeout)

    # -- submission (main thread; must stay cheap) ------------------------

    def submit(self, record: dict[str, Any]) -> None:
        self._queue.put(("record", record))

    def submit_blob(self, sha: str, ext: str, data: bytes) -> bool:
        """Queue an image. Returns False if it was dropped for budget reasons."""
        with self._lock:
            if sha in self._seen_blobs:
                return True  # content-addressed: already have it
            if self.blob_bytes + len(data) > BLOB_BUDGET_BYTES:
                return False
            self._seen_blobs.add(sha)
            self.blob_bytes += len(data)
        self._queue.put(("blob", sha, ext, data))
        return True

    # -- worker thread ----------------------------------------------------

    def _run(self) -> None:
        handle = None
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    break
                try:
                    kind = item[0]
                    if kind == "record":
                        handle = self._write_record(handle, item[1])
                    elif kind == "blob":
                        self._write_blob(item[1], item[2], item[3])
                    elif kind == "fsync":
                        self._fsync(handle)
                        item[1].set()
                except Exception as exc:
                    self.errors += 1
                    self._log_error(exc)
                finally:
                    self._queue.task_done()
        finally:
            self._fsync(handle)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass

    def _session_file(self) -> Path:
        return self._dir / "runs" / f"{self.session_id}.jsonl"

    def _write_record(self, handle: Any, record: dict[str, Any]) -> Any:
        if record.get("type") == "run":
            record = enforce_size(record)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        for attempt in (1, 2):
            try:
                if handle is None:
                    path = self._session_file()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = path.open("a", encoding="utf-8")
                handle.write(line)
                handle.flush()
                self.records_written += 1
                return handle
            except Exception:
                handle = None
                if attempt == 1 and not self.using_fallback:
                    self._switch_to_fallback()
                else:
                    raise
        return handle

    def _write_blob(self, sha: str, ext: str, data: bytes) -> None:
        target = self._dir / "blobs" / f"{sha}.{ext}"
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so a half-synced blob is never visible to the engine.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)

    def _switch_to_fallback(self) -> None:
        self.using_fallback = True
        self._dir = self.fallback
        try:
            (self._dir / "runs").mkdir(parents=True, exist_ok=True)
            (self._dir / "blobs").mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._warn(
            f"Trail couldn't write to {self.paths.dir}, so it's recording to "
            f"{self.fallback} instead. It'll merge them back on the next trail.start()."
        )

    def _fsync(self, handle: Any) -> None:
        if handle is None:
            return
        try:
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            pass

    def _log_error(self, exc: Exception) -> None:
        """Internal errors go to a file, never to the user's cell output."""
        try:
            from trail.capture.schema import utc_now

            path = self.paths.errors_log
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{utc_now()} writer {type(exc).__name__}: {exc}\n")
        except Exception:
            pass


def merge_fallback(paths: ProjectPaths, fallback: Path) -> int:
    """Copy any fallback session files into the real root. Returns files merged.

    Session ids are unique, so there is never a name clash and a copy is always safe
    to repeat. A marker records what has already been merged (SPEC 6, 8.7).
    """
    if not fallback.is_dir():
        return 0
    merged = 0
    try:
        paths.ensure()
        paths.fallback_imported.mkdir(parents=True, exist_ok=True)
        for sub, target in (("runs", paths.runs), ("blobs", paths.blobs)):
            source_dir = fallback / sub
            if not source_dir.is_dir():
                continue
            for source in source_dir.iterdir():
                if not source.is_file():
                    continue
                marker = paths.fallback_imported / f"{sub}-{source.name}"
                if marker.exists():
                    continue
                shutil.copy2(source, target / source.name)
                marker.write_text("", encoding="utf-8")
                merged += 1
    except Exception:
        return merged
    return merged
