# 0002 — How `cell_id` reaches the capture hook

Date: 2026-09-11 · Status: accepted (verified against installed source)

## Question
SPEC 8.2 asks us to VERIFY that `ExecutionInfo.cell_id` exists and that ipykernel
fills it in, because identity resolution (SPEC 10.3) leans on it whenever the user
hasn't written a `# @cell:` tag.

## What I found
Verified against the versions installed in this repo's venv, not from memory.

- `IPython/core/interactiveshell.py:251,269` — `ExecutionInfo` declares `cell_id`
  (default `None`) and sets it in `__init__`. The attribute is real, and
  `getattr(info, "cell_id", None)` is the right way to read it since older IPythons
  predate it.
- `ipykernel/kernelbase.py:797-798` — the kernel reads it out of the **message
  metadata**, not the content:
  ```python
  cell_meta = parent.get("metadata", None)
  cell_id = cell_meta.get("cellId")
  ```
- `ipykernel/kernelbase.py:321,825` and `ipkernel.py:395,419` — it is only forwarded
  if `do_execute`/`run_cell` advertise a `cell_id` parameter, which both do here.

## Consequences
- The chain works, so `cell_id` is worth capturing.
- **It depends entirely on the frontend choosing to send `metadata.cellId`.** Nothing
  in the kernel invents one. `jupyter_client.KernelClient.execute()` does *not* send
  it, so a test that only calls `kc.execute()` proves nothing about the tagged path.
  `tests/kernel_driver.py` therefore builds the message by hand for the tagged case
  and tests both paths.
- Which real frontends actually send it (Colab especially) is still unknown and is
  the main question the M2 Colab spike answers. Until then, `# @cell:` tags remain
  the reliable way to track a cell, which is what the README recommends.
