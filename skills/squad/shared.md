# Squad Shared Context

Manages project tasks in **PostgreSQL** via the Squad board HTTP API.
All projects share a single centralized DB on the deployed Squad board.

## Project Config & Auth

Read the project name from `.squadrc` (`SQUAD_PROJECT=`, committed at the repo root, created by `/squad-init`).
Auth is resolved tool-agnostically: the `SQUAD_AUTH_TOKEN` env var first, then the bare `SQUAD_AUTH_TOKEN=` line in the `~/.squad/auth` credential file (mode 600). `SQUAD_ORG` is read from the env, else from `.squadrc` (REQUIRED — tenant is the `/api/orgs/<org>/` path). The token is a **Personal Access Token (PAT)** scoped to the user; it is never echoed, cat'd, or Read.

```bash
# 1. Project name: .squadrc → directory name
PROJECT=""
[ -f .squadrc ] && PROJECT=$(grep '^SQUAD_PROJECT=' .squadrc | cut -d= -f2-)
[ -z "$PROJECT" ] && PROJECT=$(basename "$(pwd)")

# 2. Auth token — env > bare `SQUAD_AUTH_TOKEN=` (from ~/.squad/auth)
SQUAD_ORG="${SQUAD_ORG:-}"
[ -z "$SQUAD_ORG" ] && [ -f .squadrc ] && SQUAD_ORG=$(grep '^SQUAD_ORG=' .squadrc | cut -d= -f2-)
if [ -z "$SQUAD_ORG" ]; then
  echo "ERROR: SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...)." >&2
  echo "Set it from the mint dialog's \`SQUAD_ORG=<slug>\` line — add \`SQUAD_ORG=<slug>\` to .squadrc" >&2
  echo "(committed) or export SQUAD_ORG=<slug> for this shell. Resolution order: env > .squadrc." >&2
  exit 1
fi
AUTH_TOKEN="${SQUAD_AUTH_TOKEN:-}"; AUTH_SOURCE=$([ -n "$AUTH_TOKEN" ] && echo env || echo none)
if [ -z "$AUTH_TOKEN" ] && [ -f "$HOME/.squad/auth" ]; then
  AUTH_TOKEN=$(grep '^SQUAD_AUTH_TOKEN=' "$HOME/.squad/auth" | cut -d= -f2-)
  [ -n "$AUTH_TOKEN" ] && AUTH_SOURCE=file
fi

# 3. Board URL — env → ~/.squad/config → deployed default
BASE_URL="${SQUAD_BASE_URL:-}"
[ -z "$BASE_URL" ] && [ -f "$HOME/.squad/config" ] && BASE_URL=$(grep '^SQUAD_BASE_URL=' "$HOME/.squad/config" | cut -d= -f2-)
BASE_URL="${BASE_URL:-https://squad-api-285415501393.asia-south1.run.app}"
AUTH_HEADER=()
if [ -n "$AUTH_TOKEN" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer $AUTH_TOKEN")
fi
```

If `.squadrc` is absent, `PROJECT` falls back to the directory name — prompt the user to run `/squad-init` to register it explicitly.

**Resolution:** token = `SQUAD_AUTH_TOKEN` env > bare `SQUAD_AUTH_TOKEN=` (`~/.squad/auth`); `SQUAD_ORG` = env > `.squadrc` (**required** — every board call is org-scoped `/api/orgs/<org>/...`; unset is a fail-fast pre-flight error pointing to the mint dialog's `SQUAD_ORG=<slug>` line / `.squadrc`); URL = `SQUAD_BASE_URL` env > `~/.squad/config` > deployed default; project = `.squadrc` (`SQUAD_PROJECT=`) > directory name.

### Token store format

`~/.squad/auth` (mode 600) holds a single bare line:

```
SQUAD_AUTH_TOKEN=<your Personal Access Token>
```

The store line is emitted **only** by the mint UI (Settings → Personal Access Tokens) — never by a skill, which never sees or writes the token. `SQUAD_ORG` (the tenant) is set separately in `.squadrc` / env.

### Auth errors — 401 vs 403

The token resolves straight into the `Authorization` header; **never** `echo`/`cat`/Read it or `~/.squad/auth`, and **never** use `curl -v`. Note: a missing `SQUAD_ORG` is a *pre-flight* failure — it stops before any request is even sent (no 401/403), with the actionable error above pointing to the mint dialog's `SQUAD_ORG=<slug>` line / `.squadrc`. Two distinct, scope-aware cases (plain text the agent relays — non-interactive):

- **401 (no / invalid / expired token).** Board returned `401` — no valid token for `$SQUAD_ORG`/this board. The human mints or refreshes a **Personal Access Token** in the board's web UI (**Settings → Personal Access Tokens**) and runs the store command it prints — the bare `SQUAD_AUTH_TOKEN=…` line (mode 600). The token is **never pasted to the agent**. (Don't print a URL — the skill only knows the API `BASE_URL`, and the mint page lives in the web UI; just point at **Settings → Personal Access Tokens**.)
- **403 FORBIDDEN (valid token, missing scope).** Board returned `403 FORBIDDEN` — the **PAT** is valid but **lacks the required scope/permission** for this action. The human mints a PAT **with the needed permissions** in the web UI (**Settings → Personal Access Tokens**). Do not retry until a wider-scoped PAT is stored.

`SQUAD_BASE_URL` is optional (defaults to the deployed board; self-host only, via env or `~/.squad/config`).

