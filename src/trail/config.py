"""Mac-side config (SPEC 6): ``~/.config/trail/config.toml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "trail" / "config.toml"


@dataclass
class Config:
    logs_root: Path | None = None
    engine: dict[str, Any] = field(default_factory=dict)
    viewer: dict[str, Any] = field(default_factory=dict)
    claude: dict[str, Any] = field(default_factory=dict)
    analyze: dict[str, Any] = field(default_factory=dict)
    path: Path = CONFIG_PATH

    @property
    def exists(self) -> bool:
        return self.path.is_file()


def load(path: Path = CONFIG_PATH) -> Config:
    """Read the config file, or return defaults if it isn't there yet."""
    if not path.is_file():
        return Config(path=path)
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return Config(path=path)

    root = data.get("logs_root")
    return Config(
        logs_root=Path(root).expanduser() if root else None,
        engine=dict(data.get("engine") or {}),
        viewer=dict(data.get("viewer") or {}),
        claude=dict(data.get("claude") or {}),
        analyze=dict(data.get("analyze") or {}),
        path=path,
    )


def resolve_root(explicit: str | None = None, config: Config | None = None) -> Path | None:
    """Logs root for CLI commands: flag, then env, then config, then the default."""
    import os

    if explicit:
        return Path(explicit).expanduser()
    from_env = os.environ.get("TRAIL_ROOT")
    if from_env:
        return Path(from_env).expanduser()
    config = config or load()
    if config.logs_root:
        return config.logs_root
    default = Path.home() / "trail-logs"
    return default if default.is_dir() else None
