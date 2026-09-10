"""Session lifecycle (SPEC 8.8) — the piece that owns a kernel's recording.

Hard rule 1 governs this whole file: **capture must never break or noticeably slow
the user's notebook.** Every hook body is wrapped in ``try/except Exception``,
internal failures go to ``trail-errors.log``, and the user sees at most one short
warning per session. Nothing here is allowed to raise into a cell.
"""

from __future__ import annotations

import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from trail.capture import env, schema
from trail.capture.display import DisplayCapture
from trail.capture.fingerprint import take as take_fingerprint
from trail.capture.hooks import Hooks, is_silent
from trail.capture.redact import redact
from trail.capture.tee import Tee
from trail.capture.writer import Writer, merge_fallback
from trail.common import tags as tagmod
from trail.common.paths import ProjectPaths, ensure_root

MANUAL_SEED_RE = re.compile(r"manual_seed\(\s*(\d+)\s*\)")
SKIPPED_CODE_CHARS = 200


class _ActiveRun:
    """Everything gathered between pre_run_cell and post_run_cell."""

    __slots__ = (
        "code",
        "cell_id",
        "ts_start",
        "perf_start",
        "tags",
        "stdout",
        "stderr",
        "checkpoint_note",
        "notes",
        "metrics",
    )

    def __init__(self, code: str, cell_id: str | None, parsed: tagmod.Tags) -> None:
        self.code = code
        self.cell_id = cell_id
        self.ts_start = schema.utc_now()
        self.perf_start = time.perf_counter()
        self.tags = parsed
        self.stdout: Tee | None = None
        self.stderr: Tee | None = None
        self.checkpoint_note: str | None = None
        self.notes: list[str] = []
        self.metrics: list[dict[str, Any]] = []