Quick debug check before a failing request (value-free — never prints the token):

```bash
echo "SQUAD_PROJECT=$PROJECT"
echo "SQUAD_BASE_URL=$BASE_URL"
echo "SQUAD_ORG=${SQUAD_ORG:-unset (REQUIRED — fail-fast; add SQUAD_ORG=<slug> to .squadrc)}"
echo "SQUAD_AUTH_TOKEN=$([ -n "$AUTH_TOKEN" ] && echo configured || echo empty)"
echo "SQUAD_AUTH_SOURCE=$AUTH_SOURCE"   # env | file | none
```

## Pipeline Levels

| Level | Path | Use Case |
|-------|------|----------|
| L1 Quick | `Req → Impl → Done` | File cleanup, config changes, typo fixes |
| L2 Standard | `Req → Plan → Impl → Review → Done` | Feature edits, bug fixes, refactoring |
| L3 Full | `Req → Plan → Plan Rev → Impl → Impl Rev → Test → Done` | New features, architecture changes |

Level is set at task creation and stored in the `level` column.

## 7-Column AI Team Pipeline

```
Req → Plan → Review Plan → Impl → Review Impl → Test → Done
```

| Column | Status | Agent | Model Key |
|--------|--------|-------|-------|
| Req | `todo` | User | - |
| Plan | `plan` | Plan Agent | `planner` |
| Review Plan | `plan_review` | Review Agent | `critic` |
| Impl | `impl` | Worker → TDD Tester (sequential) | `builder` → `shield` |
| Review Impl | `impl_review` | Code Review Agent | `inspector` |
| Test | `test` | Test Runner | `ranger` |
| Done | `done` | - | - |

Model keys are resolved to real provider models through `models.json`.

### Model Resolution

Skills that dispatch agents (squad-run, squad-refine, …) resolve models the same way — defined once here. Detect the provider, then `read_model <key>` / `read_effort <key>` look the key up in `models.json`.

```bash
# Provider: SQUAD_MODEL_PROVIDER env → Codex/Claude env signals → .claude/.codex dir → models.json default_provider
MODEL_PROVIDER=${SQUAD_MODEL_PROVIDER:-}
if [ -z "$MODEL_PROVIDER" ] && [ -n "${CODEX_THREAD_ID:-}${CODEX_CI:-}" ]; then MODEL_PROVIDER=codex; fi
if [ -z "$MODEL_PROVIDER" ] && [ -n "${CLAUDE_PROJECT_DIR:-}${CLAUDECODE:-}" ]; then MODEL_PROVIDER=claude; fi
if [ -z "$MODEL_PROVIDER" ] && [ -d .claude ]; then MODEL_PROVIDER=claude; fi
if [ -z "$MODEL_PROVIDER" ] && [ -d .codex ]; then MODEL_PROVIDER=codex; fi

read_model() {   # read_model <key> → real model name for the resolved provider
  local key="$1"
  python3 - "$MODEL_PROVIDER" "$key" <<'PY'
import json, pathlib, sys
d = json.loads(pathlib.Path("../squad/models.json").read_text())
provider = sys.argv[1] or d["default_provider"]
print(d["providers"][provider][sys.argv[2]])
PY
}

read_effort() {  # read_effort <key> → reasoning_effort for provider/key (may be empty)
  local key="$1"
  python3 - "$MODEL_PROVIDER" "$key" <<'PY'
import json, pathlib, sys
d = json.loads(pathlib.Path("../squad/models.json").read_text())
provider = sys.argv[1] or d["default_provider"]
print(d.get("reasoning_effort", {}).get(provider, {}).get(sys.argv[2], ""))
PY
}
```

### Move Protocol (orchestrator-owned)

This protocol belongs to the orchestrator (`squad-run`). **Only the orchestrator moves cards.** Individual agents never run it — they record verdicts (via the record-only endpoints) and the orchestrator reads those verdicts and issues the move. Always follow this sequence before moving a card.

**Step 1 — Check current state**

```bash
TASK=$(curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT&fields=status,level")
STATUS=$(echo "$TASK" | jq -r '.status')
LEVEL=$(echo "$TASK" | jq -r '.level')
```

**Step 2 — Determine next status via the Level × Status matrix**

| Current Status | L1 Quick | L2 Standard       | L3 Full                |
|-------------|----------|-------------------|------------------------|
| `todo`      | `impl`   | `plan`            | `plan`                 |
| `plan`      | —        | `impl`            | `plan_review` / `todo` |
| `plan_review` | —      | —                 | `impl` / `plan`        |
| `impl`      | `done`   | `impl_review`     | `impl_review`          |
| `impl_review` | —      | `done` / `impl`   | `test` / `impl`        |
| `test`      | —        | —                 | `done` / `impl`        |
| `done`      | (reopen → todo) | (reopen → todo) | (reopen → todo)    |

> `done` has no forward transition — it is reached only by normal moves and left only by the explicit `POST /api/task/:id/reopen` action (done → todo). It is reopenable, not strictly terminal.

**Step 3 — Execute the move**

```bash
RESPONSE=$(curl -sL -w "\n%{http_code}" "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d "{\"status\": \"$NEXT_STATUS\"}")
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)
```

**Self-correction on 400 (once)**

