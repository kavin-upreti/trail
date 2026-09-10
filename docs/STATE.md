# Current State
Last updated: 2026-09-11 by Claude Code

## Done
- Spec written (docs/SPEC.md).
- **M0 — Scaffolding.** Git repo, `pyproject.toml` (hatchling, dist `trail-nb`, import
  `trail`, zero base deps, `[mac]` + `[dev]` extras), src layout, ruff + pytest config,
  `CLAUDE.md`, README skeleton, ADR 0001 (why raw append-only logs), smoke tests.
  `uv run pytest` passes.

## In progress
- Nothing. M0 is closed and committed.

## Next
1. **M1 — Capture core** (SPEC 7, 8, 9): hooks, tee, display capture, fingerprint,
   redaction, writer + fallback, session lifecycle, public API, tags parser,
   `trail.report()`. Done when the 17.2 real-kernel scenarios pass.
2. M2 — Colab spike (needs the user to run `examples/colab_spike.ipynb`).

## Open questions
- [BLOCKS M2] The repo `github.com/kavin-upreti/trail` does not exist yet, and the `gh`
  CLI on this Mac is authenticated as a *different* account (`KavinUpreti`). Before the
  Colab spike can install Trail, the user needs to create the empty **public** repo under
  `kavin-upreti` and run `gh auth login` as that account. The remote is already set.

## Decisions pending my input
- Repo visibility: public (so Colab can `pip install git+https://…` without credentials —
  the repo holds only Trail's code, never notebooks or logs). Owner: `kavin-upreti`.
- Note: this repo lives in a path containing a space
  (`~/Desktop/Claude projs/gitlog sim`). That is deliberate cover for hard rule 8;
  say if you'd rather it moved to `~/code/trail`.
