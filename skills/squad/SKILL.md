---
name: squad
description: Manage tasks on the Squad board. Supports task CRUD (add, edit, move, complete, cancel, reopen, remove), board viewing, session context persistence, and statistics. For pipeline orchestration use /squad-run, for requirements refinement use /squad-refine. Run /squad-init first to register the project.
license: MIT
---

> Shared context: read `shared.md` for project config & auth, pipeline levels, status transitions, API endpoints, error handling, and agent context flow.
> Safety principles: read `principles.md` — **mandatory, not optional.**

## Commands

### `/squad` or `/squad list` — View Board

```bash
BOARD=$(api GET /board?summary=true)
```

Output: markdown table with ID, Status, Priority, Title.

**Epics**: the board response carries an `epics` aggregate (each with `children_progress` and a derived `epic_status`). Group children under their epic from this aggregate + the embedded `parent`/`children` edges — never from tag parsing (see `shared.md` → **Task Relationships & Epics**). Show each epic's `children_progress` (e.g. `2/5 done`).

### `/squad context` — Session Handoff

**Run first when starting a new session.** Fetch board and output pipeline state:
Implementing / Plan Review / Impl Review / Testing / Recently Done / Next Todo.

```bash
BOARD=$(api GET /board?summary=true)
```

### `/squad add <title>` — Add Task

1. Ask user for priority, level (L1/L2/L3), description, tags (use AskUserQuestion)
2. Build JSON safely with `jq` (see shared.md → JSON Safety), POST to API, capture the new task ID.
   `tags` MUST be a **JSON array** — the canonical stored format the board renders. Split the user's
   comma-separated input into an array, e.g. `--arg tags "$TAGS"` then `tags: ($tags | split(",") | map(gsub("^ +| +$";"")))`
   in the jq body (no tags → omit the field or pass `[]`, never `""`).
3. **Images**: if the user gave image **file path(s)** (e.g. `/squad add "Login bug" --image ./bug.png`, or "attach ./shot.png"), upload each to the new task via the attachment API (see shared.md → "Upload an image attachment"). Output the task ID + the returned attachment `url`(s). A pasted image with no path → ask the user to save it to a file first (the upload reads a local file).

### `/squad move <ID> <status>` — Move Task

> **Always follow `shared.md` → Move Protocol in order.**
> Step 1 (check current status + level) → Step 2 (consult the matrix) → Step 3 (execute the move).
> On 400: self-correct once via the response's `.allowed[0]`; notify the user after 2 failures.

### `/squad edit <ID>` — Edit Task

Ask user which fields to modify, then PATCH via API. To attach an image to an existing task, upload a local image file via the attachment API (shared.md → "Upload an image attachment").

### `/squad complete <ID> [note]` — Complete Task (administrative completion)

Mark a task **done** from **any non-terminal** status. This is **non-interactive** — no
`AskUserQuestion`, no confirmation prompt; completing is history-preserving and reversible, so just do it.

```bash
NOTE="$*"   # everything after the ID; may be empty
# omit/empty note → send {} ; otherwise send {"completion_note": "<note>"}
if [ -n "$NOTE" ]; then
  api POST /task/$ID/complete --json "$(jq -n --arg n "$NOTE" '{completion_note:$n}')"
else
  api POST /task/$ID/complete --json '{}'
fi
# → {"success":true,"status":"done","version":<int>}
```

Complete is the **paired twin** of `/squad cancel`: complete = **finished**, cancel = **won't-do**. Both
are **history-preserving** (plan, notes, comments, counts, results are kept) and **reversible** via
`/squad reopen`, unlike the irreversible `/squad remove` (a hard DELETE). Re-completing an already-done
task is a safe no-op; a **cancelled** target returns `409` — reopen it first. The card records
`completed_via:"admin"` (vs `"pipeline"` for a gated pipeline finalize) plus the optional `completion_note`.

### `/squad cancel <ID> [reason]` — Cancel Task (preferred abandon verb)

Cancel a task from **any** status. This is **non-interactive** — no `AskUserQuestion`, no
confirmation prompt; cancelling is history-preserving and reversible, so just do it.

```bash
REASON="$*"   # everything after the ID; may be empty
# omit/empty reason → send {} ; otherwise send {"cancel_reason": "<reason>"}
if [ -n "$REASON" ]; then
  api POST /task/$ID/cancel --json "$(jq -n --arg r "$REASON" '{cancel_reason:$r}')"
else
  api POST /task/$ID/cancel --json '{}'
fi
# → {"success":true,"status":"cancelled","version":<int>}
```

Cancel is the **preferred** way to abandon work: it is **history-preserving** (plan, notes,
comments, counts, results are kept) and **reversible** via `/squad reopen`. Re-cancelling an
already-cancelled task is a safe no-op. Use it for won't-do / superseded / deprioritized work
instead of `/squad remove`.

### `/squad reopen <ID>` — Reopen Task (the un-cancel / un-complete path)

Restore a terminal task (`cancelled` **OR** `done`) back to `todo`. This is the un-cancel **and**
un-complete path — reopening clears lifecycle timestamps, `current_agent`, `cancel_reason`,
`completion_note`, and `completed_via`, and preserves prior work.

```bash
api POST /task/$ID/reopen --json '{"reason": "<why reopening>"}'
# → {"success":true,"status":"todo","version":<int>}
```

Reopening a non-terminal task (anything other than `cancelled`/`done`) returns `409` and changes nothing.

### `/squad remove <ID>` — Delete Task

```bash
api DELETE /task/$ID
```

> `remove` is a hard `DELETE` — **irreversible** (the card and its attachments are gone). Reserve it
> for never-started mistakes / duplicates. For won't-do or superseded work, prefer **`/squad cancel`**
> (history-preserving and reversible).

