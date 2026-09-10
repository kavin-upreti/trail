# Current State
Last updated: 2026-09-11 by Claude Code

## Done
- Spec written (docs/SPEC.md).
- **M0 — Scaffolding.** Git repo, `pyproject.toml` (hatchling, dist `trail-nb`, import
  `trail`, zero base deps, `[mac]` + `[dev]` extras), src layout, ruff + pytest config,
  `CLAUDE.md`, README, ADR 0001 (why raw append-only logs).
  Pushed to https://github.com/kavin-upreti/trail (public).
- **M1 — Capture core** (SPEC 7, 8, 9). 57 tests pass, ruff clean.
  - `common/tags.py` — tag parsing and slugs. `common/paths.py` — folder layout.
  - `capture/`: `schema` (record builders, 256 KB cap), `env` (frontend detection,
    root resolution, Drive mounting), `redact`, `fingerprint`, `tee`, `display`,
    `hooks`, `writer` (background thread + fallback), `session` (lifecycle).
  - Public API in `trail/__init__.py`: start, stop, pause, resume, status,
    checkpoint, note, metric, report.
  - `tests/kernel_driver.py` drives a **real ipykernel**; all eight SPEC 17.2
    scenarios pass, including the `cell_id`-in-metadata path.
  - Measured main-thread hook overhead: **p50 0.027 ms, p95 0.030 ms** (budget 5 ms).
  - `examples/demo_evolution.ipynb` produces sensible JSONL end to end.

## In progress
- Nothing. M1 is closed and committed.

## Next
1. **M2 — Colab spike. Needs the user.** Build `examples/colab_spike.ipynb` per
   SPEC 20.2, have the user run it in Colab and paste back `trail.report()`. The open
   question it answers: **does Colab send `metadata.cellId`?** If it doesn't, untagged
   cells fall back to fuzzy matching and `# @cell:` tags become essential.
2. M3 — Engine (SPEC 10) + `trail log`, `trail rebuild`, `trail cells`.

## Decisions and findings
- ADR 0001 — raw append-only logs.
- ADR 0002 — `cell_id` arrives via execute_request `metadata.cellId`; verified against
  installed IPython 9.17.1 / ipykernel 7.3.0 source. Nothing in the kernel invents one.
- **Deviation from SPEC 8.6:** redaction is also applied to string values in the
  variable fingerprint. The spec's list of redacted fields missed `vars`, and a real
  kernel test caught `api_key = "sk-ant-..."` reaching disk.
- **Deviation from SPEC 8.3:** `\r` overwrites in place rather than discarding the
  line. A terminal does not erase on carriage return, and "discard" lost the final
  tqdm bar (which ends in `\r`, not `\n`) entirely.

## Open questions
- Does Colab populate `cell_id`? (M2 answers this.)
- If it doesn't: should Trail print a one-time reminder when an untagged cell is
  edited? SPEC 21 default is yes, once per session.
