# 0006 — What the first real look at the viewer changed

Date: 2026-09-11 · Status: accepted

## Context
M6 shipped with passing tests and every route returning 200. The user opened it and
said the font was bad, the UI was "trash", and they couldn't tell where to navigate.
They were right, and none of it was visible from the test suite — the tests asserted
that content was *present*, never that it was *legible*.

## What was actually broken
Found by taking a headless screenshot and looking at it, which I should have done
before claiming the milestone was done.

1. **Pygments' light stylesheet on a dark page.** `get_style_defs()` emits a
   background colour for the container, which painted a white slab inside the dark
   layout. It also emits unscoped rules (`pre`, `td.linenos`) that leaked into the
   rest of the page. Fixed by keeping only `.hl`-scoped token rules and emitting a
   second, dark theme (github-dark) under the same guards as the palette.
2. **Line numbers wrapped mid-number** — `10` rendered as `1` above `0` — because
   the gutter was `width: 1%` with wrapping allowed.
3. **Code lines wrapped**, so the left and right panes drifted out of step and a
   change appeared beside the wrong line. Now `white-space: pre` with horizontal
   scrolling, so a row is always one line on both sides.
4. **The "new runs synced" banner showed on every page load.** `.banner { display:
   flex }` overrides the `[hidden]` attribute — a specificity bug, not a logic one.
5. **No sense of place.** A bare nav with no breadcrumb, no indication of which
   section you were in, and a story rail that listed "train" twice.
6. **Markdown wasn't rendered**, so every `variable` in Claude's prose showed its
   backticks. SPEC 13.1 called for markdown-it-py; I had simply not wired it up.

## Decisions
- **Bundle IBM Plex after all** (SIL OFL, latin subsets, 138 KB for 5 faces). ADR-less
  earlier reasoning said the system stack was good enough and kept binaries out of the
  repo. The user disagreed on sight, and SPEC 13.5 asked for Plex in the first place.
- Breadcrumbs (`Trail / project / cell`) plus a tab bar with the current section
  marked, on every project page.
- A one-line explanation wherever a mechanic isn't self-evident — what A and B mean on
  the cell page, what the keyboard does in story mode.
- Story mode uses a one-column diff; a reading column is too narrow for two panes.
  The cell page keeps side-by-side, with a real toggle, and gets a wider shell.

## Consequence for how I work
Route-returns-200 is not evidence that a page is usable. For UI, take a screenshot and
look at it before calling it done.
