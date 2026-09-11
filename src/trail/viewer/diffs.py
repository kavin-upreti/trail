"""Server-rendered diffs and sparklines (SPEC 13.1).

Rendered in Python so the page stays a plain document: no diff library over the
wire, no CDN, and the escaping happens once, here. Everything in these files was
printed by the user's own notebook, so it is treated as hostile text throughout
(hard rule 7).
"""

from __future__ import annotations

import difflib
import html
from dataclasses import dataclass
from typing import Any

try:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import PythonLexer
except ImportError:  # pragma: no cover - pygments ships with [mac]
    highlight = None


@dataclass
class Row:
    kind: str  # equal | add | remove | change | skip
    left_no: str
    left: str
    right_no: str
    right: str


def highlight_code(code: str) -> str:
    """Syntax-highlighted HTML, or escaped plain text if Pygments isn't available."""
    if highlight is None:
        return html.escape(code)
    formatter = HtmlFormatter(nowrap=True)
    return highlight(code, PythonLexer(stripnl=False), formatter)


def _highlight_lines(code: str) -> list[str]:
    rendered = highlight_code(code)
    lines = rendered.split("\n")
    # Pygments adds a trailing newline; keep the line count aligned with the source.
    if lines and lines[-1] == "":
        lines.pop()
    source_lines = code.split("\n")
    while len(lines) < len(source_lines):
        lines.append("")
    return lines[: len(source_lines)] or [""]


def side_by_side(before: str, after: str, context: int = 3) -> list[Row]:
    """Two-column diff rows, with long runs of unchanged lines folded away."""
    left_lines, right_lines = before.split("\n"), after.split("\n")
    left_html, right_html = _highlight_lines(before), _highlight_lines(after)
    rows: list[Row] = []

    matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
    opcodes = matcher.get_opcodes()

    for index, (op, i1, i2, j1, j2) in enumerate(opcodes):
        if op == "equal":
            length = i2 - i1
            first = index == 0
            last = index == len(opcodes) - 1
            keep_head = 0 if first else context
            keep_tail = 0 if last else context
            if length > keep_head + keep_tail + 1:
                for offset in range(keep_head):
                    rows.append(_equal_row(i1 + offset, j1 + offset, left_html, right_html))
                hidden = length - keep_head - keep_tail
                rows.append(Row("skip", "", f"{hidden} unchanged lines", "", ""))
                for offset in range(length - keep_tail, length):
                    rows.append(_equal_row(i1 + offset, j1 + offset, left_html, right_html))
            else:
                for offset in range(length):
                    rows.append(_equal_row(i1 + offset, j1 + offset, left_html, right_html))
            continue

        span = max(i2 - i1, j2 - j1)
        for offset in range(span):
            left_index = i1 + offset if i1 + offset < i2 else None
            right_index = j1 + offset if j1 + offset < j2 else None
            kind = (
                "change"
                if left_index is not None and right_index is not None
                else ("remove" if left_index is not None else "add")
            )
            rows.append(
                Row(
                    kind,
                    str(left_index + 1) if left_index is not None else "",
                    left_html[left_index] if left_index is not None else "",
                    str(right_index + 1) if right_index is not None else "",
                    right_html[right_index] if right_index is not None else "",
                )
            )
    return rows


def _equal_row(i: int, j: int, left_html: list[str], right_html: list[str]) -> Row:
    return Row("equal", str(i + 1), left_html[i], str(j + 1), right_html[j])


def unified(before: str, after: str, a_label: str, b_label: str) -> list[tuple[str, str]]:
    """(kind, escaped-line) pairs for the unified view."""
    out: list[tuple[str, str]] = []
    for line in difflib.unified_diff(
        before.split("\n"), after.split("\n"), fromfile=a_label, tofile=b_label, lineterm=""
    ):
        if line.startswith("+++") or line.startswith("---"):
            kind = "meta"
        elif line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "remove"
        else:
            kind = "equal"
        out.append((kind, html.escape(line)))
    return out


def sparkline(values: list[float], width: int = 120, height: int = 24) -> str:
    """A tiny inline SVG. Returns "" when there's nothing meaningful to draw."""
    points = [v for v in values if isinstance(v, (int, float))]
    if len(points) < 2:
        return ""
    low, high = min(points), max(points)
    span = high - low
    if span == 0:
        span = 1.0

    step = width / (len(points) - 1)
    coords = []
    for index, value in enumerate(points):
        x = index * step
        y = height - ((value - low) / span) * (height - 2) - 1
        coords.append(f"{x:.1f},{y:.1f}")

    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="currentColor" '
        f'stroke-width="1.5" stroke-linejoin="round" /></svg>'
    )


#: Light and dark token themes. Two problems with Pygments' stylesheet, both of
#: which showed up as a white slab inside a dark page: it sets a background colour
#: on the container, and it emits unscoped rules (`pre`, `td.linenos`) that would
#: leak into the rest of the viewer. We keep only the `.hl`-scoped token colours.
LIGHT_STYLE = "default"
DARK_STYLE = "github-dark"


def _tokens(style: str) -> list[str]:
    """Token-colour rules only, as a list of single-selector CSS rules."""
    rules: list[str] = []
    for rule in HtmlFormatter(style=style).get_style_defs(".hl").split("\n"):
        rule = rule.strip()
        # `.hl { background: ... }` is the slab; anything not starting `.hl ` is unscoped.
        if not rule.startswith(".hl ") or rule.startswith(".hl {"):
            continue
        rules.append(rule)
    return rules


def _scoped(prefix: str, rules: list[str]) -> str:
    return "\n".join(f"{prefix} {rule}" for rule in rules)


def pygments_css() -> str:
    """Token colours for both themes, guarded exactly like the rest of the palette."""
    if highlight is None:
        return ""
    light, dark = _tokens(LIGHT_STYLE), _tokens(DARK_STYLE)
    return "\n".join(
        [
            "\n".join(light),
            "@media (prefers-color-scheme: dark) {",
            _scoped(':root:not([data-theme="light"])', dark),
            "}",
            _scoped(':root[data-theme="dark"]', dark),
        ]
    )


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))