```bash
if [ "$HTTP_CODE" = "400" ]; then
  # Read a valid destination from the response's allowed[] array and retry
  ALLOWED=$(echo "$BODY" | jq -r '.allowed[0]')
  if [ -n "$ALLOWED" ] && [ "$ALLOWED" != "null" ]; then
    curl -sL "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT" \
      -H 'Content-Type: application/json' \
      -d "{\"status\": \"$ALLOWED\"}"
  else
    # If allowed is also empty: keep status, record the failure via POST /activity, notify the user
    echo "ERROR: cannot move task $ID from $STATUS — API returned: $BODY"
  fi
fi
```

On 2 consecutive failures: keep status, record the failure via `POST /api/task/:id/activity` (actor=`Orchestrator`), notify the user.

## API Access

All DB operations go through the deployed Squad board HTTP API (`$BASE_URL`).

### API Endpoints

```bash
# Board — full (web UI, task detail views)
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/board?project=$PROJECT"

# Board — summary (list/stats/context — excludes large TEXT fields)
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/board?project=$PROJECT&summary=true"

# Read task — full
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT"

# Read task — agent-specific fields only (always includes id, project, status)
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT&fields=title,description,plan"

# Update task fields / status
curl -sL "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"plan": "...", "status": "plan_review"}'

# Create task
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task" \
  -H 'Content-Type: application/json' \
  -d "{\"title\": \"...\", \"project\": \"$PROJECT\", \"priority\": \"medium\", \"level\": 3, \"description\": \"...\"}"

# The next three endpoints are RECORD-ONLY: each appends its verdict object to the
# matching comments/results array (and /plan-review, /review also bump their review
# count), bumps `version`, and returns the recorded verdict. They do NOT change
# `status`. The orchestrator reads the recorded verdict and issues any status move
# separately via the generic PATCH above.

# Plan review result (record-only)
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/plan-review?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer": "Critic", "model": "<MODEL_CRITIC>", "status": "approved", "comment": "..."}'
# → {"success":true,"comment":{...},"version":<int>} — verdict recorded; status unchanged.

# Impl review result (record-only)
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/review?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer": "Inspector", "model": "<MODEL_INSPECTOR>", "status": "approved", "comment": "..."}'
# → {"success":true,"comment":{...},"version":<int>} — verdict recorded; status unchanged.

# Test result (record-only)
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/test-result?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"tester": "test-runner", "status": "pass", "lint": "...", "build": "...", "tests": "...", "comment": "..."}'
# → {"success":true,"result":{...},"version":<int>} — verdict recorded; status unchanged.

# Append an activity event (machine event stream — see "Activity vs Comments" below)
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/activity?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"actor": "Orchestrator", "model": "system", "message": "Committed abc1234: <subject> [squad #'$ID']"}'
# → {"success":true,"event":{...}}

# Read a task's activity events (chronological reader)
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/activity?project=$PROJECT&limit=50"

# Add a human comment (human-only channel — skills NEVER write this)
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/comment?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"content": "Looks good to ship."}'

# Reorder
curl -sL "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/reorder?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"status": "plan", "after_id": null, "before_id": null}'

# Delete
curl -sL "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT"

# Reopen a completed task (done → todo). Optional reason is recorded as an activity event.
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/reopen?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reason": "regression found in prod"}'
# → {"success":true,"status":"todo","version":<int>}

# Upload an image attachment (base64 over JSON; stored in R2, served from a public URL)
DATA=$(base64 < "$IMG_PATH" | tr -d '\n')
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/attachment?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg filename "$(basename "$IMG_PATH")" --arg data "$DATA" '{filename: $filename, data: $data}')"
# → {"success":true,"attachment":{"filename","stored_name","url","size","uploaded_at"}}

# Delete an attachment (stored_name from the task's attachments array)
curl -sL "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/attachment/$STORED_NAME?project=$PROJECT"

# Download a task's attachments to local files (host-agnostic; temp dir, no repo pollution)
DIR="${TMPDIR:-/tmp}/squad-attachments/$ID"; mkdir -p "$DIR"
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID/attachment?project=$PROJECT" \
  | jq -r '.[] | "\(.url)\t\(.filename)"' \
  | while IFS=$'\t' read -r url fn; do curl -s "$url" -o "$DIR/$fn"; done   # files now in $DIR
```

`GET /task/:id/attachment` returns a JSON array of `{filename, stored_name, url, size, uploaded_at}` — the `url` is a public R2 link, and the web board renders it for humans. Accepted: png, jpg/jpeg, gif, webp, svg. Deleting a task removes its R2 objects.

**Viewing an attachment as an agent is host-dependent**:
- **Claude Code**: download it (above), then `Read` the local file — it renders as vision. ✅
- **Codex**: a URL in the prompt is treated as *text* (not fetched); Codex sees images only when attached at launch via `--image <path>`. So download first then pass `--image`, or just cite the `url`.

Don't assume an agent auto-sees an attachment — surface the `url`/local path and use the host's image tool where available.

If `AUTH_TOKEN` is set, keep using the shared `AUTH_HEADER` array so every request can target the same protected board deployment without repeating conditional header logic.

Only a `done` task can be reopened; reopening clears its lifecycle timestamps and `current_agent`, preserves prior work (plan, comments, counts, results), and records the action as an activity event (server-side). Reopening any non-`done` task returns `409 {"error":"only a done task can be reopened","status":"<current>"}` and changes nothing.

### Optimistic Concurrency (version / ETag / If-Match)

Every task row carries an integer `version` that increases by 1 on every write. A single-task GET returns it both as the `version` field and as a strong `ETag: "<version>"` header.

