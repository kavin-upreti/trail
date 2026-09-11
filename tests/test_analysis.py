"""Analysis tests (SPEC 17.3) — every branch, no real Claude calls."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from trail.analysis import concepts as concepts_mod
from trail.analysis import runner
from trail.analysis.render import effect_chip, render
from trail.analysis.validate import InvalidAnalysis, extract_json, validate

FAKE_DIR = str(Path(__file__).parent / "fake_claude")


@pytest.fixture
def fake_claude(monkeypatch, tmp_path):
    """Put the stand-in CLI first on PATH."""
    monkeypatch.setenv("PATH", FAKE_DIR + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLAUDE_COUNTER", str(tmp_path / "counter"))
    return tmp_path


# -- the vocabulary ---------------------------------------------------------


def test_the_packaged_vocabulary_loads():
    loaded = concepts_mod.load()
    assert len(loaded) > 30
    assert "kaiming-init" in loaded
    assert loaded["kaiming-init"].refs[0].url.startswith("https://")


def test_vocabulary_lines_carry_no_urls():
    # They'd cost tokens in every bundle and Claude never needs them.
    text = concepts_mod.vocabulary_lines()
    assert "http" not in text
    assert "kaiming-init — " in text


# -- extracting JSON --------------------------------------------------------


def test_extract_json_from_a_fenced_block():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_from_a_chatty_reply():
    assert extract_json('Sure!\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_extract_json_rejects_an_empty_reply():
    with pytest.raises(InvalidAnalysis):
        extract_json("   ")


def test_extract_json_rejects_prose():
    with pytest.raises(InvalidAnalysis):
        extract_json("I could not complete this task.")


# -- validation -------------------------------------------------------------


def minimal(**overrides):
    base = {
        "title": "A title",
        "summary": "A summary.",
        "effect": {
            "metric": "loss",
            "before": 3.0,
            "after": 2.0,
            "direction": "improved",
            "confidence": "high",
        },
        "self_check": [{"question": "q", "answer": "a"}],
    }
    base.update(overrides)
    return base


def test_unknown_concept_ids_are_demoted_not_rejected():
    """Hard rule 6: never invent a link, but never bin a good explanation either."""
    out = validate(minimal(concepts=["kaiming-init", "made-up-thing"]), concepts_mod.known)
    assert out["concepts"] == ["kaiming-init"]
    assert any(o["name"] == "made-up-thing" for o in out["other_concepts"])


def test_a_missing_title_or_summary_is_fatal():
    for field in ("title", "summary"):
        broken = minimal()
        broken.pop(field)
        with pytest.raises(InvalidAnalysis):
            validate(broken, concepts_mod.known)


def test_self_check_is_required_and_capped():
    with pytest.raises(InvalidAnalysis):
        validate(minimal(self_check=[]), concepts_mod.known)
    many = [{"question": f"q{i}", "answer": "a"} for i in range(9)]
    assert len(validate(minimal(self_check=many), concepts_mod.known)["self_check"]) == 3


def test_bad_enum_values_fall_back_safely():
    out = validate(
        minimal(effect={"metric": "loss", "direction": "amazing", "confidence": "total"}),
        concepts_mod.known,
    )
    assert out["effect"]["direction"] == "unclear"
    assert out["effect"]["confidence"] == "low"


def test_title_is_trimmed():
    assert len(validate(minimal(title="x" * 200), concepts_mod.known)["title"]) == 70


def test_non_numeric_metrics_become_none():
    out = validate(minimal(effect={"before": "lots", "after": None}), concepts_mod.known)
    assert out["effect"]["before"] is None


# -- rendering --------------------------------------------------------------


def test_effect_chip_always_states_confidence():
    chip = effect_chip(
        {
            "metric": "loss",
            "before": 3.31,
            "after": 3.07,
            "direction": "improved",
            "confidence": "medium",
        }
    )
    assert "3.31" in chip and "3.07" in chip and "medium confidence" in chip


def test_render_links_known_concepts_and_flags_the_rest():
    markdown = render(
        validate(
            minimal(
                concepts=["kaiming-init"],
                other_concepts=[{"name": "Vibes", "why_relevant": "none"}],
            ),
            concepts_mod.known,
        ),
        {"model": "sonnet"},
    )
    assert "https://arxiv.org/abs/1502.01852" in markdown
    assert "*(unverified — no link)*" in markdown
    assert "<details><summary>Answer</summary>" in markdown


def test_render_surfaces_context_warnings_as_a_caution():
    markdown = render(validate(minimal(context_warnings=["lr also changed"]), concepts_mod.known))
    assert "Careful" in markdown and "lr also changed" in markdown


# -- the runner -------------------------------------------------------------


def test_runner_parses_a_normal_reply(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "valid")
    result = runner.run("prompt", tmp_path)
    assert result.session_id == "fake-session-1"
    assert result.cost_usd == 0.01
    assert validate(extract_json(result.text), concepts_mod.known)["title"]


def test_runner_sends_the_prompt_on_stdin(fake_claude, monkeypatch, tmp_path):
    # A 60 KB bundle would blow past the shell's argument limit.
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "echo_prompt")
    result = runner.run("MARKER-TEXT-12345", tmp_path)
    assert "MARKER-TEXT-12345" in extract_json(result.text)["summary"]


def test_runner_raises_on_a_usage_limit(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "usage_limit")
    with pytest.raises(runner.UsageLimit):
        runner.run("prompt", tmp_path)


def test_runner_spots_a_usage_limit_reported_in_the_result_text(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "usage_limit_in_result")
    with pytest.raises(runner.UsageLimit):
        runner.run("prompt", tmp_path)


def test_runner_raises_on_an_auth_problem(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "auth")
    with pytest.raises(runner.AuthProblem):
        runner.run("prompt", tmp_path)


def test_runner_reports_a_plain_failure_with_its_stderr(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nonzero")
    with pytest.raises(RuntimeError, match="something went wrong"):
        runner.run("prompt", tmp_path)


def test_runner_times_out(fake_claude, monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run("prompt", tmp_path, timeout=1)


def test_runner_explains_non_json_output(fake_claude, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "not_json_output")
    with pytest.raises(RuntimeError, match="didn't return JSON"):
        runner.run("prompt", tmp_path)


def test_missing_binary_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(runner.ClaudeNotFound, match="which claude"):
        runner.run("prompt", tmp_path)


def test_the_runner_never_allows_dangerous_tools(fake_claude, monkeypatch, tmp_path):
    captured = {}
    real = runner.subprocess.run

    def spy(command, **kwargs):
        captured["command"] = command
        return real(command, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", spy)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "valid")
    runner.run("prompt", tmp_path)

    command = captured["command"]
    assert "--dangerously-skip-permissions" not in command
    assert "--allow-dangerously-skip-permissions" not in command
    deny = command[command.index("--disallowedTools") + 1]
    for tool in ("Bash", "Edit", "Write", "WebFetch", "WebSearch"):
        assert tool in deny


@pytest.mark.live
def test_a_real_claude_call(tmp_path):
    """Only runs with TRAIL_LIVE=1 — it costs real usage."""
    if os.environ.get("TRAIL_LIVE") != "1":
        pytest.skip("set TRAIL_LIVE=1 to run against the real claude")
    result = runner.run('Reply with exactly: {"ok": true}', tmp_path, max_turns=1)
    assert extract_json(result.text) == {"ok": True}
