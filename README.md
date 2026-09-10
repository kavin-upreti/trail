# Trail

Trail records how your ML notebook code actually evolved — the code, what it printed,
the plots, the errors, every run — then groups those runs into meaningful versions and
uses Claude Code to explain each optimisation you made. A local web viewer replays the
whole lecture as a sequence of changes, so you can revise from what you really did.

**Status: in development.** Milestone 0 (scaffolding) is done; capture lands in M1.
See `docs/SPEC.md` for the full design and `docs/STATE.md` for where things stand.

## Install (Mac)

```bash
uv tool install -e ".[mac]"   # gives you the `trail` command
trail init                    # finds your Google Drive folder, writes config
trail doctor                  # everything should be ✓
```

Then in Finder, right-click `My Drive/trail` → **Available offline**, so the logs are
real local files instead of on-demand placeholders.

## Record a Colab lecture

First cell:

```python
# @skip
!pip install -q git+https://github.com/kavin-upreti/trail.git
import trail
trail.start("makemore-3")
```

Code along normally. Tag the moments that matter:

```python
# @cell: mlp-init
# @cp initial loss is 27, should be ~3.3
W2 = torch.randn((n_hidden, vocab_size), generator=g) * 0.01
```

| Tag | Meaning |
|---|---|
| `# @cell: name` | Names this cell so Trail tracks it across edits and sessions. |
| `# @cp note` | Checkpoint. Only checkpoints get explained, and the note is sent to Claude. |
| `# @fix` | This run replaces the previous version (a typo fix that still ran). |
| `# @keep` | Force a real version even for a tiny change like `0.1 → 0.01`. |
| `# @skip` | Don't record this cell (installs, downloads). |

Last cell: `trail.stop()`.

## Then, on the Mac

```bash
trail log makemore-3        # check the grouping looks right
trail analyze makemore-3    # explain the checkpoints
trail serve                 # open the viewer
trail ask makemore-3 "why did scaling W1 help the tanh layer?"
```

## Development

```bash
uv run pytest -q                              # tests
uv run ruff check . && uv run ruff format .   # lint
```

Read `CLAUDE.md` before changing anything; `docs/SPEC.md` is the source of truth.

## Licence

MIT.
