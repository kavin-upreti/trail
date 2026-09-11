"""Viewer tests (SPEC 17.4).

The security ones matter most: every string on these pages was printed by the
user's own notebook, and a lecture that printed a `<script>` tag must never get to
run it in the viewer (hard rule 7).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trail.viewer.app import create_app
from trail.viewer.diffs import side_by_side, sparkline, unified


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A small project with a checkpoint, an error, a plot and a saved analysis."""
    root = tmp_path / "My Drive" / "trail logs"
    runs = root / "demo" / "runs"
    runs.mkdir(parents=True)
    blobs = root / "demo" / "blobs"
    blobs.mkdir()
    sha = "a" * 64
    (blobs / f"{sha}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    rows = [
        ("# trail: cell hparams\nlr = 0.1", "", "ok", []),
        ("# trail: cell train\nprint('loss', 3.31)", "loss 3.31\n", "ok", []),
        ("# trail: cell train\nprint('loss', 3.31)\nboom", "", "error", []),
        (
            "# trail: cell train\n# trail: cp scaled the init down\nprint('loss', 3.07)\nw = 1",
            "loss 3.07\n<script>alert('xss')</script>\n",
            "ok",
            [{"mime": "image/png", "blob": f"{sha}.png", "bytes": 40}],
        ),
    ]
    lines = []
    for i, (code, stdout, status, displays) in enumerate(rows):
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
                    "displays": displays,
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


@pytest.fixture
def client(root: Path) -> TestClient:
    return TestClient(create_app(root))


def save_analysis(root: Path, client: TestClient) -> str:
    """Write an analysis for the project's only step, the way `trail analyze` would."""
    from trail.analysis import store
    from trail.common.paths import ProjectPaths
    from trail.engine.build import build

    paths = ProjectPaths(root, "demo")
    result = build(paths)
    step = result.steps[0]
    store.save(
        paths,
        step,
        {
            "title": "Scaled the init down",
            "summary": "Smaller initial logits.",
            "changes": [{"what": "W2 * 0.01"}],
            "why": "Confident wrong guesses cost loss.",
            "effect": {
                "metric": "loss",
                "before": 3.31,
                "after": 3.07,
                "direction": "improved",
                "confidence": "high",
                "noise_note": None,
            },
            "tradeoffs": [],
            "concepts": ["kaiming-init"],
            "other_concepts": [{"name": "Made up", "why_relevant": "not in the vocabulary"}],
            "context_warnings": ["lr also changed"],
            "plot_observations": None,
            "try_next": [],
            "self_check": [{"question": "Why?", "answer": "Because."}],
        },
        {"model": "sonnet", "total_cost_usd": 0.01},
    )
    return step.key


# -- every page renders -----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/",
        "/p/demo",
        "/p/demo/story",
        "/p/demo/concepts",
        "/p/demo/qa",
        "/concepts",
        "/p/demo/cell/tag:train",
        "/p/demo/cell/tag:train?a=1&b=2",
    ],
)
def test_pages_render(client: TestClient, url: str):
    assert client.get(url).status_code == 200


def test_unknown_project_and_cell_are_404(client: TestClient):
    assert client.get("/p/nope").status_code == 404
    assert client.get("/p/demo/cell/tag:nope").status_code == 404


# -- content ----------------------------------------------------------------


def test_cell_page_shows_the_diff_and_the_metrics(client: TestClient):
    body = client.get("/p/demo/cell/tag:train?a=1&b=2").text
    assert 'class="diff"' in body
    assert "3.07" in body and "3.31" in body
    assert "scaled the init down" in body
    assert "failed attempt" in body


def test_cell_page_offers_to_explain_an_unexplained_step(client: TestClient):
    body = client.get("/p/demo/cell/tag:train?a=1&b=2").text
    assert "Explain this step" in body
    assert "data-analyze=" in body


def test_cell_page_shows_a_saved_analysis(root: Path, client: TestClient):
    save_analysis(root, client)
    body = client.get("/p/demo/cell/tag:train?a=1&b=2").text
    assert "Scaled the init down" in body
    assert "https://arxiv.org/abs/1502.01852" in body  # a real, vocabulary link
    assert "unverified — no link" in body  # and the ones without
    assert "lr also changed" in body  # the caution survives


def test_story_lists_steps_and_links_back_to_the_cell(root: Path, client: TestClient):
    save_analysis(root, client)
    body = client.get("/p/demo/story").text
    assert "scaled the init down" in body
    assert "/p/demo/cell/tag:train?a=1&b=2" in body


