# Squad Shared Context

Manages project tasks in **PostgreSQL** via the Squad board HTTP API.
All projects share a single centralized DB on the deployed Squad board.

## Project Config & Auth

Read the project name from `.squadrc` (`SQUAD_PROJECT=`, committed at the repo root, created by `/squad-init`).
Auth is resolved tool-agnostically: the `SQUAD_AUTH_TOKEN` env var first, then the `~/.squad/auth` credential file (mode 600).

```bash
# 1. Project name: .squadrc → directory name
PROJECT=""
[ -f .squadrc ] && PROJECT=$(grep '^SQUAD_PROJECT=' .squadrc | cut -d= -f2-)
[ -z "$PROJECT" ] && PROJECT=$(basename "$(pwd)")

# 2. Auth token — env first (tool-agnostic), then the ~/.squad/auth secret file
AUTH_TOKEN="${SQUAD_AUTH_TOKEN:-}"
[ -z "$AUTH_TOKEN" ] && [ -f "$HOME/.squad/auth" ] && AUTH_TOKEN=$(grep '^SQUAD_AUTH_TOKEN=' "$HOME/.squad/auth" | cut -d= -f2-)

# 3. Board URL — env → ~/.squad/config → deployed default
BASE_URL="${SQUAD_BASE_URL:-}"
[ -z "$BASE_URL" ] && [ -f "$HOME/.squad/config" ] && BASE_URL=$(grep '^SQUAD_BASE_URL=' "$HOME/.squad/config" | cut -d= -f2-)
BASE_URL="${BASE_URL:-https://steloit-squad.vercel.app}"
AUTH_HEADER=()
if [ -n "$AUTH_TOKEN" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer $AUTH_TOKEN")
fi
```

If `.squadrc` is absent, `PROJECT` falls back to the directory name — prompt the user to run `/squad-init` to register it explicitly.

**Resolution:** token = `SQUAD_AUTH_TOKEN` env > `~/.squad/auth`; URL = `SQUAD_BASE_URL` env > `~/.squad/config` > deployed default; project = `.squadrc` (`SQUAD_PROJECT=`) > directory name.

**If `AUTH_TOKEN` is empty** (no env var, no `~/.squad/auth`), the board returns `401` on write. Don't guess — tell the user to set the shared token tool-agnostically, then retry (no extra skill needed):

```bash
export SQUAD_AUTH_TOKEN='<token>'   # any agent's shell; add to ~/.zshrc to persist
# …or a credential file:
mkdir -p ~/.squad && printf 'SQUAD_AUTH_TOKEN=%s\n' '<token>' > ~/.squad/auth && chmod 600 ~/.squad/auth
```

`SQUAD_BASE_URL` is optional (defaults to the deployed board; self-host only, via env or `~/.squad/config`). The token is also shown on the board's lock screen at `$BASE_URL`.

Quick debug check before a failing request:

```bash
echo "SQUAD_PROJECT=$PROJECT"
echo "SQUAD_BASE_URL=$BASE_URL"
echo "SQUAD_AUTH_TOKEN=$([ -n "$AUTH_TOKEN" ] && echo configured || echo empty)"
echo "SQUAD_AUTH_SOURCE=$([ -n "${SQUAD_AUTH_TOKEN:-}" ] && echo env || { [ -f "$HOME/.squad/auth" ] && echo squad-auth-file || echo none; })"
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

### Move Protocol (required before any move)

Always follow this sequence before moving a card.

**Step 1 — Check current state**

```bash
TASK=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=status,level")
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
| `done`      | (terminal) | (terminal)      | (terminal)             |

**Step 3 — Execute the move**

```bash
RESPONSE=$(curl -s -w "\n%{http_code}" "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/task/$ID?project=$PROJECT" \
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
    curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/task/$ID?project=$PROJECT" \
      -H 'Content-Type: application/json' \
      -d "{\"status\": \"$ALLOWED\"}"
  else
    # If allowed is also empty: keep status, log to agent_log, notify the user
    echo "ERROR: cannot move task $ID from $STATUS — API returned: $BODY"
  fi
fi
```

On 2 consecutive failures: keep status, record the failure in `agent_log`, notify the user.

## API Access

All DB operations go through the deployed Squad board HTTP API (`$BASE_URL`).

### API Endpoints

