"""Calling `claude -p` (SPEC 11.1).

Flags verified against the installed CLI, not remembered — see ADR 0005. The prompt
goes in on **stdin**, never as an argument: bundles reach 60 KB and would blow past
the shell's argument limit.

Read-only by construction: `--allowedTools Read` so it can look at plot PNGs, and
everything that writes or reaches the network explicitly denied. Never
`--dangerously-skip-permissions`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 240
DEFAULT_MAX_TURNS = 4
DENY = "Bash,Edit,Write,WebFetch,WebSearch,NotebookEdit,Task"

#: Phrases that mean "stop, and don't burn the rest of the steps failing too".
USAGE_LIMIT_HINTS = (
    "usage limit",
    "rate limit",
    "quota",
    "too many requests",
    "upgrade to increase",
)
AUTH_HINTS = ("not logged in", "unauthorized", "authentication", "please run `claude`", "api key")


class ClaudeNotFound(RuntimeError):
    pass


class UsageLimit(RuntimeError):
    pass


class AuthProblem(RuntimeError):
    pass


@dataclass
class Result:
    text: str
    session_id: str | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def meta(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "duration_ms": self.duration_ms,
            "num_turns": self.num_turns,
            "total_cost_usd": self.cost_usd,
        }


def find_binary(name: str = "claude") -> str:
    binary = shutil.which(name)
    if binary is None:
        raise ClaudeNotFound(
            "Claude Code isn't on your PATH. Check with `which claude`, "
            "or set [claude] binary in ~/.config/trail/config.toml."
        )
    return binary


def _classify_failure(stderr: str, stdout: str) -> None:
    blob = f"{stderr}\n{stdout}".lower()
    if any(hint in blob for hint in USAGE_LIMIT_HINTS):
        raise UsageLimit(stderr.strip() or stdout.strip() or "usage limit reached")
    if any(hint in blob for hint in AUTH_HINTS):
        raise AuthProblem(
            "Claude Code couldn't authenticate. Run `claude` once interactively to log in."
        )


def run(
    prompt: str,
    cwd: Path,
    *,
    binary: str = "claude",
    model: str = "",
    max_turns: int = DEFAULT_MAX_TURNS,
    timeout: int = DEFAULT_TIMEOUT,
    allowed_tools: str = "Read",
    extra_args: list[str] | None = None,
    resume: str | None = None,
    output_json: bool = True,
) -> Result:
    """Run one non-interactive Claude call and return its text plus run stats."""
    command = [find_binary(binary), "-p"]
    if output_json:
        command += ["--output-format", "json"]
    command += ["--max-turns", str(max_turns)]
    command += ["--allowedTools", allowed_tools, "--disallowedTools", DENY]
    if model:
        command += ["--model", model]
    if resume:
        command += ["--resume", resume]
    command += extra_args or []

    try:
        completed = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClaudeNotFound(str(exc)) from exc

    if completed.returncode != 0:
        _classify_failure(completed.stderr, completed.stdout)
        first_lines = "\n".join((completed.stderr or completed.stdout).strip().split("\n")[:5])
        raise RuntimeError(f"claude exited {completed.returncode}:\n{first_lines}")

    if not output_json:
        return Result(text=completed.stdout)

    try:
        wrapper = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError("claude didn't return JSON; try running it once interactively") from exc

    if isinstance(wrapper, dict) and wrapper.get("is_error"):
        _classify_failure("", str(wrapper.get("result", "")))
        raise RuntimeError(str(wrapper.get("result", "claude reported an error"))[:500])

    text = str(wrapper.get("result", "")) if isinstance(wrapper, dict) else str(wrapper)
    _classify_failure("", text)
    return Result(
        text=text,
        session_id=wrapper.get("session_id"),
        duration_ms=wrapper.get("duration_ms"),
        num_turns=wrapper.get("num_turns"),
        cost_usd=wrapper.get("total_cost_usd"),
        raw=wrapper if isinstance(wrapper, dict) else {},
    )
