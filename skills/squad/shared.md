# Squad Shared Context

Manages project tasks in **PostgreSQL** via the Squad board HTTP API.
All projects share a single centralized DB on the deployed Squad board.

## Project Config & Auth

Read the project name from `.squadrc` (`SQUAD_PROJECT=`, committed at the repo root, created by `/squad-init`).
Auth is resolved tool-agnostically: the `SQUAD_AUTH_TOKEN` env var first, then the bare `SQUAD_AUTH_TOKEN=` line in the `~/.squad/auth` credential file (mode 600). `SQUAD_ORG` is read from the env, else from `.squadrc` (REQUIRED — tenant is the `/api/orgs/<org>/` path). The token is a **Personal Access Token (PAT)** scoped to the user; it is never echoed, cat'd, or Read.

Every board call goes through the **`api.py` helper**, sourced once as `api`. The helper owns — internally and opaquely — auth (the PAT, env `SQUAD_AUTH_TOKEN` > bare `SQUAD_AUTH_TOKEN=` in `~/.squad/auth`), transport (`BASE_URL` resolution + the `/api/orgs/<org>/` path prefix + the `project=` query merge), JSON encode + `Content-Type`, and a fail-fast `SQUAD_ORG` pre-flight. Skills never assemble `curl`, headers, or the token by hand.

```bash
# Board access — sourced once, then call `api <GET|POST|PATCH|DELETE> <path> [--json …] [-q …]`.
# Path is the resource AFTER the org prefix (api.py prepends /api/orgs/<org> and merges project=).
api() { python3 ../squad/scripts/api.py "$@"; }

# 1. Project name (the project a call targets, used in resource paths): env > .squadrc → directory name
PROJECT="${SQUAD_PROJECT:-}"
[ -z "$PROJECT" ] && [ -f .squadrc ] && PROJECT=$(grep '^SQUAD_PROJECT=' .squadrc | cut -d= -f2-)
[ -z "$PROJECT" ] && PROJECT=$(basename "$(pwd)")

# 2. Org / tenant — env > .squadrc. api.py resolves this itself for every call; resolve it in the
#    shell too only to export it to a child tool that reads the env (e.g. plan_batch.py).
SQUAD_ORG="${SQUAD_ORG:-}"
[ -z "$SQUAD_ORG" ] && [ -f .squadrc ] && SQUAD_ORG=$(grep '^SQUAD_ORG=' .squadrc | cut -d= -f2-)
if [ -z "$SQUAD_ORG" ]; then
  echo "ERROR: SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...)." >&2
  echo "Set it from the mint dialog's \`SQUAD_ORG=<slug>\` line — add \`SQUAD_ORG=<slug>\` to .squadrc" >&2
  echo "(committed) or export SQUAD_ORG=<slug> for this shell. Resolution order: env > .squadrc." >&2
  exit 1
fi
```

If `.squadrc` is absent, `PROJECT` falls back to the directory name — prompt the user to run `/squad-init` to register it explicitly.

**Per-key resolution** (first match wins; `api.py` is the single resolver):

| Key            | Precedence (high → low)                                              |
|----------------|---------------------------------------------------------------------|
| Base URL       | env `SQUAD_BASE_URL` > `~/.squad/config` > deployed default          |
|                | (default = `https://squad-api-285415501393.asia-south1.run.app`)    |
| Org (tenant)   | env `SQUAD_ORG` > committed `.squadrc` — **required, no default**    |
| Project        | env `SQUAD_PROJECT` > committed `.squadrc` > current-directory name  |
| Auth token     | env `SQUAD_AUTH_TOKEN` > `~/.squad/auth` — **never `.squadrc`**      |

The token is **never** read from `.squadrc` (secrets stay out of the committed file), and the org is **not** token-derivable (the PAT is user-scoped and valid across multiple orgs, so it cannot disambiguate the tenant).

