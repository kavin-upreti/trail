"""Variable fingerprint (SPEC 8.5).

A cheap, safe snapshot of the user's namespace taken after each run: scalars as
values, tensors/arrays as shape + dtype, containers as lengths. It is what lets the
engine later say "lr changed from 0.1 to 0.01 between these two runs".

The safety rules matter more than the completeness rules. A notebook namespace is
full of objects that run code when you touch them — lazy loaders, properties,
CUDA tensors whose repr synchronises the device. So: never ``repr()``, never
``hasattr()``, and never read a property on an object we don't recognise.
"""

from __future__ import annotations

import inspect
import math
from typing import Any

from trail.capture.redact import redact

MAX_ENTRIES = 200
MAX_STR = 80

#: Names IPython puts in the namespace that say nothing about the user's work.
_IPYTHON_NAMES = frozenset({"In", "Out", "exit", "quit", "get_ipython", "open", "trail"})

#: Only objects from these libraries get the shape/dtype treatment.
_ARRAY_MODULES = ("torch", "numpy", "jax", "pandas")

_CONTAINERS = (list, tuple, dict, set, frozenset)


def _describe(obj: Any) -> Any:
    """Describe one value, or raise ``_Skip`` if it isn't worth recording."""
    # Order matters: bool is a subclass of int, and must be tested first.
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        # why: NaN and infinity are not valid JSON, so they travel as strings.
        if math.isnan(obj):
            return "nan"
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        return obj
    if isinstance(obj, complex):
        return {"type": "complex", "real": obj.real, "imag": obj.imag}
    if isinstance(obj, str):
        # why: a notebook's namespace routinely holds `api_key = "sk-ant-..."`, and
        # SPEC 8.6's list of redacted fields missed this one. Logs go to Drive.
        return redact(obj) if len(obj) <= MAX_STR else {"type": "str", "len": len(obj)}
    if isinstance(obj, (bytes, bytearray)):
        return {"type": type(obj).__name__, "len": len(obj)}
    if isinstance(obj, _CONTAINERS):
        # Never inspect the contents — a list of a million tensors must stay cheap.
        return {"type": type(obj).__name__, "len": len(obj)}

    # type(obj).__module__ reads the *class*, so it cannot trigger __getattr__.
    module = getattr(type(obj), "__module__", "") or ""
    if module.startswith(_ARRAY_MODULES):
        shape = getattr(obj, "shape", None)
        if shape is not None:
            entry: dict[str, Any] = {"shape": [int(d) for d in shape]}
            dtype = getattr(obj, "dtype", None)
            if dtype is not None:
                entry["dtype"] = str(dtype)
            return entry
    raise _Skip


class _Skip(Exception):
    """Sentinel: this value isn't worth a fingerprint entry."""


def take(namespace: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint a user namespace. Never raises."""
    out: dict[str, Any] = {}
    try:
        names = sorted(namespace)
    except Exception:
        return out

    for name in names:
        if len(out) >= MAX_ENTRIES:
            break
        if name.startswith("_") or name in _IPYTHON_NAMES:
            continue
        try:
            obj = namespace[name]
            if inspect.ismodule(obj) or inspect.isclass(obj) or inspect.isroutine(obj):
                continue
            out[name] = _describe(obj)
        except _Skip:
            continue
        except Exception:
            # A single hostile object must not cost us the whole fingerprint.
            continue
    return out


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What changed between two fingerprints (used by the engine's context panel)."""
    added = {k: after[k] for k in after.keys() - before.keys()}
    removed = sorted(before.keys() - after.keys())
    changed = {
        k: {"before": before[k], "after": after[k]}
        for k in before.keys() & after.keys()
        if before[k] != after[k]
    }
    return {"added": added, "removed": removed, "changed": changed}
