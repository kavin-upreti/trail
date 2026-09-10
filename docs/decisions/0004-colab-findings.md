# 0004 — What the Colab spike found

Date: 2026-09-11 · Status: accepted (measured, not assumed) · Closes M2

## Context
SPEC 20.2 exists to answer one question before the engine is built: **does Colab give
each cell a stable id?** Identity resolution (SPEC 10.3) prefers `cell_id` over fuzzy
matching, so the answer decides how much the user has to tag by hand.

The user ran `examples/colab_spike.ipynb` and pasted back `trail.report()`.

## Findings

```
frontend    : colab              python : 3.13.15
IPython     : 7.34.0             ipykernel : 6.17.1
runs on disk    : 5
with cell_id    : 0/5
with stdout     : 1/5
with stderr     : 1/5
displays by mime: {'image/png': 1}
fallback : no    writer errs : 0    submit ms : p50=0.024 p95=0.034
```

**1. Colab does not provide cell ids. `0/5`.**

My first guess was that Colab's older IPython predates the feature. That was wrong,
and checking it mattered — I installed both of Colab's exact versions and read them:

- `IPython 7.34.0` **does** define `ExecutionInfo.cell_id` (`interactiveshell.py:301`),
  and its `__init__` takes and sets it. The attribute is there.
- `ipykernel 6.17.1` **does** forward it: `kernelbase.py:709` reads
  `(parent.get("metadata") or {}).get("cellId")` and passes it through
  (`kernelbase.py:718`, `ipkernel.py:357`), gated on `_accepts_cell_id`.

So the entire kernel-side chain works in Colab's own versions. The value arrives as
`None` for one reason: **Colab's web frontend does not put `cellId` in the
execute_request metadata.** Nothing in the kernel invents one (ADR 0002), so there is
nothing for Trail to read.

This is a property of Colab's frontend, not of Trail or of a stale library, and it is
not fixable from our side.

**2. Everything else works.** Frontend detected, Drive mounted, an inline plot captured
as a PNG blob (13 KB), tqdm's stderr captured, no fallback, no writer errors.

**3. Overhead holds on real hardware.** Submit p50 0.024 ms / p95 0.034 ms, against the
5 ms budget in hard rule 1. Colab's slower VM cost roughly nothing versus the Mac.

**4. `runs: 4` vs `runs on disk: 5`** is correct, not a bug: `skipped` records are
written but not counted as runs. Worth making explicit in the report's wording.

## Consequences
- **On Colab, `# trail: cell <name>` tags are the only reliable way to track a cell
  across edits.** The README must say this plainly rather than presenting tags as a
  nice-to-have; the earlier framing was too relaxed.
- Fuzzy matching (SPEC 10.3 step 3, `fuzzy_threshold = 0.5`) is not a fallback on Colab
  — it is *the* mechanism for every untagged cell. M3 must treat it as load-bearing and
  test it against realistic incremental edits, not as a last resort.
- SPEC 21's open question — "should Trail remind the user when an untagged cell is
  edited?" — resolves to **yes** for Colab, since there is no automatic recovery there.
- Trail must keep supporting IPython 7.x — Colab runs 7.34.0 with Python 3.13.15. No
  capture code may assume an 8.x-only API. `getattr(info, "cell_id", None)` stays the
  right way to read it regardless.
- The same code path still pays off outside Colab: JupyterLab and VS Code do send
  `cellId`, and the M1 kernel test covers that path directly.
- The spike's edit-and-rerun step was not exercised (stdout 1/5 shows the `a` cell ran
  once). It didn't matter: with no `cell_id` attribute in IPython 7.34, the outcome is
  determined regardless.
