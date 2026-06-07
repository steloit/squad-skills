---
name: squad
description: Manage tasks on the Squad board. Supports task CRUD (add, edit, move, remove), board viewing, session context persistence, and statistics. For pipeline orchestration use /squad-run, for requirements refinement use /squad-refine. Run /squad-init first to register the project.
license: MIT
---

> Shared context: read `shared.md` for project config & auth, pipeline levels, status transitions, API endpoints, error handling, and agent context flow.
> Safety principles: read `principles.md` — **mandatory, not optional.**

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

### `/squad context save` — Save Session State

Captures current board state + git branch + decisions made this session to `.squad-context.md`.
Use before ending a session so the next session can resume without context loss.

```bash
BOARD=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true")
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
DIRTY=$(git diff --stat 2>/dev/null | tail -1 || echo "")
```

Write `.squad-context.md` with:
1. **Saved at**: timestamp + branch
2. **In Progress**: tasks currently in `impl` / `impl_review` / `test` columns (ID, title, status)
3. **Pending Review**: tasks in `plan_review` or `impl_review` (needs human decision)
4. **Next Todo**: first task in `todo` column
5. **Git State**: branch name, dirty working tree summary (`$DIRTY`)
6. **Decisions this session**: ask user "Any decisions to note before saving?" and append their answer verbatim

