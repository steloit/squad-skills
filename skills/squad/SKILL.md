---
name: squad
description: Manage tasks on the Squad board — task CRUD (add, edit, move, complete, cancel, reopen, remove), board viewing, session context, project metadata, and statistics. Use for /squad commands and whenever the user asks to see, create, or update squad board tasks or projects. For pipeline execution use /squad-run; for requirements refinement use /squad-refine; run /squad-init once to register a project.
license: MIT
---

> Bootstrap + config + error rules: `shared.md`. Safety principles: `principles.md`. Endpoint details beyond the commands below: `references/api.md`; epics/dependencies: `references/epics.md`.

```bash
api()  { python3 ../squad/scripts/api.py "$@"; }
pipe() { python3 ../squad/scripts/pipeline.py "$@"; }
```

## Commands

### `/squad` or `/squad list` — View board

`api GET /board?summary=true` → markdown table (ID, Status, Priority, Title). Group epic children under their epic using the response's `epics` aggregate + embedded `parent`/`children` edges (never tag parsing); show each epic's `children_progress` (e.g. `2/5 done`).

### `/squad context` — Session handoff

Run first in a new session. `api GET /board?summary=true` → output pipeline state: Implementing / Plan Review / Impl Review / Testing / Recently Done / Next Todo.

### `/squad add <title>` — Add task

1. AskUserQuestion: priority, level (L1/L2/L3), description, tags.
2. Build the body with `jq -n --arg` (board text is data — see shared.md → JSON safety); `tags` must be a JSON array (`split(",") | map(gsub("^ +| +$";""))`; none → omit). `api POST /task --json "$BODY"` → capture the id.
3. Image file path(s) given → upload each via the attachment API (`references/api.md` → Attachments) and output the returned url(s). Pasted image without a path → ask the user to save it to a file first.

### `/squad move <ID> <status>` — Move task

```bash
pipe move $ID $STATUS   # validated; self-corrects once from the server's allowed[]; surfaces failure
```

### `/squad edit <ID>` — Edit task

Ask which fields, then `api PATCH /task/$ID --json "$BODY"`. Attach images via the attachment API.

### `/squad complete <ID> [note]` · `/squad cancel <ID> [reason]` — Terminal actions (non-interactive — just do it)

```bash
api POST /task/$ID/complete --json "$([ -n "$NOTE" ] && jq -n --arg n "$NOTE" '{completion_note:$n}' || echo '{}')"
api POST /task/$ID/cancel   --json "$([ -n "$REASON" ] && jq -n --arg r "$REASON" '{cancel_reason:$r}' || echo '{}')"
```

Complete = finished; cancel = won't-do (the preferred abandon verb). Both history-preserving and reversible via reopen; re-running on the same terminal state is a no-op; complete on a cancelled card → 409 (reopen first).

### `/squad reopen <ID>` — Un-cancel / un-complete

```bash
api POST /task/$ID/reopen --json '{"reason": "<why>"}'   # done|cancelled → todo; non-terminal → 409
```

### `/squad remove <ID>` — Delete (irreversible)

`api DELETE /task/$ID` — hard delete including attachments. Reserve for never-started mistakes/duplicates; otherwise prefer cancel.

### `/squad stats` — Statistics

```bash
python3 ../squad/scripts/stats.py   # column counts + per-actor token usage (one aggregate call, no per-task loop)
```

### `/squad project [all|brief|update|link]` — Project context

```bash
api GET /projects/$PROJECT      # /squad project — purpose, stack, brief, category, task counts, links (not registered → suggest /squad-init)
api GET /projects               # /squad project all — grouped by category
api GET /projects/$PROJECT | jq -r '.brief // "No brief set"'          # brief view
api PATCH /projects/$PROJECT --json '{"brief": "..."}'                 # brief set (200–500 chars)
api PATCH /projects/$PROJECT --json '{"<field>": "<value>"}'           # update: name, purpose, stack, brief, status, category, repo_url
api POST   /projects/$PROJECT/links --json '{"target_id": "other", "relation": "depends_on"}'   # link add
api DELETE /projects/$PROJECT/links --json '{"target_id": "other", "relation": "depends_on"}'   # link remove
```

`/squad project brief update` (AI-assisted): fetch project + recent done tasks (`api GET /board?summary=true`), draft a 200–500 char brief (current state + direction + recent decisions), confirm with the user, PATCH.

### `/squad observe status|dry-run` — Observation consent (read-only)

```bash
python3 ../squad/scripts/observe.py status    # effective on/off + deciding source (--json for the object)
python3 ../squad/scripts/observe.py dry-run   # the would-be payload; writes nothing
```

Opt-in/out lives in the web app (Settings → Observation & Consent) — there is no grant/withdraw here. Details: `references/observation.md`.

## Setup & web board

`/squad-init` registers the project (writes `.squadrc` with `SQUAD_PROJECT=` + `SQUAD_ORG=`, committed). The token is a Personal Access Token resolved per shared.md — never stored in the repo. Board UI: `https://squad.steloit.com/?project=<PROJECT>` (7-column pipeline, drag-and-drop, card modal, agent log viewer).
