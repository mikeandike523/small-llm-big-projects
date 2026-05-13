---
name: feedback-write-python-scripts
description: User prefers one-off filesystem operations to be done via a small Python script written to the repo root, then deleted — not via inline bash commands like find/xargs/rm
metadata:
  type: feedback
---

For one-off batch operations on files (deleting, renaming, transforming), write a small Python script to the repo root, run it, then delete it.

**Why:** Inline bash pipelines (find | xargs rm) are opaque and harder to review. A named script is visible, auditable, and the user can see exactly what it will do before it runs.

**How to apply:** Whenever I'd reach for a multi-step bash pipeline to manipulate files, write a `_something.py` script at the repo root instead. Run it with `python _something.py`, then `rm _something.py`.