To make a conditional (compare-and-set) write, echo that version back on the generic `PATCH`:

- `If-Match: "<version>"` header (preferred), or
- `"expected_version": <version>` in the JSON body (curl-friendly fallback; the header wins if both are present).

If the supplied version no longer matches the row, the PATCH is rejected with **412** `{"error":"Precondition failed: version mismatch","currentVersion":<int>}` and nothing is written — re-read the task and retry. Omit the precondition for an unconditional write (back-compatible default). A successful PATCH returns `{"success":true,"version":<new version>}` — except a bare same-status no-op PATCH (no field actually changes), which returns the **full task row** instead of `{success, version}`.

```bash
# Conditional update: only applies if the row is still at version 7
curl -sL "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/orgs/$SQUAD_ORG/task/$ID?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "7"' \
  -d '{"status": "plan_review"}'
# → {"success":true,"version":8}   (or 412 {"error":"Precondition failed: version mismatch","currentVersion":<int>})
```

> The pipeline orchestrator is the **sole** writer of status transitions, so by default it issues moves without a precondition — correctness rests on that single-ownership, not on the conditional write. The machinery above guards against *other* concurrent writers (a second orchestrator, a batch run, or a manual board edit).

### Derived Verdict Fields (read-only)

A single-task GET exposes three read-only derived fields — the status of the latest verdict at each stage, or `null` if that stage has no verdict yet:

| Field | Latest verdict from | Values |
|-------|---------------------|--------|
| `last_plan_review_status` | plan reviews | `approved` / `changes_requested` / `null` |
| `last_review_status` | impl reviews | `approved` / `changes_requested` / `null` |
| `last_test_status` | test results | `pass` / `fail` / `null` |

The orchestrator reads these to get each stage's verdict directly, instead of parsing the comment/result JSON arrays. They are computed fields, not columns — you cannot write them. A full read returns all three; a projected `fields=` read returns only those you name. (The board summary view computes only `last_review_status` and `last_plan_review_status`, not `last_test_status` — read the single task for the test verdict.)

### Projects API Endpoints

```bash
# List all projects with links
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/projects"

# Get single project with task counts and links
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/projects/$PROJECT"

# Create/upsert project
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/projects" \
  -H 'Content-Type: application/json' \
  -d '{"id": "my-project", "name": "My Project", "purpose": "...", "stack": "...", "category": "personal"}'

# Update project fields (purpose, stack, brief, status, category, repo_url)
curl -sL "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/orgs/$SQUAD_ORG/projects/$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"brief": "Current state + direction + recent decisions"}'

# Delete project
curl -sL "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/orgs/$SQUAD_ORG/projects/$PROJECT"

# List project links
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/projects/$PROJECT/links"

# Create project link
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/projects/$PROJECT/links" \
  -H 'Content-Type: application/json' \
  -d '{"target_id": "other-project", "relation": "depends_on"}'

# Delete project link
curl -sL "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/orgs/$SQUAD_ORG/projects/$PROJECT/links" \
  -H 'Content-Type: application/json' \
  -d '{"target_id": "other-project", "relation": "depends_on"}'
```

> For full schema, column descriptions, and JSON field formats, read `schema.md`.

### Activity vs Comments

A task has two distinct append-only channels, backed by the `task_activities` and `task_comments` child tables (see `schema.md`):

- **`activity` (machine event stream).** Every event is produced by a squad **actor** as a side-effect of work — agent steps, the commit record, batch "Verified", kickstart "Impact", heartbeat warnings, reopen. Skills append events here; events are **immutable** (no edit/delete route). This replaces the old `agent_log` JSON column.
- **`comments` (human channel).** Free-form human comments only. **Skills NEVER write the human channel** (`/comment`). Machine records are events, not comments.

**The differentiation rule:** machine work → `activity`; humans → `comments`. A skill that wants to record anything it did writes an **event**, never a comment.

#### Append an event — `POST /api/task/:id/activity?project=`

The single atomic append path (no read-modify-write). Body `{actor, model, message, tokens?}`:

```json
{"actor": "Builder", "model": "<MODEL_BUILDER>", "message": "Implementation complete.", "tokens": 25000}
```

- `actor`, `model`, `message` — required, must be **non-empty strings**.
- `tokens` — optional; if present must be a **finite number** (omit the key when unknown — never send `tokens: null`).
- **No client timestamp** — the server sets `created_at`.
- On success → `{"success": true, "event": {id, project, task_id, actor, model, message, tokens, created_at}}` and the task `version` is bumped.
- Invalid body → **400** and nothing is written.

#### Actor vocabulary (the `actor` field)

| Actor | When | `model` |
|-------|------|---------|
| `Planner` / `Critic` / `Builder` / `Shield` / `Inspector` / `Ranger` | the orchestrator records one event per pipeline agent step | resolved LLM from `models.json` |
| `Refiner` | squad-refine records the refine summary | resolved LLM (e.g. `opus`) |
| `Orchestrator` | skill-level events from squad-run / squad-batch-run / squad-kickstart: the commit record, batch "Verified", kickstart "Impact", move failures | `system` |
| `Heartbeat` | squad-heartbeat stagnation warnings | `system` |

Pipeline **agents do NOT self-append** — the orchestrating skill (`squad-run`) appends one event per agent step; each agent writes only its own domain field (plan, implementation_notes, the verdict endpoints, …). See **Agent Context Flow**.

