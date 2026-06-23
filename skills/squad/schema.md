# Squad DB Schema & Data Formats

## Table: tasks

The **task resource as returned by the board REST API** (`GET /api/orgs/:org/task/:id`).
This documents the JSON the API exposes — the board owns its own storage. Tasks are
addressed by their **display id** `<KEY>-<seq>` (e.g. `SQD-42`) in every API path.

| Field (JSON) | Type | Description |
|--------------|------|-------------|
| `id` | string | Display id `<KEY>-<seq>` (e.g. `SQD-42`) — used in all API paths and as activity `task_id` |
| `project` | string | Project key/name (matches `.squadrc` `SQUAD_PROJECT`) |
| `title` | string | Task title |
| `status` | string | `todo` / `plan` / `plan_review` / `impl` / `impl_review` / `test` / `done` |
| `priority` | string | `urgent` / `high` / `medium` / `low` |
| `card_type` | string | `task` (runnable) or `epic` (container) |
| `description` | string\|null | The human's **original request** — immutable; agents NEVER overwrite it. The refined, testable requirements live in **`spec`**. |
| `spec` | object\|null | The Refiner's structured spec `{goal, requirements[], qa[], version}` (null until refined). Written ONLY via `POST /task/:id/spec`. |
| `spec_version` | number | `0` = no spec yet; bumped on each spec write (under the task-`version` CAS) |
| `plan` | string\|null | Implementation plan in markdown (Planner) |
| `implementation_notes` | string\|null | Implementation log in markdown (Builder + Shield) |
| `decision_log` | string\|null | Key architecture decisions by Planner (markdown table) |
| `done_when` | string\|null | Verifiable completion criteria by Planner (markdown checklist) |
| `tags` | string[] | structured array (NOT a stringified blob) |
| `review_comments` / `plan_review_comments` / `test_results` | object[] | structured arrays of verdict objects (see JSON Formats below) |
| `current_agent` | string\|null | Currently active agent nickname |
| `version` | number | Optimistic-concurrency token; bumped on every write; sent as `expected_version` on conditional PATCH / spec writes (412 on mismatch) |
| `level` | number | 1 (Quick) / 2 (Standard) / 3 (Full) |
| `plan_review_count` / `impl_review_count` | number | Review iteration counts |
| `pinned` | boolean | Pinned-to-top flag |
| `rank` | number | Display order within column |
| `created_at` / `updated_at` / `started_at` / `planned_at` / `reviewed_at` / `tested_at` / `completed_at` | string\|null | ISO 8601 timestamps |

A **projected read** (`?fields=a,b,c`) returns only the requested fields (plus `id`,
`project`, `status`); a **full read** (no `?fields=`) additionally embeds `activity`,
`comments`, and `relationships`.

> **Attachments** are not part of the task JSON — they live behind their own endpoints
> (`POST /task/:id/attachment`, `DELETE /task/:id/attachment/:stored_name`, download
> `GET /uploads/:stored_name`). A task read does NOT embed an `attachments` array.

## Agent Nicknames

Each agent has a fixed nickname used in all log records, field headers, and `current_agent`.

| Nickname | Role | Model Key | Writes to |
|----------|------|-------|-----------|
| `Refiner` | Requirements Refiner | `refiner` | `spec` (via `POST /task/:id/spec`; `description` untouched) |
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

The immutable machine **event stream** for a task — one append-only event per agent step; events are never edited or deleted.

**Event shape as returned by the activity API:**

```json
{"id": "<uuid>", "task_id": "SQD-42", "actor": "Planner", "model": "<MODEL_PLANNER>", "message": "Plan complete. 4 files to modify.", "tokens": 12000, "created_at": "2026-02-20T10:05:00.000Z"}
```

- `id` is an opaque string (used as the `?before=<id>` pagination cursor); `task_id` is the **display id** `<KEY>-<seq>` (e.g. `SQD-42`), not a number. There is no `project` field on the event.
- `actor` is the squad actor (see actor vocabulary below); `model` is the resolved provider model from `models.json` (or `system` for `Orchestrator`/`Heartbeat`) — it may be `null`.
- `tokens` is optional/`null` — estimated total tokens (input + output) for the step; omit when unknown (missing counts as 0 in stats).
- `created_at` is server-set — clients do **not** send a timestamp.
- **Clients send only** `{actor, model?, message, tokens?}` on append. The board classifies each event internally (whether it was written by a human, an agent, or the system, and the kind of event); those classifications are NOT part of the append body or the returned shape — do not send or expect them.

## Table: task_comments

The mutable **human** comment channel. Skills NEVER write this.

Comment shape as returned by the API: `{"id": "<uuid>", "task_id": "SQD-42", "author": <string|null>, "content": "...", "created_at": "<iso>"}` (`task_id` is the display id; there is no `project` field).

## Activity & Comment Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/task/:id/activity?project=` | Append one event `{actor, message, model?, tokens?}` → `{success, event}`. Single atomic INSERT, no read-modify-write; `actor` + `message` are required non-empty strings, `model` optional non-empty, `tokens` if present finite, else 400. `actor` must be a known actor (see vocabulary). |
| `GET /api/task/:id/activity?project=` | Reader, **newest-first** (`ORDER BY created_at DESC`), `?limit` (≤500), `?before=<id>` (returns events older than that cursor id). |
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

(The **Coach** is not an activity actor — it writes to the run-audit store + files friction cards, never `/task/:id/activity`.)

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
