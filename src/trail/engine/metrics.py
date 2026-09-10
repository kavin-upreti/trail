"""Pulling numbers out of what the cell printed (SPEC 10.7).

Nobody logs metrics properly while following a lecture — they `print(loss)`. So the
engine reads the printed output, in the formats these lectures actually produce.
Explicit `trail.metric()` calls always win, because they can't be misread.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

MAX_SERIES = 200

# why: SPEC 10.7's exponent pattern was [eE]-?\d+, which misses a positive exponent —
# and a diverging loss prints as 3.9e+47, exactly the case worth catching.
_FLOAT = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"

#: Karpathy's step logger: "  10000/ 200000: 2.0718"
STEP_LOG = re.compile(rf"^\s*\d+\s*/\s*\d+\s*:\s*(?P<value>{_FLOAT})", re.MULTILINE)

#: "loss 2.07", "val_loss: 2.07", "train loss = 2.07"
NAMED_LOSS = re.compile(
    rf"(?i)\b(?P<name>(?:train|val|valid|test)[ _]?loss|loss)\b\s*[:=]?\s*(?P<value>{_FLOAT})"
)

#: Karpathy's split printer: a line that is just "train 2.0718"
SPLIT_LOSS = re.compile(rf"^(?P<name>train|val|test)\s+(?P<value>{_FLOAT})\s*$", re.MULTILINE)

#: "tensor(3.3147, grad_fn=...)" or a bare float as the cell's result.
TENSOR_REPR = re.compile(rf"^tensor\(\s*(?P<value>{_FLOAT})")
BARE_FLOAT = re.compile(rf"^(?P<value>{_FLOAT})$")


def _clean_name(name: str) -> str:
    name = name.strip().lower().replace(" ", "_")
    if name in ("train", "val", "test"):
        return f"{name}_loss"
    return "val_loss" if name == "valid_loss" else name


def _to_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value else None  # drop NaN


def downsample(values: list[float], limit: int = MAX_SERIES) -> list[float]:
    """Thin a long series, always keeping the last point (that's the final loss)."""
    if len(values) <= limit:
        return values
    step = len(values) / limit
    thinned = [values[int(i * step)] for i in range(limit - 1)]
    thinned.append(values[-1])
    return thinned


def _add(series: dict[str, list[float]], name: str, value: float | None) -> None:
    if value is not None:
        series.setdefault(name, []).append(value)


def extract(run: Any, extra_patterns: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """All metrics for one run, as ``{name: {"final": float, "series": [...]}}``."""
    series: dict[str, list[float]] = {}

    stdout = run.stdout
    if stdout:
        for match in STEP_LOG.finditer(stdout):
            _add(series, "loss", _to_float(match.group("value")))
        for match in SPLIT_LOSS.finditer(stdout):
            _add(series, _clean_name(match.group("name")), _to_float(match.group("value")))
        for match in NAMED_LOSS.finditer(stdout):
            _add(series, _clean_name(match.group("name")), _to_float(match.group("value")))

        for pattern in extra_patterns or []:
            try:
                for match in re.finditer(pattern, stdout, re.MULTILINE):
                    groups = match.groupdict()
                    if "value" not in groups:
                        continue
                    _add(
                        series,
                        _clean_name(groups.get("name") or "custom"),
                        _to_float(groups["value"]),
                    )
            except re.error:
                continue

    repr_text = run.raw.get("result_repr")
    if isinstance(repr_text, str) and repr_text:
        last_line = (run.norm.semantic.split("\n") or [""])[-1].lower()
        if "loss" in last_line:
            match = TENSOR_REPR.match(repr_text) or BARE_FLOAT.match(repr_text.strip())
            if match:
                _add(series, "loss", _to_float(match.group("value")))

    out: dict[str, dict[str, Any]] = {}
    for name, values in series.items():
        if values:
            out[name] = {"final": values[-1], "series": downsample(values)}

    # Explicit trail.metric() calls override anything parsed.
    for entry in run.raw.get("metrics") or []:
        if isinstance(entry, dict) and "name" in entry:
            value = _to_float(entry.get("value"))
            if value is not None:
                name = _clean_name(str(entry["name"]))
                out[name] = {"final": value, "series": [value], "source": "explicit"}

    out["duration_s"] = {"final": round(run.duration_s, 4), "series": [run.duration_s]}
    return out


def primary_name(metrics: dict[str, dict[str, Any]]) -> str | None:
    """The metric a human means when they say "did it get better?"."""
    for name in ("val_loss", "loss", "train_loss", "test_loss"):
        if name in metrics:
            return name
    for name in metrics:
        if name != "duration_s":
            return name
    return None


def noise_estimate(values: list[float]) -> float | None:
    """Spread across identical re-runs — how much of a change is just luck."""
    return statistics.stdev(values) if len(values) >= 2 else None
