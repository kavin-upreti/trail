"""Where are we running, and where do the logs go? (SPEC 6, 8.1)

All of this is best-effort: if detection is wrong the worst outcome is logs in a
slightly odd place, never a broken notebook.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

COLAB = "colab"
VSCODE = "vscode"
JUPYTER = "jupyter"
IPYTHON = "ipython"

CONFIG_PATH = Path.home() / ".config" / "trail" / "config.toml"
COLAB_DRIVE = Path("/content/drive")
COLAB_DEFAULT_ROOT = COLAB_DRIVE / "MyDrive" / "trail"
LOCAL_DEFAULT_ROOT = Path.home() / "trail-logs"

#: Read from metadata only — importing torch at start() costs seconds (SPEC 7.1).
TRACKED_PACKAGES = ("torch", "numpy", "matplotlib", "pandas")


def detect_frontend(shell: Any = None) -> str:
    """Which notebook frontend is driving this kernel."""
    if "google.colab" in sys.modules or os.environ.get("COLAB_RELEASE_TAG"):
        return COLAB

    user_ns = getattr(shell, "user_ns", {}) if shell is not None else {}
    in_vscode = os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_CWD")
    if "__vsc_ipynb_file__" in user_ns or in_vscode:
        return VSCODE

    if shell is not None and "ZMQ" in type(shell).__name__:
        return JUPYTER
    return IPYTHON


def notebook_path(shell: Any = None) -> str | None:
    """VS Code puts the notebook's path in the namespace; nobody else reliably does."""
    user_ns = getattr(shell, "user_ns", {}) if shell is not None else {}
    value = user_ns.get("__vsc_ipynb_file__")
    return str(value) if value else None


def package_versions() -> dict[str, str]:
    from importlib.metadata import version

    found: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            found[name] = version(name)
        except Exception:
            continue  # not installed, or a broken dist-info; either way, skip it
    return found


def device_info() -> dict[str, str]:
    """GPU details, but only if the user already imported torch (SPEC 7.2)."""
    if "torch" not in sys.modules:
        return {}
    try:
        torch = sys.modules["torch"]
        if not torch.cuda.is_available():
            return {"device": "cpu"}
        return {"device": "cuda", "gpu": torch.cuda.get_device_name(0)}
    except Exception:
        return {}


def session_info(shell: Any = None) -> dict[str, Any]:
    """The body of the ``session_start`` record."""
    from trail._version import __version__

    info: dict[str, Any] = {
        "trail_version": __version__,
        "frontend": detect_frontend(shell),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "notebook": notebook_path(shell),
        "packages": package_versions(),
    }
    info.update(device_info())
    return info


# -- logs root --------------------------------------------------------------


def _config_root() -> Path | None:
    """``logs_root`` from the Mac config file, when we're on the Mac."""
    try:
        import tomllib
    except ImportError:  # Python 3.10 has no tomllib; config is a Mac-side nicety.
        return None
    try:
        with CONFIG_PATH.open("rb") as handle:
            value = tomllib.load(handle).get("logs_root")
        return Path(value).expanduser() if value else None
    except Exception:
        return None


def resolve_root(
    explicit: str | os.PathLike[str] | None = None, frontend: str | None = None
) -> Path:
    """Logs root, by SPEC 6's order of precedence."""
    if explicit:
        return Path(explicit).expanduser()

    from_env = os.environ.get("TRAIL_ROOT")
    if from_env:
        return Path(from_env).expanduser()

    from_config = _config_root()
    if from_config is not None:
        return from_config

    if (frontend or detect_frontend()) == COLAB:
        return COLAB_DEFAULT_ROOT
    return LOCAL_DEFAULT_ROOT


def ensure_drive_mounted(root: Path, printer: Any = print) -> bool:
    """Mount Google Drive if the root lives there and it isn't mounted yet.

    Returns True if the root is usable. Mounting shows Google's permission popup,
    so we explain ourselves *before* triggering it.
    """
    try:
        root.relative_to(COLAB_DRIVE)
    except ValueError:
        return True  # Not a Drive path; nothing to do.

    if (COLAB_DRIVE / "MyDrive").exists():
        return True
    try:
        from google.colab import drive
    except ImportError:
        return False

    printer("Trail keeps your logs in Google Drive, so Colab will now ask for permission.")
    try:
        drive.mount(str(COLAB_DRIVE))
        return True
    except Exception:
        return False


def fallback_dir(project: str, frontend: str | None = None) -> Path:
    """Where to write when the real root refuses (SPEC 8.7)."""
    if (frontend or detect_frontend()) == COLAB:
        return Path("/content/trail-fallback") / project
    return Path.home() / ".cache" / "trail-fallback" / project