```bash
# Board — full (web UI, task detail views)
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT"

# Board — summary (list/stats/context — excludes large TEXT fields)
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true"

# Read task — full
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT"

# Read task — agent-specific fields only (always includes id, project, status)
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=title,description,plan"

# Update task fields / status
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/task/$ID?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"plan": "...", "status": "plan_review"}'

# Create task
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task" \
  -H 'Content-Type: application/json' \
  -d "{\"title\": \"...\", \"project\": \"$PROJECT\", \"priority\": \"medium\", \"level\": 3, \"description\": \"...\"}"

# Plan review result
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/plan-review?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer": "Critic", "model": "<MODEL_CRITIC>", "status": "approved", "comment": "..."}'

# Impl review result
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/review?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer": "Inspector", "model": "<MODEL_INSPECTOR>", "status": "approved", "comment": "..."}'

# Test result
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/test-result?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"tester": "test-runner", "status": "pass", "lint": "...", "build": "...", "tests": "...", "comment": "..."}'

# Add note
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/note?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"content": "Commit: abc1234"}'

# Reorder
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/task/$ID/reorder?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"status": "plan", "afterId": null, "beforeId": null}'

# Delete
curl -s "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/task/$ID?project=$PROJECT"

# Upload an image attachment (base64 over JSON; stored in R2, served from a public URL)
DATA=$(base64 < "$IMG_PATH" | tr -d '\n')
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/attachment?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg filename "$(basename "$IMG_PATH")" --arg data "$DATA" '{filename: $filename, data: $data}')"
# → {"success":true,"attachment":{"filename","storedName","url","size","uploaded_at"}}

# Delete an attachment (storedName from the task's attachments array)
curl -s "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/task/$ID/attachment/$STORED_NAME?project=$PROJECT"

# Download a task's attachments to local files (host-agnostic; temp dir, no repo pollution)
DIR="${TMPDIR:-/tmp}/squad-attachments/$ID"; mkdir -p "$DIR"
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=attachments" \
  | jq -r '.attachments[]? | "\(.url)\t\(.filename)"' \
  | while IFS=$'\t' read -r url fn; do curl -s "$url" -o "$DIR/$fn"; done   # files now in $DIR
```

The `attachments` field on a task read is a JSON array of `{filename, storedName, url, size, uploaded_at}` — the `url` is a public R2 link, and the web board renders it for humans. Accepted: png, jpg/jpeg, gif, webp, svg. Deleting a task removes its R2 objects.

**Viewing an attachment as an agent is host-dependent**:
- **Claude Code**: download it (above), then `Read` the local file — it renders as vision. ✅
- **Codex**: a URL in the prompt is treated as *text* (not fetched); Codex sees images only when attached at launch via `--image <path>`. So download first then pass `--image`, or just cite the `url`.

Don't assume an agent auto-sees an attachment — surface the `url`/local path and use the host's image tool where available.

If `AUTH_TOKEN` is set, keep using the shared `AUTH_HEADER` array so every request can target the same protected board deployment without repeating conditional header logic.

### Projects API Endpoints

```bash
# List all projects with links
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects"

# Get single project with task counts and links
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects/$PROJECT"

# Create/upsert project
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/projects" \
  -H 'Content-Type: application/json' \
  -d '{"id": "my-project", "name": "My Project", "purpose": "...", "stack": "...", "category": "personal"}'

# Update project fields (purpose, stack, brief, status, category, repo_url)
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/projects/$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"brief": "Current state + direction + recent decisions"}'

# Delete project
curl -s "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/projects/$PROJECT"

# List project links
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects/$PROJECT/links"

# Create project link
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/projects/$PROJECT/links" \
  -H 'Content-Type: application/json' \
  -d '{"target_id": "other-project", "relation": "depends_on"}'

# Delete project link
curl -s "${AUTH_HEADER[@]}" -X DELETE "$BASE_URL/api/projects/$PROJECT/links" \
  -H 'Content-Type: application/json' \
  -d '{"target_id": "other-project", "relation": "depends_on"}'
```