**Resolution:** `api.py` resolves the credential + transport internally — token = `SQUAD_AUTH_TOKEN` env > bare `SQUAD_AUTH_TOKEN=` (`~/.squad/auth`); URL = `SQUAD_BASE_URL` env > `~/.squad/config` > deployed default. The shell resolves identity for the call paths: `SQUAD_ORG` = env > `.squadrc` (**required** — every board call is org-scoped `/api/orgs/<org>/...`; unset is a fail-fast pre-flight error pointing to the mint dialog's `SQUAD_ORG=<slug>` line / `.squadrc`); project = env `SQUAD_PROJECT` > `.squadrc` (`SQUAD_PROJECT=`) > directory name.

### Token store format

`~/.squad/auth` (mode 600) holds a single bare line:

```
SQUAD_AUTH_TOKEN=<your Personal Access Token>
```

The store line is emitted **only** by the mint UI (Settings → Personal Access Tokens) — never by a skill, which never sees or writes the token. `SQUAD_ORG` (the tenant) is set separately in `.squadrc` / env.

### Auth errors — 401 vs 403

`api.py` resolves the token straight into the `Authorization` header internally; **never** `echo`/`cat`/Read it or `~/.squad/auth`, and **never** try to print or log it. Note: a missing `SQUAD_ORG` is a *pre-flight* failure — it stops before any request is even sent (no 401/403), with the actionable error above pointing to the mint dialog's `SQUAD_ORG=<slug>` line / `.squadrc`. Two distinct, scope-aware cases (plain text the agent relays — non-interactive):

- **401 (no / invalid / expired token).** Board returned `401` — no valid token for `$SQUAD_ORG`/this board. The human mints or refreshes a **Personal Access Token** in the board's web UI (**Settings → Personal Access Tokens**) and runs the store command it prints — the bare `SQUAD_AUTH_TOKEN=…` line (mode 600). The token is **never pasted to the agent**. (Don't print a URL — the skill only knows the API `BASE_URL`, and the mint page lives in the web UI; just point at **Settings → Personal Access Tokens**.)
- **403 FORBIDDEN (valid token, missing scope).** Board returned `403 FORBIDDEN` — the **PAT** is valid but **lacks the required scope/permission** for this action. The human mints a PAT **with the needed permissions** in the web UI (**Settings → Personal Access Tokens**). Do not retry until a wider-scoped PAT is stored.

`SQUAD_BASE_URL` is optional (defaults to the deployed board; self-host only, via env or `~/.squad/config`).

Quick debug check before a failing request (value-free — never prints the token):

```bash
echo "SQUAD_PROJECT=$PROJECT"
echo "SQUAD_ORG=${SQUAD_ORG:-unset (REQUIRED — fail-fast; add SQUAD_ORG=<slug> to .squadrc)}"
# Token + BASE_URL live inside api.py and are never printed. To check connectivity + auth
# without mutating the board, run the read-only smoke: python3 ../squad/scripts/api_smoke.py
# A failing call surfaces an actionable auth/transport error on stderr (exit 3 auth, 6 network).
```

## Observation & Consent

Squad can observe **abstracted user steering** (corrections to a plan/step) to improve the team over time — but only with explicit, opt-in consent, and never the raw content. The act of opting **in/out lives in the web app** (Settings → Observation & Consent); skills **only read** consent state, they never grant or withdraw. Off by default.

Before the orchestrator emits any `user_steering` event it consults the **consent gate** — `scripts/observe.py`, a zero-dep helper alongside `api.py`, invoked the same way:

```bash
# Read-only consent gate. observe.py NEVER handles the token — it subprocesses
# api.py for one GET /consent and reads the wire shape; api.py owns auth.
observe() { python3 ../squad/scripts/observe.py "$@"; }

observe gate    --json   # the emit decision (exit 0 = on, non-zero = off)
observe status           # effective on/off + the source that decided it
observe dry-run | jq .   # the would-be payload, written/sent nowhere
```

**Local kill-switches (a HARD off — env beats config, like the GitHub-CLI rule).** Any of these, set and not in `{"", "0", "false"}`, resolves the gate **OFF with no network call** — they override even an active server grant:

