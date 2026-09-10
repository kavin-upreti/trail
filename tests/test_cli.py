"""CLI smoke tests — the commands run, and say true things."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trail.cli import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A small recorded project, in a path with a space in it (hard rule 8)."""
    root = tmp_path / "My Drive" / "trail logs"
    runs = root / "demo" / "runs"
    runs.mkdir(parents=True)
    rows = [
        ("# trail: cell hparams\nlr = 0.1", "", "ok"),
        ("# trail: cell train\nprint('loss', 3.31)", "loss 3.31\n", "ok"),
        ("# trail: cell train\nprint('loss', 3.31)\nboom", "", "error"),
        (
            "# trail: cell train\n# trail: cp scaled the init down\nprint('loss', 3.07)\nw = 1",
            "loss 3.07\n",
            "ok",
        ),
    ]
    lines = []
    for i, (code, stdout, status) in enumerate(rows):
        lines.append(
            json.dumps(
                {
                    "type": "run",
                    "schema": 1,
                    "session": "s1",
                    "seq": i,
                    "ts_start": f"2026-01-01T00:00:0{i}.000Z",
                    "code": code,
                    "status": status,
                    "duration_s": 0.5,
                    "cell_id": None,
                    "stdout": {"text": stdout, "truncated": False, "total_lines": 1},
                    "error": None
                    if status == "ok"
                    else {
                        "type": "NameError",
                        "message": "boom",
                        "traceback_tail": [],
                        "stage": "exec",
                    },
                }
            )
        )
    (runs / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


# why: Rich wraps to the terminal width, which would split phrases like
# "1 failed attempt" across lines and make these assertions width-dependent.
WIDE = {"COLUMNS": "200", "TERM": "dumb"}


def run(*args: str, root: Path):
    return runner.invoke(app, [*args, "--logs", str(root)], env=WIDE)


def test_log_shows_versions_metrics_and_the_checkpoint(project: Path):
    result = run("log", root=project)
    assert result.exit_code == 0, result.output
    assert "train" in result.output
    assert "3.07" in result.output
    assert "scaled the init down" in result.output
    assert "failed attempt" in result.output  # the error was folded in, not lost


def test_log_hides_setup_cells_until_asked(project: Path):
    (project / "demo" / "runs" / "setup.jsonl").write_text(
        json.dumps(
            {
                "type": "run",
                "schema": 1,
                "session": "s2",
                "seq": 0,
                "ts_start": "2026-01-01T00:00:09.000Z",
                "code": "import numpy as np",
                "status": "ok",
                "duration_s": 0.1,
                "stdout": {"text": "", "truncated": False, "total_lines": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert "setup cell" in run("log", root=project).output
    assert "import numpy" in run("log", "--all", root=project).output


def test_log_on_one_cell(project: Path):
    result = run("log", "--cell", "train", root=project)
    assert result.exit_code == 0
    assert "hparams" not in result.output


def test_unknown_cell_fails_with_a_helpful_message(project: Path):
    result = run("log", "--cell", "nope", root=project)
    assert result.exit_code == 1
    assert "Try one of" in result.output


def test_projects_lists_what_was_recorded(project: Path):
    result = run("projects", root=project)
    assert result.exit_code == 0 and "demo" in result.output


def test_show_diffs_two_versions(project: Path):
    result = run("show", "demo", "train", "1", "2", root=project)
    assert result.exit_code == 0
    assert "-print('loss', 3.31)" in result.output or "3.31" in result.output
    assert "+" in result.output


def test_rebuild_writes_versions_json(project: Path):
    result = run("rebuild", "demo", root=project)
    assert result.exit_code == 0
    built = json.loads((project / "demo" / "derived" / "versions.json").read_text())
    assert built["project"] == "demo"
    assert [c["identity"] for c in built["cells"]] == ["tag:hparams", "tag:train"]
    assert built["steps"][0]["note"] == "scaled the init down"


def test_cells_rename_changes_what_log_prints(project: Path):
    assert (
        runner.invoke(
            app,
            [
                "cells",
                "rename",
                "tag:train",
                "the training loop",
                "--project",
                "demo",
                "--logs",
                str(project),
            ],
        ).exit_code
        == 0
    )
    assert "the training loop" in run("log", root=project).output


def test_cells_hide_and_unhide(project: Path):
    runner.invoke(app, ["cells", "hide", "tag:train", "--project", "demo", "--logs", str(project)])
    assert "setup cell" in run("log", root=project).output
    runner.invoke(
        app, ["cells", "unhide", "tag:train", "--project", "demo", "--logs", str(project)]
    )
    assert "scaled the init down" in run("log", root=project).output


def test_missing_logs_root_explains_itself(tmp_path: Path):
    result = runner.invoke(app, ["log", "--logs", str(tmp_path / "nope")], env=WIDE)
    assert result.exit_code == 1
    assert "trail init" in result.output


def test_empty_root_says_how_to_start(tmp_path: Path):
    empty = tmp_path / "empty root"
    empty.mkdir()
    result = run("log", root=empty)
    assert result.exit_code == 1
    assert "trail.start" in result.output
