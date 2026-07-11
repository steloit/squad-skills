# Board API Reference

All calls go through `api` (see `shared.md`). Paths are the resource AFTER the org prefix — `api.py` prepends `/api/orgs/<org>` and merges `project=`.

## Tasks

```bash
api GET /board                      # full board (heavy — task detail views only)
api GET /board?summary=true         # summary: object keyed by status, arrays of cards; excludes large TEXT fields
api GET /task/$ID                   # full task (embeds activity + comments arrays)
api GET /task/$ID?fields=title,plan # projected read (id, project, status always included; does NOT embed activity)
api PATCH /task/$ID --json '{"plan": "...", "status": "plan_review"}'
api POST /task --json '{"title": "...", "project": "'$PROJECT'", "priority": "medium", "level": 3, "description": "..."}'
api DELETE /task/$ID                # hard delete — irreversible
api PATCH /task/$ID/reorder --json '{"status": "plan", "after_id": null, "before_id": null}'
```

`tags` is a JSON array on create/update. `card_type ∈ {task, epic}` (default `task`).

## Lifecycle actions

```bash
api POST /task/$ID/complete --json '{"completion_note": "..."}'  # any non-terminal → done; note optional ({} ok)
api POST /task/$ID/cancel   --json '{"cancel_reason": "..."}'    # any status → cancelled; reason optional
api POST /task/$ID/reopen   --json '{"reason": "..."}'           # done OR cancelled → todo
```

- Complete/cancel are history-preserving and reversible via reopen; re-completing done / re-cancelling cancelled is a safe no-op. Complete on a cancelled target → 409 (reopen first). Reopen on a non-terminal → 409.
- Complete records `completed_via:"admin"` (vs `"pipeline"` for a gated finalize, `"rollup"` for epic auto-complete). Reopen clears lifecycle timestamps, `current_agent`, `cancel_reason`, `completion_note`, `completed_via`; prior work is preserved.

## Verdicts (record-only — they never change status)

Each POST appends to its verdict array, bumps `version`, and returns the recorded verdict. The orchestrator reads the verdict and issues any move separately.

```bash
api POST /task/$ID/plan-review --json '{"reviewer": "Critic", "model": "...", "status": "approved|changes_requested", "comment": "...", "correlation_id": "..."}'
api POST /task/$ID/review      --json '{"reviewer": "Inspector", "model": "...", "status": "approved|changes_requested", "comment": "...", "correlation_id": "..."}'
api POST /task/$ID/test-result --json '{"tester": "Ranger", "model": "...", "status": "pass|fail", "lint": "...", "build": "...", "tests": "...", "comment": "...", "correlation_id": "..."}'
# Human gate-override (ELEVATED: needs the task:override-review scope; reason REQUIRED — omit/empty → 400; a 403 must be surfaced):
api POST /task/$ID/override-review --json '{"gate": "impl_review", "reason": "...", "expected_version": 7, "correlation_id": "..."}'
```

The override appends a superseding `changes_requested`/`fail` verdict that flips the derived `last_*_status`; the orchestrator then computes the backward reject-loop move from the flipped verdict. Attribution is delegation, not impersonation: the decision is the human's (`actor_kind=human`), stamped server-side with `executed_by=<PAT>` + `on_behalf_of=<owner>` even when relayed over the run's user-scoped PAT.

Derived read-only fields on a task GET give the latest verdict per stage: `last_plan_review_status` (`approved|changes_requested|null`), `last_review_status` (same), `last_test_status` (`pass|fail|null`). Read these — never parse the comment arrays. (Board summary carries only the two review fields, not `last_test_status`.)

## Activity & comments

Two append-only channels: **activity** = machine events (skills write here, immutable); **comments** = human channel (**skills never write it**).

```bash
api POST /task/$ID/activity --json '{"actor": "Orchestrator", "model": "system", "message": "...", "tokens": 25000, "correlation_id": "..."}'
api GET /task/$ID/activity?limit=50          # chronological; ?before=<id> paginates
api GET /activity/stats                      # per-actor {actor, model, events, tokens, reported} + totals — ONE call, no per-task loop
```

- `actor`, `model`, `message` required non-empty; `tokens` optional finite number (omit when unknown, never null); server sets `created_at`.
- Actor vocabulary: agent nicknames (`Planner`/`Critic`/`Builder`/`Shield`/`Inspector`/`Ranger`), `Refiner`, `Orchestrator` (skill-level events, model `system`), `Heartbeat`.
- `correlation_id` (optional uuid) groups a step's verdict write + activity event into one timeline entry. squad-run threads one fresh id per agent step; squad-refine mints one id at save and threads it through the `POST /task/:id/spec` write AND its Refiner activity note.
- Stats: per-actor `tokens` is `number | null` (null = unreported — render as unknown, never 0); `reported` = the count of that actor's events carrying a token figure; `totals.tokens` stays a plain coalesced number.

## Optimistic concurrency

Every task carries an integer `version` (also returned as a strong ETag). Conditional write: include `"expected_version": <n>` in a PATCH body — mismatch → **412** `{"error": "...", "currentVersion": <n>}`, nothing written; re-read and retry. Omit for unconditional writes. A successful PATCH returns `{"success":true,"version":<n+1>}` (a bare same-status no-op PATCH returns the full row instead).

## Attachments (images: png, jpg/jpeg, gif, webp, svg)

```bash
DATA=$(base64 < "$IMG_PATH" | tr -d '\n')
api POST /task/$ID/attachment --json "$(jq -n --arg filename "$(basename "$IMG_PATH")" --arg data "$DATA" '{filename: $filename, data: $data}')"
api GET /task/$ID/attachment           # array of {filename, stored_name, url, size, uploaded_at}
api DELETE /task/$ID/attachment/$STORED_NAME
# Download (presigned urls are self-authenticating + short-TTL; re-list if stale):
DIR="${TMPDIR:-/tmp}/squad-attachments/$ID"; mkdir -p "$DIR"
api GET /task/$ID/attachment | jq -r '.[] | "\(.url)\t\(.filename)"' \
  | while IFS=$'\t' read -r url fn; do curl -s "$url" -o "$DIR/$fn"; done
```

Viewing as an agent is host-dependent: Claude Code — download then `Read` the local file (renders as vision). Codex — pass `--image <path>` at launch or cite the url. Never assume an agent auto-sees an attachment.

## Projects

```bash
api GET /projects                    # all projects with links
api GET /projects/$PROJECT           # one project + task counts + links
api POST /projects --json '{"id": "my-project", "name": "...", "purpose": "...", "stack": "...", "category": "personal"}'
api PATCH /projects/$PROJECT --json '{"brief": "..."}'   # fields: name, purpose, stack, brief, status, category, repo_url
api DELETE /projects/$PROJECT
api POST /projects/$PROJECT/links --json '{"target_id": "other", "relation": "depends_on"}'   # relations: extends, serves, depends_on, shares_data
api DELETE /projects/$PROJECT/links --json '{"target_id": "other", "relation": "depends_on"}'
```

For full column-level schema see `schema.md`.