Add `.squad-context.md` to `.gitignore` if not already present (it's session-local, not shared state).

### `/squad context restore` — Restore Session State

Loads `.squad-context.md` if it exists, then fetches the live board to show what changed since save.
Use at session start instead of `/squad context` when you were mid-task last session.

```bash
SAVED=$(cat .squad-context.md 2>/dev/null || echo "")
BOARD=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true")
```

Output:
1. Show saved state (what was in progress, decisions noted)
2. Show current live board state
3. Highlight any status changes since the save (tasks that moved columns)
4. Suggest: "Resume task #ID [title]?" for the first in-progress task

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

### `/squad stats health` — Code Health Score

Auto-detects available tools and computes a 0–10 composite code health score.
Use when: "health check", "how healthy is this codebase". Runs locally — no board access needed.

```bash
python3 - <<'PY'
import subprocess, json, sys

checks = []

def run(cmd, label, parse=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        detail = parse(r) if parse else ""
        checks.append({"label": label, "ok": ok, "detail": detail})
    except FileNotFoundError:
        pass  # tool not installed — skip silently
    except subprocess.TimeoutExpired:
        checks.append({"label": label, "ok": False, "detail": "timeout"})

# TypeScript
run(["npx", "--no", "tsc", "--noEmit", "--pretty", "false"],
    "TypeScript",
    lambda r: f"{r.stdout.count('error TS')} errors" if r.returncode != 0 else "")

# Python type check (pyright preferred, mypy fallback)
if subprocess.run(["which", "pyright"], capture_output=True).returncode == 0:
    run(["pyright", "--outputjson"], "Pyright",
        lambda r: f"{json.loads(r.stdout).get('summary',{}).get('errorCount',0)} errors" if r.stdout else "")
elif subprocess.run(["which", "mypy"], capture_output=True).returncode == 0:
    run(["mypy", ".", "--ignore-missing-imports"], "mypy",
        lambda r: r.stdout.strip().split('\n')[-1] if r.stdout else "")

# Linter
if subprocess.run(["which", "ruff"], capture_output=True).returncode == 0:
    run(["ruff", "check", "--statistics"], "ruff",
        lambda r: r.stdout.strip().split('\n')[0] if r.stdout else "")
elif subprocess.run(["npx", "--no", "eslint", "--version"], capture_output=True).returncode == 0:
    run(["npx", "--no", "eslint", ".", "--max-warnings=0"], "ESLint",
        lambda r: f"{r.stdout.count('warning') + r.stdout.count('error')} issues" if r.returncode != 0 else "")

# Tests
if subprocess.run(["which", "pytest"], capture_output=True).returncode == 0:
    run(["pytest", "--tb=no", "-q"], "pytest",
        lambda r: r.stdout.strip().split('\n')[-1] if r.stdout else "")
elif subprocess.run(["npx", "--no", "jest", "--version"], capture_output=True).returncode == 0:
    run(["npx", "--no", "jest", "--passWithNoTests", "--silent"], "Jest",
        lambda r: r.stderr.strip().split('\n')[-1] if r.stderr else "")

# Rust
run(["cargo", "check", "--quiet"], "cargo check")

# Shell lint
if subprocess.run(["which", "shellcheck"], capture_output=True).returncode == 0:
    sh_files = subprocess.run(["find", ".", "-name", "*.sh", "-not", "-path", "*/.git/*"],
                               capture_output=True, text=True).stdout.strip().split()
    if sh_files:
        run(["shellcheck"] + sh_files[:20], "shellcheck",
            lambda r: f"{r.stdout.count('SC')} warnings" if r.returncode != 0 else "")

# Score
if not checks:
    print("## Code Health\nNo supported tools found (tsc/pyright/ruff/pytest/jest/cargo/shellcheck).")
    sys.exit(0)

passed = sum(1 for c in checks if c["ok"])
score = round(passed / len(checks) * 10, 1)
grade = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"

print(f"## Code Health: {grade} {score}/10  ({passed}/{len(checks)} checks passed)\n")
print("| Check | Status | Detail |")
print("|-------|--------|--------|")
for c in checks:
    icon = "✅" if c["ok"] else "❌"
    print(f"| {c['label']} | {icon} | {c['detail'] or ''} |")
PY
```

### `/squad retro` — Retrospective Analysis

Analyzes completed tasks + git history to produce a sprint retrospective report.
Use at the end of a week/sprint: "squad retro", "what did we ship this week".

```bash
BOARD=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT")
python3 << 'PY' <<< "$BOARD"
import json, sys, subprocess
from collections import defaultdict

board = json.load(sys.stdin)
columns = ['todo', 'plan', 'plan_review', 'impl', 'impl_review', 'test', 'done']
done_tasks = board.get('done', [])

print("## Retrospective\n")

# --- Completed tasks ---
print(f"### Completed: {len(done_tasks)} tasks\n")
if done_tasks:
    print("| ID | Title | Level | Rework |")
    print("|----|-------|-------|--------|")
    for t in done_tasks[-10:]:
        rework = t.get('impl_review_count', 0) or 0
        flag = f"⚠️ {rework}x" if rework > 1 else "✅"
        print(f"| {t.get('id','')} | {t.get('title','')[:45]} | L{t.get('level',1)} | {flag} |")

# --- Rework rate ---
rework_tasks = [t for t in done_tasks if (t.get('impl_review_count') or 0) > 1]
rate = len(rework_tasks) / len(done_tasks) * 100 if done_tasks else 0
print(f"\n**Rework rate**: {rate:.0f}% ({len(rework_tasks)}/{len(done_tasks)} tasks needed re-impl)")

# --- Pipeline snapshot (non-done) ---
snapshot = {col: len(board.get(col, [])) for col in columns[:-1] if board.get(col)}
if snapshot:
    print("\n### Pipeline Snapshot\n")
    print("| Column | Count |")
    print("|--------|-------|")
    for col, count in snapshot.items():
        print(f"| {col} | {count} |")

# --- Agent token spend (done tasks) ---
agent_stats = defaultdict(lambda: {'entries': 0, 'tokens': 0})
for t in done_tasks:
    raw = t.get('agent_log')
    if not raw:
        continue
    try:
        logs = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        continue
    for entry in logs:
        a = entry.get('agent', 'unknown')
        agent_stats[a]['entries'] += 1
        agent_stats[a]['tokens'] += entry.get('tokens', 0)

total = sum(v['tokens'] for v in agent_stats.values())
if total > 0:
    print(f"\n### Token Spend (completed): {total:,} est.\n")
    print("| Agent | Tokens |")
    print("|-------|--------|")
    for a in sorted(agent_stats, key=lambda x: -agent_stats[x]['tokens']):
        print(f"| {a} | {agent_stats[a]['tokens']:,} |")

# --- Git commits ---
git = subprocess.run(
    ['git', 'log', '--oneline', '--since=7 days ago'],
    capture_output=True, text=True
)
commits = [l for l in git.stdout.strip().split('\n') if l]
if commits:
    print(f"\n### Git Activity: {len(commits)} commits (last 7 days)")
PY
```

To scope to a custom period (e.g. 14 days), adjust `--since=14 days ago` in the git subprocess call.

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