#### Read events — `GET /api/task/:id/activity?project=`

The purpose-built reader: chronological (`ORDER BY id ASC`), supports `?limit` (≤500) and `?before=<id>` for pagination. Returns `{"activity": [<event>, …]}`.

#### Full-read-only embedding

A **single-task GET with no `?fields=` param** embeds the full `activity` + `comments` arrays directly on the task. A **projected** read (`?fields=...`) does NOT embed them, and the **board summary/list does NOT carry activity at all**. So to read a task's activity, use a full task GET (embedded `activity`) or the dedicated `GET /api/task/:id/activity` — **never** `?fields=activity` (not embedded) and never the board summary.

#### Per-actor stats — `GET /api/activity/stats?project=[&task_id=]`

Server-side per-actor aggregate (one `GROUP BY actor`) → `{"success": true, "stats": [{"actor", "events", "tokens"}, …], "totals": {"events", "tokens"}}`. The scalable source for cross-task token stats — one call, no per-task loop (the board summary no longer carries activity).

#### Human comments — `POST /api/task/:id/comment` · `DELETE /api/task/:id/comment/:commentId`

The human-only channel (`{content}`, optional `author`). Documented for completeness; **skills must not write it.**

## Squad Friction Reports

Any squad skill or pipeline agent that hits friction **with Squad itself** (the skills/board/orchestrator you work *with*, not the project you work *on*) — an ambiguous
skill instruction, an awkward board API, a clunky orchestrator step, a weak or missing template, an
agent-ergonomics annoyance, or a bug — files a structured **friction** report so Squad improves
from its own use. This is **report, not fix**: never leave your actual task to chase it, and never file
the worked project's own bugs here (those go to that project's board). See `principles.md` → Forbidden.

A report is a low-priority card on **project `squad`**, tagged `friction, triage`. It lands as
a `todo` card carrying both tags (not promoted into the active backlog); a human triages it later —
promoting it into a real card (removing `triage`) or deleting it.

### Report schema

The card description is this structured body (Markdown is fine; keep the field labels):

| Field | Required | Values / notes |
|-------|----------|----------------|
| `area` | yes | one of: `skill` \| `template` \| `orchestrator` \| `board-api` \| `board-ui` \| `agent-ergonomics` \| `other` |
| `severity` | yes | `low` \| `med` \| `high` |
| `title` | yes | one concise line naming the friction (becomes the card title) |
| `evidence` | **yes** | what you were doing + the concrete friction, with a `file:line` reference or a reproduction. **No concrete evidence → not a report.** |
| `suggestion` | no | a possible fix or direction, if you have one |
| `source_project` | yes | the project you were actually working on when you hit the friction |
| `source_task` | yes | the task id on that project you were working on |

### Anti-flood guardrails

- **Evidence bar.** No `file:line` or repro → do not file. Vague "this felt awkward" is not a report.
- **Per-invocation cap N=3.** A single skill run files at most **3** reports. One squad-run pipeline
  pass counts as **one** invocation across all 6 agents (not 3 per agent) — the orchestrator owns the
  budget for a run; standalone runs (one refine, one explore) own their own.
- **Dedup against the board.** Before filing, read open friction cards and skip (or append your
  evidence to a **`friction`-tagged** card) that already covers the same friction — match on `area` + the **normalized title**
  (lowercase, collapse whitespace, drop punctuation). Don't re-file a duplicate.

### Dedup check (before filing)

```bash
# Open friction cards (not done), id+title from the summary.
# The summary is an object keyed by status (todo/plan/plan_review/impl/impl_review/test/done),
# each an array of cards; flatten the non-done buckets so `done` cards are excluded by construction.
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/board?project=squad&summary=true" \
  | jq -r '[ .todo, .plan, .plan_review, .impl, .impl_review, .test ] | add // []
           | .[]
           | select((.tags // "") | test("friction"))
           | "\(.id)\t\(.title)"'
# If a returned title (normalized) matches your report's area+title, skip or append — do not re-file.
```

### Filing a report (reuses the Create-task endpoint)

A report is created with the **same `POST /api/task`** documented above (API Access → API Endpoints),
forced to `project=squad`, `priority=low`, with the two tags as a JSON array. Build the body
with jq or Python (see JSON Safety) so newlines/quotes in `evidence` can't break the JSON:

```bash
SQUAD_BASE_URL_FOR_REPORTS="${SQUAD_BASE_URL:-https://squad-api-285415501393.asia-south1.run.app}"
BODY=$(jq -n \
  --arg area "board-api" \
  --arg severity "med" \
  --arg title "<one-line friction>" \
  --arg evidence "<what you did + concrete friction + file:line or repro>" \
  --arg suggestion "<optional fix/direction>" \
  --arg source_project "<project you were working on>" \
  --arg source_task "<task id on that project>" \
  '{title: $title, project: "squad", priority: "low", level: 1,
    tags: ["friction", "triage"],
    description: ("**area:** " + $area + "\n**severity:** " + $severity
      + "\n**evidence:** " + $evidence
      + "\n**suggestion:** " + $suggestion
      + "\n**source_project:** " + $source_project
      + "\n**source_task:** " + $source_task)}')
curl -sL "${AUTH_HEADER[@]}" -X POST "$SQUAD_BASE_URL_FOR_REPORTS/api/orgs/$SQUAD_ORG/task" \
  -H 'Content-Type: application/json' -d "$BODY"
# → {"success":true,"id":<NNN>} — a todo card tagged `friction, triage` on project squad.
```

