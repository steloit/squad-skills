---
name: squad-heartbeat
description: "Scans Squad boards for stagnant tasks — tasks in any active column with no activity for N days (default 3) — across all active projects or one project. Prints a markdown report table and appends one Heartbeat activity event per stagnant task unless --dry-run. Use for periodic board-hygiene sweeps or when the user asks which tasks have gone quiet."
license: MIT
metadata:
  internal: true
---

> Shared context: `../squad/shared.md` (config resolution, error rules).

## `/squad-heartbeat [--project X] [--days N] [--dry-run]`

Run the script — scanning, stagnation math, reporting, and event writes all happen inside:

```bash
python3 scripts/heartbeat.py [--project X] [--days N] [--dry-run]
```

| Flag | Meaning | Default |
|------|---------|---------|
| `--project X` | scan one project | all active projects |
| `--days N` | stagnation threshold in days | 3 |
| `--dry-run` | report only, write nothing | off |

## Reading the output

| ID | Project | Status | Days | Title |
|----|---------|--------|------|-------|
| 2100 | cpet.db | impl | 12 | Add export feature |

- Rows are stagnant tasks (active columns todo…test; done/cancelled excluded), sorted by `Days` descending.
- `Days` = days since the task's newest activity event (read via `api GET /task/$ID/activity`; a task with no events falls back to its creation time).
- A stagnation row means the task has sat untouched in `Status` for `Days` days — surface it to the user as needing a nudge, a re-plan, or cancellation. The script never changes task status.
- `No stagnant tasks found.` → healthy board, nothing written.

Unless `--dry-run`, the script writes one Heartbeat warning per stagnant task via `api POST /task/$ID/activity` (actor `Heartbeat`), making the stagnation visible on the task's timeline.
