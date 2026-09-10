"""Trail — record how notebook code evolves, and explain the optimisations.

Everything you need in a notebook::

    import trail
    trail.start("makemore-3")
    ...                          # code along; tag cells with # @cell: name and # @cp note
    trail.stop()

The whole public surface is defined here (SPEC 9.1). One module-level Session holds
the recording, because one kernel records one thing at a time.
"""

from __future__ import annotations

from trail._version import __version__
from trail.capture.session import Session

__all__ = [
    "__version__",
    "checkpoint",
    "metric",
    "note",
    "pause",
    "report",
    "resume",
    "session",
    "start",
    "status",
    "stop",
]

_session = Session()


def session() -> Session:
    """The live Session object. Handy for debugging; not needed for normal use."""
    return _session


def start(project: str | None = None, root: str | None = None) -> None:
    """Start recording this kernel into ``project``.

    Safe to call twice — the same project just prints its status, and a different one
    stops the current recording first. In VS Code the project name defaults to the
    notebook's filename.
    """
    _session.start(project, root)


def stop(unmount: bool | None = None) -> None:
    """Stop recording, flush everything to disk, and put the streams back.

    In Colab this also flushes and unmounts Google Drive so your logs actually
    upload; pass ``unmount=False`` if you want to keep working in the same runtime.
    """
    _session.stop(unmount)


def pause() -> None:
    """Stop capturing cells without ending the session."""
    _session.pause()


def resume() -> None:
    """Resume after :func:`pause`."""
    _session.resume()


def status(verbose: bool = False) -> None:
    """Print what Trail is currently recording, and any warnings."""
    _session.status(verbose)


def checkpoint(note: str = "") -> None:
    """Mark the current cell as a checkpoint — a moment worth explaining.

    Equivalent to putting ``# @cp your note`` in the cell. Only checkpoints get
    analysed, and the note is passed to Claude.
    """
    _session.checkpoint(note)


def note(text: str) -> None:
    """Attach a free-text note to the current run."""
    _session.note(text)


def metric(name: str, value: float) -> None:
    """Record a number you care about, e.g. ``trail.metric("val_loss", 2.07)``.

    Explicit metrics beat anything Trail can parse out of your printed output.
    """
    _session.metric(name, value)


def report() -> None:
    """Print a diagnostic report: what was captured, where it went, what failed."""
    _session.report()


def load_ipython_extension(ip: object) -> None:
    """Support ``%load_ext trail``."""
    print('Trail loaded. Start recording with: trail.start("your-project-name")')
