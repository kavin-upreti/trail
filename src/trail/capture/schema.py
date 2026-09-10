"""Record builders for the on-disk format (SPEC 7), schema version 1.

Raw logs are append-only and never rewritten (ADR 0001), so this format is a
promise. Adding fields is fine; changing the meaning of one is not.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from typing import Any

SCHEMA_VERSION = 1

#: SPEC 7.2 — the whole record, serialised, must fit in this.
MAX_RECORD_BYTES = 256 * 1024
MAX_STREAM_CHARS = 64 * 1024
MAX_RESULT_REPR = 2 * 1024
MAX_ERROR_BYTES = 2 * 1024
MAX_TRACEBACK_LINES = 6


def utc_now() -> str:
    """UTC ISO-8601 with milliseconds, e.g. ``2026-09-12T10:15:00.123Z``."""
    now = dt.datetime.now(dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_session_id() -> str:
    """``YYYYMMDD-HHMMSS-<4 hex>`` — sortable, and unique across machines."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(2)}"


def _base(kind: str, session: str) -> dict[str, Any]:
    return {"type": kind, "schema": SCHEMA_VERSION, "session": session, "ts": utc_now()}


def session_start(session: str, **fields: Any) -> dict[str, Any]:
    record = _base("session_start", session)
    record.update(fields)
    return record


def session_end(session: str, runs: int, clean: bool) -> dict[str, Any]:
    record = _base("session_end", session)
    record.update({"runs": runs, "clean": clean})
    return record


def marker(session: str, kind: str) -> dict[str, Any]:
    record = _base("marker", session)
    record["kind"] = kind
    return record


def note(session: str, text: str) -> dict[str, Any]:
    record = _base("note", session)
    record["text"] = text
    return record


def error_block(
    exc_type: str, message: str, traceback_tail: list[str], stage: str
) -> dict[str, Any]:
    block = {
        "type": exc_type,
        "message": message[:MAX_ERROR_BYTES],
        "traceback_tail": [line[:400] for line in traceback_tail[-MAX_TRACEBACK_LINES:]],
        "stage": stage,
    }
    return block


def size_of(record: dict[str, Any]) -> int:
    try:
        return len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return MAX_RECORD_BYTES + 1


def enforce_size(record: dict[str, Any]) -> dict[str, Any]:
    """Shrink an oversized run record, worst offender first (SPEC 7.2)."""
    if size_of(record) <= MAX_RECORD_BYTES:
        return record

    record["oversize"] = True
    # why: outputs are the only fields that can plausibly be megabytes, and they are
    # the least valuable per byte. Code and metrics are never sacrificed.
    for _ in range(6):
        streams = [k for k in ("stdout", "stderr") if isinstance(record.get(k), dict)]
        streams.sort(key=lambda k: len(record[k].get("text", "")), reverse=True)
        if not streams or not record[streams[0]].get("text"):
            break
        block = record[streams[0]]
        block["text"] = block["text"][: max(200, len(block["text"]) // 2)]
        block["truncated"] = True
        if size_of(record) <= MAX_RECORD_BYTES:
            return record

    if size_of(record) > MAX_RECORD_BYTES and isinstance(record.get("result_repr"), str):
        record["result_repr"] = record["result_repr"][:200]
    if size_of(record) > MAX_RECORD_BYTES:
        record["displays"] = [{"omitted": "oversize"}]
    return record
