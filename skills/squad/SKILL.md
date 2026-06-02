---
name: squad
description: Manage tasks on the Squad board. Supports task CRUD (add, edit, move, remove), board viewing, session context persistence, and statistics. For pipeline orchestration use /squad-run, for requirements refinement use /squad-refine. Run /squad-init first to register the project.
license: MIT
---

> Shared context: read `shared.md` for project config & auth, pipeline levels, status transitions, API endpoints, error handling, and agent context flow.

## Commands

### `/squad` or `/squad list` — View Board

```bash
BOARD=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true")
```

Output: markdown table with ID, Status, Priority, Title.

### `/squad context` — Session Handoff

**Run first when starting a new session.** Fetch board and output pipeline state:
Implementing / Plan Review / Impl Review / Testing / Recently Done / Next Todo.

```bash
BOARD=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true")
```

### `/squad add <title>` — Add Task

1. Ask user for priority, level (L1/L2/L3), description, tags (use AskUserQuestion)
2. Build JSON safely with `jq` (see shared.md → JSON Safety), POST to API, capture the new task ID
3. **Images**: if the user gave image **file path(s)** (e.g. `/squad add "Login bug" --image ./bug.png`, or "attach ./shot.png"), upload each to the new task via the attachment API (see shared.md → "Upload an image attachment"). Output the task ID + the returned attachment `url`(s). A pasted image with no path → ask the user to save it to a file first (the upload reads a local file).

### `/squad move <ID> <status>` — Move Task

> **Always follow `shared.md` → Move Protocol in order.**
> Step 1 (check current status + level) → Step 2 (consult the matrix) → Step 3 (execute the move).
> On 400: self-correct once via the response's `.allowed[0]`; notify the user after 2 failures.

### `/squad edit <ID>` — Edit Task

Ask user which fields to modify, then PATCH via API. To attach an image to an existing task, upload a local image file via the attachment API (shared.md → "Upload an image attachment").

### `/squad remove <ID>` — Delete Task

```bash
curl -s "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/task/$ID?project=$PROJECT"
```

### `/squad stats` — Statistics

```bash
BOARD=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT")
python3 << 'PY' <<< "$BOARD"
import json, sys
from collections import defaultdict

board = json.load(sys.stdin)
columns = ['todo', 'plan', 'plan_review', 'impl', 'impl_review', 'test', 'done']

# Column counts
counts = {col: len(board.get(col, [])) for col in columns}
counts['total'] = sum(counts.values())
print("## Column Counts\n")
print("| Status | Count |")
print("|--------|-------|")
for col in columns:
    print(f"| {col} | {counts[col]} |")
print(f"| **total** | **{counts['total']}** |")

# Token stats per agent
agent_stats = defaultdict(lambda: {'entries': 0, 'tokens': 0})
for col in columns:
    for task in board.get(col, []):
        raw = task.get('agent_log')
        if not raw:
            continue
        try:
            logs = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        for entry in logs:
            agent = entry.get('agent', 'unknown')
            agent_stats[agent]['entries'] += 1
            agent_stats[agent]['tokens'] += entry.get('tokens', 0)

total_tokens = sum(v['tokens'] for v in agent_stats.values())
total_entries = sum(v['entries'] for v in agent_stats.values())

print("\n## Agent Token Usage\n")
if total_tokens == 0:
    print("No token data")
else:
    print("| Agent | Entries | Tokens (est.) |")
    print("|-------|---------|---------------|")
    for agent in sorted(agent_stats):
        s = agent_stats[agent]
        print(f"| {agent} | {s['entries']} | {s['tokens']:,} |")
    print(f"| **Total** | **{total_entries}** | **{total_tokens:,}** |")
PY
```

### `/squad project` — Current Project Context (AI Context Docking)

Fetch the current project's context from the projects table. Use this at the start of a session to load project purpose, stack, brief, relationships, and task counts in one call.

```bash
PROJECT_DATA=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects/$PROJECT")
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
ALL_PROJECTS=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects")
```

Output: projects grouped by category (e.g. personal, tools, skills) with names and purposes.

### `/squad project brief` — View/Update Project Brief

The **brief** is a compressed context summary (200–500 chars) that agents consume at low token cost.

**View current brief:**
```bash
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects/$PROJECT" | jq -r '.brief // "No brief set"'
```

**Set brief directly:**
```bash
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/projects/$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"brief": "..."}'
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
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/projects/$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"purpose": "new purpose"}'

# Archive project
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/projects/$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"status": "archived"}'
```

Supported fields: `name`, `purpose`, `stack`, `brief`, `status`, `category`, `repo_url`.

### `/squad project link` — Manage Project Relationships

```bash
# Add relationship
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/projects/$PROJECT/links" \
  -H 'Content-Type: application/json' \
  -d '{"target_id": "other-project", "relation": "depends_on"}'

# Remove relationship
curl -s "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/projects/$PROJECT/links" \
  -H 'Content-Type: application/json' \
  -d '{"target_id": "other-project", "relation": "depends_on"}'
```

Relations: `extends`, `serves`, `depends_on`, `shares_data`.

## Setup & Web Board

Run `/squad-init` first to register this project — it writes `.squadrc` (`SQUAD_PROJECT=…`) at the repo root, committed so your whole team's agents target the same board project. The token never goes in a project file (it lives in the `SQUAD_AUTH_TOKEN` env var or `~/.squad/auth`).

Open the deployed board at `https://steloit-squad.vercel.app/?project=<PROJECT>` (or via the configured `SQUAD_BASE_URL`).
Features: 7-column pipeline, drag-and-drop (valid transitions only), card lifecycle modal, agent log viewer, 10s auto-refresh.