> Reports always target **project `squad`**, even when you are working on a different project. The board
> URL is the same `$BASE_URL` you already resolved and the same org path `/api/orgs/$SQUAD_ORG/...`;
> only the `project` field changes to `squad`. The reporting org (`$SQUAD_ORG`) must own project `squad`
> (single-DB reality; a dedicated reports-org override is a noted follow-up, not in scope).

## Run Audit

Every squad run records its full Coach audit to an append-only run-audits store on project `squad`,
so triage and eval both derive from one lossless log. The Coach POSTs this **every run** (clean and
friction); material rows are ALSO surfaced as `friction, triage` cards (see Squad Friction Reports).

### POST /api/run-audit?project=squad  (append-only, Bearer-gated → `{ "id": <int> }`)

Body (JSON). `rubric`, `signals`, `filed_card_ids` MUST be valid JSON values — the endpoint returns
**400** (`"<field> must be valid JSON"`) on bare text. `overall_status` must be `clean` or `friction`.

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `source_project` | **yes** | string | project the run worked on |
| `skill` | **yes** | string | skill that ran (e.g. `squad-run`) |
| `source_task` | no | string | task id on that project |
| `level` | no | int \| null | pipeline level if known; else null/omit |
| `provider` | no | string \| null | resolved model provider (claude/codex); else null/omit |
| `overall_status` | yes | enum | `clean` (no material rows) \| `friction` (≥1 material row) |
| `rubric` | yes | JSON array | the 6 scored rows (ALL material rows, regardless of the N=3 card cap) — MUST be valid JSON |
| `signals` | yes | JSON array/object | friction signals as a JSON array or object (never a bare string scalar) — MUST be valid JSON |
| `filed_card_ids` | yes | JSON array | ids of the `friction, triage` cards filed this run (`[]` on a clean run) — MUST be valid JSON |

### GET /api/run-audits?project=&since=&status=&skill=  →  `{ "audits": [ … ] }`

Read-back / verification. Optional filters: `since` (ISO), `status` (clean|friction), `skill`.
Each row echoes the POST fields plus `id` and `created_at`.

> Best-effort: the Coach POSTs the audit but a failed POST (endpoint unreachable / network) is logged
> and the run continues — the audit is observability and must NOT break the run or block triage.

## Coach Dispatch

> **Invoked by the agent-run skills at their close — `squad-run`, `squad-explore`, `squad-batch-run`, `squad-refine`, `squad-gen-wiki`.** The CRUD/setup skills (`squad`, `squad-init`, `squad-kickstart`, `squad-heartbeat`) do NOT dispatch the Coach — like Move Protocol and Run Audit, they load this file but never invoke this procedure.

After a run is done, dispatch the **Coach** ONCE — an independent (fresh-context) judge of the run trajectory (not the worked project). It scans for friction with **Squad itself** and files a friction report only when friction clears a strict materiality bar (default ZERO). **One invocation per run** — the orchestrator owns the N=3 report budget across the run (see Squad Friction Reports), and the Coach POSTs its full audit every run (see Run Audit).

**Prerequisite:** `MODEL_PROVIDER` + the `read_model` / `read_effort` helpers are resolved per **Model Resolution** above. If the calling skill has not already resolved them during its own work, resolve them first.

**The caller supplies these per-run inputs** (everything else below is identical for every skill):
- `skill_name` — the calling skill (e.g. `squad-run`).
- `source_task` — the task id this run worked (or `(wiki)` for gen-wiki / the first batch id for batch-run).
- `run_summary` — one line describing what the run did.
- `trajectory` — this run's activity events + agent outputs (what the Coach judges).
- `friction_signals` — reject loops / retries / stop-condition trips observed this run; `none` if clean.

```bash
# --- Coach: friction review of THIS run (default-zero; files only material friction) ---
# Prereq: MODEL_PROVIDER + read_model/read_effort resolved per Model Resolution (above).
MODEL_COACH=$(read_model coach)
EFFORT_COACH=$(read_effort coach)   # "" under claude (no reasoning_effort.claude) — used only on the codex branch
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
SOURCE_PROJECT="$PROJECT"
# Caller sets these four per-run inputs (see table above):
SOURCE_TASK="<source_task>"
RUN_SUMMARY="<run_summary>"
TRAJECTORY="<trajectory>"
FRICTION_SIGNALS="<friction_signals>"
COACH_PROMPT=$(python3 ../squad/scripts/render_agent_prompt.py \
  --template ../squad/templates/coach.md \
  --models ../squad/models.json \
  --provider "$MODEL_PROVIDER" \
  --set PROJECT="$PROJECT" \
  --set skill_name="<skill_name>" \
  --set source_project="$SOURCE_PROJECT" \
  --set source_task="$SOURCE_TASK" \
  --set run_summary="$RUN_SUMMARY" \
  --set trajectory="$TRAJECTORY" \
  --set friction_signals="$FRICTION_SIGNALS" \
  --set TIMESTAMP="$TIMESTAMP")
# <MODEL_COACH> / <EFFORT_COACH> are resolved by the script from models.json (no --set needed for them).
```

Launch via the Task tool (same pattern as the pipeline agents):
- codex: `Task(subagent_type="general-purpose", model="$MODEL_COACH", model_reasoning_effort="$EFFORT_COACH", prompt=$COACH_PROMPT)`
- claude: `Task(subagent_type="general-purpose", model="$MODEL_COACH", prompt=$COACH_PROMPT)`