class Session:
    """One kernel lifetime of recording, from start() to stop()."""

    def __init__(self) -> None:
        self.project: str | None = None
        self.paths: ProjectPaths | None = None
        self.session_id: str | None = None
        self.frontend: str = env.IPYTHON
        self.writer: Writer | None = None
        self.display: DisplayCapture | None = None
        self.hooks: Hooks | None = None
        self.shell: Any = None
        self.paused = False
        self.run_count = 0
        self.seq = 0
        self.warnings: list[str] = []
        self.merged_fallback = 0
        self._active: _ActiveRun | None = None
        self._warned = False
        self._device: dict[str, str] | None = None
        self._write_latencies: list[float] = []

    # -- state ------------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self.writer is not None

    def _warn_once(self, message: str) -> None:
        """At most one visible warning per session (hard rule 1)."""
        self.warnings.append(message)
        if not self._warned:
            self._warned = True
            print(f"Trail: {message}", file=sys.__stderr__)

    def _log_error(self, where: str, exc: BaseException) -> None:
        if self.paths is None:
            return
        try:
            self.paths.errors_log.parent.mkdir(parents=True, exist_ok=True)
            with self.paths.errors_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{schema.utc_now()} {where} {type(exc).__name__}: {exc}\n")
                handle.write("".join(traceback.format_exception(exc))[:4000])
        except Exception:
            pass

    # -- start / stop -----------------------------------------------------

    def start(self, project: str | None = None, root: str | None = None) -> None:
        shell = _get_shell()
        if shell is None:
            raise RuntimeError(
                "Trail records notebook cells, and there's no IPython kernel here. "
                "For a .py script, script mode isn't built yet (see the README)."
            )

        frontend = env.detect_frontend(shell)
        slug = self._resolve_project(project, shell, frontend)

        if self.recording:
            if slug == self.project:
                self.status()
                return
            print(f"Trail: switching from {self.project} to {slug}.")
            self.stop(unmount=False)

        logs_root = env.resolve_root(root, frontend)
        if not env.ensure_drive_mounted(logs_root, printer=print):
            local = env.fallback_dir(slug, frontend)
            self._warn_once(f"couldn't mount Google Drive; recording to {local}")

        self.shell = shell
        self.frontend = frontend
        self.project = slug
        self.session_id = schema.new_session_id()
        self.run_count = 0
        self.seq = 0
        self.paused = False
        self.warnings = []
        self._warned = False
        self._device = None
        self._write_latencies = []

        try:
            ensure_root(logs_root)
        except Exception as exc:
            self._log_error("ensure_root", exc)
        self.paths = ProjectPaths(Path(logs_root), slug)

        fallback = env.fallback_dir(slug, frontend)
        self.writer = Writer(self.paths, self.session_id, fallback, warn=self._warn_once)
        self.writer.start()
        self.merged_fallback = merge_fallback(self.paths, fallback)

        self.display = DisplayCapture(self.writer.submit_blob)
        self.display.install(shell)
        self.hooks = Hooks(self.on_pre, self.on_post)
        self.hooks.register(shell)

        self.writer.submit(
            schema.session_start(self.session_id, project=slug, **env.session_info(shell))
        )

        print(f"Trail recording → {slug} (session {self.session_id})")
        print(f"  logs: {self.paths.dir}")
        if self.merged_fallback:
            print(f"  merged {self.merged_fallback} file(s) from a previous fallback run")

    def _resolve_project(self, project: str | None, shell: Any, frontend: str) -> str:
        if project:
            slug = tagmod.slugify(project)
            if not slug:
                raise ValueError(f"{project!r} doesn't contain any letters or digits to name it.")
            if slug != project:
                print(f"Trail: using '{slug}' as the project name.")
            return slug

        notebook = env.notebook_path(shell)
        if notebook:
            slug = tagmod.slugify(Path(notebook).stem)
            if slug:
                return slug
        raise ValueError(
            'Trail needs a project name, e.g. trail.start("makemore-3"). '
            "It groups one lecture's history together."
        )

    def stop(self, unmount: bool | None = None) -> None:
        if not self.recording:
            print("Trail isn't recording.")
            return

        if self.hooks is not None:
            self.hooks.unregister()
        if self.display is not None:
            self.display.uninstall()
        self._restore_streams()

        writer, paths, project = self.writer, self.paths, self.project
        assert writer is not None and paths is not None
        writer.submit(schema.session_end(self.session_id or "", self.run_count, clean=True))
        writer.flush(timeout=10.0)
        writer.stop()

        self.writer = None
        self.hooks = None
        self.display = None
        self._active = None

        if writer.using_fallback:
            merge_fallback(paths, env.fallback_dir(project or "", self.frontend))

        print(f"Trail stopped. {self.run_count} run(s) recorded in {paths.dir}")

        if unmount is None:
            unmount = self.frontend == env.COLAB
        if unmount and self.frontend == env.COLAB:
            self._unmount_drive()

    def _unmount_drive(self) -> None:
        try:
            from google.colab import drive

            drive.flush_and_unmount()
            print("  Google Drive flushed and unmounted, so your logs are uploaded.")
        except Exception as exc:
            self._log_error("unmount", exc)

    def pause(self) -> None:
        if not self.recording or self.paused:
            return
        self.paused = True
        self._submit(schema.marker(self.session_id or "", "pause"))
        print("Trail paused.")

    def resume(self) -> None:
        if not self.recording or not self.paused:
            return
        self.paused = False
        self._submit(schema.marker(self.session_id or "", "resume"))
        print("Trail resumed.")

    def _submit(self, record: dict[str, Any]) -> None:
        if self.writer is not None:
            self.writer.submit(record)

    # -- marks from user code --------------------------------------------

    def checkpoint(self, note: str = "") -> None:
        if self._active is not None:
            self._active.checkpoint_note = note
            self._active.notes.append("checkpoint via trail.checkpoint()")
        elif self.recording:
            self._submit(schema.note(self.session_id or "", f"checkpoint (no active cell): {note}"))

    def note(self, text: str) -> None:
        if self._active is not None:
            self._active.notes.append(text)
        elif self.recording:
            self._submit(schema.note(self.session_id or "", text))

    def metric(self, name: str, value: float) -> None:
        if self._active is None:
            return
        try:
            self._active.metrics.append(
                {"name": str(name), "value": float(value), "source": "explicit"}
            )
        except (TypeError, ValueError):
            pass

    # -- the hooks --------------------------------------------------------

    def on_pre(self, info: Any) -> None:
        try:
            if self.paused or not self.recording or is_silent(info):
                return
            code = getattr(info, "raw_cell", "") or ""
            parsed = tagmod.parse(code)
            run = _ActiveRun(code, getattr(info, "cell_id", None), parsed)
            self._active = run

            if parsed.skip:
                return  # SPEC 7.2: skipped cells get a minimal record, and no capture.

            run.stdout = Tee(sys.stdout)
            run.stderr = Tee(sys.stderr)
            sys.stdout, sys.stderr = run.stdout, run.stderr
            if self.display is not None:
                self.display.begin_run()
        except Exception as exc:
            self._active = None
            self._log_error("on_pre", exc)

    def on_post(self, result: Any) -> None:
        run, self._active = self._active, None
        try:
            # SPEC 8.2: post fires without a pre for the very cell that called start().
            if run is None or not self.recording:
                return
            self._restore_streams()
            duration = time.perf_counter() - run.perf_start
            self.seq += 1

            if run.tags.skip:
                self._submit(self._skipped_record(run, duration))
                return

            record = self._build_record(run, result, duration)
            started = time.perf_counter()
            self._submit(record)
            self._write_latencies.append(time.perf_counter() - started)
            self.run_count += 1
        except Exception as exc:
            self._log_error("on_post", exc)
            try:
                self._restore_streams()
            except Exception:
                pass

    def _restore_streams(self) -> None:
        if isinstance(sys.stdout, Tee):
            sys.stdout = sys.stdout._orig
        if isinstance(sys.stderr, Tee):
            sys.stderr = sys.stderr._orig

    def _skipped_record(self, run: _ActiveRun, duration: float) -> dict[str, Any]:
        return {
            "type": "run",
            "schema": schema.SCHEMA_VERSION,
            "session": self.session_id,
            "seq": self.seq,
            "ts_start": run.ts_start,
            "duration_s": round(duration, 4),
            "cell_id": run.cell_id,
            "code": redact(run.code)[:SKIPPED_CODE_CHARS],
            "status": "ok",
            "skipped": True,
        }

    def _build_record(self, run: _ActiveRun, result: Any, duration: float) -> dict[str, Any]:
        status, error = _classify(result)
        displays = self.display.end_run() if self.display is not None else []

        record: dict[str, Any] = {
            "type": "run",
            "schema": schema.SCHEMA_VERSION,
            "session": self.session_id,
            "seq": self.seq,
            "exec_count": getattr(result, "execution_count", None),
            "ts_start": run.ts_start,
            "duration_s": round(duration, 4),
            "cell_id": run.cell_id,
            "code": redact(run.code),
            "status": status,
            "error": error,
            "stdout": _stream(run.stdout),
            "stderr": _stream(run.stderr),
            "result_repr": _result_repr(result),
            "displays": displays,
            "vars": self._fingerprint(),
            "metrics": run.metrics,
            "notes": run.notes,
            "checkpoint_call": run.checkpoint_note,
            "seed": self._seed(run.code),
            "skipped": False,
        }
        record.update(self._device_info())
        return record

    def _fingerprint(self) -> dict[str, Any]:
        try:
            return take_fingerprint(self.shell.user_ns)
        except Exception:
            return {}

    def _seed(self, code: str) -> dict[str, Any]:
        seed: dict[str, Any] = {
            "manual_seed_literals": [int(m) for m in MANUAL_SEED_RE.findall(code)[:8]]
        }
        if "torch" in sys.modules:
            try:
                seed["torch_initial_seed"] = sys.modules["torch"].initial_seed()
            except Exception:
                pass
        return seed

    def _device_info(self) -> dict[str, str]:
        # Computed once per session: torch.cuda.get_device_name is not free.
        if self._device is None:
            self._device = env.device_info()
        return self._device

    # -- user-facing reporting -------------------------------------------

    def status(self, verbose: bool = False) -> None:
        if not self.recording:
            print('Trail isn\'t recording. Start with trail.start("project-name").')
            return
        assert self.paths is not None and self.writer is not None
        state = "paused" if self.paused else "recording"
        print(f"Trail {state} → {self.project} (session {self.session_id})")
        print(f"  {self.run_count} run(s) captured · logs: {self.paths.dir}")
        if self.writer.using_fallback:
            print(f"  ⚠ writing to fallback: {self.writer.fallback}")
        if self.warnings:
            print(f"  {len(self.warnings)} warning(s); latest: {self.warnings[-1]}")
        if verbose:
            print(f"  frontend={self.frontend} blobs={self.writer.blob_bytes / 1e6:.1f} MB")

    def report(self) -> None:
        """Diagnostic dump for the Colab spike (SPEC 20.2)."""
        import platform

        print("=== Trail report ===")
        print(f"trail       : {_trail_version()}")
        print(f"frontend    : {self.frontend}")
        print(f"python      : {platform.python_version()}")
        for name in ("IPython", "ipykernel"):
            print(f"{name:<12}: {_module_version(name)}")
        print(f"project     : {self.project}")
        print(f"session     : {self.session_id}")
        print(f"logs path   : {self.paths.dir if self.paths else '(none)'}")
        print(f"runs        : {self.run_count} (skipped cells are logged but not counted)")

        if self.paths is not None and self.session_id is not None:
            _report_from_log(self.paths.session_file(self.session_id))

        if self.writer is not None:
            print(f"fallback    : {self.writer.fallback if self.writer.using_fallback else 'no'}")
            print(f"blob bytes  : {self.writer.blob_bytes}")
            print(f"writer errs : {self.writer.errors}")
        if self._write_latencies:
            ordered = sorted(self._write_latencies)
            p50 = ordered[len(ordered) // 2] * 1000
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000
            print(f"submit ms   : p50={p50:.3f} p95={p95:.3f}")
        print(f"warnings    : {len(self.warnings)}")
        for warning in self.warnings[-5:]:
            print(f"  - {warning}")
        errors_log = self.paths.errors_log if self.paths else None
        if errors_log is not None and errors_log.exists():
            print(f"internal errors logged in {errors_log}")


# -- helpers ----------------------------------------------------------------


def _get_shell() -> Any:
    try:
        from IPython import get_ipython
    except ImportError:
        return None
    return get_ipython()


def _trail_version() -> str:
    from trail._version import __version__

    return __version__


def _module_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "not installed"


def _stream(tee: Tee | None) -> dict[str, Any]:
    if tee is None:
        return {"text": "", "truncated": False, "total_lines": 0}
    block = tee.result()
    block["text"] = redact(block["text"])
    return block


def _classify(result: Any) -> tuple[str, dict[str, Any] | None]:
    """Map an ExecutionResult onto our status vocabulary (SPEC 7.2)."""
    before = getattr(result, "error_before_exec", None)
    during = getattr(result, "error_in_exec", None)

    if before is not None:
        return "syntax_error", _error_block(before, "compile")
    if during is not None:
        if isinstance(during, KeyboardInterrupt):
            return "interrupted", _error_block(during, "exec")
        return "error", _error_block(during, "exec")
    return "ok", None


def _error_block(exc: BaseException, stage: str) -> dict[str, Any]:
    try:
        tail = traceback.format_exception(type(exc), exc, exc.__traceback__)
    except Exception:
        tail = []
    return schema.error_block(
        type(exc).__name__,
        redact(str(exc)) or "",
        [line.rstrip("\n") for line in tail],
        stage,
    )


def _result_repr(result: Any) -> str | None:
    value = getattr(result, "result", None)
    if value is None:
        return None
    try:
        # why: repr() on a user object can be slow or throw (SPEC 7.2 says wrap it).
        text = repr(value)
    except Exception:
        return None
    return redact(text[: schema.MAX_RESULT_REPR])


def _report_from_log(path: Path) -> None:
    """Read back what actually landed on disk — the spike's whole point."""
    import json

    if not path.exists():
        print("log file    : not written yet")
        return
    runs = 0
    with_cell_id = 0
    with_stdout = 0
    with_stderr = 0
    mimes: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("type") != "run":
                continue
            runs += 1
            if record.get("cell_id"):
                with_cell_id += 1
            if (record.get("stdout") or {}).get("text"):
                with_stdout += 1
            if (record.get("stderr") or {}).get("text"):
                with_stderr += 1
            for display in record.get("displays") or []:
                mimes[display.get("mime", "?")] = mimes.get(display.get("mime", "?"), 0) + 1
    except Exception as exc:
        print(f"log file    : unreadable ({exc})")
        return

    print(f"log file    : {path} ({path.stat().st_size} bytes)")
    print(f"  runs on disk    : {runs}")
    print(f"  with cell_id    : {with_cell_id}/{runs}")
    print(f"  with stdout     : {with_stdout}/{runs}")
    print(f"  with stderr     : {with_stderr}/{runs}")
    print(f"  displays by mime: {mimes or 'none'}")
