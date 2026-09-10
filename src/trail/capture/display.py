"""Display capture (SPEC 8.4).

Inline matplotlib figures never pass through stdout — the inline backend flushes
them through ``display()`` during ``post_execute``, which runs *before*
``post_run_cell``. So to record plots we wrap the shell's display publisher, call
the original first (the user must see their figure no matter what we do), and then
keep a copy of the MIME bundle.

Images are content-addressed into ``blobs/<sha256>.<ext>``, so re-running a cell
that draws the same figure costs nothing.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from trail.capture.redact import redact

MAX_HTML_CHARS = 20 * 1024
MAX_TEXT_CHARS = 2 * 1024

_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg"}

#: Interactive widgets are live objects, not results; recording them is meaningless.
_WIDGET_PREFIXES = ("application/vnd.jupyter.widget", "application/vnd.jupyter.wid")


class DisplayCapture:
    """Wraps ``shell.display_pub.publish`` for the lifetime of a session."""

    def __init__(self, submit_blob: Any) -> None:
        self._submit_blob = submit_blob
        self._shell: Any = None
        self._original: Any = None
        self._active = False
        self._items: list[dict[str, Any]] = []
        self._by_display_id: dict[str, int] = {}
        self.budget_hit = False

    # -- lifecycle --------------------------------------------------------

    def install(self, shell: Any) -> bool:
        pub = getattr(shell, "display_pub", None)
        if pub is None or self._original is not None:
            return False
        self._shell = shell
        self._original = pub.publish
        pub.publish = self._publish
        return True

    def uninstall(self) -> None:
        if self._original is None:
            return
        try:
            self._shell.display_pub.publish = self._original
        except Exception:
            pass
        self._original = None
        self._shell = None

    def begin_run(self) -> None:
        self._active = True
        self._items = []
        self._by_display_id = {}

    def end_run(self) -> list[dict[str, Any]]:
        self._active = False
        items, self._items = self._items, []
        self._by_display_id = {}
        return items

    # -- the wrapper ------------------------------------------------------

    def _publish(self, *args: Any, **kwargs: Any) -> Any:
        # The user's output first, arguments untouched. Then, and only then, us.
        result = self._original(*args, **kwargs)
        try:
            if self._active:
                self._record(*args, **kwargs)
        except Exception:
            pass
        return result

    def _record(self, data: Any = None, metadata: Any = None, *args: Any, **kwargs: Any) -> None:
        if not isinstance(data, dict):
            return
        transient = kwargs.get("transient") or {}
        display_id = transient.get("display_id") if isinstance(transient, dict) else None
        update = bool(kwargs.get("update"))

        entry = self._describe(data)
        if entry is None:
            return

        # Progress displays republish the same display_id over and over; keep the last.
        if display_id is not None and display_id in self._by_display_id:
            self._items[self._by_display_id[display_id]] = entry
            return
        if update and display_id is None:
            return
        if display_id is not None:
            self._by_display_id[display_id] = len(self._items)
        self._items.append(entry)

    def _describe(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Pick the most useful representation out of a MIME bundle."""
        for mime, ext in _IMAGE_EXT.items():
            if mime in data:
                return self._store_image(mime, ext, data[mime])

        for mime in data:
            if mime.startswith(_WIDGET_PREFIXES):
                return {"mime": mime, "omitted": True}

        if "text/html" in data:
            html = redact(str(data["text/html"]))[:MAX_HTML_CHARS]
            return {"mime": "text/html", "html": html}

        if "text/plain" in data:
            text = redact(str(data["text/plain"]))[:MAX_TEXT_CHARS]
            return {"mime": "text/plain", "text": text}

        return None

    def _store_image(self, mime: str, ext: str, payload: Any) -> dict[str, Any]:
        try:
            if isinstance(payload, str):
                # PNG/JPEG arrive base64-encoded; SVG arrives as plain XML text.
                raw = payload.encode("utf-8") if ext == "svg" else base64.b64decode(payload)
            else:
                raw = bytes(payload)
        except Exception:
            return {"mime": mime, "omitted": "undecodable"}

        sha = hashlib.sha256(raw).hexdigest()
        if not self._submit_blob(sha, ext, raw):
            self.budget_hit = True
            return {"mime": mime, "omitted": "budget"}
        return {"mime": mime, "blob": f"{sha}.{ext}", "bytes": len(raw)}