> **The Coach runs in the background.** Surface it to the user only when it filed friction — a single line: `🔍 N friction report(s) filed for triage`.

## Markdown Authoring

Authored markdown (plans, notes, descriptions, friction reports) frequently quotes code and fences. Two rules keep it valid CommonMark so it renders correctly in the card modal — both are the same mechanical idea: **pick a delimiter that can't collide with the content inside.**

**Block — a block that quotes content containing ``` fences:** wrap it in a `~~~` tilde outer fence (no backtick counting; tildes can't collide with backticks). A 4+-backtick outer fence is equivalent.

**Inline — a literal backtick run mentioned in prose:** delimit the inline-code span with a run one longer than the longest run inside it (to show N backticks, use N+1). **Never type a bare ``` mid-sentence** — it opens a phantom code block. To show a literal triple-backtick inline, use a four-backtick span.

**Before** (flat ``` inside ``` — the inner fence closes the block early and the rest leaks as headings/text):

````
```
```bash
echo hi
```
```
````

**After** (`~~~` outer fence — the whole quoted block, backticks and all, renders as one code block):

````
~~~
```bash
echo hi
```
~~~
````

**Inline escape** (mentioning a literal triple-backtick in a sentence — shown raw inside a `~~~` block so the backticks are literal):

~~~
to display   ```   in prose, type a 4-backtick span around it:   ```` ``` ````
~~~

## JSON Safety in curl

When passing user-supplied text (titles, descriptions) to curl, use `jq` or Python to build the JSON — never embed raw text in shell strings, as literal newlines and quotes break JSON:

```bash
# Safe: use jq
PAYLOAD=$(jq -n \
  --arg title "$TITLE" \
  --arg project "$PROJECT" \
  --arg description "$DESCRIPTION" \
  --argjson level 2 \
  '{title: $title, project: $project, priority: "medium", level: $level, description: $description}')
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD"
```

Or use Python `json.dumps()` to serialize the body safely.

## Error Handling

> **CRITICAL: If the API call fails, NEVER fall back to SQLite or any direct DB access.**
> The squad DB is PostgreSQL — there is no local SQLite file. Fix the API call and retry.

- **Board unreachable**: Check `BASE_URL`, network reachability to `https://squad-api-285415501393.asia-south1.run.app`, and whether `AUTH_TOKEN` is configured
- **API error**: Debug the request (check JSON validity, `PROJECT`, `BASE_URL`, and whether `AUTH_TOKEN` is configured) — do NOT bypass the API
- **Agent failure**: 1 retry on first failure; 2nd failure → keep status, record via `POST /activity` (actor=`Orchestrator`), notify user
- **Plan review loop**: `plan_review_count > 3` → circuit breaker, ask user
- **Impl review loop**: `impl_review_count > 3` → circuit breaker, ask user
- **Mid-pipeline crash**: preserve current status, record via `POST /activity` (actor=`Orchestrator`), notify user
- In `--auto` mode: circuit breaker still fires, requires user intervention

## Agent Context Flow (Card = Work Record)

Each agent **signs their output** with a header: `> **Nickname** \`model\` · timestamp`
The task's **`activity`** event stream accumulates the full chronological history of all agents who touched the task — the orchestrator appends one event per agent step (see **Activity vs Comments**).

The `model` value should be the resolved provider model from `models.json` (not a hardcoded provider name in the template).

| Nickname | Reads | Writes (signed) |
|----------|-------|-----------------|
| `Refiner` | `title`, `description` | `spec` (via `/task/:id/spec`; `description` untouched) |
| `Planner` | `description`, `spec` | `plan`, `decision_log`, `done_when` |
| `Critic` | `description`, `spec`, `plan`, `decision_log`, `done_when` | `plan_review_comments` (records verdict) |
| `Builder` | `description`, `spec`, `plan`, `done_when`, `plan_review_comments` | `implementation_notes` |
| `Shield` | `description`, `spec`, `implementation_notes` | `implementation_notes` (append) |
| `Inspector` | `description`, `spec`, `plan`, `done_when`, `implementation_notes` | `review_comments` (records verdict) |
| `Ranger` | `title`, `implementation_notes` | `test_results` (records verdict) |

