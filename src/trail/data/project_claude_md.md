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
