"""Code normalisation and hashes (SPEC 10.2).

Two questions the engine keeps asking: "is this literally the same code as before?"
and "is this the same code *ignoring cosmetics*?" Two hashes answer them.

- ``code_hash``     — the code with tags and trailing whitespace removed.
- ``semantic_hash`` — the same, minus comments and blank lines.

A comment-only edit therefore changes ``code_hash`` but not ``semantic_hash``, which
is what lets grouping update a version's text without creating a new version.
"""

from __future__ import annotations

import hashlib
import io
import tokenize
from dataclasses import dataclass

from trail.common.tags import match_tag


@dataclass(frozen=True)
class Normalized:
    normalized: str
    code_hash: str
    semantic: str
    semantic_hash: str


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_code(code: str) -> str:
    """Drop tag lines and trailing whitespace; leave everything else alone."""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept = [line.rstrip() for line in lines if not match_tag(line)]
    while kept and not kept[-1]:
        kept.pop()
    return "\n".join(kept)


def strip_comments(code: str) -> str:
    """Remove comments using the tokenizer, falling back to a line-wise guess.

    The tokenizer knows a ``#`` inside a string isn't a comment. It also refuses to
    parse IPython magics (``%matplotlib inline``) and half-written code, which is
    exactly when the crude fallback is good enough.
    """
    lines = code.split("\n")
    edited = list(lines)
    try:
        for token in tokenize.generate_tokens(io.StringIO(code).readline):
            if token.type == tokenize.COMMENT:
                row, col = token.start
                edited[row - 1] = edited[row - 1][:col]
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        # why: magics and syntax errors are normal input here — a cell that failed to
        # compile is still a run we have to group. Keep % and ! lines verbatim.
        return "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    return "\n".join(edited)


def semantic_code(normalized: str) -> str:
    """What the cell actually *does*: no comments, no blank lines."""
    stripped = strip_comments(normalized)
    return "\n".join(line.rstrip() for line in stripped.split("\n") if line.strip())


def analyse(code: str) -> Normalized:
    normalized = normalize_code(code)
    semantic = semantic_code(normalized)
    return Normalized(normalized, _sha1(normalized), semantic, _sha1(semantic))
