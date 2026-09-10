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

- **M2 — Colab spike. Done, run by the user on real Colab.** See ADR 0004.
  - Capture works in Colab: frontend detected, Drive mounted, inline plot stored as a
    PNG blob, tqdm stderr captured, no fallback, no writer errors.
  - Overhead on Colab hardware: submit p50 0.024 ms / p95 0.034 ms (budget 5 ms).
  - **Colab sends no cell ids (0/5.)** Verified it is the *frontend*, not the library
    versions: IPython 7.34.0 defines `ExecutionInfo.cell_id` and ipykernel 6.17.1
    forwards `metadata.cellId`. Colab just never sends it.
  - Colab runs Python 3.13.15 / IPython 7.34.0, so 7.x support is required.
  - Tag syntax collided with Colab's form annotations; fixed per ADR 0003.

- **M3 — Engine** (SPEC 10). 110 tests pass, ruff clean.
  - `common/normalize.py` — tag-stripped `code_hash` and comment-free `semantic_hash`,
    tokenizer-based with a line-wise fallback for magics and syntax errors.
  - `engine/`: `loader` (tolerant JSONL, Drive conflict copies, partial last lines),
    `identity` (tag → cell_id → fuzzy), `grouping` (versions, attempts, minor),
    `metrics`, `steps` (checkpoint anchoring), `context`, `overrides`, `build`.
  - CLI: `trail log`, `show`, `projects`, `rebuild`, `cells rename/merge/hide/unhide`,
    `version`. Plus `config.py` for `~/.config/trail/config.toml`.

## In progress
- Nothing. M0–M3 are closed and committed.

## Next
1. **M4 — CLI basics**: `init` (find the Drive folder, write config), `doctor`,
   `template`. This is what the user needs to get Colab logs onto the Mac —
   Google Drive for desktop is not installed there yet.
2. M5 — Analysis (`claude -p`), the first milestone that spends usage.

## Decisions and findings
- ADR 0001 — raw append-only logs.
- ADR 0002 — `cell_id` arrives via execute_request `metadata.cellId`; verified against
  installed IPython 9.17.1 / ipykernel 7.3.0 source. Nothing in the kernel invents one.
- ADR 0003 — tag syntax is `# trail: name value`; `# @name` kept as a silent alias,
  because Colab reserves `# @word` for its own form annotations.
- ADR 0004 — what the Colab spike measured, including a first guess I checked and
  found wrong (Colab's IPython is not too old; its frontend simply omits `cellId`).
- **Deviation from SPEC 8.6:** redaction is also applied to string values in the
  variable fingerprint. The spec's list of redacted fields missed `vars`, and a real
  kernel test caught `api_key = "sk-ant-..."` reaching disk.
- **Deviation from SPEC 8.3:** `\r` overwrites in place rather than discarding the
  line. A terminal does not erase on carriage return, and "discard" lost the final
  tqdm bar (which ends in `\r`, not `\n`) entirely.
- **Deviation from SPEC 10.7:** the metric float pattern now accepts a positive
  exponent (`[eE][+-]?\d+`). The spec's `[eE]-?\d+` silently truncated a diverging
  loss of `3.9e+47` to `3.9`, which is the single most important number to get right
  when a learning rate is too high.
- **Deviation from SPEC 10.5:** `loss_std` is computed only across re-runs with no
  other cell running in between. Spread caused by an edit elsewhere is not noise, and
  labelling it as noise was actively misleading (a real demo showed `noise ±2.1e+47`).
- `trail log` additions beyond the spec, both because the spec-faithful output hid
  the lesson: collapsed minor versions show what changed (`lr = 1.5 → lr = 0.5`), and
  a version whose identical code produced very different numbers says so.

## Open questions
- Answered: Colab does not populate `cell_id`.
- Should Trail print a one-time reminder when an untagged cell is edited on Colab?
  ADR 0004 resolves SPEC 21's default to **yes** — there is no automatic recovery
  there — but it isn't built yet. Belongs with M3, once the engine can tell.