- `DO_NOT_TRACK` — the cross-tool [consoledonottrack.com](https://consoledonottrack.com) convention.
- `SQUAD_OBSERVE_DISABLED` — a dedicated Squad-only switch.
- `CI` — a CI runner is detected ⇒ default OFF (never observe in automation).

**Gate contract (the `gate` exit code — squad-run branches on the code, no parsing):**

| Code | Meaning |
|------|---------|
| 0 | observation **ON** — opted-in for `behavioral_capture`, no local override |
| 1 | **OFF**, clean — an env kill-switch is set, OR not opted-in (no row / `opted_in:false`) |
| 2 | **OFF**, fail-closed — a consent-read error (api.py non-zero or non-JSON). Any read failure → OFF, never accidental ON |

Resolution order: **env override first** (no network) → else **one** `GET /consent`, ON iff the `behavioral_capture` row is `opted_in`. The gate **fails closed** — any auth/transport/parse error is OFF.

**Once-per-run cadence.** `observe.py` is stateless — one `GET` per `gate` call. The run-scoped cache is the **caller's** job: squad-run resolves `gate` **ONCE at run start**, caches the exit code, and every per-correction emit reuses it (a mid-run web opt-out takes effect on the **next** run; any straggler emit is rejected server-side). The server (SQD-937) independently 403s un-consented `user_steering` writes, so the gate is an **optimization + the local override**, not the sole privacy guarantee.

## Abstraction Rubric (emitting `user_steering`)

When the gate is ON, an orchestrating skill emits ONE abstracted `user_steering` event at each **human correction** — a deterministic `AskUserQuestion` moment where the human redirects the run (rejects a plan, edits a spec, picks a non-recommended direction, flags a deviation). Routine **approvals** emit nothing — Tier-1 captures corrections, not confirmations. The emit is one `observe.py emit` call:

```bash
# Consent-gated, leak-filtered, BEST-EFFORT. Guard with the cached gate decision and
# `|| true` so an emit failure NEVER breaks the host run. Body goes to api.py on stdin
# (the PAT stays inside api.py; observe.py never sees it).
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$ID" \
  --modality <m> --valence <v> --target <t> --severity <s> --attributability <a> \
  --comment "<abstracted pattern>" --correlation-id "$CID" || true
```

**The enums are TRUSTED — derived from the gate context, never inferred from free text.** The skill knows what the human did at each gate, so it maps the gate directly to the five enums (`modality, valence, target, severity, attributability`). The canonical vocabularies are single-sourced in `packages/types/src/activity.ts` (SQD-935) and bound to `observe.py emit`'s `choices=` (a bad value → exit 2 before any network).

### Per-gate enum mapping

| Skill | Correction gate (the `AskUserQuestion` moment) | modality | valence | target | severity | attributability |
|-------|-----------------------------------------------|----------|---------|--------|----------|-----------------|
| squad-run | Critic **changes_requested** @ plan_review (or default-mode human reject of the plan) | `evaluative` | `negative` | `planning` | `moderate` | `violated_constraint` |
| squad-run | Inspector **changes_requested** @ impl_review | `evaluative` | `negative` | `verification` | `moderate` | `violated_constraint` |
| squad-run | Ranger **fail** @ test | `evaluative` | `negative` | `verification` | `major` | `violated_constraint` |
| squad-refine | ⑥ "Edit more" (spec sent back to interview) | `corrective` | `negative` | `scope` | `moderate` | `latent_preference` |
| squad-refine | ⑥ "Cancel" (spec discarded) | `corrective` | `negative` | `scope` | `moderate` | `ambiguous` |
| squad-refine | ④ interview redirect (a Q&A answer that changes direction) | `corrective` | `na` | `scope` | `trivial` | `latent_preference` |
| squad-explore | ④ a **non-recommended** direction chosen | `corrective` | `negative` | `planning` | `moderate` | `latent_preference` |
| squad-explore | ④ "Cancel" (report saved, no tasks) | `corrective` | `negative` | `planning` | `trivial` | `ambiguous` |
| squad-batch-run | post-Verify **unexpected design change** / deviation | `corrective` | `negative` | `scope` | `major` | `violated_constraint` |

(These are sensible defaults; a skill MAY pick a closer enum from the canonical vocab when the gate context is more specific — e.g. `target=git_strategy` / `tooling` / `pipeline_flow` when that is plainly what the human steered.)

### The `comment` — never capture raw

The five enums are the analyzable signal and require NO free text. The optional `--comment` is the ONLY free-text surface; it is an **abstracted pattern**, never raw user words, code, paths, or secrets. `observe.py emit` runs it through a deterministic, zero-dep **reject-on-detect leak filter** (prose-charset + Shannon-entropy + email/URL/IP/path/dotfile/key=value/digit-run regex); on ANY hit the comment is dropped to the **`(redacted)`** sentinel — but the enums always emit.

- **GOOD** (abstracted patterns): `"preferred a smaller scope"`, `"wanted tests first"`, `"redirected to the web app"`, `"asked to research before building"`.
- **BAD** (raw / leaky — the filter drops these to `(redacted)`): `"change src/auth/login.ts line 42"`, `"use key=sk_live_…"`, `"email me at a@b.com"`, `"the server at 10.0.0.1"`.

**Sentinel note.** The platform write-path requires `comment` (`z.string().min(1).max(120)`), so a dropped/empty comment can't be omitted — it becomes the leak-free `(redacted)` constant. "enums-always" therefore means *enums + a safe sentinel comment*. The top-level `message` is a second free-text surface, so `emit` **templates it from the enums** (`"user steering: <modality>/<valence> on <target> (<severity>)"`) — leak-free by construction, never raw text.

**Cadence + best-effort.** Resolve `gate` ONCE per run (cache `OBSERVE_OK`); emit exactly ONE event per correction occurrence (a reject-loop re-dispatch is a NEW occurrence with a fresh `correlation_id`, not a duplicate). Every emit is `|| true` best-effort — an api.py error is logged and the host run continues. The server (SQD-937) independently 403s un-consented writes as the backstop (see **Observation & Consent**).

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
TASK=$(api GET /task/$ID?fields=status,level)
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
| `cancelled` | (reopen → todo) | (reopen → todo) | (reopen → todo)    |

> `done` has no forward transition — it is reached by normal pipeline moves **and**, from **any non-terminal** status, via the explicit `POST /api/task/:id/complete` action (administrative completion → `done`, in addition to the gated pipeline path); it is left only by the explicit `POST /api/task/:id/reopen` action (done → todo, unchanged).
> `cancelled` is **terminal** and reachable from **ANY** status via `POST /api/task/:id/cancel` (it is not a column the matrix walks *into*); it too is left only by `POST /api/task/:id/reopen` (cancelled → todo).
> So `done` AND `cancelled` are the **two reopenable terminal statuses** — both reachable only as described, neither has a forward transition.

**Step 3 — Execute the move**

```bash
ERR=$(mktemp)
BODY=$(api PATCH /task/$ID --json "{\"status\": \"$NEXT_STATUS\"}" 2>"$ERR")
RC=$?   # 0 ok · 4 rejected transition (4xx) · 3 auth · 5 server · 6 network
```

**Self-correction on a rejected transition (exit 4, once)**

```bash
if [ "$RC" -eq 4 ]; then
  # api.py prints the board's 4xx body to stderr (after its "ERROR: board returned HTTP <code>." line).
  # Read a valid destination from the response's allowed[] array and retry.
  ALLOWED=$(grep -v '^ERROR:' "$ERR" | jq -r '.allowed[0] // empty' 2>/dev/null)
  if [ -n "$ALLOWED" ]; then
    api PATCH /task/$ID --json "{\"status\": \"$ALLOWED\"}"
  else
    # If allowed is also empty: keep status, record the failure via POST /activity, notify the user
    echo "ERROR: cannot move task $ID from $STATUS — API returned: $(cat "$ERR")"
  fi
fi
rm -f "$ERR"
```

On 2 consecutive failures: keep status, record the failure via `POST /api/task/:id/activity` (actor=`Orchestrator`), notify the user.

## API Access

All DB operations go through the deployed Squad board HTTP API (`$BASE_URL`).

### API Endpoints

```bash
# Board — full (web UI, task detail views)
api GET /board

# Board — summary (list/stats/context — excludes large TEXT fields)
api GET /board?summary=true

# Read task — full
api GET /task/$ID

# Read task — agent-specific fields only (always includes id, project, status)
api GET /task/$ID?fields=title,description,plan

# Update task fields / status
api PATCH /task/$ID --json '{"plan": "...", "status": "plan_review"}'

# Create task
api POST /task --json "{\"title\": \"...\", \"project\": \"$PROJECT\", \"priority\": \"medium\", \"level\": 3, \"description\": \"...\"}"

# The next three endpoints are RECORD-ONLY: each appends its verdict object to the
# matching comments/results array (and /plan-review, /review also bump their review
# count), bumps `version`, and returns the recorded verdict. They do NOT change
# `status`. The orchestrator reads the recorded verdict and issues any status move
# separately via the generic PATCH above.
# All three verdict POSTs + the /activity append + the generic task PATCH + the /spec write
# accept an optional `correlation_id` — a client-supplied uuid grouping token. squad-run threads
# ONE fresh id per agent step through the step's record-results write AND its /activity
# event; squad-refine threads ONE id (minted at step ⑦ Save) through the `/spec` write AND the
# Refiner `/activity` note — either way the board groups them into a single timeline entry.
# Omit when not threading.

# Plan review result (record-only)
api POST /task/$ID/plan-review --json '{"reviewer": "Critic", "model": "<MODEL_CRITIC>", "status": "approved", "comment": "...", "correlation_id": "<correlation_id>"}'
# → {"success":true,"comment":{...},"version":<int>} — verdict recorded; status unchanged.

# Impl review result (record-only)
api POST /task/$ID/review --json '{"reviewer": "Inspector", "model": "<MODEL_INSPECTOR>", "status": "approved", "comment": "...", "correlation_id": "<correlation_id>"}'
# → {"success":true,"comment":{...},"version":<int>} — verdict recorded; status unchanged.

# Test result (record-only)
api POST /task/$ID/test-result --json '{"tester": "test-runner", "status": "pass", "lint": "...", "build": "...", "tests": "...", "comment": "...", "correlation_id": "<correlation_id>"}'
# → {"success":true,"result":{...},"version":<int>} — verdict recorded; status unchanged.

# Append an activity event (machine event stream — see "Activity vs Comments" below)
api POST /task/$ID/activity --json '{"actor": "Orchestrator", "model": "system", "message": "Committed abc1234: <subject> [squad #'$ID']"}'
# → {"success":true,"event":{...}}
# (the per-step orchestrator activity event also carries "correlation_id": the step's id;
#  this commit-record event is the Orchestrator's own and may omit it.)

# Read a task's activity events (chronological reader)
api GET /task/$ID/activity?limit=50

# Add a human comment (human-only channel — skills NEVER write this)
api POST /task/$ID/comment --json '{"content": "Looks good to ship."}'

# Reorder
api PATCH /task/$ID/reorder --json '{"status": "plan", "after_id": null, "before_id": null}'

# Delete
api DELETE /task/$ID

# Complete a task administratively (ANY non-terminal status → done). Optional completion_note is recorded.
api POST /task/$ID/complete --json '{"completion_note": "shipped manually"}'
# → {"success":true,"status":"done","version":<int>}
# completion_note is optional (omit/empty → '{}'); re-completing an already-done task is a safe no-op;
# a cancelled target returns 409 (reopen first). The card records completed_via:"admin" (vs "pipeline" for a gated finalize).

# Cancel a task (ANY status → cancelled). Optional cancel_reason is recorded.
api POST /task/$ID/cancel --json '{"cancel_reason": "superseded by new approach"}'
# → {"success":true,"status":"cancelled","version":<int>}
# cancel_reason is optional (omit/empty → '{}'); re-cancelling an already-cancelled task is a safe no-op.

# Reopen a terminal task (done OR cancelled → todo). Optional reason is recorded as an activity event.
api POST /task/$ID/reopen --json '{"reason": "regression found in prod"}'
# → {"success":true,"status":"todo","version":<int>}

# Upload an image attachment (base64 over JSON; stored in a private bucket; the returned url is a presigned download link)
DATA=$(base64 < "$IMG_PATH" | tr -d '\n')
api POST /task/$ID/attachment --json "$(jq -n --arg filename "$(basename "$IMG_PATH")" --arg data "$DATA" '{filename: $filename, data: $data}')"
# → {"success":true,"attachment":{"filename","stored_name","url","size","uploaded_at"}}

# Delete an attachment (stored_name from the task's attachments array)
api DELETE /task/$ID/attachment/$STORED_NAME

# Download a task's attachments to local files (host-agnostic; temp dir, no repo pollution)
DIR="${TMPDIR:-/tmp}/squad-attachments/$ID"; mkdir -p "$DIR"
api GET /task/$ID/attachment \
  | jq -r '.[] | "\(.url)\t\(.filename)"' \
  | while IFS=$'\t' read -r url fn; do curl -s "$url" -o "$DIR/$fn"; done   # presigned fetch stays raw; files now in $DIR
```

`GET /task/:id/attachment` returns a JSON array of `{filename, stored_name, url, size, uploaded_at}` — the `url` is an absolute, short-TTL **presigned download URL** (private bucket): fetch it directly with a plain `curl` — it is self-authenticating, so **no `Authorization` header is needed on the per-file fetch**. It **expires** — if a `url` is stale, re-list via `GET /task/:id/attachment` for a fresh one. Note the `GET /task/:id/attachment` **list** call itself requires the PAT (`attachment:read`); only the per-file presigned `url` does not. Accepted: png, jpg/jpeg, gif, webp, svg. Deleting a task removes its stored objects.

**Viewing an attachment as an agent is host-dependent**:
- **Claude Code**: download it (above), then `Read` the local file — it renders as vision. ✅
- **Codex**: a URL in the prompt is treated as *text* (not fetched); Codex sees images only when attached at launch via `--image <path>`. So download first then pass `--image`, or just cite the `url`.

Don't assume an agent auto-sees an attachment — surface the `url`/local path and use the host's image tool where available.

A `done` **OR** `cancelled` task can be reopened (`reopen` is both the un-cancel and the un-complete path); reopening clears its lifecycle timestamps, `current_agent`, `cancel_reason`, `completion_note`, **and** `completed_via`, preserves prior work (plan, comments, counts, results), and records the action as an activity event (server-side). Reopening any non-terminal task (a status other than `done`/`cancelled`) returns `409` with the current status and changes nothing. Cancel and complete are the mirror actions: `POST /task/:id/cancel` moves a task from **any** status to `cancelled` (history-preserving, optional `cancel_reason`); `POST /task/:id/complete` moves a task from **any non-terminal** status to the `done` terminal (history-preserving, optional `completion_note`, sets `completed_via:"admin"`, `409` on a cancelled target — reopen first); re-cancelling/re-completing an already-terminal task in the same state is a safe no-op.

### Optimistic Concurrency (version / ETag / If-Match)

Every task row carries an integer `version` that increases by 1 on every write. A single-task GET returns it both as the `version` field and as a strong `ETag: "<version>"` header.

To make a conditional (compare-and-set) write, echo that version back on the generic `PATCH`:

- `If-Match: "<version>"` header (preferred), or
- `"expected_version": <version>` in the JSON body (curl-friendly fallback; the header wins if both are present).

`api.py` sets headers internally and forwards no custom `If-Match` header, so a conditional write through the helper uses the **`expected_version` body form** (the example below). If the supplied version no longer matches the row, the PATCH is rejected with **412** `{"error":"Precondition failed: version mismatch","currentVersion":<int>}` and nothing is written — re-read the task and retry. Omit the precondition for an unconditional write (back-compatible default). A successful PATCH returns `{"success":true,"version":<new version>}` — except a bare same-status no-op PATCH (no field actually changes), which returns the **full task row** instead of `{success, version}`.

```bash
# Conditional update: only applies if the row is still at version 7
api PATCH /task/$ID --json '{"expected_version": 7, "status": "plan_review"}'
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
api GET /projects

# Get single project with task counts and links
api GET /projects/$PROJECT

# Create/upsert project
api POST /projects --json '{"id": "my-project", "name": "My Project", "purpose": "...", "stack": "...", "category": "personal"}'

# Update project fields (purpose, stack, brief, status, category, repo_url)
api PATCH /projects/$PROJECT --json '{"brief": "Current state + direction + recent decisions"}'

# Delete project
api DELETE /projects/$PROJECT

# List project links
api GET /projects/$PROJECT/links

# Create project link
api POST /projects/$PROJECT/links --json '{"target_id": "other-project", "relation": "depends_on"}'

# Delete project link
api DELETE /projects/$PROJECT/links --json '{"target_id": "other-project", "relation": "depends_on"}'
```

> For full schema, column descriptions, and JSON field formats, read `schema.md`.

### Activity vs Comments

A task has two distinct append-only channels, backed by the `task_activities` and `task_comments` child tables (see `schema.md`):

- **`activity` (machine event stream).** Every event is produced by a squad **actor** as a side-effect of work — agent steps, the commit record, batch "Verified", kickstart "Impact", heartbeat warnings, reopen. Skills append events here; events are **immutable** (no edit/delete route). This replaces the old `agent_log` JSON column.
- **`comments` (human channel).** Free-form human comments only. **Skills NEVER write the human channel** (`/comment`). Machine records are events, not comments.

**The differentiation rule:** machine work → `activity`; humans → `comments`. A skill that wants to record anything it did writes an **event**, never a comment.

#### Append an event — `POST /api/task/:id/activity?project=`

The single atomic append path (no read-modify-write). Body `{actor, model, message, tokens?, correlation_id?}`:

```json
{"actor": "Builder", "model": "<MODEL_BUILDER>", "message": "Implementation complete.", "tokens": 25000, "correlation_id": "<correlation_id>"}
```

- `actor`, `model`, `message` — required, must be **non-empty strings**.
- `tokens` — optional; if present must be a **finite number** (omit the key when unknown — never send `tokens: null`).
- `correlation_id` — optional; a client-supplied uuid grouping token. squad-run sends the step's id here (matching the agent's record-results write) so the board groups them into one timeline entry. squad-refine ALSO threads correlation_id: it mints one id at step ⑦ Save and sends the SAME id on the spec write (`POST /task/:id/spec`) AND this Refiner activity note, grouping the spec snapshot + note into one stage. Omit when not threading a step.
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
# Open friction cards (not terminal), id+title from the summary.
# The summary is an object keyed by status (todo/plan/plan_review/impl/impl_review/test/done/cancelled),
# each an array of cards; flatten only the non-terminal buckets so `done` AND `cancelled` cards are
# excluded by construction (both are terminal — neither is an active-context bucket).
api GET /board?project=squad&summary=true \
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
api POST /task?project=squad --json "$BODY"
# → {"success":true,"id":<NNN>} — a todo card tagged `friction, triage` on project squad.
# project=squad is forced in the query (api.py won't override an explicit project=); the body
# also carries "project":"squad" — both agree, so the report lands on project squad regardless.
```

> Reports always target **project `squad`**, even when you are working on a different project. `api.py`
> resolves the same board URL and the same org path `/api/orgs/<org>/...`; only the targeted project
> changes to `squad` (`?project=squad`). The reporting org must own project `squad`
> (single-DB reality; a dedicated reports-org override is a noted follow-up, not in scope).

## Run Audit

Every squad run records its full Coach audit to an append-only run-audits store on project `squad`,
so triage and eval both derive from one lossless log. The Coach POSTs this **every run** (clean and
friction); material rows are ALSO surfaced as `friction, triage` cards (see Squad Friction Reports).

### POST /api/orgs/{org}/run-audit?project=squad  (append-only, Bearer-gated → `{ "id": <int> }`)

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

### GET /api/orgs/{org}/run-audits?project=&since=&status=&skill=  →  `{ "audits": [ … ] }`

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

## JSON Safety

When passing user-supplied text (titles, descriptions) to a board write, use `jq` or Python to build the JSON body — never embed raw text in shell strings, as literal newlines and quotes break JSON:

```bash
# Safe: use jq
PAYLOAD=$(jq -n \
  --arg title "$TITLE" \
  --arg project "$PROJECT" \
  --arg description "$DESCRIPTION" \
  --argjson level 2 \
  '{title: $title, project: $project, priority: "medium", level: $level, description: $description}')
