# Trail — Build Specification

> A tool that records how ML notebook code evolves (code + outputs + plots, every run),
> groups those runs into meaningful versions, uses Claude Code (`claude -p`) to explain
> each optimisation, and shows it all in a local web viewer with a "story mode" for revision.

**Spec version:** 1.0 · **Owner:** the user · **Builder:** Claude Code
**Placeholders to fill before starting:** `<GITHUB_USER>` (your GitHub username). Everything else has a default.

---

## 0. How to use this file

**For the user:**
1. Create an empty folder, e.g. `~/code/trail`, and put this file at `docs/SPEC.md`.
2. Open Claude Code in that folder and say:
   *"Read docs/SPEC.md fully. Then do Milestone 0 and stop so I can check it."*
3. After each milestone, Claude Code updates `docs/STATE.md`. At the start of your next
   session, say *"Read docs/STATE.md and docs/SPEC.md, then continue with the next milestone."*

**For Claude Code:**
- Read this entire file before writing any code. It is the source of truth.
- Work milestone by milestone (section 18). Use plan mode at the start of each milestone.
- Commit at the end of every milestone with a clear message.
- Keep `docs/STATE.md` current using the format in Appendix F (rewrite it, don't append a log).
- When this spec says **VERIFY**, do not assume: inspect the installed library source,
  run a real experiment, or run `claude --help`, and record what you found in
  `docs/decisions/` (short ADR) or `docs/STATE.md`.
- If something in this spec turns out to be impossible or wrong, stop, explain it plainly,
  propose an alternative, and wait for the user's decision if it changes behaviour they'd notice.
- Communication: the user is a student learning ML (Karpathy's *Neural Networks: Zero to Hero*).
  Explain what you did and why in plain language, be encouraging, and if you make a mistake,
  say so simply and fix it.

---

## 1. Goals and non-goals

### Goals
1. **Record everything, silently.** Every cell run in a notebook (Colab first, VS Code / Jupyter too)
   is captured with its code, printed output, plots, errors, timing, and a fingerprint of simple variables.
2. **Turn noise into a clean history.** Many runs become a few meaningful *versions* per cell;
   typo fixes and failed attempts are folded away, not lost.
3. **Explain the optimisations.** For *checkpoints* the user marks, Claude explains what changed,
   why it helps, the measured effect (with honest noise warnings), related concepts with real
   paper links, and self-check questions for revision.
4. **Make revision pleasant.** A local browser viewer with per-cell timelines, side-by-side diffs
   with outputs, and **story mode**: the whole lecture replayed as a sequence of changes.
5. **Let the user ask questions** about any recorded history, with answers saved.

### Non-goals (v1)
- Code autocomplete (existing tools already do this well).
- Recovering history that was never recorded.
- A hosted/cloud service, accounts, or multi-user features.
- Tracking `.py` scripts (designed in section 19, built only as a stretch goal).
- A VS Code extension UI.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Project** | One folder of history, usually one lecture/notebook, e.g. `makemore-3`. |
| **Session** | One kernel lifetime from `trail.start()` until the kernel dies or `trail.stop()`. One JSONL file. |
| **Run** | One execution of one cell. The atomic raw record. Never modified after writing. |
| **Identity** | "Which cell is this?" A stable key for a cell across edits and sessions. |
| **Version** | A meaningful state of a cell's code. Created by successful runs whose code changed semantically. |
| **Attempt** | A failed run with changed code. Attached to the next version, never a version itself. |
| **Minor version** | A version whose change vs the previous one is tiny. Kept, but collapsed in UIs. |
| **Checkpoint** | A version the user marked (`# @cp note` or `trail.checkpoint()`). Only checkpoints get analysed by default. |
| **Step / segment** | The range from the previous checkpoint (or first version) to a checkpoint. The unit of analysis. |
| **Analysis** | Claude's structured explanation of one step, stored as JSON + rendered Markdown. |
| **Logs root** | The top folder holding all projects (Google Drive folder by default). |

---

## 3. Hard rules (never break these)

1. **Capture must never break or noticeably slow the user's notebook.** Every hook body is wrapped
   in `try/except Exception`; internal errors go to `<project>/trail-errors.log` and produce at most
   one short warning per session. Never raise into user code. Target overhead: < 5 ms per cell
   on the main thread (file/blob I/O happens on a background thread).
2. **Raw logs are append-only and never rewritten.** All interpretation (grouping, identities,
   metrics) is derived and rebuildable. User corrections live in a separate `overrides.json`.
3. **The base package has zero third-party dependencies** (IPython is assumed present because it
   runs inside a kernel). It must install cleanly in Colab without touching Colab's preinstalled
   packages. Mac-only features live behind the `[mac]` extra.
4. **Capture is dumb, the engine is smart.** The capture layer never decides what is a version,
   typo, or checkpoint beyond recording tags it sees.
5. **Integration tests use a real ipykernel**, not mocked IPython objects (section 17).
6. **No invented paper links.** Links come only from `concepts.yaml` (Appendix A). Anything else
   Claude suggests is shown as "unverified".
7. **Viewer binds to 127.0.0.1 only**, escapes all recorded text, and renders recorded HTML
   only inside sandboxed iframes.
8. **Paths may contain spaces** (Google Drive's `My Drive`). Quote everything; test with spaces.
9. **Don't build the viewer before the engine works** (Milestone order in section 18).

---

## 4. Architecture overview

```
┌──────────────── In the notebook (Colab / VS Code / Jupyter) ────────────────┐
│  trail.start("makemore-3")                                                  │
│    ├─ IPython hooks: pre_run_cell / post_run_cell                           │
│    ├─ stdout/stderr tee (keeps what you see, saves a trimmed copy)          │
│    ├─ display publisher wrapper (catches inline plots, display())           │
│    ├─ variable fingerprint (scalars + tensor shapes)                        │
│    └─ background writer → runs/<session>.jsonl + blobs/<sha>.png            │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ Google Drive for desktop sync (Colab case)
                                ▼                (direct write in VS Code case)
┌──────────────────────────────── On the Mac ─────────────────────────────────┐
│  engine:   load runs → resolve identities → group into versions            │
│            → find checkpoints/steps → extract metrics → versions.json       │
│  analysis: bundle step → `claude -p` (Read-only tools) → JSON → Markdown    │
│  ask:      question + history → `claude -p` → saved Q&A (with follow-ups)   │
│  viewer:   FastAPI + Jinja2, offline, http://127.0.0.1:8765                 │
│  cli:      trail init | log | analyze | ask | serve | rebuild | cells | ... │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Repository layout and packaging

```
trail/
  pyproject.toml
  README.md
  CLAUDE.md                      # repo instructions for Claude Code (Appendix E)
  docs/
    SPEC.md                      # this file
    STATE.md                     # handoff file (Appendix F)
    decisions/                   # short ADRs: 0001-title.md
  src/trail/
    __init__.py                  # public notebook API (section 9)
    _version.py
    capture/
      session.py                 # Session lifecycle, idempotent start/stop
      hooks.py                   # IPython event registration
      tee.py                     # stdout/stderr tee with \r + ANSI handling
      display.py                 # display_pub wrapper
      fingerprint.py             # variable fingerprint
      env.py                     # frontend detection, Drive mounting, root resolution
      writer.py                  # background writer thread, fallback dir
      redact.py                  # secret redaction
      schema.py                  # record builders, SCHEMA_VERSION = 1
    common/
      tags.py                    # tag parsing (shared by capture and engine)
      normalize.py               # code normalisation + hashes
      paths.py                   # layout helpers for a project folder
    engine/
      loader.py                  # tolerant JSONL loading, dedupe
      identity.py                # identity resolution
      grouping.py                # runs → versions, attempts, minor flags
      steps.py                   # checkpoints → steps (segments)
      metrics.py                 # metric extraction
      context.py                 # cross-cell changes, var diffs, restarts between two points
      build.py                   # produce versions.json (+ cache)
      overrides.py               # rename/merge/hide identities
    analysis/
      concepts.py                # load/validate concepts.yaml
      bundle.py                  # build the prompt bundle for a step
      runner.py                  # subprocess wrapper around `claude -p`
      validate.py                # JSON extraction + schema validation
      render.py                  # analysis JSON → Markdown
      ask.py                     # Q&A bundles, saving, follow-ups
      project_claude_md.py       # writes <project>/CLAUDE.md (Appendix D)
    viewer/
      app.py                     # FastAPI app factory
      jobs.py                    # single-worker background job queue
      diffs.py                   # side-by-side diff HTML (difflib + Pygments)
      sparkline.py               # server-rendered SVG sparklines
      templates/                 # Jinja2
      static/css/trail.css
      static/js/trail.js         # small vanilla JS, no framework
      static/fonts/              # IBM Plex Sans + Mono woff2 (OFL), if downloadable
    data/
      concepts.yaml              # Appendix A
      prompts/analysis.md        # Appendix B
      prompts/ask.md             # Appendix C
      project_claude_md.md       # Appendix D template
    cli.py                       # Typer app
    config.py                    # ~/.config/trail/config.toml
  tests/
    conftest.py
    kernel_driver.py             # real-kernel harness (section 17)
    fake_claude/claude           # fake CLI for runner tests
    fixtures/                    # synthetic run logs, sample projects
    test_*.py
  examples/
    colab_template.ipynb         # setup cell + tag cheat sheet
    colab_spike.ipynb            # Milestone 2 diagnostic notebook
    demo_evolution.ipynb         # small numpy-only notebook for manual testing
```

### `pyproject.toml` essentials
- Build backend: `hatchling`. Distribution name `trail-nb`, import name `trail`.
- `requires-python = ">=3.10"` (Colab currently ships a recent 3.x; VERIFY in the spike).
- **Base dependencies: none.**
- `[project.optional-dependencies]`
  - `mac = ["typer>=0.12", "rich>=13", "fastapi>=0.110", "uvicorn>=0.29", "jinja2>=3.1", "pyyaml>=6", "pygments>=2.17", "markdown-it-py>=3", "pydantic>=2.6", "tomli-w>=1.0"]`
  - `dev = ["pytest", "pytest-timeout", "ruff", "ipykernel", "jupyter_client", "matplotlib", "numpy", "httpx"]`
- Console script: `trail = "trail.cli:app"`. If the CLI is invoked without the `[mac]` extra
  installed, print: *"The trail command needs the Mac extras: uv tool install -e '.[mac]'"*.
- Package data: include `data/**` and `viewer/templates/**`, `viewer/static/**`.
- Tooling: `uv` for envs, `ruff` for lint/format, `pytest` for tests. Python 3.12 on the Mac.

---

## 6. Configuration and paths

### Mac config file: `~/.config/trail/config.toml`
```toml
logs_root = "/Users/<you>/Library/CloudStorage/GoogleDrive-<email>/My Drive/trail"

[claude]
binary = "claude"          # path or name on PATH
model = ""                 # empty = your Claude Code default; e.g. "sonnet" to save usage (VERIFY alias support)
analysis_timeout_s = 240
ask_timeout_s = 300
analysis_max_turns = 4
ask_max_turns = 8
include_images = true      # let Claude Read before/after plot PNGs
max_images = 4

[analyze]
max_per_run = 10           # confirm before analysing more than this many steps

[viewer]
port = 8765
open_browser = true

[engine]
minor_max_chars = 12       # a change this small (and ≤ 1 line) is a "minor" version
fuzzy_threshold = 0.5      # similarity needed to link an untagged cell to an existing identity
extra_metric_patterns = [] # user regexes, each with a named group "value" and optional "name"
```

### Logs root resolution (in the notebook)
Order of precedence:
1. `trail.start(project, root="...")` argument.
2. Environment variable `TRAIL_ROOT`.
3. Mac config file `logs_root` (only readable when running on the Mac, e.g. VS Code).
4. Frontend default: Colab → `/content/drive/MyDrive/trail` (mount Drive if needed);
   anything else → `~/trail-logs`.

### `trail init` auto-detection (Mac)
- Glob `~/Library/CloudStorage/GoogleDrive-*/My Drive`. If exactly one match, propose
  `<match>/trail`. If several, list them and let the user choose. If none, explain how to install
  Google Drive for desktop, and offer `~/trail-logs` as a local-only root.
- Remind the user to right-click the `trail` folder in Finder → **Available offline**, so files
  are real local files rather than on-demand placeholders.

### Project folder layout (inside logs root)
```
<logs_root>/
  .trail-root                    # {"created": "...", "schema": 1}
  <project>/
    runs/<session_id>.jsonl      # append-only raw records (section 7)
    blobs/<sha256>.<ext>         # images/svg, content-addressed, deduplicated
    fallback-imported/           # marker files for fallback logs already merged
    trail-errors.log             # internal capture errors (never user errors)
    derived/
      versions.json              # engine output (rebuildable, section 10.8)
      build-cache.json           # file sizes/mtimes used to skip rebuilds
    overrides.json               # user corrections (renames, merges, hides)
    analyses/<identity_slug>/<step_key>.json  (+ .md, + bundle.md when --dry-run)
    qa/<timestamp>-<slug>.md     # saved questions and answers
    CLAUDE.md                    # generated guide for Claude (Appendix D)
```
Project names: lowercase slug `[a-z0-9][a-z0-9-]{0,63}`. `trail.start("Makemore 3")` is
slugified to `makemore-3` with a printed note.

---

## 7. On-disk format (schema version 1)

Every line of `runs/<session_id>.jsonl` is one JSON object with `"type"` and `"schema": 1`.
Timestamps are UTC ISO-8601 with milliseconds. Session IDs: `YYYYMMDD-HHMMSS-<4 hex>`.

### 7.1 `session_start`
```json
{"type":"session_start","schema":1,"session":"20260912-101500-a1b2",
 "ts":"2026-09-12T10:15:00.123Z","project":"makemore-3","trail_version":"0.1.0",
 "frontend":"colab","python":"3.12.x","platform":"Linux-...",
 "notebook":"makemore_part3.ipynb","packages":{"torch":"2.x","numpy":"2.x","matplotlib":"3.x"}}
```
- `frontend`: `colab` | `vscode` | `jupyter` | `ipython` (terminal). Detection in section 8.1.
- `notebook`: VS Code exposes `__vsc_ipynb_file__` in the user namespace; otherwise `null`.
- `packages`: from `importlib.metadata.version()` for torch, numpy, matplotlib, pandas (skip missing).
  **Never import torch** at start (slow); only read metadata.

### 7.2 `run`
```json
{"type":"run","schema":1,"session":"20260912-101500-a1b2","seq":17,"exec_count":23,
 "ts_start":"...","duration_s":1.234,
 "cell_id":"abc123-or-null",
 "code":"# @cell: mlp-init\nW1 = torch.randn(...) * 0.2\n...",
 "status":"ok",
 "error":null,
 "stdout":{"text":"...","truncated":false,"total_lines":42},
 "stderr":{"text":"","truncated":false,"total_lines":0},
 "result_repr":"tensor(3.3147, grad_fn=<NllLossBackward0>)",
 "displays":[{"mime":"image/png","blob":"3f2a...png","bytes":84211},
             {"mime":"text/plain","text":"<Figure size 2000x1000 with 1 Axes>"}],
 "vars":{"lr":0.1,"n_hidden":200,"W1":{"shape":[30,200],"dtype":"torch.float32"},
         "words":{"type":"list","len":32033}},
 "metrics":[{"name":"val_loss","value":2.07,"source":"explicit"}],
 "notes":["checkpoint via trail.checkpoint()"],
 "checkpoint_call":null,
 "seed":{"torch_initial_seed":2147483647,"manual_seed_literals":[2147483647]},
 "device":"cuda","gpu":"Tesla T4",
 "skipped":false}
```
Field rules:
- `status`: `ok` | `error` | `interrupted` (KeyboardInterrupt) | `syntax_error` (error before exec).
- `error`: `{"type","message","traceback_tail":[≤ 6 lines], "stage":"exec"|"compile"}`, ≤ 2 KB.
- `stdout`/`stderr`: see section 8.3 for trimming. `text` ≤ 64 KB each.
- `result_repr`: `repr()` of the last-expression value from `ExecutionResult.result`, ≤ 2 KB,
  wrapped in try/except (some reprs throw or are slow; cap with the size limit only).
- `displays`: images go to `blobs/`; `text/html` stored inline truncated to 20 KB;
  `text/plain` ≤ 2 KB; widget MIME types recorded as `{"mime": "...", "omitted": true}`.
- `vars`: the fingerprint *after* this run (section 8.5).
- `metrics`: only explicit `trail.metric()` calls at capture time. Parsed metrics are derived by the engine.
- `checkpoint_call`: note string if `trail.checkpoint(note)` was called during the run, else null.
- `seed.manual_seed_literals`: integers found by regex `manual_seed\(\s*(\d+)\s*\)` in the code.
- `device`/`gpu`: only if `"torch" in sys.modules`; computed once per session then cached.
- `skipped: true` records (from `# @skip`) store only `code` (first 200 chars), `ts_start`,
  `seq`, `cell_id`, `status`, and omit outputs, vars, and displays.
- Whole record capped at 256 KB; if larger, shrink stdout/stderr further and set `"oversize": true`.

### 7.3 Other record types
```json
{"type":"marker","schema":1,"session":"...","ts":"...","kind":"pause"|"resume"}
{"type":"session_end","schema":1,"session":"...","ts":"...","runs":123,"clean":true}
{"type":"note","schema":1,"session":"...","ts":"...","text":"..."}   // trail.note() outside any cell run
```
A session without `session_end` is treated by the engine as ended by a kernel restart/crash
at its last record's time.

### 7.4 Compatibility
The engine ignores unknown fields and unknown record types (with a warning in `trail log`).
If it sees `schema > 1` it warns: *"These logs were written by a newer Trail; update Trail on this Mac."*

---

## 8. Capture layer (runs inside the kernel)

### 8.1 Frontend detection (`capture/env.py`)
- **Colab:** `"google.colab" in sys.modules` or env var `COLAB_RELEASE_TAG` present.
- **VS Code:** `"__vsc_ipynb_file__"` in the user namespace, or env `VSCODE_PID` / `VSCODE_CWD`.
- **Jupyter:** running under ipykernel (`get_ipython().__class__.__name__` contains `ZMQ`) and not the above.
- **ipython:** terminal IPython.
- **Not IPython at all:** `trail.start()` raises a friendly `RuntimeError`:
  *"Trail records notebook cells. For a .py script, script mode isn't built yet (see the README)."*

**Colab Drive mounting:** if the root is under `/content/drive` and `/content/drive/MyDrive` doesn't
exist, call `from google.colab import drive; drive.mount("/content/drive")`. This shows Google's
permission popup; print a one-line explanation *before* calling it.

### 8.2 Hooks (`capture/hooks.py`)
- Register with `shell.events.register("pre_run_cell", on_pre)` and `("post_run_cell", on_post)`;
  unregister on `stop()`.
- `on_pre(info)`: `info` is IPython's `ExecutionInfo`. Record `raw_cell`, `getattr(info, "cell_id", None)`,
  start time (`time.perf_counter()` and wall clock). Install the tee (8.3). Mark a run as active.
- `on_post(result)`: `result` is `ExecutionResult`. **If no run is active, ignore it** (this happens for
  the very cell that called `trail.start()`, because `pre_run_cell` already fired before hooks existed).
  Otherwise: restore stdout/stderr, compute status from `result.error_before_exec` /
  `result.error_in_exec` (KeyboardInterrupt → `interrupted`), read `result.execution_count`,
  `result.result` (for `result_repr`), take the fingerprint, assemble the record, and hand it to the writer.
- **VERIFY** that `ExecutionInfo.cell_id` exists in the installed IPython and that ipykernel fills it
  from the `cellId` field in the execute request metadata. Record which frontends actually provide
  it (Colab, VS Code, JupyterLab) in an ADR after the spike.
- Silent executions (`info.silent` or `store_history=False`, e.g. frontend introspection) are ignored.

### 8.3 Output tee (`capture/tee.py`)
- On pre: replace `sys.stdout` and `sys.stderr` with a `Tee` object that writes through to the
  original stream **and** feeds a bounded capture buffer. Forward all attributes the original has
  (`encoding`, `isatty`, `fileno` if present, `flush`) via `__getattr__`, so libraries keep working.
- Terminal semantics while buffering, so memory stays bounded even with tqdm:
  - `\r` resets the current line buffer; `\n` commits it.
  - Strip ANSI escape sequences (`\x1b\[[0-9;]*[A-Za-z]`).
- Trimming: keep the first 200 and last 200 committed lines, count `total_lines`, cap text at 64 KB,
  and insert `… [N lines omitted] …` between head and tail when trimmed.
- Known limitations (document in README, don't fight them): output written at the C level directly
  to file descriptor 1, output from background threads after the cell finishes, and cells using
  `%%capture` (that magic swaps stdout itself).
- **VERIFY** in a real kernel that `!shell commands` and tqdm output (stderr) are captured.

### 8.4 Display capture (`capture/display.py`)
- Wrap `shell.display_pub.publish` with a function that calls the original first (with `*args, **kwargs`
  passed through unchanged), then, if a run is active, records the MIME bundle.
- This catches inline matplotlib figures (the inline backend flushes figures via `display()` during
  `post_execute`, which runs before `post_run_cell`) and any `display()` calls. **VERIFY** ordering.
- For `image/png` / `image/jpeg`: base64-decode, SHA-256, queue for writing to `blobs/<sha>.<ext>`
  (skip if it exists). For `image/svg+xml`: same, `.svg`.
- Ignore `update=True` publishes except keep the latest one per `display_id` (progress displays).
- Per-session blob budget: 200 MB. Beyond it, record `{"mime":"image/png","omitted":"budget"}` and warn once.
- On `stop()`, restore the original `publish`.

### 8.5 Variable fingerprint (`capture/fingerprint.py`)
Taken in `on_post`, from `shell.user_ns`:
- Skip names starting with `_`, IPython internals (`In`, `Out`, `exit`, `quit`, `get_ipython`),
  modules, functions, classes, and `trail`.
- `bool`, `int`, `float`, `complex`, `None`: stored as-is (`float('nan')`/`inf` → strings `"nan"`, `"inf"`).
- `str`: stored if ≤ 80 chars, else `{"type":"str","len":N}`.
- Objects whose `type(obj).__module__` starts with `torch`, `numpy`, `jax`, or `pandas` and that
  have a `shape`: `{"shape":[...],"dtype":str(obj.dtype)}`. Wrap in try/except.
- `list`, `tuple`, `dict`, `set`: `{"type":"list","len":N}` (never inspect contents).
- Anything else: skipped. **Never call `repr()`, `hasattr()` on arbitrary objects, or properties**
  (lazy objects can run code).
- Cap at 200 entries (alphabetical) per run.

### 8.6 Secret redaction (`capture/redact.py`)
Applied to `code`, `stdout`, `stderr`, `result_repr`, and HTML displays before writing. Replace matches with `[REDACTED]`:
`sk-ant-[A-Za-z0-9_-]{20,}`, `sk-[A-Za-z0-9_-]{20,}`, `hf_[A-Za-z0-9]{20,}`, `ghp_[A-Za-z0-9]{30,}`,
`github_pat_[A-Za-z0-9_]{30,}`, `AKIA[0-9A-Z]{16}`, `AIza[0-9A-Za-z_-]{35}`, and assignments
`(?i)\b(api[_-]?key|token|secret|password)\s*=\s*(['"])[^'"]{8,}\2` (keep the name, redact the value).

### 8.7 Writer (`capture/writer.py`)
- One daemon thread with a queue. Opens `runs/<session>.jsonl` in append mode, writes one line per
  record, `flush()` after each. `os.fsync()` on `stop()` and at interpreter exit (`atexit`).
- Blobs are written by the same thread (write to `<name>.tmp`, then `os.replace`).
- **Failure fallback:** if a write raises (Drive disconnected, permissions), switch to a local fallback
  folder (`/content/trail-fallback/<project>/` in Colab, `~/.cache/trail-fallback/<project>/` elsewhere),
  warn once, and keep going. `trail.status()` shows the fallback state. On `stop()` (and each new
  `start()`), try to copy fallback files into the real root (session file names are unique so no clash),
  then write a marker in `fallback-imported/`.
- Main-thread cost per record is only building a dict and `queue.put`.

### 8.8 Session lifecycle (`capture/session.py`)
- `start()` is idempotent: same project already running → print status and return. Different project →
  stop the current one (with a printed note) and start the new one.
- `start()` prints two lines: `Trail recording → makemore-3 (session …)` and the logs path.
- `stop()`: flush queue, fsync, write `session_end`, unregister hooks, restore streams and publisher.
  In Colab, if `unmount=True` (default **True** in Colab, since `stop()` is meant as "I'm done"),
  call `drive.flush_and_unmount()` to force uploads, and print that Drive was unmounted.
- `pause()`/`resume()`: write `marker` records; while paused, hooks do nothing.

---

## 9. Notebook API and tags

### 9.1 Python API (`trail/__init__.py`)
```python
trail.start(project: str | None = None, root: str | None = None) -> None
trail.stop(unmount: bool | None = None) -> None     # None = frontend default
trail.pause() / trail.resume()
trail.status(verbose: bool = False) -> None          # prints project, session, runs, fallback state, warnings
trail.checkpoint(note: str = "") -> None             # marks the CURRENT run as a checkpoint
trail.note(text: str) -> None                        # attaches a note to the current run
trail.metric(name: str, value: float) -> None        # explicit metric on the current run
trail.report() -> None                               # diagnostic report used by the Colab spike (section 20)
```
- `project=None`: in VS Code use the notebook file stem (slugified); otherwise raise with a friendly
  message asking for a name.
- Also provide `load_ipython_extension(ip)` so `%load_ext trail` works (it prints how to call `start`).

### 9.2 Comment tags (`common/tags.py`)
A tag is a whole line matching `^\s*#\s*@(\w+)(?:[:\s]\s*(.*))?$`. Tags can be on any line.
Because they are comments, cells still run normally without Trail.

> **Amended by ADR 0003:** the documented spelling is now `# trail: name value`, because
> Colab reserves `# @word` for its own form annotations and warns on anything else. The
> `# @name` form below still parses, as an alias. Read the table's `@` as either form.

| Tag | Value | Meaning |
|---|---|---|
| `# @cell: mlp-init` | slug, required | Names the cell's identity. Most reliable way to track a cell. |
| `# @cp fixing dead tanh neurons` | optional note | Checkpoint (alias: `@checkpoint`). The note is sent to Claude. |
| `# @fix` | none | This run replaces the previous version's code (typo fixes that still ran "ok"). |
| `# @keep` | none | Force a new, non-minor version even for a tiny change like `0.1 → 0.01`. |
| `# @skip` | none | Minimal record only; engine ignores it (installs, downloads). |

Unknown tags are ignored by capture and listed as warnings by `trail log`.

---

## 10. Engine (Mac side)

### 10.1 Loading (`engine/loader.py`)
- Read every `runs/*.jsonl`. Skip a final line that fails to parse (partially synced). Lines that fail
  mid-file are skipped and counted as warnings.
- Google Drive conflict copies like `name (1).jsonl`: load them too and dedupe runs by `(session, seq)`.
- Order all runs globally by `ts_start`, then `(session, seq)`.

### 10.2 Normalisation (`common/normalize.py`)
- `normalized`: remove tag lines, convert `\r\n` → `\n`, strip trailing whitespace per line and trailing blank lines.
- `code_hash = sha1(normalized)`.
- `semantic`: normalized code with comments and blank lines removed using `tokenize` (drop `COMMENT`
  tokens, then `untokenize` or reconstruct lines). If tokenizing fails (syntax errors, IPython magics),
  fall back to stripping lines that are only comments. Lines starting with `%` or `!` are kept verbatim.
- `semantic_hash = sha1(semantic)`.
- Comment-only edits therefore change `code_hash` but not `semantic_hash`.

### 10.3 Identity resolution (`engine/identity.py`)
Processed in global order. For each non-skipped run:
1. `@cell` tag present → identity `tag:<slug>`. If the run also has a `cell_id`, remember
   `cell_id → tag:<slug>` so later untagged runs of that cell stay linked.
2. Else `cell_id` present → mapped identity if remembered, else `id:<cell_id>`.
3. Else fuzzy match: compare the run's `semantic` lines to the latest version text of each identity
   seen in the project (most recent first, at most 50), using `difflib.SequenceMatcher` on lines.
   Best ratio ≥ `fuzzy_threshold` (default 0.5) → that identity (ties → most recently run).
   Otherwise create `auto:<n>`.
- Display names: tag slug; otherwise `auto` names from the first meaningful code line, truncated to 40
  chars (e.g. `W1 = torch.randn((n_embd * block_size…`).
- Apply `overrides.json` last (renames, merges, hides).
- **Duplicate-tag warning:** if one tag appears with two different `cell_id`s alternating, warn
  *"Tag `train` seems to be on two different cells (maybe a duplicated cell)."*

### 10.4 Setup cells
Auto-hidden (still recorded and versioned, just collapsed in UIs) when every non-blank, non-comment
line is one of: a magic (`%…`), a shell command (`!…`), an `import`/`from … import`, a `trail.` call,
or `drive.mount(...)`.

### 10.5 Grouping runs into versions (`engine/grouping.py`)
Per identity, in order, maintaining the current version `V` and a list `pending_attempts`:

```
for run R:
  if R.skipped: continue
  if R.status != "ok":
      if V and R.semantic_hash == V.semantic_hash: V.failed_runs.append(R)
      else: pending_attempts.append(R)
      continue
  if V is None:                       V = new_version(R)
  elif R has @fix:                    V.replaced_code.append(V.code); V.code = R.code; V.runs.append(R)
  elif R.semantic_hash == V.semantic_hash:
                                      V.runs.append(R); V.code = R.code   # comment-only edits update text
  else:                               V = new_version(R, minor = is_minor(V, R) and not R.has_keep)
  V.attempts.extend(pending_attempts); pending_attempts = []
```
- `is_minor`: char-level diff between semantic texts ≤ `minor_max_chars` (default 12) **and**
  at most one line changed.
- Versions are numbered per identity from 1. Minor versions still count and are shown collapsed.
- Attempts are shown as "N failed attempts" with their error types.
- Identical reruns give a noise estimate: if a version has ≥ 2 ok runs with a parsed final loss,
  store `loss_std` across them.

### 10.6 Checkpoints and steps (`engine/steps.py`)
- A version is *marked* if any of its runs has an `@cp` tag or a `checkpoint_call`. Its note is the
  latest non-empty note among those runs.
- **Anchoring rule:** consecutive marked versions of the same identity with the **same note text**
  form one step, anchored at the **last** of them (the step's final state). A new or removed note ends the step.
- Step start = previous step's anchor for that identity, or version 1 if none.
- `step_key = sha1(start.code_hash + end.code_hash + note)[:12]`. If versions are added so an anchor
  moves, the key changes; the old analysis is kept but marked **stale** in the UI.
- Warn in `trail log` when one step spans > 5 versions: *"`@cp` note on `train` has stayed the same
  for 7 versions — did you forget to change or remove it?"*
- Global story order = steps sorted by the anchor's last run time.

### 10.7 Metrics (`engine/metrics.py`)
Per run, produce `{name: {"final": float, "series": [floats ≤ 200, downsampled]}}`:
1. Explicit `trail.metric` values (highest priority).
2. Parsed from stdout (all matches, in order; final = last), built-in patterns:
   - Karpathy step logs: `^\s*(\d+)\s*/\s*(\d+)\s*:\s*(?P<value>-?\d+\.\d+)` → `loss`
   - `(?i)\b(?P<name>(train|val|valid|test)[ _]?loss|loss)\b\s*[:=]?\s*(?P<value>-?\d+(\.\d+)?([eE]-?\d+)?)`
   - Split printers: `^(?P<name>train|val|test)\s+(?P<value>-?\d+\.\d+)\s*$` → `<name>_loss`
3. Parsed from `result_repr`: `^tensor\((?P<value>-?\d+\.\d+)` or a bare float → `loss`
   **only if** the code's last line mentions `loss`.
4. User patterns from config `extra_metric_patterns`.
- Always add `duration_s`.
- Version metrics: from its **latest ok run** (plus `loss_std` from 10.5 when available).

### 10.8 `derived/versions.json` (`engine/build.py`)
```json
{"project":"makemore-3","built_at":"...","trail_version":"0.1.0","schema":1,
 "sessions":[{"id":"...","start":"...","end":"...","clean":true,"frontend":"colab","notebook":"..."}],
 "cells":[{"identity":"tag:mlp-init","name":"mlp-init","hidden":false,
   "first_ts":"...","last_ts":"...",
   "versions":[{"n":1,"code":"...","code_hash":"...","semantic_hash":"...","minor":false,
     "runs":[["sess","seq"]],"failed_runs":[],"attempts":[{"ref":["sess","seq"],"error_type":"NameError"}],
     "replaced_code":[],"metrics":{"loss":{"final":3.31,"series":[...]},"duration_s":{"final":4.2}},
     "loss_std":null,"marked":true,"note":"initial loss way too high",
     "first_ts":"...","last_ts":"..."}]}],
 "steps":[{"key":"a1b2c3d4e5f6","identity":"tag:mlp-init","start_n":1,"end_n":3,"note":"...",
   "analysis":"fresh"|"stale"|"missing","ts":"..."}],
 "warnings":["..."]}
```
- Rebuild only if any `runs/*.jsonl` size/mtime or `overrides.json` changed (`build-cache.json`).
- Build is deterministic: same inputs → identical output.

### 10.9 Context between two points (`engine/context.py`)
Given two runs (start-of-step's latest ok run, end-of-step's latest ok run), compute:
- **Variable changes:** diff of the fingerprint right *before* each run (= fingerprint after the
  previous run in that session). Report added/removed/changed names (shape changes included).
- **Other cells changed** in the time window: identities that got new versions, with short diffs (≤ 40 lines total).
- **Kernel restarts** (session boundaries) in the window.
- **Seed comparison:** both seeded with the same literal? different? unseeded?
- **Different sessions/devices** between the two runs (CPU vs GPU timing isn't comparable).

### 10.10 Overrides (`engine/overrides.py`)
```json
{"renames":{"auto:7":"train-loop"},"merges":[["auto:9","tag:train"]],"hidden":["auto:2"],"unhidden":[]}
```
Written only by CLI/viewer actions; applied after identity resolution; raw logs untouched.

---

## 11. Analysis with `claude -p`

### 11.1 Flow for one step
1. Build the bundle (11.2) as Markdown text.
2. Run (from the project folder as working directory):
   ```bash
   claude -p --output-format json --max-turns 4 --allowedTools "Read" \
          --disallowedTools "Bash,Edit,Write,WebFetch,WebSearch" [--model <cfg>] < bundle.md
   ```
   **VERIFY** every flag with `claude --help` before implementing (flag names change between
   versions). Pass the prompt on **stdin**, never as a giant argument. Use `subprocess.run` with
   `timeout=analysis_timeout_s`. Never use `--dangerously-skip-permissions`.
3. Parse stdout as the JSON wrapper. The model's text is in the `result` field; also keep
   `session_id`, `duration_ms`, `num_turns`, and `total_cost_usd` if present (VERIFY names).
4. Extract the analysis JSON from the text: strip Markdown fences, take the substring from the first
   `{` to the matching last `}`, `json.loads` it, validate with a pydantic model (11.3).
5. If invalid: retry **once** with a short prompt containing the validation error and the previous
   output, asking for corrected JSON only. If still invalid, save the raw text as
   `<step_key>.failed.txt` and report the failure.
6. Save `<step_key>.json` (analysis + `meta`: model, date, trail_version, bundle hash, runner stats)
   and render `<step_key>.md` (11.4).

### 11.2 Bundle contents (`analysis/bundle.py`)
Prompt template in Appendix B, filled with:
- Project, cell display name, step range (`v1 → v3`), the user's note.
- **Code before** (full) and **code after** (full), and a unified diff.
- **Path:** one line per intermediate version (diff stats, minor flag, final loss).
- **Outputs before/after:** stdout trimmed to ≤ 60 lines each, `result_repr`, and attempts summary
  (`3 failed attempts: NameError ×2, RuntimeError: shape mismatch ×1`).
- **Metrics before/after**, run counts, `loss_std` noise estimates.
- **Context** (10.9): variable changes, other cells changed, restarts, seed comparison, device changes.
- **Plots:** if enabled, absolute paths of up to 2 "before" and 2 "after" images, with the
  instruction that Claude may `Read` them.
- **Concept vocabulary:** `id — name — one-line summary` for every concept in `concepts.yaml`
  (no URLs, to save tokens).
- **Already learned in this project:** concept ids from earlier analyses (for consistent wording).
- The JSON schema and rules.
Hard cap the bundle at ~60 KB; shrink outputs first, then diffs of other cells, then path lines.

### 11.3 Analysis JSON schema (`analysis/validate.py`)
```json
{
  "title": "string, ≤ 70 chars, sentence case",
  "summary": "2–3 sentences",
  "changes": [{"what": "string", "detail": "optional string"}],
  "why": "1–3 short paragraphs: the reasoning behind the change, beginner-friendly but precise",
  "effect": {
    "metric": "loss | val_loss | duration_s | other name | null",
    "before": "number | null", "after": "number | null",
    "direction": "improved | worse | unchanged | unclear",
    "confidence": "high | medium | low",
    "noise_note": "string | null"
  },
  "tradeoffs": ["string"],
  "concepts": ["concept ids from the vocabulary only"],
  "other_concepts": [{"name": "string", "why_relevant": "string"}],
  "context_warnings": ["e.g. 'lr also changed in cell hparams between these runs'"],
  "plot_observations": "string | null",
  "try_next": ["string"],
  "self_check": [{"question": "string", "answer": "string"}]
}
```
Validation: unknown concept ids are moved into `other_concepts` (not rejected); `self_check` has 1–3
items; `title` trimmed to 70 chars.

### 11.4 Rendered Markdown (`analysis/render.py`)
Title, summary, a one-line effect chip (`loss 3.31 → 3.07 · improved · medium confidence`),
"What changed", "Why it helps", tradeoffs, context warnings (as a clearly marked caution),
concepts with **links from `concepts.yaml`**, other concepts labelled *(unverified — no link)*,
try next, and self-check questions with answers in `<details>` blocks.

### 11.5 `trail analyze` behaviour
- Finds steps whose analysis is `missing` or `stale` (and all steps with `--force`).
- If more than `max_per_run`, list them and ask for confirmation (`--yes` skips; `--limit N`).
- `--dry-run`: writes `bundle.md` next to where the analysis would go and prints its size; no Claude call.
- Runs sequentially, prints progress per step, stops cleanly on:
  - `claude` not found → *"Claude Code isn't on your PATH. Check with `which claude`."*
  - non-zero exit / auth error → show the first lines of stderr and suggest running `claude` once interactively.
  - usage-limit messages (stderr or result text mentions a limit) → stop, keep remaining steps pending,
    print *"Hit your usage limit; the remaining N steps will be analysed next time."*
  - timeout → mark that step failed, continue with the next.
- After finishing, regenerate `<project>/CLAUDE.md` (Appendix D).

### 11.6 Concepts file (`analysis/concepts.py`)
- Packaged default at `trail/data/concepts.yaml` (Appendix A). A user file at
  `~/.config/trail/concepts.yaml` is merged on top (same id → user wins).
- Schema per entry: `id`, `name`, `category`, `aliases` (list), `summary` (one line),
  `refs` (list of `{title, url, kind: paper|docs}`; may be empty).
- `scripts/check_concept_links.py` (dev only): HEAD/GET each URL, report non-200s.
  Run it once during Milestone 5 and fix/null any broken link. Never invent replacements.

---

## 12. Ask (questions about recorded history)

- `trail ask [project] "question" [--cell NAME] [--step KEY]`
- Bundle (Appendix C): the question; if a cell/step is given, that cell's version list with diffs,
  metrics, notes, and existing analysis summaries; otherwise a project overview (cells, steps, analysis titles).
- Invocation: like 11.1 but `--allowedTools "Read,Grep,Glob"`, `--max-turns ask_max_turns`,
  timeout `ask_timeout_s`, working directory = project folder (so Claude can dig into `runs/`,
  `analyses/`, `derived/versions.json`, guided by `<project>/CLAUDE.md`). Output is Markdown, not JSON.
- Save to `qa/<YYYYMMDD-HHMMSS>-<slug-of-question>.md` with front matter:
  `question`, `cell`, `step`, `date`, `claude_session_id`, `thread` (id of the first Q in a thread).
- Follow-ups: `trail ask --continue <qa-file-stem> "follow-up"` → `claude -p --resume <session_id>`
  (VERIFY resume works with `-p`; if not, include the previous Q&A text in a fresh bundle instead).
  Appended to the same thread file under a new heading.
- Also supported naturally: `cd` into the project folder and run `claude` interactively; the generated
  `CLAUDE.md` explains the layout.

---

## 13. Viewer

### 13.1 Tech
FastAPI app served by uvicorn on `127.0.0.1:<port>`. Server-rendered Jinja2 templates, a small vanilla
JS file, no CDN (fully offline). Diffs rendered server-side (difflib + Pygments with a custom theme),
Markdown via markdown-it-py (HTML disabled), sparklines as inline SVG generated in Python.
The viewer calls the engine's build (cached) on each page load.

### 13.2 Pages and routes
| Route | Page |
|---|---|
| `GET /` | Projects: name, last activity, #cells, #steps, #analyses missing/stale. Empty state explains how to start recording. |
| `GET /p/{project}` | Overview: session strip (dates, frontend, restarts), cells list (hidden setup cells collapsed under "Setup cells"), each row with a mini version spine and loss sparkline; warnings panel. |
| `GET /p/{project}/cell/{identity}` | Cell page (13.3). Query `?a=1&b=3` picks the comparison. |
| `GET /p/{project}/story` | Story mode (13.4). `?all=1` includes non-checkpoint versions. |
| `GET /p/{project}/concepts` and `GET /concepts` | Concept index: each concept → where it appeared (project, cell, step), with links. |
| `GET /p/{project}/qa` | Saved questions and answers, grouped by thread. |
| `POST /api/p/{project}/analyze` | Body: `{"steps":[keys]}` or `{"all_pending":true}` → job id. |
| `POST /api/p/{project}/ask` | Body: `{"question","cell"?, "step"?, "continue"?}` → job id. |
| `GET /api/jobs/{id}` | `{"status":"queued|running|done|failed","message","result_url"}` |
| `POST /api/p/{project}/rebuild` | Force rebuild. |
| `POST /api/p/{project}/cells/{identity}` | Rename / hide / unhide / merge (writes overrides). |
| `GET /api/p/{project}/stamp` | Latest runs mtime; JS polls every 5 s and shows "New runs synced — Refresh". |
| `GET /blobs/{project}/{name}` | Serves images (validate name against `^[0-9a-f]{64}\.(png|jpg|svg)$`). |

Jobs run on a single background worker thread (Claude calls are serialized). Before analysing more
than `max_per_run` steps, the UI shows a confirm dialog with the count.

### 13.3 Cell page
- **Left: the version spine** (the one bold, memorable element). A vertical line with a dot per
  version; minor versions are small dots grouped as "3 small edits"; checkpoints are amber diamonds
  with their note; each dot shows final loss and a delta vs the previous version (green if lower,
  red if higher, grey if within `loss_std`). Clicking two dots sets A and B. Default A/B = the latest step.
- **Right: comparison.**
  - Header chips: `loss 3.31 → 3.07`, `time 4.2 s → 5.5 s (+31%)`, `same seed` / `different seeds`,
    `different device` warnings.
  - Side-by-side diff with syntax highlighting; toggle to unified.
  - Outputs A | B: stdout (collapsible, monospace), result repr, HTML displays in sandboxed iframes
    (`sandbox=""`, `srcdoc`), plots side by side with an "overlay slider" toggle.
  - Attempts: "2 failed attempts" expandable with error type + message.
  - Context panel: variable changes, other cells changed, restarts in between.
  - **Analysis card** for the step, or an "Explain this step" button (queues a job, shows progress,
    replaces itself with the card when done). Stale analyses show "Code changed since this was written — re-explain".
    Self-check questions are click-to-reveal.
  - **Ask box** scoped to this cell, with its previous Q&A threads below.
- Header actions: rename cell, hide cell, merge into… (select).

### 13.4 Story mode
A single reading column: each step, in chronological order, is one section containing the note,
the analysis title and summary, the effect chip, the diff (collapsed by default, expand with a click),
before/after plots, "why it helps", concepts with links, and self-check questions. Steps without an
analysis show the note, diff, and metrics plus an "Explain this step" button. Keyboard: `j`/`k` or
arrow keys move between steps; `e` expands the diff. A progress rail on the side shows position in the
lecture. Export button → Markdown file of the whole story (same as `trail export`).

### 13.5 Visual design (apply the principles in the frontend-design guidance)
Subject: a lab notebook for tracing experiments. Quiet, precise, readable for long revision sessions.
- **Palette (light):** Paper `#F6F7F5` background, Ink `#1B2230` text, Graphite `#5B6472` secondary text,
  Rule `#D8DCD5` borders, Signal blue `#2457C5` links/selection, Gain green `#1F7A4D` additions/improvements,
  Loss red `#B23A2B` removals/regressions, Checkpoint amber `#B7791F`.
  **Dark:** background `#12161C`, text `#E4E7EC`, secondary `#9AA3AF`, rules `#2A313B`, blue `#7FA2F0`,
  green `#5BC08A`, red `#E07A6B`, amber `#E0A94A`. Follow `prefers-color-scheme` with a manual toggle.
  Diff backgrounds use 12–15% tints of green/red.
- **Type:** IBM Plex Sans for UI and prose, IBM Plex Mono for code (bundle woff2 files, SIL OFL,
  downloaded from the IBM/plex GitHub releases; fall back to the system font stack if unavailable).
  Body 16 px / 1.6, code 13.5 px / 1.5. Sentence case everywhere, no all-caps labels.
- **Layout:** cell page = 280 px spine column + fluid comparison area; story mode = 720 px reading
  column with code blocks allowed to extend to 1080 px. Left-aligned text. Structure with rules and
  whitespace, not stacks of identical shadowed cards.
- **Motion:** none on load; only responsive feedback (expanding a diff, a job finishing).
- **Words:** name things by what they mean to the user ("Explain this step", "Hide cell",
  "New runs synced — Refresh"). Errors say what happened and how to fix it.
- Accessibility: visible focus, keyboard navigation, text contrast ≥ 4.5:1, `prefers-reduced-motion` respected.

---

## 14. CLI reference (`trail`, Typer + Rich)

`[project]` is optional everywhere: default = the most recently active project (print which one was chosen).

| Command | What it does |
|---|---|
| `trail init [--logs PATH]` | Detect Drive folder (6), create logs root + `.trail-root`, write config, check `claude --version`, print the Colab setup cell with the repo URL (from `git remote get-url origin` of the install dir if available). |
| `trail doctor` | Check config, root exists/writable, Python version, `claude` availability, projects found, schema versions, any `trail-errors.log` entries, fallback logs not yet imported. Each check: ✓ or a fix hint. |
| `trail projects` | Table of projects with last activity and counts. |
| `trail log [project] [--cell NAME] [--all] [--sessions]` | Text timeline: per cell, versions with final loss, checkpoints with notes, folded attempts, restarts, warnings. `--all` expands minor versions and hidden cells. |
| `trail show [project] CELL [A] [B]` | Terminal diff between versions (default: latest step) plus metric chips. |
| `trail analyze [project] [--cell] [--step KEY] [--dry-run] [--yes] [--limit N] [--force]` | Section 11.5. |
| `trail ask [project] "Q" [--cell] [--step] [--continue QA]` | Section 12. |
| `trail serve [--port] [--no-open]` | Start the viewer; opens the browser unless disabled. |
| `trail rebuild [project]` | Force engine rebuild. |
| `trail cells [project]` / `cells rename OLD NEW` / `cells merge FROM INTO` / `cells hide NAME` / `cells unhide NAME` | Manage identities via overrides. |
| `trail export [project] [--out FILE]` | Story as one Markdown file (great for notes). |
| `trail template [project]` | Print the Colab setup cell for a project name. |
| `trail version` | Versions of Trail, Python, and `claude`. |

Exit codes: 0 ok, 1 user-fixable problem (message explains), 2 internal error (message + path to a traceback file).

---

## 15. Setup and everyday use (also goes into the README)

### 15.1 One-time Mac setup
```bash
cd ~/code/trail
uv tool install -e ".[mac]"      # gives you the `trail` command; -e = picks up code changes
trail init                         # finds your Google Drive folder, writes config
trail doctor                       # everything should be ✓
```
Then in Finder: right-click `My Drive/trail` → **Available offline**.
The GitHub repo (`https://github.com/kavin-upreti/trail`) should be **public** so Colab can install it
without credentials (it contains only Trail's code, never your notebooks or logs).

### 15.2 Colab (lectures)
First cell of every notebook (use `examples/colab_template.ipynb` → *File → Save a copy*):
```python
# @skip
!pip install -q git+https://github.com/kavin-upreti/trail.git
import trail
trail.start("makemore-3")
```
Code along normally, adding tags where useful:
```python
# @cell: mlp-init
# @cp initial loss is 27, should be ~3.3
W2 = torch.randn((n_hidden, vocab_size), generator=g) * 0.01
b2 = torch.randn(vocab_size, generator=g) * 0
```
Last cell: `trail.stop()` (forces Drive to upload and unmounts it).
After a runtime restart: rerun the setup cell with the **same project name**; timelines continue.

### 15.3 VS Code / local Jupyter notebooks
The notebook's kernel environment needs Trail installed (the `uv tool` install is separate):
```bash
uv pip install -e ~/code/trail     # inside the project's venv; base package only
```
Then `import trail; trail.start("project-name")` (no pip line, no Drive mount). Logs go to the same
logs root, so these projects appear in the same viewer.

### 15.4 After recording (Mac)
```bash
trail log makemore-3        # sanity-check grouping before spending usage
trail analyze makemore-3    # explain new checkpoints
trail serve                 # open the viewer
trail ask makemore-3 "why did scaling W1 help the tanh layer?"
```

---

## 16. Edge cases (all must be handled)

| Situation | Expected behaviour |
|---|---|
| Setup cell forgotten | Nothing recorded until `start()`; runs after it are captured normally. |
| `start()` cell itself | Its `post_run_cell` fires without a matching pre → ignored (8.2). |
| `start()` run twice | Idempotent; prints status. |
| Different project started mid-kernel | Previous session stopped with a note; new session begins. |
| Kernel restart / Colab disconnect | Session ends without `session_end`; engine marks a restart boundary; new `start()` continues identities via tags/cell ids. |
| "Run all" reruns everything | Identical code adds runs to existing versions; loss noise estimate improves. |
| Syntax error | `status: syntax_error`; counted as an attempt. |
| Runtime error with unchanged code | Added to the version's `failed_runs` (probably state, not code). |
| KeyboardInterrupt mid-training | `status: interrupted`; outputs so far are kept; treated like a failed run. |
| Huge prints / tensor dumps | Trimmed per 8.3; record cap 256 KB. |
| tqdm progress bars | `\r` handling keeps only final line states. |
| Many plots | Blob dedupe + 200 MB per-session budget. |
| HTML outputs (DataFrames) | Stored ≤ 20 KB; rendered in sandboxed iframes. |
| Secrets printed or in code | Redacted (8.6). |
| Drive write fails in Colab | Local fallback + warning; merged on `stop()`/next `start()`; `trail doctor` reports unmerged fallbacks. |
| Partially synced last JSONL line | Skipped silently; picked up after sync completes. |
| Drive conflict copies `(1).jsonl` | Loaded and deduped by `(session, seq)`. |
| Cell duplicated with same `@cell` tag | Warning (10.3); user can split via different tag names. |
| Cells reordered/split | Tags/cell ids keep identities; fuzzy matching best-effort; `cells merge/rename` to fix. |
| `@cp` note never removed | Step keeps growing; warning after 5 versions (10.6). |
| Comment-only edits | Update text, no new version. |
| Two notebooks share a project | Works (separate sessions); tags with the same name merge — README recommends one notebook per project. |
| Paths with spaces | Everything quoted; tested. |
| Viewer open while new runs sync | Stamp polling shows a Refresh banner. |
| `claude` missing / logged out / usage limit / timeout | Clear messages per 11.5; nothing corrupted; pending steps stay pending. |
| Clock differences between Colab and Mac | Within a session, order by `seq`; across sessions by timestamp (UTC). |
| Newer schema on disk | Warning to update Trail (7.4). |
| User wants to delete a project | Just delete its folder; README says so. |

---

## 17. Testing strategy

### 17.1 Unit tests
Tags parsing; normalisation + both hashes (including magics and syntax-error code); tee (`\r`, ANSI,
trimming, attribute forwarding); fingerprint (exclusions, caps, no repr calls — use an object whose
`__repr__`/`__getattr__` raises to prove it); redaction; identity resolution (tags, cell ids,
cell_id→tag memory, fuzzy, duplicates, overrides); grouping (table-driven synthetic runs covering every
rule in 10.5); steps (anchoring, same-note spans, stale keys); metrics (Karpathy formats, split printers,
tensor reprs, user patterns); context diffs; loader tolerance (partial lines, conflict copies);
build determinism; bundle size capping; JSON extraction/validation/unknown-concept handling; render.

### 17.2 Real-kernel integration tests (`tests/kernel_driver.py`)
- Start an ipykernel with `jupyter_client.KernelManager`, execute cells with `kc.execute(...)`, and
  also send execute requests with `metadata={"cellId": "..."}` built via `kc.session.msg(...)` to
  simulate frontends that send cell ids. Test both paths.
- Scenarios (numpy + matplotlib only; no torch in CI):
  1. Evolving cell: v1 → typo (error) → fix → tweak → `@cp` → rerun identical → verify versions,
     attempts, checkpoint, noise estimate.
  2. stdout with prints, tqdm-like `\r` output on stderr, `!echo hi`, large output trimming.
  3. Inline matplotlib plot captured as a blob; `display()` of HTML captured.
  4. KeyboardInterrupt via `km.interrupt_kernel()` during a sleep loop.
  5. `start()` idempotency, `start()` in the same cell as other code, `pause/resume`, `stop()`.
  6. Unwritable root → fallback folder used → merged on next start.
  7. Variable fingerprint: `lr` changed in another cell appears in context between two runs.
  8. Logs root path containing spaces.
- Performance: 200 trivial cells, mean hook overhead on the main thread < 5 ms (mark `slow`).

### 17.3 Claude runner tests
`tests/fake_claude/claude` is an executable Python script placed first on `PATH` in tests. Via env vars
it can: return valid wrapper JSON, return invalid JSON then valid on retry, sleep past the timeout,
exit non-zero with an auth-like message, or print a usage-limit message. Test every branch in 11.5.
One `@pytest.mark.live` test runs the real `claude` on a tiny bundle; skipped unless `TRAIL_LIVE=1`.

### 17.4 Viewer tests
FastAPI `TestClient` on a fixture project: every route returns 200; a cell page contains the diff and
metrics; story mode lists steps in order; recorded `<script>` text in stdout is escaped; blob route
rejects path traversal; overrides actions change `trail log` output.

### 17.5 Manual tests (the user does these; Claude Code prepares them)
The Colab spike (section 20) and one real lecture session before calling v1 done.

---

## 18. Milestones and session plan

Each milestone ends with: tests passing, `ruff` clean, a commit, and `docs/STATE.md` rewritten.
If usage runs low, finish the current milestone cleanly rather than starting a new one half-way.
Priority if time runs out: M1 > M3 > M5 > cell page > story mode > ask > everything else.

### Session 1
**M0 — Scaffolding (short).** `git init`, `pyproject.toml`, `src/` layout, ruff + pytest config,
`CLAUDE.md` (Appendix E), `docs/STATE.md` (Appendix F), first ADR "why raw append-only logs",
README skeleton. Ask the user for `<GITHUB_USER>` and to create the empty public repo; add the remote.
*Done when:* `uv run pytest` runs (even with zero tests) and the first commit exists.

**M1 — Capture core.** Sections 7, 8, 9: hooks, tee, display capture, fingerprint, redaction,
writer + fallback, session lifecycle, public API, tags parser, `trail.report()`.
*Done when:* all 17.2 scenarios pass against a real kernel and a demo notebook produces sensible JSONL.

**M2 — Colab spike (needs the user).** Push to GitHub. Prepare `examples/colab_spike.ipynb` (section 20).
The user runs it in Colab and pastes back the `trail.report()` output. Record findings in an ADR
(cell ids? plots captured? stdout captured? Drive timing?) and fix anything broken.
*Done when:* capture works in Colab or known gaps are documented with workarounds.

**M3 — Engine.** Section 10 entirely, plus `trail log`, `trail rebuild`, `trail cells …`.
*Done when:* unit tests pass and `trail log` on the spike + demo projects reads correctly to the user.

**M4 — CLI basics.** `init`, `doctor`, `projects`, `template`, `version`, `show`. README setup section.
*Done when:* a fresh `uv tool install -e ".[mac]"` + `trail init` + `trail doctor` works on the user's Mac.

### Session 2
**M5 — Analysis.** Section 11 + `concepts.yaml` + link check + project `CLAUDE.md` generation.
Start with `--dry-run` and show the user one bundle before the first real call.
*Done when:* runner tests pass and one real step is analysed and rendered well.

**M6 — Viewer.** Section 13: projects, overview, cell page, story mode, concepts, jobs, polling.
*Done when:* viewer tests pass and the user can revise one lecture in story mode.

**M7 — Ask.** Section 12 (CLI + viewer box + follow-ups).

**M8 — Polish.** README complete, `colab_template.ipynb`, `trail export`, error-message pass,
first tagged release `v0.1.0` (Colab can then pin `@v0.1.0`).

**Stretch (only if everything above is done):** script mode, git import, suggestions (section 19).

---

## 19. Stretch designs (build only after M8)

### 19.1 Script mode (for the GPT lectures, where code moves into `.py` files)
- Notebook API: `trail.script("train.py", args=[...], track=["model.py"])` runs
  `python train.py …` as a subprocess, streams its output live to the cell, and records a `run` whose
  identity is `file:train.py`, `code` = the file's contents (plus tracked files concatenated with
  `# ==== file: model.py ====` headers), stdout/stderr from the subprocess, status from the exit code.
- CLI equivalent on the Mac: `trail run [project] train.py -- args`.
- Everything downstream (grouping, steps, analysis, viewer) works unchanged.

### 19.2 Git import (backfill from step-by-step repos)
`trail import-git [project] REPO --file train_gpt2.py [--branch main]`: one synthetic session;
each commit touching the file becomes an ok run (code = file at that commit), commit message = note,
every commit marked as a checkpoint; no outputs. Record `"source":"git","commit":"<sha>"` on runs.
(Some of Karpathy's repos were committed step by step alongside the videos — worth checking which.)

### 19.3 Suggestions
`trail suggest [project] CELL`: sends the cell's current code plus the list of concepts the user has
learned (from analyses across all projects, with where they learned them) and asks for up to 3
applicable ideas, each tied to a learned concept or marked "new to you". Saved like Q&A.

### 19.4 Future: Claude Code edit history
For VS Code projects where Claude Code writes the code, a Claude Code `PostToolUse` hook could append
edit records (file, diff, Claude's stated reason) into a Trail project. Design later; not in scope.

---

## 20. Things the user must do (Claude Code: prompt the user at the right moment)

1. **M0:** create the public GitHub repo `trail` and tell Claude Code the username.
2. **M2 — Colab spike.** Claude Code prepares `examples/colab_spike.ipynb` with these cells:
   1. `# @skip` install from GitHub + `import trail; trail.start("spike")`
   2. `# @cell: a` → `x = 1; print("hello"); x`
   3. edit of cell a → `x = 2; print("hello again"); x` (tell the user to edit the same cell and rerun)
   4. `# @cell: plot` → a small matplotlib plot
   5. `# @cell: bar` → a loop with `tqdm` and a `time.sleep`
   6. `# @cell: err` → `1/0`
   7. `trail.report()` → prints: frontend, Python/IPython/ipykernel versions, whether `cell_id` was
      non-null for recorded runs, number of runs, displays captured (count by MIME), stdout captured
      (yes/no per run), stderr captured, logs path, fallback state, write latency p50/p95, any internal errors.
   8. `trail.stop()`
   The user uploads it to Colab, runs it top to bottom, pastes the report into Claude Code, and then
   checks on the Mac that `My Drive/trail/spike/` appeared (and how long it took).
3. **M4:** install Google Drive for desktop (if not already), set the folder offline, run `trail init`.
4. **M5:** approve the first real `claude -p` call after seeing a dry-run bundle.
5. **Before v1 is "done":** record one real lecture segment with tags and try story mode.

---

## 21. Decisions already made (with defaults) and open questions

| Decision | Default chosen | Change if… |
|---|---|---|
| Name | Trail (`trail-nb` dist, `trail` import) | you prefer another name — rename before M1. |
| Repo visibility | Public (Colab installs without credentials) | you need private → install from a Drive copy of `src/trail` instead. |
| Logs root | `My Drive/trail` | you want logs elsewhere (`trail init --logs`). |
| Model for analyses | Claude Code default | you want to save usage → set `model = "sonnet"` (VERIFY alias) in config. |
| When analysis runs | Manually (`trail analyze` or viewer button) | you want automatic → later add `trail watch` (not in v1). |
| Minor-version threshold | ≤ 12 chars and ≤ 1 line | too many or too few small versions in practice. |
| `stop()` in Colab | Flushes and unmounts Drive | you keep working after `stop()` → `trail.stop(unmount=False)`. |

**Open questions (none blocking; Claude Code should ask when reached):**
- `<GITHUB_USER>` (needed at M0).
- After the spike: if Colab provides no cell ids, should Trail print a gentle reminder the first time an
  untagged cell is edited? (Default: yes, once per session.)

---

## Appendix A — `trail/data/concepts.yaml`

Categories: `initialization`, `normalization`, `architecture`, `optimizer`, `schedule`, `regularization`,
`numerics`, `efficiency`, `data`, `debugging`, `language-modeling`.
Run the link checker in M5; if any URL fails, set it aside (don't guess a replacement) and tell the user.

```yaml
- id: output-layer-init-scale
  name: Small output-layer initialisation
  category: initialization
  aliases: [scale down logits at init, W2 * 0.01]
  summary: Start with near-uniform predictions so the initial loss is about -log(1/vocab) instead of huge.
  refs: []
- id: activation-saturation
  name: Tanh/sigmoid saturation and dead neurons
  category: initialization
  aliases: [saturated tanh, dead neurons, vanishing gradients]
  summary: Pre-activations that are too large push tanh to ±1 where gradients vanish.
  refs:
    - {title: "Glorot & Bengio (2010) Understanding the difficulty of training deep feedforward neural networks", url: "http://proceedings.mlr.press/v9/glorot10a.html", kind: paper}
- id: xavier-init
  name: Xavier/Glorot initialisation
  category: initialization
  aliases: [glorot init]
  summary: Scale weights by fan-in/fan-out to keep activation variance stable across layers.
  refs:
    - {title: "Glorot & Bengio (2010)", url: "http://proceedings.mlr.press/v9/glorot10a.html", kind: paper}
- id: kaiming-init
  name: Kaiming/He initialisation
  category: initialization
  aliases: [he init, gain / sqrt(fan_in), 5/3 gain for tanh]
  summary: Scale weights by gain/sqrt(fan_in) so activations keep unit variance through nonlinearities.
  refs:
    - {title: "He et al. (2015) Delving Deep into Rectifiers", url: "https://arxiv.org/abs/1502.01852", kind: paper}
    - {title: "torch.nn.init docs", url: "https://pytorch.org/docs/stable/nn.init.html", kind: docs}
- id: residual-init-scaling
  name: Scaling residual projections at init
  category: initialization
  aliases: [1/sqrt(2*n_layer), NANOGPT_SCALE_INIT]
  summary: Shrink the init of layers that add into the residual stream so its variance doesn't grow with depth.
  refs:
    - {title: "Radford et al. (2019) Language Models are Unsupervised Multitask Learners (GPT-2)", url: "https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf", kind: paper}
- id: batchnorm
  name: Batch normalisation
  category: normalization
  aliases: [BatchNorm1d, batch norm]
  summary: Normalise pre-activations with batch statistics, then learn a scale and shift.
  refs:
    - {title: "Ioffe & Szegedy (2015) Batch Normalization", url: "https://arxiv.org/abs/1502.03167", kind: paper}
- id: layernorm
  name: Layer normalisation
  category: normalization
  aliases: [LayerNorm, pre-norm]
  summary: Normalise across features per example; no dependence on the batch.
  refs:
    - {title: "Ba, Kiros & Hinton (2016) Layer Normalization", url: "https://arxiv.org/abs/1607.06450", kind: paper}
- id: rmsnorm
  name: RMS normalisation
  category: normalization
  aliases: [RMSNorm]
  summary: Like LayerNorm but only rescales by the root-mean-square, no mean subtraction.
  refs:
    - {title: "Zhang & Sennrich (2019) Root Mean Square Layer Normalization", url: "https://arxiv.org/abs/1910.07467", kind: paper}
- id: bengio-mlp-lm
  name: MLP language model with embeddings
  category: language-modeling
  aliases: [Bengio 2003, character embeddings, context window MLP]
  summary: Embed previous tokens, concatenate, and predict the next token with an MLP.
  refs:
    - {title: "Bengio et al. (2003) A Neural Probabilistic Language Model", url: "https://www.jmlr.org/papers/volume3/bengio03a/bengio03a.pdf", kind: paper}
- id: word-embeddings
  name: Learned embeddings
  category: language-modeling
  aliases: [word2vec, embedding table]
  summary: Map discrete tokens to dense vectors learned by gradient descent.
  refs:
    - {title: "Mikolov et al. (2013) Efficient Estimation of Word Representations in Vector Space", url: "https://arxiv.org/abs/1301.3781", kind: paper}
- id: wavenet-hierarchy
  name: Hierarchical / dilated context fusion
  category: architecture
  aliases: [WaveNet, FlattenConsecutive, dilated causal convolution]
  summary: Fuse context progressively in a tree instead of squashing it all in one layer.
  refs:
    - {title: "van den Oord et al. (2016) WaveNet", url: "https://arxiv.org/abs/1609.03499", kind: paper}
- id: residual-connections
  name: Residual connections
  category: architecture
  aliases: [skip connections, x = x + f(x)]
  summary: Add a block's output to its input so gradients flow directly through depth.
  refs:
    - {title: "He et al. (2015) Deep Residual Learning for Image Recognition", url: "https://arxiv.org/abs/1512.03385", kind: paper}
- id: self-attention
  name: Self-attention and the Transformer
  category: architecture
  aliases: [attention, multi-head attention, causal mask, scaled dot-product]
  summary: Tokens exchange information via learned query/key/value weighted averages.
  refs:
    - {title: "Vaswani et al. (2017) Attention Is All You Need", url: "https://arxiv.org/abs/1706.03762", kind: paper}
- id: gelu
  name: GELU activation
  category: architecture
  aliases: [gelu tanh approximation]
  summary: Smooth ReLU-like activation used in GPT-style models.
  refs:
    - {title: "Hendrycks & Gimpel (2016) Gaussian Error Linear Units", url: "https://arxiv.org/abs/1606.08415", kind: paper}
- id: weight-tying
  name: Tying input and output embeddings
  category: architecture
  aliases: [wte = lm_head, shared embeddings]
  summary: Share the token embedding matrix with the output projection to save parameters and help learning.
  refs:
    - {title: "Press & Wolf (2016) Using the Output Embedding to Improve Language Models", url: "https://arxiv.org/abs/1608.05859", kind: paper}
- id: gru
  name: Gated recurrent units
  category: architecture
  aliases: [GRU, RNN gating]
  summary: Recurrent cell with gates that control what to keep and update.
  refs:
    - {title: "Cho et al. (2014) Learning Phrase Representations using RNN Encoder-Decoder", url: "https://arxiv.org/abs/1406.1078", kind: paper}
- id: dropout
  name: Dropout
  category: regularization
  aliases: [nn.Dropout]
  summary: Randomly zero activations during training to reduce overfitting.
  refs:
    - {title: "Srivastava et al. (2014) Dropout", url: "https://jmlr.org/papers/v15/srivastava14a.html", kind: paper}
- id: weight-decay
  name: Weight decay / L2 regularisation
  category: regularization
  aliases: [decoupled weight decay, AdamW weight decay, regularization loss]
  summary: Pull weights toward zero; in AdamW it's applied separately from the gradient update.
  refs:
    - {title: "Loshchilov & Hutter (2017) Decoupled Weight Decay Regularization", url: "https://arxiv.org/abs/1711.05101", kind: paper}
- id: adam
  name: Adam / AdamW optimiser
  category: optimizer
  aliases: [adam, adamw, betas, eps]
  summary: Per-parameter adaptive step sizes from running averages of gradients and squared gradients.
  refs:
    - {title: "Kingma & Ba (2014) Adam", url: "https://arxiv.org/abs/1412.6980", kind: paper}
    - {title: "Loshchilov & Hutter (2017) AdamW", url: "https://arxiv.org/abs/1711.05101", kind: paper}
- id: minibatch-sgd
  name: Mini-batch SGD
  category: optimizer
  aliases: [minibatches, batch size, torch.randint batch]
  summary: Estimate the gradient from a small random batch to take many cheap steps.
  refs: []
- id: lr-search
  name: Finding a good learning rate
  category: schedule
  aliases: [lr sweep, exponential lr range test, lri]
  summary: Sweep learning rates exponentially and pick where loss falls fastest before blowing up.
  refs:
    - {title: "Smith (2015) Cyclical Learning Rates for Training Neural Networks", url: "https://arxiv.org/abs/1506.01186", kind: paper}
- id: lr-decay
  name: Learning-rate decay
  category: schedule
  aliases: [step decay, lr = 0.01 after 100k steps]
  summary: Lower the learning rate later in training to settle into a better minimum.
  refs: []
- id: cosine-schedule
  name: Cosine learning-rate schedule
  category: schedule
  aliases: [cosine decay, cosine annealing]
  summary: Decay the learning rate along a cosine curve toward a minimum.
  refs:
    - {title: "Loshchilov & Hutter (2016) SGDR", url: "https://arxiv.org/abs/1608.03983", kind: paper}
- id: lr-warmup
  name: Learning-rate warmup
  category: schedule
  aliases: [linear warmup]
  summary: Ramp the learning rate up over the first steps to avoid early instability.
  refs:
    - {title: "Goyal et al. (2017) Accurate, Large Minibatch SGD", url: "https://arxiv.org/abs/1706.02677", kind: paper}
- id: gradient-clipping
  name: Gradient norm clipping
  category: optimizer
  aliases: [clip_grad_norm_]
  summary: Rescale gradients whose global norm is too large to prevent destabilising updates.
  refs:
    - {title: "Pascanu, Mikolov & Bengio (2012) On the difficulty of training RNNs", url: "https://arxiv.org/abs/1211.5063", kind: paper}
- id: gradient-accumulation
  name: Gradient accumulation
  category: efficiency
  aliases: [grad_accum_steps, micro-batches]
  summary: Sum gradients over several micro-batches to simulate a larger batch on limited memory.
  refs: []
- id: vectorization
  name: Vectorisation and broadcasting
  category: efficiency
  aliases: [remove python loops, broadcasting rules, keepdim]
  summary: Replace Python loops with tensor operations; broadcasting stretches shapes automatically.
  refs:
    - {title: "PyTorch broadcasting semantics", url: "https://pytorch.org/docs/stable/notes/broadcasting.html", kind: docs}
    - {title: "NumPy broadcasting", url: "https://numpy.org/doc/stable/user/basics.broadcasting.html", kind: docs}
- id: fused-cross-entropy
  name: Fused, numerically stable cross-entropy
  category: numerics
  aliases: [F.cross_entropy, logsumexp trick, subtract max logit]
  summary: One fused op that avoids overflow and is faster than manual softmax + log + mean.
  refs:
    - {title: "torch.nn.functional.cross_entropy", url: "https://pytorch.org/docs/stable/generated/torch.nn.functional.cross_entropy.html", kind: docs}
- id: manual-backprop
  name: Manual backpropagation
  category: debugging
  aliases: [backprop ninja, chain rule by hand, cmp()]
  summary: Derive and code gradients yourself, checking against autograd.
  refs:
    - {title: "Rumelhart, Hinton & Williams (1986) Learning representations by back-propagating errors", url: "https://doi.org/10.1038/323533a0", kind: paper}
- id: activation-diagnostics
  name: Activation and gradient diagnostics
  category: debugging
  aliases: [histograms of activations, update-to-data ratio, saturation plots]
  summary: Plot activations, gradients, and update/data ratios per layer to spot training problems.
  refs: []
- id: no-grad
  name: Disabling gradient tracking
  category: efficiency
  aliases: [torch.no_grad, eval mode]
  summary: Skip building the autograd graph during evaluation to save memory and time.
  refs:
    - {title: "torch.no_grad", url: "https://pytorch.org/docs/stable/generated/torch.no_grad.html", kind: docs}
- id: train-val-split
  name: Train / validation / test splits
  category: data
  aliases: [dev set, overfitting check, 80/10/10]
  summary: Measure generalisation on data the model never trained on.
  refs: []
- id: bpe-tokenization
  name: Byte-pair encoding tokenisation
  category: data
  aliases: [BPE, tiktoken, merges]
  summary: Build a vocabulary by repeatedly merging the most frequent adjacent pairs.
  refs:
    - {title: "Sennrich, Haddow & Birch (2015) Neural Machine Translation of Rare Words with Subword Units", url: "https://arxiv.org/abs/1508.07909", kind: paper}
- id: reproducibility-seeds
  name: Seeds and reproducibility
  category: debugging
  aliases: [torch.Generator().manual_seed, random seed]
  summary: Fix random seeds so comparisons between runs aren't just noise.
  refs:
    - {title: "PyTorch reproducibility notes", url: "https://pytorch.org/docs/stable/notes/randomness.html", kind: docs}
- id: tf32-matmul
  name: TF32 matmul precision
  category: efficiency
  aliases: [set_float32_matmul_precision('high')]
  summary: Let tensor cores use reduced-precision internals for float32 matmuls, much faster.
  refs:
    - {title: "torch.set_float32_matmul_precision", url: "https://pytorch.org/docs/stable/generated/torch.set_float32_matmul_precision.html", kind: docs}
- id: mixed-precision
  name: Mixed precision (bf16/fp16 autocast)
  category: efficiency
  aliases: [torch.autocast, bfloat16, AMP]
  summary: Run most ops in 16-bit while keeping sensitive parts in float32.
  refs:
    - {title: "Micikevicius et al. (2017) Mixed Precision Training", url: "https://arxiv.org/abs/1710.03740", kind: paper}
    - {title: "torch.amp docs", url: "https://pytorch.org/docs/stable/amp.html", kind: docs}
- id: torch-compile
  name: torch.compile
  category: efficiency
  aliases: [kernel fusion, graph compilation]
  summary: Compile the model into fused kernels to cut Python overhead and memory traffic.
  refs:
    - {title: "torch.compile", url: "https://pytorch.org/docs/stable/generated/torch.compile.html", kind: docs}
- id: flash-attention
  name: FlashAttention
  category: efficiency
  aliases: [scaled_dot_product_attention, fused attention]
  summary: IO-aware attention kernel that never materialises the full attention matrix.
  refs:
    - {title: "Dao et al. (2022) FlashAttention", url: "https://arxiv.org/abs/2205.14135", kind: paper}
- id: nice-numbers
  name: Hardware-friendly sizes
  category: efficiency
  aliases: [vocab 50304, powers of two]
  summary: Pad dimensions to multiples of large powers of two so GPU kernels run efficiently.
  refs: []
- id: ddp
  name: Distributed data parallel training
  category: efficiency
  aliases: [DDP, torchrun, all-reduce]
  summary: Run a model copy per GPU and average gradients across them.
  refs:
    - {title: "PyTorch DDP notes", url: "https://pytorch.org/docs/stable/notes/ddp.html", kind: docs}
- id: large-batch-gpt3-hparams
  name: GPT-3 style training hyperparameters
  category: schedule
  aliases: [GPT-3 paper settings, batch size ramp]
  summary: The optimiser, schedule, and batch settings reported for GPT-3.
  refs:
    - {title: "Brown et al. (2020) Language Models are Few-Shot Learners", url: "https://arxiv.org/abs/2005.14165", kind: paper}
```

---

## Appendix B — `trail/data/prompts/analysis.md` (template)

Placeholders in `{{double_braces}}` are filled by `bundle.py`.

~~~markdown
You are helping a student understand how a piece of ML code evolved while they followed a lecture.
Explain ONE step: how the cell changed from version {{start_n}} to version {{end_n}}, why that change
helps, and what the recorded outputs show. Be accurate, concrete, and kind. Prefer clear intuition
over jargon, but keep the maths correct.

Rules:
- Only claim an effect if the recorded numbers support it. If the change in the metric is small
  relative to the noise estimate, or seeds/devices differ, say the result is uncertain.
- If the context shows other things changed at the same time (other cells, variables, restarts),
  say which part of the effect might come from those, in `context_warnings`.
- Use ONLY concept ids from the vocabulary below in `concepts`. Anything else goes in
  `other_concepts` with no links. Never invent paper titles or URLs.
- You may use the Read tool to look at the plot images listed below. Do not use any other tools.
- Reply with ONE JSON object matching the schema. No text before or after it.

## Step
Project: {{project}}
Cell: {{cell_name}}
Versions: v{{start_n}} → v{{end_n}}
Student's note: {{note}}

## Code before (v{{start_n}})
```python
{{code_before}}
```

## Code after (v{{end_n}})
```python
{{code_after}}
```

## Diff
```diff
{{diff}}
```

## Path between them
{{path_lines}}

## Outputs before
{{outputs_before}}

## Outputs after
{{outputs_after}}

## Metrics
{{metrics_block}}

## Context
{{context_block}}

## Plots you may Read
{{plot_paths}}

## Concept vocabulary (id — name — summary)
{{concept_vocab}}

## Concepts already learned in this project
{{learned_concepts}}

## JSON schema
{{json_schema}}
~~~

---

## Appendix C — `trail/data/prompts/ask.md` (template)

~~~markdown
You are helping a student revise ML code they recorded with Trail while following a lecture.
Answer their question using the recorded history below and, if needed, files in this folder
(see CLAUDE.md for the layout). Refer to versions like "v3" and quote only short code lines.
If the recordings don't contain enough information, say so and answer from general knowledge,
clearly labelled as such. Never invent paper links; use links from existing analyses if relevant.
Be clear and encouraging. Do not modify any files.

## Question
{{question}}

## Scope
{{scope_description}}

## Recorded history
{{history_block}}

## Existing analyses (summaries)
{{analyses_block}}
~~~

---

## Appendix D — generated `<project>/CLAUDE.md` (template)

~~~markdown
# Trail project: {{project}}

This folder is a recording of how notebook code evolved. Read-only: never modify anything here.

- `derived/versions.json` — start here. Cells → versions (code, metrics, notes) and steps (checkpoints).
- `runs/*.jsonl` — raw run records, one JSON object per line (code, stdout, errors, vars, displays).
- `blobs/` — plot images referenced by runs (`displays[].blob`).
- `analyses/<cell>/<step>.json|.md` — explanations of checkpoint steps.
- `qa/` — earlier questions and answers.

Cells: {{cell_list_with_version_counts}}
Steps (chronological): {{step_list_with_titles}}

When answering, cite cell names and version numbers (e.g. "mlp-init v3").
~~~

---

## Appendix E — repo `CLAUDE.md` (for Claude Code while building Trail)

~~~markdown
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
~~~

---

## Appendix F — initial `docs/STATE.md`

~~~markdown
# Current State
Last updated: <date> by Claude Code

## Done
- Spec written (docs/SPEC.md).

## In progress
- Nothing yet.

## Next
1. M0 scaffolding.
2. M1 capture core.

## Open questions
- [BLOCKING for M0 remote] GitHub username for the repo URL.

## Decisions pending my input
- Confirm repo visibility (default: public).
~~~

---

## Appendix G — acceptance checklist for v1

- [ ] Recording a Colab notebook produces runs on Drive that appear on the Mac.
- [ ] `trail log` shows sensible versions, folded attempts, and checkpoints for a real lecture.
- [ ] `trail analyze` explains checkpoints with correct metrics, honest noise notes, working links.
- [ ] Cell page shows diff + outputs + plots side by side for any two versions.
- [ ] Story mode walks through the lecture step by step, with self-check questions.
- [ ] `trail ask` answers questions using the recordings and saves them.
- [ ] Nothing Trail does ever breaks or visibly slows a notebook.