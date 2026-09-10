# 0001 — Raw logs are append-only; everything else is derived

Date: 2026-09-11 · Status: accepted

## Context
Trail has to turn a messy stream of cell runs into a tidy history: versions, folded
typo fixes, checkpoints, steps. Every one of those rules is a guess that will be
wrong sometimes — the minor-version threshold, the fuzzy identity matcher, the metric
regexes. We will change them while using the tool on real lectures.

The alternative shape is a "smart" capture layer that decides, at record time, what
counts as a version and writes only the tidy result.

## Decision
`runs/<session>.jsonl` is written once and never rewritten. Grouping, identity
resolution and metric extraction all happen later on the Mac, and their output
(`derived/versions.json`) is disposable and rebuildable from the raw logs. User
corrections live in a separate `overrides.json`, not in the logs.

## Why
- **Changing a rule doesn't cost history.** Improve the grouping heuristic, run
  `trail rebuild`, and every past lecture is regrouped. A smart capture layer would
  have already thrown the evidence away.
- **Capture stays cheap and safe.** The hook builds a dict and hands it to a queue.
  Nothing it does can be "wrong" enough to matter, which is what lets us honour the
  hard rule that Trail must never break or slow the notebook.
- **Append-only survives crashes.** A kernel dying mid-lecture, or Drive syncing a
  half-written last line, costs at most one record. There is no file to corrupt.
- **Debuggable.** When grouping looks wrong, the raw JSONL is right there to read.

## Consequences
- Logs are larger than the tidy version would be (trimmed outputs and the 256 KB
  record cap keep this bounded).
- The engine must be tolerant: unknown fields, unknown record types, partial final
  lines, and Drive conflict copies are all normal input, not errors.
- Any user-visible correction (rename, merge, hide) needs a separate overrides path.
