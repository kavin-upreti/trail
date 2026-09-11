"""The generated `<project>/CLAUDE.md` (Appendix D).

Dropped into the project folder so that `cd`-ing there and running `claude`
interactively just works — it explains the layout without the user describing it.
"""

from __future__ import annotations

from pathlib import Path

from trail.common.paths import ProjectPaths
from trail.engine.build import Build

TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "project_claude_md.md"


def write(paths: ProjectPaths, result: Build) -> Path:
    cells = (
        ", ".join(
            f"{cell.name} ({len(cell.versions)} versions)"
            for cell in result.cells
            if not cell.hidden
        )
        or "(none)"
    )

    def step_line(step) -> str:
        cell = result.cell(step.identity)
        name = cell.name if cell else step.identity
        return f"  - {step.key} · {name} v{step.start_n}→v{step.end_n} · {step.note or '(no note)'}"

    steps = "\n".join(step_line(s) for s in result.steps) or "  (none)"

    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("{{project}}", result.project)
    text = text.replace("{{cell_list_with_version_counts}}", cells)
    text = text.replace("{{step_list_with_titles}}", "\n" + steps)

    paths.dir.mkdir(parents=True, exist_ok=True)
    paths.claude_md.write_text(text, encoding="utf-8")
    return paths.claude_md
