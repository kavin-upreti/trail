"""IPython event registration (SPEC 8.2).

Thin on purpose: this module knows how to attach and detach, and nothing about what
a version or a checkpoint is. Hard rule 4 — capture is dumb, the engine is smart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

PRE = "pre_run_cell"
POST = "post_run_cell"


class Hooks:
    def __init__(self, on_pre: Callable[[Any], None], on_post: Callable[[Any], None]) -> None:
        self._on_pre = on_pre
        self._on_post = on_post
        self._shell: Any = None

    def register(self, shell: Any) -> bool:
        if self._shell is not None:
            return False
        try:
            shell.events.register(PRE, self._on_pre)
            shell.events.register(POST, self._on_post)
        except Exception:
            return False
        self._shell = shell
        return True

    def unregister(self) -> None:
        if self._shell is None:
            return
        for event, callback in ((PRE, self._on_pre), (POST, self._on_post)):
            try:
                self._shell.events.unregister(event, callback)
            except Exception:
                pass
        self._shell = None


def is_silent(info: Any) -> bool:
    """Frontend introspection and `store_history=False` runs aren't the user's work."""
    if getattr(info, "silent", False):
        return True
    return getattr(info, "store_history", True) is False
