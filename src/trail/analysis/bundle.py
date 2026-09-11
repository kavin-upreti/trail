"""Building the prompt for one step (SPEC 11.2).

The bundle is the whole argument: here is the code before and after, here is what
each one printed, here are the numbers and how noisy they are, and here is
everything *else* that changed at the same time. That last part is what stops an
explanation confidently crediting the wrong change.

Capped at ~60 KB, shrinking the least valuable material first.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trail.analysis import concepts as concepts_mod
from trail.analysis.validate import SCHEMA_TEXT
from trail.common.paths import ProjectPaths
from trail.engine import context as context_mod
from trail.engine.build import Build, Cell
from trail.engine.grouping import Version
from trail.engine.metrics import primary_name
from trail.engine.steps import Step

MAX_BUNDLE_CHARS = 60_000
MAX_OUTPUT_LINES = 60
MAX_PLOTS_PER_SIDE = 2

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "data" / "prompts" / "analysis.md"


@dataclass
class Bundle:
    text: str
    plot_paths: list[Path]

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _trim_output(text: str, limit: int = MAX_OUTPUT_LINES) -> str:
    if not text.strip():
        return "(no output)"
    lines = text.split("\n")
    if len(lines) <= limit:
        return text
    head, tail = lines[: limit // 2], lines[-(limit // 2) :]
    return "\n".join(head + [f"… [{len(lines) - limit} lines omitted] …"] + tail)


def _outputs(version: Version) -> str:
    run = version.latest_ok
    if run is None:
        return "(this version never ran successfully)"
    parts = [f"stdout:\n{_trim_output(run.stdout)}"]
    if run.raw.get("result_repr"):
        parts.append(f"result: {run.raw['result_repr']}")
    if version.attempts:
        errors: dict[str, int] = {}
        for attempt in version.attempts:
            errors[attempt.error_type or "error"] = errors.get(attempt.error_type or "error", 0) + 1
        summary = ", ".join(f"{name} ×{count}" for name, count in sorted(errors.items()))
        parts.append(f"{len(version.attempts)} failed attempts before this worked: {summary}")
    return "\n\n".join(parts)


def _metrics_block(before: Version, after: Version) -> str:
    lines: list[str] = []
    names = [n for n in dict.fromkeys(list(before.metrics) + list(after.metrics))]
    for name in names:
        a = before.metrics.get(name, {}).get("final")
        b = after.metrics.get(name, {}).get("final")
        lines.append(f"- {name}: {a!r} → {b!r}")

    for label, version in (("before", before), ("after", after)):
        if version.loss_std:
            lines.append(
                f"- noise estimate ({label}): ±{version.loss_std:.4g} across identical re-runs"
            )
        if len(version.run_finals) > 1 and min(version.run_finals) != max(version.run_finals):
            lines.append(
                f"- the {label} version's own runs ranged {min(version.run_finals):.4g} "
                f"→ {max(version.run_finals):.4g}, so its code alone doesn't determine the number"
            )
    lines.append(f"- runs: {len(before.runs)} before, {len(after.runs)} after")
    if not any(version.loss_std for version in (before, after)):
        lines.append(
            "- no noise estimate available (no identical re-runs), so treat small "
            "differences with caution"
        )
    return "\n".join(lines)


def _context_block(ctx: context_mod.Context, before: Version, after: Version) -> str:
    lines: list[str] = []
    changed = ctx.var_changes.get("changed") or {}
    if changed:
        for name, pair in list(changed.items())[:12]:
            lines.append(f"- variable `{name}` changed: {pair['before']!r} → {pair['after']!r}")
    added = ctx.var_changes.get("added") or {}
    if added:
        lines.append(f"- new variables: {', '.join(sorted(added)[:12])}")

    for other in ctx.other_cells:
        diff = "\n".join(other["diff"])
        lines.append(f"- another cell (`{other['identity']}`) also changed:\n```diff\n{diff}\n```")

    if ctx.restarts:
        lines.append(f"- {ctx.restarts} kernel restart(s) happened between these runs")
    if not ctx.same_session:
        lines.append("- these runs are from different sessions")
    if ctx.device_changed:
        lines.append("- the device changed (CPU vs GPU), so timings aren't comparable")
    if ctx.seed_note:
        lines.append(f"- {ctx.seed_note}")
    return "\n".join(lines) if lines else "Nothing else changed between these two runs."


def _path_lines(cell: Cell, start_n: int, end_n: int) -> str:
    lines: list[str] = []
    for version in cell.versions:
        if not (start_n < version.n <= end_n):
            continue
        name = primary_name(version.metrics)
        final = version.metrics.get(name, {}).get("final") if name else None
        flags = " (minor)" if version.minor else ""
        lines.append(
            f"- v{version.n}{flags}: {len(version.runs)} run(s), "
            f"{name or 'no metric'}={final!r}"
            + (f", {len(version.attempts)} failed attempt(s)" if version.attempts else "")
        )
    return "\n".join(lines) if lines else "- (no intermediate versions)"


def _plots(paths: ProjectPaths, version: Version) -> list[Path]:
    run = version.latest_ok
    if run is None:
        return []
    found: list[Path] = []
    for display in run.displays:
        blob = display.get("blob")
        if not blob:
            continue
        candidate = paths.blobs / str(blob)
        if candidate.is_file():
            found.append(candidate)
        if len(found) >= MAX_PLOTS_PER_SIDE:
            break
    return found


def _learned(paths: ProjectPaths) -> str:
    """Concept ids from earlier analyses, so wording stays consistent across a lecture."""
    import json

    found: set[str] = set()
    if paths.analyses.is_dir():
        for path in paths.analyses.rglob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            found.update(data.get("analysis", {}).get("concepts") or [])
    return ", ".join(sorted(found)) if found else "(none yet — this is the first step)"


def build_bundle(
    result: Build, step: Step, paths: ProjectPaths, include_images: bool = True
) -> Bundle:
    """Assemble the prompt for one step."""
    cell = result.cell(step.identity)
    if cell is None:
        raise ValueError(f"no cell {step.identity!r}")

    by_n = {v.n: v for v in cell.versions}
    before, after = by_n[step.start_n], by_n[step.end_n]

    before_run, after_run = before.latest_ok, after.latest_ok
    ctx = context_mod.Context()
    if before_run is not None and after_run is not None:
        ctx = context_mod.between(
            before_run, after_run, result.runs, {k: v for k, v in result.identity_of.items()}
        )

    # why: the first checkpoint of a cell has no earlier version, so start_n == end_n
    # and the diff is empty. Asking "how did it change from v1 to v1" wastes a call and
    # invites a made-up answer; reframe it as "explain this starting point" instead.
    is_first = step.start_n == step.end_n
    framing = ""
    if is_first:
        framing = (
            "IMPORTANT: this is the FIRST recorded version of this cell, so there is no\n"
            "earlier version to compare against and the diff below is empty. Do not invent a\n"
            "change. Instead explain what this code does, what the recorded output shows, and\n"
            'why the student\'s note matters. Set `effect.direction` to "unclear" unless the\n'
            "output itself demonstrates something, and describe the starting state in\n"
            "`changes` (e.g. what the initial loss was and why)."
        )

    diff = "\n".join(
        difflib.unified_diff(
            before.code.split("\n"),
            after.code.split("\n"),
            fromfile=f"v{step.start_n}",
            tofile=f"v{step.end_n}",
            lineterm="",
        )
    )

    plots: list[Path] = []
    if include_images:
        plots = _plots(paths, before) + _plots(paths, after)

    plot_text = (
        "\n".join(f"- {p}" for p in plots) if plots else "(no plots recorded for these versions)"
    )

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if is_first:
        diff = "(no diff — this is the first recorded version of this cell)"

    values = {
        "framing": framing,
        "project": result.project,
        "cell_name": cell.name,
        "start_n": str(step.start_n),
        "end_n": str(step.end_n),
        "note": step.note or "(no note)",
        "code_before": before.code,
        "code_after": after.code,
        "diff": diff,
        "path_lines": _path_lines(cell, step.start_n, step.end_n),
        "outputs_before": _outputs(before),
        "outputs_after": _outputs(after),
        "metrics_block": _metrics_block(before, after),
        "context_block": _context_block(ctx, before, after),
        "plot_paths": plot_text,
        "concept_vocab": concepts_mod.vocabulary_lines(),
        "learned_concepts": _learned(paths),
        "json_schema": SCHEMA_TEXT,
    }

    text = _fill(template, values)
    if len(text.encode("utf-8")) > MAX_BUNDLE_CHARS:
        text = _shrink(template, values)
    return Bundle(text, plots)


def _shrink(template: str, values: dict[str, str]) -> str:
    """Trim the least valuable material first: outputs, then other-cell diffs, then path."""
    for key, replacement in (
        ("outputs_before", lambda v: _trim_output(v, 20)),
        ("outputs_after", lambda v: _trim_output(v, 20)),
        ("context_block", lambda v: v[:2000] + "\n… (context truncated) …"),
        ("path_lines", lambda v: "\n".join(v.split("\n")[:10] + ["- …"])),
        ("diff", lambda v: "\n".join(v.split("\n")[:200] + ["… (diff truncated) …"])),
    ):
        values = dict(values)
        values[key] = replacement(values[key])  # type: ignore[operator]
        text = _fill(template, values)
        if len(text.encode("utf-8")) <= MAX_BUNDLE_CHARS:
            return text
    return _fill(template, values)[:MAX_BUNDLE_CHARS]


def as_dict(values: Any) -> dict[str, Any]:  # pragma: no cover - convenience
    return dict(values)
