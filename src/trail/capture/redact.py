"""Secret redaction (SPEC 8.6).

Applied to code, stdout, stderr, result reprs and HTML displays before anything is
written to disk. Logs land in Google Drive, so a pasted API key must never survive
the trip. Over-redacting is fine; under-redacting is not.
"""

from __future__ import annotations

import re

PLACEHOLDER = "[REDACTED]"

_TOKEN_PATTERNS = [
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"sk-[A-Za-z0-9_-]{20,}",
    r"hf_[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{30,}",
    r"github_pat_[A-Za-z0-9_]{30,}",
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
]
_TOKEN_RE = re.compile("|".join(_TOKEN_PATTERNS))

# Keep the variable name (it is often the point of the line) and redact the value.
_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*=\s*(['\"])[^'\"]{8,}\2",
)


def redact(text: str | None) -> str | None:
    """Return ``text`` with anything that looks like a credential replaced. Never raises."""
    if not text:
        return text
    try:
        out = _TOKEN_RE.sub(PLACEHOLDER, text)
        out = _ASSIGN_RE.sub(lambda m: f"{m.group(1)}={m.group(2)}{PLACEHOLDER}{m.group(2)}", out)
        return out
    except Exception:
        # why: hard rule 1 — capture never raises. A redaction bug must not cost the
        # user their cell, but it must also not leak, so drop the text entirely.
        return PLACEHOLDER