api POST /task --json "$PAYLOAD"
```

Or use Python `json.dumps()` to serialize the body safely. `api.py` re-encodes the body it
receives, so the safe-build pattern above stays the right way to assemble user-supplied text.

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

- **`blocks`** — a dependency DAG. `A blocks B` ⟺ B is `blocked_by` A; B is not ready until A is **resolved** — i.e. `done` (or `cancelled`, the other terminal status).
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

> The `epics` aggregate also exposes a derived **`complete`** boolean per epic (true when `children_progress.done == total > 0`). It is **DISPLAY / REPORTING only** — a progress rollup, **NOT** a dependency-satisfaction signal. An epic used as a blocker is unblocked by explicitly `/complete`-ing it (its status → `done`, recording `completed_via:"admin"`), never by this derived flag; readiness stays status-based.

### Declaring edges

```bash
# Declare a blocks dependency: DEP blocks ID (ID is blocked_by DEP)
# `to` is an opaque <KEY>-<seq> display id string — use --arg, never --argjson
api POST /task/$DEP/relationships --json "$(jq -n --arg to "$ID" '{to:$to, type:"blocks"}')"

# Attach a child to its epic: CHILD's parent is EPIC
api POST /task/$CHILD/relationships --json "$(jq -n --arg to "$EPIC" '{to:$to, type:"parent"}')"
```

### Resolving dependencies (squad-run ⓪ʙ)

Read `blocks` edges via `GET /api/task/:id/relationships` → `.blocked_by` (NOT description text).

**Readiness gate (hard block)**: a dep is **resolved** when its status is `done` **or** `cancelled` (the two terminal statuses). If any `.blocked_by[].status` is not in `{done, cancelled}` → default mode `AskUserQuestion` confirm; `--auto` → refuse `"blocked by incomplete dependency #N"` and abort. This precedes (and overrides) the soft sub-task nudge. An **epic** used as a blocker should be `/complete`'d (→ `done`) to unblock its dependents; readiness is **status-based** — the derived epic `complete` rollup is display-only and does NOT satisfy a dependency (the resolved set is unchanged: `{done, cancelled}`).

**Context injection**: take dep ids from `.blocked_by[].id`, then fetch each dep's context fields:
```bash
api GET /task/$DEP_ID?fields=title,status,decision_log,implementation_notes
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
[IN PROGRESS] ← only if status not in {done, cancelled} (a done OR cancelled dep is resolved — no marker)