Agents write only their own domain field above; they do **not** append to the activity stream themselves. The orchestrating skill (`squad-run`) appends one signed `POST /api/task/:id/activity` event per agent step (actor=the agent's nickname, model=its resolved model, optional `tokens`), reads the domain fields, and performs every status move (see Move Protocol).

> **Planner entry move**: the orchestrator (squad-run) performs the `todo → plan` move and sets `current_agent:"Planner"` in one PATCH *before* the Planner runs — the Planner does not move `todo → plan` itself. The Planner runs at `plan` and exits with a single level-aware move (`plan → plan_review` for L3, `plan → impl` for L2). A Critic reject (`plan_review → plan`, server-side) re-dispatches the Planner at `plan`.

## Task Relationships & Epics

Tasks relate through **two typed, structured edges** stored on the board (not encoded in text or tags):

- **`blocks`** — a dependency DAG. `A blocks B` ⟺ B is `blocked_by` A; B is not ready until A is `done`.
- **`parent`** — a single-parent hierarchy tree. A child's `parent` is its containing **epic** card.

> **REMOVED — legacy conventions.** The `Depends on: #ID` description-text convention is **retired** (dependencies are `blocks` edges). The `epic:<name>` **tag-as-hierarchy** convention is **retired** (hierarchy is `card_type:'epic'` cards + `parent` edges). Skills must NOT parse `Depends on:` text or write `epic:` tags. `phase:` tags remain valid free labels.

### Card types

`card_type ∈ {task, epic}` (default `task`), settable on `POST /api/task` create AND generic `PATCH`, and embedded on a full task GET alongside an embedded `relationships` object.

- A **`task`** is runnable through the pipeline.
- An **`epic`** is a **container** — it groups child tasks, is **excluded from the agent pipeline** (`squad-run` refuses it, `squad-batch-run` skips it, `squad-refine` treats it as a container), and carries a **derived `epic_status`** + rolled-up `children_progress`.

### Endpoints (deployed)

```
POST   /api/task/:id/relationships  {to, type}   to = <KEY>-<seq> id string · type ∈ {blocks, parent}
       → {success, relationship}
       400 self-edge / second parent / bad input · 404 task · 409 cycle (blocks DAG or parent ancestor)
GET    /api/task/:id/relationships
       → {blocked_by:[{id,title,status}], blocking:[{id,title,status}],
          parent:{id,title,status}|null, children:[{id,title,status}],
          children_progress:{done,total}}   (no `success` wrapper)
DELETE /api/task/:id/relationships/:relId    → {success:true} (200) / 404 no-match
```

The server **enforces acyclicity at write time** (in-transaction CTE) and single-parent. There is **no client-side circular-dependency check** — a cycling `POST` returns **409**, a second parent returns **400**, a DELETE of a missing edge returns **404**. Surface these from the write path; never pre-validate.

`/api/board` emits an **`epics` aggregate** (each with `children_progress`); board/context summaries group by it (and the embedded `parent`/`children`), not by tag parsing.

### Declaring edges

```bash
# Declare a blocks dependency: DEP blocks ID (ID is blocked_by DEP)
# `to` is an opaque <KEY>-<seq> display id string (e.g. SQD-12) — use --arg, never --argjson
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$DEP/relationships?project=$PROJECT" \
  -H 'Content-Type: application/json' -d "$(jq -n --arg to "$ID" '{to:$to, type:"blocks"}')"

# Attach a child to its epic: CHILD's parent is EPIC
curl -sL "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/orgs/$SQUAD_ORG/task/$CHILD/relationships?project=$PROJECT" \
  -H 'Content-Type: application/json' -d "$(jq -n --arg to "$EPIC" '{to:$to, type:"parent"}')"
```

### Resolving dependencies (squad-run ⓪ʙ)

Read `blocks` edges via `GET /api/task/:id/relationships` → `.blocked_by` (NOT description text).

**Readiness gate (hard block)**: if any `.blocked_by[].status != "done"` → default mode `AskUserQuestion` confirm; `--auto` → refuse `"blocked by incomplete dependency #N"` and abort. This precedes (and overrides) the soft sub-task nudge.

**Context injection**: take dep ids from `.blocked_by[].id`, then fetch each dep's context fields:
```bash
curl -sL "${AUTH_HEADER[@]}" "$BASE_URL/api/orgs/$SQUAD_ORG/task/$DEP_ID?project=$PROJECT&fields=title,status,decision_log,implementation_notes"
```
All fields are fetched once and cached. Per-agent filtering happens at context assembly time.

| Agent | Fields Injected | Truncation |
|-------|----------------|------------|
| `Planner` | `decision_log` + `implementation_notes` | 500 chars each |
| `Builder` | `implementation_notes` | 500 chars |
| `Inspector` | `decision_log` | 300 chars |

Truncation format: first N chars + `...[truncated]` suffix when the field exceeds the limit.

Context format per dependency:
```
### #<DEP_ID>: <title> [<status>]
[IN PROGRESS] ← only if status != done

**Decision Log:**
<decision_log truncated per agent rule>

**Implementation Notes:**
<implementation_notes truncated per agent rule>
```
Fields not applicable to the current agent are omitted entirely.

### Sub-task readiness nudge (soft)

`squad-run` on a `task` with incomplete `.children` → warn `"Task #N has M open sub-task(s) — usually run those first"`; default `AskUserQuestion` confirm, `--auto` proceeds + logs an `Orchestrator` activity note. This is a **nudge, not a block** — the message distinguishes it from the dep hard-block. If a task is BOTH blocked by an incomplete dep AND has open sub-tasks, the **hard dep block wins** (abort); the nudge is never reached.

### Error handling

- **404 on a dep context fetch**: warn in orchestrator log, skip that dependency, continue pipeline
- **Dep status != `done`**: prepend `[IN PROGRESS]` to that dep's context block (the readiness gate already handled the block decision)
- **No dependencies / no children**: context resolves to empty string; no behavioral change
- **Cycle / second parent / missing edge**: surfaced as 409 / 400 / 404 from the write path

### Review Feedback Injection

These placeholders carry feedback from previous review cycles (re-runs):

| Placeholder | Source Field | When Populated |
|-------------|-------------|----------------|
| `<critic_feedback>` | `plan_review_comments` | Planner re-run: last entry's `comment` from the JSON array |
| `<inspector_feedback>` | `review_comments` | Builder re-run: last entry's `comment` from the JSON array |

If the source field is empty or null (first run), the placeholder resolves to empty string.