### `/squad stats` — Statistics

Column counts come from the board summary; per-actor token/event totals come from a **single**
`GET /api/activity/stats` call (server-side `GROUP BY actor` — no per-task loop, no board fetch for tokens).

```bash
export BOARD=$(api GET /board?summary=true)
export STATS=$(api GET /activity/stats)
python3 << 'PY'
import json, os

board = json.loads(os.environ['BOARD'])
stats = json.loads(os.environ['STATS'])
columns = ['todo', 'plan', 'plan_review', 'impl', 'impl_review', 'test', 'done', 'cancelled']

# Column counts (summary is keyed by status, each an array of cards)
counts = {col: len(board.get(col, [])) for col in columns}
counts['total'] = sum(counts.values())
print("## Column Counts\n")
print("| Status | Count |")
print("|--------|-------|")
for col in columns:
    print(f"| {col} | {counts[col]} |")
print(f"| **total** | **{counts['total']}** |")

# Per-actor token/event stats — straight from the aggregate endpoint
rows = stats.get('stats', [])
totals = stats.get('totals', {})
print("\n## Agent Token Usage\n")
if not rows or totals.get('tokens', 0) == 0 and totals.get('events', 0) == 0:
    print("No token data")
else:
    print("| Actor | Events | Tokens (est.) |")
    print("|-------|--------|---------------|")
    for r in sorted(rows, key=lambda r: r.get('actor', '')):
        print(f"| {r.get('actor', 'unknown')} | {r.get('events', 0)} | {r.get('tokens', 0):,} |")
    print(f"| **Total** | **{totals.get('events', 0)}** | **{totals.get('tokens', 0):,}** |")
PY
```

### `/squad project` — Current Project Context (AI Context Docking)

Fetch the current project's context from the projects table. Use this at the start of a session to load project purpose, stack, brief, relationships, and task counts in one call.

```bash
PROJECT_DATA=$(api GET /projects/$PROJECT)
```

Output: formatted project context including:
- **Purpose** (WHY this project exists)
- **Stack** (technologies used)
- **Brief** (compressed current state + direction + recent decisions)
- **Category** and status
- **Task counts** by status
- **Links** to related projects

If the project is not registered, suggest running `/squad-init` to register it.

### `/squad project all` — Full Project Map

Fetch all projects grouped by category. Useful for understanding the full project landscape.

```bash
ALL_PROJECTS=$(api GET /projects)
```

Output: projects grouped by category (e.g. personal, tools, skills) with names and purposes.

### `/squad project brief` — View/Update Project Brief

The **brief** is a compressed context summary (200–500 chars) that agents consume at low token cost.

**View current brief:**
```bash
api GET /projects/$PROJECT | jq -r '.brief // "No brief set"'
```

**Set brief directly:**
```bash
api PATCH /projects/$PROJECT --json '{"brief": "..."}'
```

**AI-assisted update (`/squad project brief update`):**
1. Fetch current project info + recent done tasks (`GET /api/board?project=$PROJECT&summary=true`)
2. Analyze: current state, recent completions, active direction
3. Draft a concise brief (200–500 chars) covering: what exists now, where we're heading, recent key decisions
4. Present to user for confirmation → PATCH to save

### `/squad project update <field> <value>` — Edit Project Metadata

Update any project field via PATCH:

```bash
# Update purpose
api PATCH /projects/$PROJECT --json '{"purpose": "new purpose"}'

# Archive project
api PATCH /projects/$PROJECT --json '{"status": "archived"}'
```

Supported fields: `name`, `purpose`, `stack`, `brief`, `status`, `category`, `repo_url`.

### `/squad project link` — Manage Project Relationships

```bash
# Add relationship
api POST /projects/$PROJECT/links --json '{"target_id": "other-project", "relation": "depends_on"}'

# Remove relationship
api DELETE /projects/$PROJECT/links --json '{"target_id": "other-project", "relation": "depends_on"}'
```

Relations: `extends`, `serves`, `depends_on`, `shares_data`.

### `/squad observe status|dry-run` — Observation Consent (read-only)

Inspect the **observation-consent** gate. Read-only — the opt-in/opt-out act lives in the **web app** (Settings → Observation & Consent); the skill never grants or withdraws. See `shared.md` → **Observation & Consent**.

```bash
observe() { python3 ../squad/scripts/observe.py "$@"; }

# status — effective on/off, the source that decided it (env override / server
# consent / default), the policy_version on record, and the web-app manage pointer.
observe status            # human-readable;  add --json for the decision object

# dry-run — print the ABSTRACTED user_steering payload that WOULD be recorded to
# stdout (pipeable to jq) + a `# DRY RUN` banner to stderr. Writes/sends NOTHING,
# in any consent state — inspect before opting in.
observe dry-run | jq .
```

There is **no** `grant`/`withdraw` here — opt in or out in the web app.

## Setup & Web Board

Run `/squad-init` first to register this project — it writes `.squadrc` (`SQUAD_PROJECT=…`, plus an optional `SQUAD_ORG=<label>` org selector) at the repo root, committed so your whole team's agents target the same board project. The token never goes in a project file — it's a **Personal Access Token** resolved as `SQUAD_AUTH_TOKEN` env > bare `SQUAD_AUTH_TOKEN=` from `~/.squad/auth` (see `shared.md`).

Open the deployed board at `https://squad.steloit.com/?project=<PROJECT>` (or via the configured `SQUAD_BASE_URL`).
Features: 7-column pipeline, drag-and-drop (valid transitions only), card lifecycle modal, agent log viewer, 10s auto-refresh.
