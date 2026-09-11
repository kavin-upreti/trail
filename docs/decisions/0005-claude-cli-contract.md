# 0005 — The `claude -p` contract, verified

Date: 2026-09-11 · Status: accepted (checked against the installed CLI)

## Context
SPEC 11.1 says to VERIFY every flag with `claude --help` before implementing, because
flag names change between versions. It also guesses at the JSON wrapper's field names.

## What I found
Ran `claude --help` and one real call. Everything the spec assumed is correct:

| Spec assumed | Reality |
|---|---|
| `-p` / `--print` | ✓ |
| `--output-format json` | ✓ (`text`, `json`, `stream-json`) |
| `--max-turns N` | ✓ |
| `--allowedTools` / `--disallowedTools` | ✓ (also spelled `--allowed-tools`) |
| `--model <alias>` | ✓ — **aliases work** (`opus`, `sonnet`, `fable`), closing SPEC 21's open question |
| `--resume <session-id>` with `-p` | ✓ (used by ask follow-ups in M7) |
| wrapper fields `result`, `session_id`, `duration_ms`, `num_turns`, `total_cost_usd` | ✓ all present |

The wrapper also carries `is_error`, `subtype`, `stop_reason`, `usage` and `modelUsage`.
We read `is_error` to catch failures reported with a zero exit code.

## Decisions
- The prompt goes on **stdin**. Bundles reach 60 KB and would exceed `ARG_MAX`.
- Tools are `--allowedTools Read` (so plots can be read) with `Bash,Edit,Write,WebFetch,
  WebSearch,NotebookEdit,Task` explicitly denied. `--dangerously-skip-permissions` is
  never passed, and a test asserts that.
- A usage limit is detected from stderr *or* the result text, since it can arrive either
  way. Remaining steps stay pending rather than being marked failed.

## Deviation from Appendix B
The prompt template gains a `{{framing}}` slot. The first checkpoint of a cell has no
earlier version, so `start_n == end_n` and the diff is empty — asking "how did it change
from v1 to v1" wastes a call and invites an invented answer. For those steps the framing
says so explicitly and asks for the starting state to be explained instead. Verified in
practice: the reply opened "there is nothing to diff against" and described the code.

## Cost, measured
One step of a small demo cost **$0.41** at the default model with `--max-turns 4`.
Worth knowing before running `trail analyze` over a whole lecture — `max_per_run`
defaults to 10 and asks for confirmation beyond that.