**Decision Log:**
<decision_log truncated per agent rule>

**Implementation Notes:**
<implementation_notes truncated per agent rule>
```
Fields not applicable to the current agent are omitted entirely.

### Sub-task readiness nudge (soft)

`squad-run` on a `task` with incomplete `.children` → warn `"Task #N has M open sub-task(s) — usually run those first"`; default `AskUserQuestion` confirm, `--auto` proceeds + logs an `Orchestrator` activity note. **Open** counts only **non-terminal** children — a child whose status is `done` or `cancelled` is resolved and does not count. This is a **nudge, not a block** — the message distinguishes it from the dep hard-block. If a task is BOTH blocked by an incomplete dep AND has open sub-tasks, the **hard dep block wins** (abort); the nudge is never reached.

### Error handling

- **404 on a dep context fetch**: warn in orchestrator log, skip that dependency, continue pipeline
- **Dep status not in `{done, cancelled}`**: prepend `[IN PROGRESS]` to that dep's context block (the readiness gate already handled the block decision). A `done` **OR** `cancelled` dep is resolved — no `[IN PROGRESS]` marker.
- **No dependencies / no children**: context resolves to empty string; no behavioral change
- **Cycle / second parent / missing edge**: surfaced as 409 / 400 / 404 from the write path

### Review Feedback Injection

These placeholders carry feedback from previous review cycles (re-runs):

| Placeholder | Source Field | When Populated |
|-------------|-------------|----------------|
| `<critic_feedback>` | `plan_review_comments` | Planner re-run: last entry's `comment` from the JSON array |
| `<inspector_feedback>` | `review_comments` | Builder re-run: last entry's `comment` from the JSON array |

If the source field is empty or null (first run), the placeholder resolves to empty string.