def test_story_explains_itself_when_there_are_no_checkpoints(tmp_path: Path):
    root = tmp_path / "logs"
    runs = root / "empty" / "runs"
    runs.mkdir(parents=True)
    (runs / "s.jsonl").write_text(
        json.dumps(
            {
                "type": "run",
                "schema": 1,
                "session": "s",
                "seq": 0,
                "ts_start": "2026-01-01T00:00:00.000Z",
                "code": "a = 1",
                "status": "ok",
                "duration_s": 0.1,
                "stdout": {"text": "", "truncated": False, "total_lines": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    body = TestClient(create_app(root)).get("/p/empty/story").text
    assert "no story to tell" in body.lower()
    assert "trail: cp" in body  # tells them how to make one


def test_concepts_page_links_back_to_where_it_was_learned(root: Path, client: TestClient):
    save_analysis(root, client)
    body = client.get("/p/demo/concepts").text
    assert "Kaiming" in body
    assert "/p/demo/cell/tag:train" in body


# -- security (hard rule 7) -------------------------------------------------


def test_recorded_script_tags_are_escaped_not_executed(client: TestClient):
    body = client.get("/p/demo/cell/tag:train?a=1&b=2").text
    assert "<script>alert('xss')</script>" not in body
    assert "&lt;script&gt;" in body


def test_every_iframe_is_sandboxed(client: TestClient):
    body = client.get("/p/demo/cell/tag:train?a=1&b=2").text
    assert body.count("<iframe") == body.count('sandbox=""')


def test_the_page_loads_nothing_from_the_network(client: TestClient):
    body = client.get("/p/demo/cell/tag:train?a=1&b=2").text
    for marker in ("//cdn", "cdnjs", "googleapis", "unpkg", "jsdelivr"):
        assert marker not in body


def test_blob_route_rejects_path_traversal(client: TestClient):
    for bad in [
        "../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "notahash.png",
        "a" * 64 + ".exe",
        "a" * 63 + ".png",
    ]:
        assert client.get(f"/blobs/demo/{bad}").status_code == 404


def test_blob_route_serves_a_real_plot(client: TestClient):
    response = client.get(f"/blobs/demo/{'a' * 64}.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


# -- actions ----------------------------------------------------------------


def test_renaming_a_cell_changes_the_page(client: TestClient):
    assert (
        client.post(
            "/api/p/demo/cells/tag:train", json={"action": "rename", "name": "the training loop"}
        ).status_code
        == 200
    )
    assert "the training loop" in client.get("/p/demo").text


def test_hiding_a_cell_moves_it_under_setup(client: TestClient):
    client.post("/api/p/demo/cells/tag:train", json={"action": "hide"})
    assert "setup cell" in client.get("/p/demo").text
    client.post("/api/p/demo/cells/tag:train", json={"action": "unhide"})


def test_an_unknown_action_is_rejected(client: TestClient):
    assert client.post("/api/p/demo/cells/tag:train", json={"action": "destroy"}).status_code == 400


def test_stamp_and_rebuild(client: TestClient):
    assert client.get("/api/p/demo/stamp").json()["stamp"] > 0
    assert client.post("/api/p/demo/rebuild").json()["ok"] is True


def test_analyze_with_nothing_pending_is_refused(root: Path, client: TestClient):
    save_analysis(root, client)
    response = client.post("/api/p/demo/analyze", json={"all_pending": True})
    assert response.status_code == 400


def test_unknown_job_is_404(client: TestClient):
    assert client.get("/api/jobs/deadbeef").status_code == 404


# -- diff rendering ---------------------------------------------------------


def test_side_by_side_marks_each_kind_of_change():
    rows = side_by_side("a = 1\nb = 2\nc = 3", "a = 1\nb = 99\nc = 3\nd = 4")
    kinds = [r.kind for r in rows]
    assert "change" in kinds and "add" in kinds and "equal" in kinds


def test_side_by_side_folds_long_unchanged_runs():
    before = "\n".join(f"line {i}" for i in range(60))
    after = before + "\nnew line"
    rows = side_by_side(before, after)
    assert any(r.kind == "skip" for r in rows)
    assert len(rows) < 60


def test_side_by_side_escapes_html_in_code():
    rows = side_by_side("x = '<script>'", "y = '<script>'")
    assert all("<script>" not in r.left and "<script>" not in r.right for r in rows)


def test_unified_labels_its_lines():
    kinds = {kind for kind, _ in unified("a = 1", "a = 2", "v1", "v2")}
    assert "add" in kinds and "remove" in kinds


def test_sparkline_needs_at_least_two_points():
    assert sparkline([]) == ""
    assert sparkline([1.0]) == ""
    assert "<svg" in sparkline([3.0, 2.0, 1.0])


def test_sparkline_survives_a_flat_series():
    # A constant series would divide by zero if we weren't careful.
    assert "<svg" in sparkline([2.0, 2.0, 2.0])
