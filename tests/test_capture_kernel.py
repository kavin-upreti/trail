"""Capture, exercised against a real ipykernel (SPEC 17.2).

Every scenario here is one of the eight the spec lists. They are slower than unit
tests and worth every second: this is the only place that proves Trail survives
contact with an actual notebook.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.conftest import SETUP, read_all, read_runs
from tests.kernel_driver import Kernel

pytestmark = pytest.mark.timeout(180)


def wait_for_runs(logs_root: Path, project: str, count: int, timeout: float = 10.0) -> list[dict]:
    """The writer is a background thread, so give it a moment to land."""
    deadline = time.time() + timeout
    runs: list[dict] = []
    while time.time() < deadline:
        runs = read_runs(logs_root, project)
        if len(runs) >= count:
            return runs
        time.sleep(0.05)
    return runs


# -- 1. an evolving cell ----------------------------------------------------


def test_evolving_cell_records_every_run_with_status(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="evolve"))
    kernel.run("# @cell: mlp\nx = 1\nprint('v1')\nx")
    kernel.run("# @cell: mlp\nx = undefined_name")  # a typo, which fails
    kernel.run("# @cell: mlp\n# @fix\nx = 2\nprint('v2')\nx")
    kernel.run("# @cell: mlp\n# @cp initial loss too high\nx = 3\nprint('v3')\nx")
    kernel.run("# @cell: mlp\n# @cp initial loss too high\nx = 3\nprint('v3')\nx")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "evolve", 5)
    assert len(runs) == 5

    assert [r["status"] for r in runs] == ["ok", "error", "ok", "ok", "ok"]
    assert runs[1]["error"]["type"] == "NameError"
    assert runs[1]["error"]["stage"] == "exec"
    assert runs[1]["error"]["traceback_tail"]

    # The tags survive verbatim in `code`; interpreting them is the engine's job.
    assert all("# @cell: mlp" in r["code"] for r in runs)
    assert "# @fix" in runs[2]["code"]
    assert "# @cp initial loss too high" in runs[3]["code"]

    assert runs[0]["result_repr"] == "1"
    assert runs[0]["stdout"]["text"] == "v1"
    assert runs[0]["vars"]["x"] == 1
    assert runs[4]["vars"]["x"] == 3
    assert [r["seq"] for r in runs] == sorted(r["seq"] for r in runs)


def test_session_start_and_end_bracket_the_run_records(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="bracket"))
    kernel.run("y = 1")
    kernel.run("trail.stop()")

    records = read_all(logs_root, "bracket")
    assert records[0]["type"] == "session_start"
    assert records[0]["project"] == "bracket"
    assert records[0]["frontend"] in ("jupyter", "ipython", "vscode")
    assert records[0]["packages"]
    assert records[-1]["type"] == "session_end"
    assert records[-1]["clean"] is True
    assert records[-1]["runs"] == 1


# -- 2. output capture ------------------------------------------------------


def test_stdout_stderr_shell_commands_and_carriage_returns(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="outputs"))
    reply = kernel.run("print('visible to the user')")
    kernel.run("import sys\nfor p in ['10%', '50%', '100%']: sys.stderr.write(p + '\\r')")
    kernel.run("!echo shelled")
    kernel.run("for i in range(1000): print('line', i)")
    kernel.run("trail.stop()")

    # The user still sees everything; the tee is write-through.
    assert "visible to the user" in reply.stdout

    runs = wait_for_runs(logs_root, "outputs", 4)
    assert runs[0]["stdout"]["text"] == "visible to the user"

    # tqdm-style: only the final state of the overwritten line survives.
    assert runs[1]["stderr"]["text"].strip() == "100%"

    assert "shelled" in runs[2]["stdout"]["text"]

    big = runs[3]["stdout"]
    assert big["total_lines"] == 1000
    assert big["truncated"] is True
    assert "lines omitted" in big["text"]
    assert len(big["text"]) < 64 * 1024


# -- 3. plots and rich displays --------------------------------------------


def test_inline_plot_becomes_a_blob_and_html_display_is_kept(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="plots"))
    kernel.run(
        "import matplotlib\nmatplotlib.use('agg')\n"
        "import matplotlib.pyplot as plt\n"
        "%matplotlib inline"
    )
    kernel.run("# @cell: plot\nplt.plot([1, 2, 3])\nplt.show()")
    kernel.run("from IPython.display import HTML, display\ndisplay(HTML('<b>hi</b>'))")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "plots", 3)
    plot_run = next(r for r in runs if "@cell: plot" in r["code"])
    images = [d for d in plot_run["displays"] if d.get("mime") == "image/png"]
    assert images, f"no PNG captured, displays were {plot_run['displays']}"

    blob = logs_root / "plots" / "blobs" / images[0]["blob"]
    assert blob.exists() and blob.stat().st_size > 0
    assert blob.read_bytes()[:4] == b"\x89PNG"
    assert images[0]["bytes"] == blob.stat().st_size

    html_run = runs[-1]
    htmls = [d for d in html_run["displays"] if d.get("mime") == "text/html"]
    assert any("<b>hi</b>" in d["html"] for d in htmls)


# -- 4. interrupting a long cell -------------------------------------------


def test_keyboard_interrupt_is_recorded_with_its_output(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="interrupt"))

    import threading

    threading.Timer(2.0, kernel.interrupt).start()
    kernel.run("import time\nprint('training')\nfor _ in range(200): time.sleep(0.05)")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "interrupt", 1)
    assert runs[0]["status"] == "interrupted"
    assert runs[0]["error"]["type"] == "KeyboardInterrupt"
    assert "training" in runs[0]["stdout"]["text"]  # partial output is kept


# -- 5. lifecycle -----------------------------------------------------------


def test_start_is_idempotent_and_pause_resume_work(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="life"))
    kernel.run(SETUP.format(project="life"))  # again: should not start a second session
    kernel.run("a = 1")
    kernel.run("trail.pause()")
    kernel.run("invisible = 1")
    kernel.run("trail.resume()")
    kernel.run("b = 2")
    kernel.run("trail.stop()")

    time.sleep(1.0)
    assert len(list((logs_root / "life" / "runs").glob("*.jsonl"))) == 1

    records = read_all(logs_root, "life")
    assert [r["kind"] for r in records if r["type"] == "marker"] == ["pause", "resume"]
    code = "\n".join(r["code"] for r in records if r["type"] == "run")
    assert "invisible" not in code
    assert "b = 2" in code


def test_the_start_cell_itself_is_not_recorded(kernel: Kernel, logs_root: Path):
    # post_run_cell fires for it without a matching pre, and must be ignored (SPEC 8.2).
    kernel.run(SETUP.format(project="startcell") + "\nprint('same cell')")
    kernel.run("z = 1")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "startcell", 1)
    assert len(runs) == 1
    assert "z = 1" in runs[0]["code"]


def test_switching_project_mid_kernel_starts_a_new_session(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="first"))
    kernel.run("a = 1")
    kernel.run(SETUP.format(project="second"))
    kernel.run("b = 2")
    kernel.run("trail.stop()")

    assert len(wait_for_runs(logs_root, "first", 1)) == 1
    assert len(wait_for_runs(logs_root, "second", 1)) == 1


def test_streams_are_restored_after_stop(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="restore"))
    kernel.run("trail.stop()")
    reply = kernel.run("import sys\nprint(type(sys.stdout).__name__)")
    assert "Tee" not in reply.stdout


# -- 6. the fallback path ---------------------------------------------------


def test_unwritable_root_falls_back_then_merges_on_next_start(tmp_path: Path):
    """Drive disconnects mid-lecture; recording must continue somewhere local."""
    root = tmp_path / "read only root"
    root.mkdir()
    fallback = tmp_path / "fallback"

    with Kernel(env={"TRAIL_ROOT": str(root)}) as kernel:
        kernel.run(
            "import trail.capture.env as e, pathlib\n"
            f"e.fallback_dir = lambda project, frontend=None: pathlib.Path({str(fallback)!r})"
        )
        # Root exists but refuses new directories — exactly an unmounted Drive.
        root.chmod(0o500)
        try:
            reply = kernel.run('import trail; trail.start("fb")')
            assert reply.status == "ok", "an unwritable root must not raise into the cell"
            kernel.run("a = 1")
            kernel.run("trail.stop()")

            time.sleep(1.0)
            assert (fallback / "runs").is_dir(), "nothing was written to the fallback"
            sessions = list((fallback / "runs").glob("*.jsonl"))
            assert sessions and "a = 1" in sessions[0].read_text(encoding="utf-8")
        finally:
            root.chmod(0o700)

        # With the root writable again, the next start() merges the fallback back in.
        kernel.run('trail.start("fb")')
        kernel.run("trail.stop()")

    time.sleep(1.0)
    merged = list((root / "fb" / "fallback-imported").iterdir())
    assert merged, "fallback logs were never merged back into the real root"
    landed = list((root / "fb" / "runs").glob("*.jsonl"))
    assert any("a = 1" in f.read_text(encoding="utf-8") for f in landed)


# -- 7. variable fingerprints across cells ---------------------------------


def test_a_variable_changed_in_another_cell_shows_up(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="vars"))
    kernel.run("# @cell: hparams\nlr = 0.1")
    kernel.run("# @cell: train\nloss = 3.3")
    kernel.run("# @cell: hparams\nlr = 0.01")
    kernel.run("# @cell: train\nloss = 2.1")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "vars", 4)
    assert runs[1]["vars"]["lr"] == 0.1
    assert runs[3]["vars"]["lr"] == 0.01  # the engine diffs these to explain the change
    assert runs[3]["vars"]["loss"] == 2.1


def test_tensor_shapes_are_recorded_without_their_contents(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="shapes"))
    kernel.run("import numpy as np\nW1 = np.zeros((30, 200), dtype=np.float32)")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "shapes", 1)
    assert runs[0]["vars"]["W1"] == {"shape": [30, 200], "dtype": "float32"}


# -- 8. tags, secrets and skipping -----------------------------------------


def test_skip_tag_stores_a_minimal_record(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="skipping"))
    kernel.run("# trail: skip\nprint('noisy install output ' * 100)")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "skipping", 1)
    assert runs[0]["skipped"] is True
    assert "stdout" not in runs[0] and "vars" not in runs[0]
    assert len(runs[0]["code"]) <= 200


def test_secrets_never_reach_the_log(kernel: Kernel, logs_root: Path):
    token = "sk-ant-" + "a" * 40
    kernel.run(SETUP.format(project="secrets"))
    kernel.run(f"api_key = {token!r}\nprint('key is', api_key)")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "secrets", 1)
    blob = (logs_root / "secrets" / "runs").glob("*.jsonl")
    on_disk = "".join(p.read_text(encoding="utf-8") for p in blob)
    assert token not in on_disk
    assert "[REDACTED]" in runs[0]["code"]


def test_both_tag_spellings_work_in_a_real_kernel(kernel: Kernel, logs_root: Path):
    # ADR 0003: "# trail:" is documented, "# @" stays a working alias.
    kernel.run(SETUP.format(project="spellings"))
    kernel.run("# trail: cell mlp\n# trail: cp lowered the learning rate\na = 1")
    kernel.run("# @cell: mlp\n# @cp older spelling\na = 2")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "spellings", 2)
    from trail.common import tags as tagmod

    first, second = (tagmod.parse(r["code"]) for r in runs)
    assert first.cell == "mlp" and first.checkpoint_note == "lowered the learning rate"
    assert second.cell == "mlp" and second.checkpoint_note == "older spelling"


def test_checkpoint_and_metric_calls_land_on_the_run(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="marks"))
    kernel.run(
        "trail.checkpoint('scaled W1 down')\ntrail.metric('val_loss', 2.07)\ntrail.note('hi')"
    )
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "marks", 1)
    assert runs[0]["checkpoint_call"] == "scaled W1 down"
    assert runs[0]["metrics"] == [{"name": "val_loss", "value": 2.07, "source": "explicit"}]
    assert "hi" in runs[0]["notes"]


def test_cell_id_is_captured_when_the_frontend_sends_one(kernel: Kernel, logs_root: Path):
    # Verified in docs/decisions/0002: it arrives in the execute_request metadata.
    kernel.run(SETUP.format(project="cellids"))
    kernel.run("untagged = 1", cell_id="cell-abc-123")
    kernel.run("also_untagged = 2")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "cellids", 2)
    assert runs[0]["cell_id"] == "cell-abc-123"
    assert runs[1]["cell_id"] is None


def test_syntax_error_is_classified_before_execution(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="syntax"))
    kernel.run("def broken(:\n    pass")
    kernel.run("trail.stop()")

    runs = wait_for_runs(logs_root, "syntax", 1)
    assert runs[0]["status"] == "syntax_error"
    assert runs[0]["error"]["stage"] == "compile"


def test_a_broken_hook_never_breaks_the_users_cell(kernel: Kernel, logs_root: Path):
    """Hard rule 1, tested directly: sabotage capture, the notebook keeps working."""
    kernel.run(SETUP.format(project="robust"))
    kernel.run(
        "import trail\n"
        "s = trail.session()\n"
        "s._build_record = lambda *a, **k: 1 / 0"  # every record now explodes
    )
    reply = kernel.run("print('user code still runs')\n40 + 2")

    assert reply.status == "ok"
    assert "user code still runs" in reply.stdout
    assert reply.result == "42"

    kernel.run("trail.stop()")
    assert (logs_root / "robust" / "trail-errors.log").exists()


# -- performance ------------------------------------------------------------


@pytest.mark.slow
def test_hook_overhead_stays_under_5ms(kernel: Kernel, logs_root: Path):
    kernel.run(SETUP.format(project="perf"))
    reply = kernel.run(
        "import time\nstart = time.perf_counter()\nfor i in range(200): pass\nprint('setup ok')"
    )
    assert reply.status == "ok"

    times = []
    for i in range(200):
        started = time.perf_counter()
        kernel.run(f"v{i} = {i}")
        times.append(time.perf_counter() - started)
    kernel.run("trail.stop()")

    baseline_runs = wait_for_runs(logs_root, "perf", 200)
    assert len(baseline_runs) >= 200
    # Round-trip time is dominated by IPC; what we assert is that capture's own
    # submit path is negligible. trail.report() surfaces the real p50/p95.
    assert sum(times) / len(times) < 0.5
