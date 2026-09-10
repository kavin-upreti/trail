"""stdout/stderr tee (SPEC 8.3).

While a cell runs we replace ``sys.stdout``/``sys.stderr`` with a Tee: it writes
straight through to the real stream, so the user sees exactly what they always saw,
and keeps a *bounded* copy for the log.

Bounded is the hard part. A training loop with tqdm emits megabytes of progress
bars, so we apply terminal semantics while buffering — ``\\r`` discards the current
line (that is what overwriting means), ``\\n`` commits it — and keep only the first
and last 200 committed lines.

Known limitations, documented rather than fought (SPEC 8.3): output written at the
C level straight to fd 1, output from background threads after the cell ends, and
cells using ``%%capture`` (that magic swaps stdout itself).
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

HEAD_LINES = 200
TAIL_LINES = 200
MAX_CHARS = 64 * 1024
# ponytail: a single line is capped so one giant tensor dump with no newline can't
# grow the buffer without limit. Raise it if real output ever gets clipped.
MAX_LINE_CHARS = 4096


class Tee:
    """A write-through, size-bounded copy of a text stream."""

    def __init__(self, original: Any) -> None:
        self._orig = original
        self._head: list[str] = []
        self._tail: deque[str] = deque(maxlen=TAIL_LINES)
        self._line = ""
        self._pos = 0
        self.total_lines = 0

    # -- stream interface -------------------------------------------------

    def write(self, text: str) -> int:
        # The user's output goes out first and unconditionally; capture is secondary.
        written = self._orig.write(text)
        try:
            self._absorb(text)
        except Exception:
            pass
        return written if written is not None else len(text)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._orig.flush()

    def __getattr__(self, name: str) -> Any:
        # why: libraries probe for encoding/isatty/fileno/buffer. Forward everything
        # we don't define. Reading __dict__ directly avoids recursing through here.
        return getattr(self.__dict__["_orig"], name)

    # -- capture ----------------------------------------------------------

    def _absorb(self, text: str) -> None:
        if not text:
            return
        text = ANSI_RE.sub("", text.replace("\r\n", "\n"))
        start = 0
        for match in re.finditer(r"[\r\n]", text):
            self._append(text[start : match.start()])
            if match.group() == "\n":
                self._commit()
            else:
                # Carriage return: cursor back to column 0. The text stays put and
                # whatever comes next overwrites it, exactly as tqdm expects.
                self._pos = 0
            start = match.end()
        self._append(text[start:])

    def _append(self, chunk: str) -> None:
        if not chunk:
            return
        chunk = chunk[: max(0, MAX_LINE_CHARS - self._pos)]
        if not chunk:
            return
        end = self._pos + len(chunk)
        self._line = self._line[: self._pos] + chunk + self._line[end:]
        self._pos = end

    def _commit(self) -> None:
        line = self._line
        self._line = ""
        self._pos = 0
        self.total_lines += 1
        if len(self._head) < HEAD_LINES:
            self._head.append(line)
        else:
            self._tail.append(line)

    def result(self) -> dict[str, Any]:
        """The record's stdout/stderr block. Safe to call once, at end of run."""
        if self._line:
            # A cell ending on `print(x, end="")` or on "100%\r" still wrote a line.
            self._commit()

        dropped = self.total_lines - len(self._head) - len(self._tail)
        parts = list(self._head)
        if dropped > 0:
            parts.append(f"… [{dropped} lines omitted] …")
        parts.extend(self._tail)
        text = "\n".join(parts)

        truncated = dropped > 0
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n… [truncated] …"
            truncated = True

        return {"text": text, "truncated": truncated, "total_lines": self.total_lines}
