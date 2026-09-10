# 0003 — Tag syntax: `# trail: name`, with `# @name` as an alias

Date: 2026-09-11 · Status: accepted · Supersedes the spelling in SPEC 9.2

## Context
SPEC 9.2 specifies tags as `# @cell: mlp-init`, `# @cp note`, and so on. Running the
M2 spike in Colab surfaced a collision the spec didn't anticipate:

> `"@skip" is not an allowed annotation - allowed values include [@param, @title, @markdown]`

Colab reserves `# @word` for its own form-annotation feature. Anything else in that
shape gets flagged in the editor. It's cosmetic — the cell is a comment, so Python
ignores it and Trail still parses the tag — but tags are the main way the user talks
to Trail, and a permanent warning on most tagged cells is a bad thing to design in.

## Decision
`# trail: name value` is the documented spelling. `# @name value` keeps working as a
silent alias; both map to the same `Tags` object.

```
# trail: cell mlp-init
# trail: cp fixing dead tanh neurons
# @cell: mlp-init                       <- still parses
```

## Alternatives considered
- **Leave it.** Cheapest, but pushes a permanent papercut onto the user in the tool's
  most-used interaction.
- **Switch to `# trail:` only.** One syntax is cleaner to document, but it invalidates
  every example in the spec and silently stops recognising already-tagged cells. Since
  the alias costs one regex, breaking things buys nothing.

## Consequences
- `common/tags.py` tries `TRAIL_RE` first, then `AT_RE`. Neither can match the other's
  input, so ordering is not load-bearing.
- README, both example notebooks and the SPEC table use the `# trail:` form.
- The engine (M3) reads tags through this same module, so it inherits both spellings.
- Anything Trail has already recorded stays readable, which matters because raw logs
  are append-only and never rewritten (ADR 0001).
