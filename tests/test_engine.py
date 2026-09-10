"""Engine unit tests (SPEC 17.1) — synthetic runs, no kernel needed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trail.common.normalize import analyse
from trail.common.paths import ProjectPaths
from trail.common.tags import parse as parse_tags
from trail.engine import identity as identity_mod
from trail.engine import overrides as overrides_mod
from trail.engine import steps as steps_mod
from trail.engine.build import build, to_json
from trail.engine.grouping import group, is_minor
from trail.engine.loader import Run, load
from trail.engine.metrics import extract

_CLOCK = [0]


def make_run(
    code: str,
    *,
    status: str = "ok",
    stdout: str = "",
    session: str = "s1",
    cell_id: str | None = None,
    result_repr: str | None = None,
    error_type: str = "NameError",
    metrics: list | None = None,
    seq: int | None = None,
    ts: str | None = None,
) -> Run:
    """One synthetic run, with a monotonically increasing timestamp."""
    _CLOCK[0] += 1
    n = _CLOCK[0]
    raw = {
        "type": "run",
        "schema": 1,
        "session": session,
        "seq": seq if seq is not None else n,
        "ts_start": ts or f"2026-09-11T10:{n // 60:02d}:{n % 60:02d}.000Z",
        "code": code,
        "status": status,
        "cell_id": cell_id,
        "duration_s": 0.1,
        "stdout": {"text": stdout, "truncated": False, "total_lines": stdout.count("\n")},
        "result_repr": result_repr,
        "displays": [],
        "vars": {},
        "metrics": metrics or [],
        "error": None
        if status == "ok"
        else {"type": error_type, "message": "boom", "traceback_tail": [], "stage": "exec"},
    }
    return Run(raw, analyse(code), parse_tags(code))


def cell_of(runs: list[Run], key: str = "tag:c") -> list:
    identities, _ = identity_mod.resolve(runs)
    return group(identities[key], all_runs=runs)


# -- normalisation ----------------------------------------------------------


def test_tags_and_trailing_whitespace_are_normalised_away():
    a = analyse("# trail: cell x\nlr = 0.1   \n\n\n")
    b = analyse("lr = 0.1")
    assert a.code_hash == b.code_hash


def test_comment_only_edits_keep_the_semantic_hash():
    a = analyse("lr = 0.1  # first thought")
    b = analyse("lr = 0.1  # second thought\n# and a note")
    assert a.code_hash != b.code_hash
    assert a.semantic_hash == b.semantic_hash


def test_a_hash_in_a_string_is_not_a_comment():
    assert analyse("s = '# not a comment'").semantic == "s = '# not a comment'"


def test_magics_and_shell_lines_survive_verbatim():
    assert analyse("%matplotlib inline\n!pip install x\na = 1").semantic == (
        "%matplotlib inline\n!pip install x\na = 1"
    )


def test_uncompilable_code_still_normalises():
    # A syntax error is a normal run to group, not an exceptional case.
    assert "def broken(" in analyse("def broken(:  # oops\n    pass").semantic


# -- loader -----------------------------------------------------------------


def _write_log(paths: ProjectPaths, name: str, lines: list[str]) -> None:
    paths.runs.mkdir(parents=True, exist_ok=True)
    (paths.runs / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_loader_tolerates_a_half_written_last_line(tmp_path: Path):
    paths = ProjectPaths(tmp_path / "my logs", "p")
    good = json.dumps(
        {
            "type": "run",
            "schema": 1,
            "session": "s",
            "seq": 1,
            "ts_start": "2026-01-01T00:00:00.000Z",
            "code": "a = 1",
            "status": "ok",
        }
    )
    _write_log(paths, "s.jsonl", [good, '{"type": "run", "sch'])
    loaded = load(paths)
    assert len(loaded.runs) == 1
    assert not loaded.warnings


def test_loader_dedupes_drive_conflict_copies(tmp_path: Path):
    paths = ProjectPaths(tmp_path / "my logs", "p")
    line = json.dumps(
        {
            "type": "run",
            "schema": 1,
            "session": "s",
            "seq": 1,
            "ts_start": "2026-01-01T00:00:00.000Z",
            "code": "a = 1",
            "status": "ok",
        }
    )
    _write_log(paths, "s.jsonl", [line])
    _write_log(paths, "s (1).jsonl", [line])
    assert len(load(paths).runs) == 1


def test_loader_warns_about_a_newer_schema(tmp_path: Path):
    paths = ProjectPaths(tmp_path / "my logs", "p")
    _write_log(
        paths,
        "s.jsonl",
        [
            json.dumps(
                {"type": "run", "schema": 99, "session": "s", "seq": 1, "code": "a", "status": "ok"}
            )
        ],
    )
    assert any("newer Trail" in w for w in load(paths).warnings)


def test_loader_ignores_unknown_record_types_with_a_warning(tmp_path: Path):
    paths = ProjectPaths(tmp_path / "my logs", "p")
    _write_log(paths, "s.jsonl", [json.dumps({"type": "from_the_future", "schema": 1})])
    loaded = load(paths)
    assert loaded.runs == []
    assert any("unknown record type" in w for w in loaded.warnings)


# -- identity ---------------------------------------------------------------


def test_tag_wins_over_everything():
    runs = [
        make_run("# trail: cell mlp\na = 1", cell_id="abc"),
        make_run("# trail: cell mlp\na = 2", cell_id="xyz"),
    ]
    identities, _ = identity_mod.resolve(runs)
    assert set(identities) == {"tag:mlp"}


def test_a_cell_id_seen_with_a_tag_stays_linked_when_the_tag_is_removed():
    runs = [make_run("# trail: cell mlp\na = 1", cell_id="abc"), make_run("a = 2", cell_id="abc")]
    identities, _ = identity_mod.resolve(runs)
    assert set(identities) == {"tag:mlp"}
    assert len(identities["tag:mlp"].runs) == 2


def test_untagged_edits_are_matched_by_similarity():
    # ADR 0004: on Colab this is the only mechanism, so it has to work.
    original = "w = np.zeros(8)\nfor i in range(100):\n    w -= lr * grad(w)\nprint(loss)"
    edited = "w = np.zeros(8)\nfor i in range(200):\n    w -= lr * grad(w)\nprint(loss)"
    identities, _ = identity_mod.resolve([make_run(original), make_run(edited)])
    assert len(identities) == 1


def test_an_unrelated_cell_does_not_steal_an_identity():
    identities, _ = identity_mod.resolve(
        [
            make_run("w = np.zeros(8)\nfor i in range(100):\n    w -= lr * grad(w)"),
            make_run("import matplotlib.pyplot as plt\nplt.plot(losses)\nplt.show()"),
        ]
    )
    assert len(identities) == 2


def test_duplicate_tag_on_two_cells_warns():
    runs = [
        make_run("# trail: cell t\na = 1", cell_id="one"),
        make_run("# trail: cell t\na = 2", cell_id="two"),
    ]
    _, warnings = identity_mod.resolve(runs)
    assert any("two different cells" in w or "different cells" in w for w in warnings)


def test_setup_cells_are_detected():
    identities, _ = identity_mod.resolve([make_run("import numpy as np\nimport trail")])
    assert all(i.hidden for i in identities.values())
    identities, _ = identity_mod.resolve([make_run("import numpy as np\nx = compute()")])
    assert not any(i.hidden for i in identities.values())


# -- grouping ---------------------------------------------------------------


def test_identical_reruns_join_the_same_version():
    versions = cell_of(
        [make_run("# trail: cell c\na = 1")] * 1 + [make_run("# trail: cell c\na = 1")]
    )
    assert len(versions) == 1 and len(versions[0].runs) == 2


def test_a_changed_cell_starts_a_new_version():
    versions = cell_of(
        [make_run("# trail: cell c\na = 1"), make_run("# trail: cell c\na = 2\nb = 3\nc = 4")]
    )
    assert [v.n for v in versions] == [1, 2]


def test_a_failed_run_becomes_an_attempt_on_the_version_that_fixed_it():
    versions = cell_of(
        [
            make_run("# trail: cell c\na = 1"),
            make_run("# trail: cell c\na = undefined", status="error"),
            make_run("# trail: cell c\na = 2\nb = 3"),
        ]
    )
    assert len(versions) == 2
    assert len(versions[1].attempts) == 1
    assert versions[1].attempts[0].error_type == "NameError"


def test_the_same_code_failing_later_is_state_not_an_edit():
    versions = cell_of(
        [
            make_run("# trail: cell c\na = 1"),
            make_run("# trail: cell c\na = 1", status="error"),
        ]
    )
    assert len(versions) == 1
    assert len(versions[0].failed_runs) == 1


def test_fix_tag_overwrites_the_current_version():
    versions = cell_of(
        [
            make_run("# trail: cell c\nprint(a)"),
            make_run("# trail: cell c\n# trail: fix\nprint(b)"),
        ]
    )
    assert len(versions) == 1
    assert "print(b)" in versions[0].code
    assert versions[0].replaced_code and "print(a)" in versions[0].replaced_code[0]


def test_comment_only_edit_updates_text_without_a_new_version():
    versions = cell_of(
        [
            make_run("# trail: cell c\na = 1"),
            make_run("# trail: cell c\na = 1  # explain myself"),
        ]
    )
    assert len(versions) == 1
    assert "explain myself" in versions[0].code


def test_tiny_changes_are_minor_and_keep_forces_a_real_version():
    minor = cell_of([make_run("# trail: cell c\nlr = 0.1"), make_run("# trail: cell c\nlr = 0.01")])
    assert minor[1].minor is True

    _CLOCK[0] += 100
    kept = cell_of(
        [
            make_run("# trail: cell c\nlr = 0.1"),
            make_run("# trail: cell c\n# trail: keep\nlr = 0.01"),
        ]
    )
    assert kept[1].minor is False


def test_is_minor_needs_both_conditions():
    assert is_minor("lr = 0.1", "lr = 0.01")
    assert not is_minor("a = 1\nb = 2", "a = 9\nb = 8")  # two lines
    assert not is_minor("a = 1", "a = compute_something_long()")  # too many chars


def test_noise_estimate_only_spans_genuinely_identical_conditions():
    """A change in another cell is not noise, and must not be reported as noise."""
    code = "# trail: cell c\nprint('loss', 1.0)"
    clean = [make_run(code, stdout="loss 1.00\n"), make_run(code, stdout="loss 1.02\n")]
    versions = cell_of(clean)
    assert versions[0].loss_std is not None and versions[0].loss_std < 0.1

    _CLOCK[0] += 100
    first = make_run(code, stdout="loss 1.00\n")
    other = make_run("# trail: cell other\nlr = 0.5")
    second = make_run(code, stdout="loss 99.0\n")
    identities, _ = identity_mod.resolve([first, other, second])
    versions = group(identities["tag:c"], all_runs=[first, other, second])
    assert versions[0].loss_std is None, "a change in another cell was reported as noise"
    assert versions[0].run_finals == [1.0, 99.0]


# -- steps ------------------------------------------------------------------


def test_versions_sharing_a_note_form_one_step_anchored_at_the_last():
    runs = [
        make_run("# trail: cell c\na = 1"),
        make_run("# trail: cell c\n# trail: cp tuning the init\na = 2\nb = 2"),
        make_run("# trail: cell c\n# trail: cp tuning the init\na = 3\nb = 3\nc = 3"),
        make_run("# trail: cell c\n# trail: cp now the lr\na = 4\nb = 4\nc = 4\nd = 4"),
    ]
    versions = cell_of(runs)
    found, _ = steps_mod.find("tag:c", versions)
    assert len(found) == 2
    assert found[0].note == "tuning the init"
    assert found[0].end_n == 3, "the step should anchor at the last version sharing the note"
    assert found[1].note == "now the lr"
    assert found[1].start_n == 3, "the next step starts where the previous anchored"


def test_a_note_left_on_for_too_long_warns():
    runs = [
        make_run("# trail: cell c\n# trail: cp same note\n" + "x" * i + " = 1") for i in range(1, 9)
    ]
    versions = cell_of(runs)
    _, warnings = steps_mod.find("tag:c", versions)
    assert any("forget to change" in w for w in warnings)


def test_step_keys_are_stable_for_the_same_inputs():
    runs = [
        make_run("# trail: cell c\na = 1"),
        make_run("# trail: cell c\n# trail: cp note\na = 2\nb = 2"),
    ]
    first, _ = steps_mod.find("tag:c", cell_of(runs))
    _CLOCK[0] += 100
    runs2 = [
        make_run("# trail: cell c\na = 1"),
        make_run("# trail: cell c\n# trail: cp note\na = 2\nb = 2"),
    ]
    second, _ = steps_mod.find("tag:c", cell_of(runs2))
    assert first[0].key == second[0].key


# -- metrics ----------------------------------------------------------------


@pytest.mark.parametrize(
    "stdout,name,value",
    [
        ("  10000/ 200000: 2.0718", "loss", 2.0718),
        ("val_loss: 2.07", "val_loss", 2.07),
        ("train loss = 3.31", "train_loss", 3.31),
        ("train 2.0718\nval 2.1052", "val_loss", 2.1052),
        ("final loss 3.895728700868263e+47", "loss", 3.895728700868263e47),
    ],
)
def test_metric_formats_from_real_lectures(stdout, name, value):
    metrics = extract(make_run("print('x')", stdout=stdout))
    assert metrics[name]["final"] == pytest.approx(value)


def test_explicit_metrics_beat_parsed_ones():
    run = make_run(
        "print('x')",
        stdout="loss 9.99",
        metrics=[{"name": "loss", "value": 1.23, "source": "explicit"}],
    )
    assert extract(run)["loss"]["final"] == 1.23


def test_tensor_repr_is_only_a_loss_when_the_code_says_so():
    assert "loss" in extract(make_run("loss", result_repr="tensor(3.3147)"))
    assert "loss" not in extract(make_run("accuracy", result_repr="tensor(3.3147)"))


def test_the_final_value_is_the_last_one_printed():
    metrics = extract(make_run("x", stdout="  0/100: 3.5\n 50/100: 2.5\n 99/100: 2.0"))
    assert metrics["loss"]["final"] == 2.0
    assert metrics["loss"]["series"] == [3.5, 2.5, 2.0]


# -- overrides and build ----------------------------------------------------


def test_overrides_rename_merge_and_hide():
    runs = [make_run("a = 1"), make_run("import os\nimport sys")]
    identities, _ = identity_mod.resolve(runs)
    keys = list(identities)
    result = overrides_mod.apply(
        identities,
        overrides_mod.Overrides(
            renames={keys[0]: "training loop"}, hidden=[keys[0]], unhidden=[keys[1]]
        ),
    )
    assert result[keys[0]].name == "training loop"
    assert result[keys[0]].hidden and not result[keys[1]].hidden


def test_merging_combines_runs_in_time_order():
    runs = [make_run("a = 1"), make_run("plt.show()")]
    identities, _ = identity_mod.resolve(runs)
    a, b = list(identities)
    merged = overrides_mod.apply(identities, overrides_mod.Overrides(merges=[[b, a]]))
    assert b not in merged
    assert len(merged[a].runs) == 2


def test_build_is_deterministic(tmp_path: Path):
    paths = ProjectPaths(tmp_path / "my logs", "p")
    paths.runs.mkdir(parents=True)
    lines = []
    for i, code in enumerate(
        ["# trail: cell c\na = 1", "# trail: cell c\n# trail: cp note\na = 2\nb = 2"]
    ):
        lines.append(
            json.dumps(
                {
                    "type": "run",
                    "schema": 1,
                    "session": "s",
                    "seq": i,
                    "ts_start": f"2026-01-01T00:00:0{i}.000Z",
                    "code": code,
                    "status": "ok",
                    "duration_s": 0.1,
                    "stdout": {"text": "", "truncated": False, "total_lines": 0},
                }
            )
        )
    (paths.runs / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    first = to_json(build(paths))
    second = to_json(build(paths))
    first.pop("built_at"), second.pop("built_at")
    assert first == second
    assert first["cells"][0]["identity"] == "tag:c"
    assert len(first["steps"]) == 1