> For full schema, column descriptions, and JSON field formats, read `schema.md`.

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
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD"
```

Or use Python `json.dumps()` to serialize the body safely.

## Error Handling

> **CRITICAL: If the API call fails, NEVER fall back to SQLite or any direct DB access.**
> The squad DB is PostgreSQL — there is no local SQLite file. Fix the API call and retry.

- **Board unreachable**: Check `BASE_URL`, network reachability to `https://steloit-squad.vercel.app`, and whether `AUTH_TOKEN` is configured
- **API error**: Debug the request (check JSON validity, `PROJECT`, `BASE_URL`, and whether `AUTH_TOKEN` is configured) — do NOT bypass the API
- **Agent failure**: 1 retry on first failure; 2nd failure → keep status, log to `agent_log`, notify user
- **Plan review loop**: `plan_review_count > 3` → circuit breaker, ask user
- **Impl review loop**: `impl_review_count > 3` → circuit breaker, ask user
- **Mid-pipeline crash**: preserve current status, log to `agent_log`, notify user
- In `--auto` mode: circuit breaker still fires, requires user intervention

## Agent Context Flow (Card = Work Record)

Each agent **signs their output** with a header: `> **Nickname** \`model\` · timestamp`
The `agent_log` accumulates the full chronological history of all agents who touched the task.

The `model` value should be the resolved provider model from `models.json` (not a hardcoded provider name in the template).

| Nickname | Reads | Writes (signed) | Moves to |
|----------|-------|-----------------|----------|
| `Refiner` | `title`, `description` | `description` (rewrite) | stays `todo` |
| `Planner` | `description` | `plan`, `decision_log`, `done_when` | `plan_review` |
| `Critic` | `description`, `plan`, `decision_log`, `done_when` | `plan_review_comments` | `impl` or `plan` |
| `Founder` | `description`, `plan`, project brief | signed `agent_log` entry (advisory) | stays `plan_review` (optional `[f]`) |
| `Builder` | `description`, `plan`, `done_when`, `plan_review_comments` | `implementation_notes` | (none) |
| `Shield` | `description`, `implementation_notes` | `implementation_notes` (append) | `impl_review` |
| `Inspector` | `description`, `plan`, `done_when`, `implementation_notes` | `review_comments` | `test` or `impl` |
| `Ranger` | `title`, `implementation_notes` | `test_results` | `done` or `impl` |
| All agents | — | append signed entry to `agent_log` | — |

## Task Dependencies

### Convention

To declare dependencies, write `Depends on: #ID` (or `Depends on: #ID1, #ID2`) on the **first non-blank line** of the task description.

Example:
```
Depends on: #2100, #2150
Add task dependency context injection to squad-run...
```

### Parsing

Regex: `Depends on:\s*(#\d+(?:,\s*#\d+)*)`  (case-insensitive)

Extract each `#ID` number. If the line is absent or no IDs match, dependency list is empty.

### Fetching Dependency Data

For each dependency ID, fetch:
```bash
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$DEP_ID?project=$PROJECT&fields=title,status,decision_log,implementation_notes"
```

All fields are fetched once and cached. Per-agent filtering happens at context assembly time, not at fetch time.

### Per-Agent Injection Rules

| Agent | Fields Injected | Truncation |
|-------|----------------|------------|
| `Planner` | `decision_log` + `implementation_notes` | 500 chars each |
| `Builder` | `implementation_notes` | 500 chars |
| `Inspector` | `decision_log` | 300 chars |

Truncation format: first N chars + `...[truncated]` suffix when the field exceeds the limit.

### Context Format (per dependency)

```
### #<DEP_ID>: <title> [<status>]
[IN PROGRESS] ← only if status != done

**Decision Log:**
<decision_log truncated per agent rule>

**Implementation Notes:**
<implementation_notes truncated per agent rule>
```

Fields not applicable to the current agent are omitted entirely.

### Error Handling

- **404 response**: warn in orchestrator log, skip that dependency, continue pipeline
- **Dep task in progress** (status != `done`): prepend `[IN PROGRESS]` warning to that dep's context block
- **Circular dependency**: if current task ID appears in a dependency's `Depends on:` line, emit error and abort the pipeline
- **No dependencies**: `<dependencies_context>` resolves to empty string; no behavioral change

### Review Feedback Injection

These placeholders carry feedback from previous review cycles (re-runs):

| Placeholder | Source Field | When Populated |
|-------------|-------------|----------------|
| `<critic_feedback>` | `plan_review_comments` | Planner re-run: last entry's `comment` from the JSON array |
| `<inspector_feedback>` | `review_comments` | Builder re-run: last entry's `comment` from the JSON array |

If the source field is empty or null (first run), the placeholder resolves to empty string.
