# Trail — notes for Claude Code

Spec: docs/SPEC.md (source of truth). State: docs/STATE.md (read at start, rewrite at end).
Decisions with real alternatives → short ADR in docs/decisions/NNNN-title.md.

## Commands
- Tests: `uv run pytest -q` (slow: `-m slow`; live Claude: `TRAIL_LIVE=1 uv run pytest -m live`)
- Lint/format: `uv run ruff check . && uv run ruff format .`
- CLI during dev: `uv run trail ...`

## Rules
- Capture code (src/trail/capture) must never raise into user code and has zero third-party deps.
- Raw logs are append-only; everything else is derived.
- Integration tests use a real ipykernel via tests/kernel_driver.py. Don't mock IPython for them.
- VERIFY external behaviour (IPython, ipykernel, Colab, `claude` flags) by inspecting source or running it.
- Viewer: offline only (no CDNs), bind 127.0.0.1, escape all recorded text.
- Commit after each milestone; keep docs/STATE.md current.

## Talking to the user
The user is a student learning ML. Explain decisions plainly and briefly, be encouraging,
and if you make a mistake, say so simply and fix it.
