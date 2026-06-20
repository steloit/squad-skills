# Squad DB Schema & Data Formats

## Table: tasks

```sql
CREATE TABLE IF NOT EXISTS tasks (
  id SERIAL PRIMARY KEY,
  project TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'todo',
  priority TEXT NOT NULL DEFAULT 'medium',
  description TEXT,
  plan TEXT,
  implementation_notes TEXT,
  tags TEXT,
  review_comments TEXT,
  plan_review_comments TEXT,
  test_results TEXT,
  current_agent TEXT,
  plan_review_count INTEGER NOT NULL DEFAULT 0,
  impl_review_count INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  level INTEGER NOT NULL DEFAULT 3,
  attachments TEXT,
  decision_log TEXT,
  done_when TEXT,
  rank INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  planned_at TIMESTAMPTZ,
  reviewed_at TIMESTAMPTZ,
  tested_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ
);
```

| Column | Type | Description |
|--------|------|-------------|
| `project` | TEXT | Project identifier |
| `status` | TEXT | `todo` / `plan` / `plan_review` / `impl` / `impl_review` / `test` / `done` |
| `priority` | TEXT | `high` / `medium` / `low` |
| `description` | TEXT | Requirements in markdown |
| `plan` | TEXT | Implementation plan in markdown |
| `implementation_notes` | TEXT | Implementation log in markdown |
| `tags` | TEXT | JSON array string (e.g., `'["api","ui"]'`) |
| `review_comments` | TEXT | JSON array of impl review objects |
| `plan_review_comments` | TEXT | JSON array of plan review objects |
| `test_results` | TEXT | JSON array of test result objects |
| `current_agent` | TEXT | Currently active agent name |
| `plan_review_count` | INTEGER | Plan review iteration count |
| `impl_review_count` | INTEGER | Impl review iteration count |
| `version` | INTEGER | Optimistic-concurrency row version; bumped on every write. Returned as the `ETag` and accepted as `If-Match` / `expected_version` on conditional PATCH |
| `level` | INTEGER | Pipeline level: 1 (Quick), 2 (Standard), 3 (Full) |
| `attachments` | TEXT | JSON array of attachment objects: `{filename, storedName, url, size, uploaded_at}` |
| `decision_log` | TEXT | Key architecture decisions by Planner (markdown table) |
| `done_when` | TEXT | Verifiable completion criteria written by Planner (markdown checklist) |
| `rank` | INTEGER | Display order within column |

## Agent Nicknames

Each agent has a fixed nickname used in all log records, field headers, and `current_agent`.

| Nickname | Role | Model Key | Writes to |
|----------|------|-------|-----------|
| `Planner` | Plan Agent | `planner` | `plan`, `decision_log`, `done_when` |
| `Critic` | Plan Review Agent | `critic` | `plan_review_comments` |
| `Builder` | Worker Agent | `builder` | `implementation_notes` |
| `Shield` | TDD Tester | `shield` | `implementation_notes` (append) |
| `Inspector` | Code Review Agent | `inspector` | `review_comments` |
| `Ranger` | Test Runner | `ranger` | `test_results` |

## Signature Header Rule

**Every agent MUST prepend a signature header** to the content it writes:

```markdown
> **Planner** `<MODEL_PLANNER>` · 2026-02-24T10:00:00Z
```

This makes every card field self-documenting — you can see at a glance who wrote what and when.

## JSON Formats

### review_comments / plan_review_comments
```json
[
  {
    "reviewer": "Inspector",
    "model": "<MODEL_INSPECTOR>",
    "status": "changes_requested",
    "comment": "> **Inspector** `<MODEL_INSPECTOR>` · 2026-02-20T14:30:00Z\n\n## Review Findings\n\n1. Missing error handling",
    "timestamp": "2026-02-20T14:30:00.000Z"
  }
]
```
`status` must be `"approved"` or `"changes_requested"`.
`reviewer` must be the agent's **nickname** (e.g. `"Inspector"`, `"Critic"`).

### test_results
```json
[
  {
    "tester": "Ranger",
    "model": "<MODEL_RANGER>",
    "status": "pass",
    "lint": "0 errors, 0 warnings",
    "build": "Build successful",
    "tests": "42 passed, 0 failed",
    "comment": "> **Ranger** `<MODEL_RANGER>` · 2026-02-20T15:00:00Z\n\nAll checks passed.",
    "timestamp": "2026-02-20T15:00:00.000Z"
  }
]
```
`status` must be `"pass"` or `"fail"`.
`tester` must be the agent's **nickname** (`"Ranger"`).

## Table: task_activities

The immutable machine **event stream** for a task (replaces the old `agent_log` JSON column). One row per event; rows are never edited or deleted.

```sql
CREATE TABLE IF NOT EXISTS task_activities (
  id SERIAL PRIMARY KEY,
  project TEXT NOT NULL,
  task_id INTEGER NOT NULL,
  actor TEXT NOT NULL,
  model TEXT NOT NULL,
  message TEXT NOT NULL,
  tokens INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Event shape (as returned by the API):

```json
{"id": 42, "project": "demo", "task_id": 1, "actor": "Planner", "model": "<MODEL_PLANNER>", "message": "Plan complete. 4 files to modify.", "tokens": 12000, "created_at": "2026-02-20T10:05:00.000Z"}
```

- `actor` is the squad actor (see actor vocabulary below); `model` is the resolved provider model from `models.json` (or `system` for `Orchestrator`/`Heartbeat`).
- `tokens` is optional — estimated total tokens (input + output) for the step; omit when unknown (missing counts as 0 in stats).
- `created_at` is server-set — clients do **not** send a timestamp.

## Table: task_comments

The mutable **human** comment channel. Skills NEVER write this.

```sql
CREATE TABLE IF NOT EXISTS task_comments (
  id SERIAL PRIMARY KEY,
  project TEXT NOT NULL,
  task_id INTEGER NOT NULL,
  author TEXT,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Comment shape: `{"id", "project", "task_id", "author", "content", "created_at"}`.

## Activity & Comment Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/task/:id/activity?project=` | Append one event `{actor, model, message, tokens?}` → `{success, event}`. Single atomic INSERT, no read-modify-write; `actor`/`model`/`message` must be non-empty strings, `tokens` if present finite, else 400. Bumps task `version`. Immutable. |
| `GET /api/task/:id/activity?project=` | Chronological reader (`ORDER BY id ASC`), `?limit` (≤500), `?before=<id>`. |
| `GET /api/activity/stats?project=[&task_id=]` | Per-actor aggregate `{success, stats:[{actor, events, tokens}], totals}` via one `GROUP BY`. |
| `POST /api/task/:id/comment?project=` | Human comment `{content}` (optional `author`). |
| `DELETE /api/task/:id/comment/:commentId?project=` | Delete a human comment. |

**Embedding rule:** a single-task GET embeds the full `activity` + `comments` arrays **only when there is no `?fields=` param**; a projected read and the board summary/list do NOT carry them. Read activity via a full GET or `GET /api/task/:id/activity` — never `?fields=activity`.

### Actor vocabulary

| Actor | Source | `model` |
|-------|--------|---------|
| `Planner` / `Critic` / `Builder` / `Shield` / `Inspector` / `Ranger` | orchestrator records one event per pipeline agent step | resolved LLM |
| `Refiner` | squad-refine refine summary | resolved LLM |
| `Orchestrator` | squad-run commit record, squad-batch-run "Verified", squad-kickstart "Impact", move failures | `system` |
| `Heartbeat` | squad-heartbeat stagnation warnings | `system` |

### Appending an event (orchestrator)

After each agent completes, the orchestrator appends ONE signed event — a single atomic POST, no read-modify-write:

```python
python3 -c "
import subprocess, json
body = {'actor': 'NICKNAME', 'model': 'MODEL', 'message': 'MESSAGE'}
# Optional: include 'tokens' (estimated input+output), omit when unknown.
# body['tokens'] = TOKENS
subprocess.run(['curl','-sL',*auth_header,'-X','POST',f'{base_url}/api/orgs/{org}/task/{task_id}/activity?project={project}','-H','Content-Type: application/json','-d',json.dumps(body)], capture_output=True)
"
```

Replace `NICKNAME` with the agent's nickname (e.g. `Planner`, `Builder`), and `MODEL` with the resolved value from `models.json`.

**Token Estimation Guide**: the orchestrator estimates each agent's usage based on context size + output length. Example: context ~8k input + ~2k output → `tokens: 10000`. If unknown, omit the key (never send `tokens: null`) — missing tokens count as 0 in stats.

## Table: projects

```sql
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  purpose TEXT,
  stack TEXT,
  brief TEXT,
  status TEXT DEFAULT 'active',
  category TEXT,
  repo_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Project identifier (matches `.squadrc` `SQUAD_PROJECT`) |
| `name` | TEXT | Display name (often same as id) |
| `purpose` | TEXT | WHY this project exists — used for AI context docking |
| `stack` | TEXT | Technologies / frameworks used |
| `brief` | TEXT | Compressed project context: current state + direction + recent decisions. Injected into agent prompts for low-token-cost project awareness |
| `status` | TEXT | `active` / `archived` / `paused` |
| `category` | TEXT | Free-form grouping (e.g. `personal`, `tools`, `skills`) |
| `repo_url` | TEXT | Git remote URL |

## Table: project_links

```sql
CREATE TABLE IF NOT EXISTS project_links (
  source_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
  target_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
  relation TEXT NOT NULL,
  PRIMARY KEY (source_id, target_id, relation)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `source_id` | TEXT | Source project ID (FK to projects) |
| `target_id` | TEXT | Target project ID (FK to projects) |
| `relation` | TEXT | Relationship type: `extends`, `serves`, `depends_on`, `shares_data` |

## Schema Migrations

New columns are added with `ADD COLUMN IF NOT EXISTS` in PostgreSQL — idempotent, no try/catch needed.
Schema migrations run automatically on the board server at startup.
