---
name: squad-refine
description: Refine backlog requirements through structured user interview. Turns rough task descriptions into concrete, actionable requirements with goal, scope, acceptance criteria, and edge cases.
license: MIT
---

> Shared context: read `../squad/shared.md` for pipeline levels, status transitions, API endpoints, error handling, and agent context flow.
> Safety principles: read `../squad/principles.md` — **mandatory, not optional.**

## `/squad-refine <ID>` — Refine Backlog Requirements

Reads a rough backlog item and refines it into concrete, actionable requirements through structured user interview.

**Target**: tasks in `todo` status (backlog). If the task is not `todo`, warn the user and confirm before proceeding.

### Procedure

```
① Read the task
   TASK = api GET /task/$ID
   Extract: title, description, priority, level, tags, card_type

   **Epic targets are containers** (`card_type:'epic'`): they hold child tasks, they are not runnable
   and have no acceptance-criteria/plan of their own. If the target is an epic, do NOT run the refine
   interview — point the user at its children (`GET /api/task/$ID/relationships` → `.children`) and stop.

   **Terminal targets are not runnable** (`status` is `cancelled` or `done`): a cancelled (or done)
   task is a non-runnable terminal — there is nothing to refine until it re-enters the pipeline. Do NOT
   run the interview; warn the user (e.g. `"Task #$ID is cancelled (terminal) — reopen it before refining"`)
   and point them at `POST /api/task/$ID/reopen` (which restores `cancelled`/`done` → `todo`), then stop.
   (A `done` target may have been reached via the gated pipeline OR an administrative
   `POST /api/task/$ID/complete`; both land on the same `done` terminal, so this one branch covers both.)
   An **epic** used as a blocker is unblocked by `/complete`-ing it (→ `done`); readiness is status-based,
   and the derived epic `complete` rollup is display-only (NOT a dependency-satisfaction signal).

① ½. Look for prior implementation context (always run this before the interview)

   a. Detect dependencies via the relationships API (NOT description text — the `Depends on:` convention
      is retired; see `../squad/shared.md` → **Task Relationships & Epics**):
      REL = api GET /task/$ID/relationships
      Dependency ids = `.blocked_by[].id`. Also check `.parent` for the containing epic.

   b. If a dependency found → fetch that card's implementation output:
      PRIOR = api GET /task/$NNN?fields=title,implementation_notes,plan
      Also inspect the actual codebase: read files, interfaces, schemas confirmed in that card.

   c. If no explicit dependency → ask ONE question before the main interview:
      "Is there a prior task whose implementation this builds on? (task ID or 'none')"
      If the user gives an ID, fetch it as in (b).
      If "none" or new work → skip, proceed with regular interview.

   d. Summarize what was confirmed from prior implementation:
      PRIOR_CONTEXT = {
        confirmed interfaces, schemas, file paths, component names, API routes, etc.
      }
      This context is injected into ③ (gap analysis) and ⑤ (description synthesis).

② Display current state
   Show the user their raw title + description as-is.
   If PRIOR_CONTEXT exists, also show: "Prior implementation context: [summary]"

③ Analyze for gaps
   Identify what's missing or vague across these dimensions:
   - WHAT: What exactly should be built/changed?
   - WHY: What problem does this solve? What's the motivation?
   - SCOPE: What's included vs excluded?
   - ACCEPTANCE: How do we know it's done?
   - CONSTRAINTS: Technical limitations, compatibility, performance?
   - EDGE CASES: Error states, boundary conditions?
   - DEPENDENCIES: Does it depend on other tasks or external systems?

④ Interview the user (MANDATORY)
   Use AskUserQuestion to ask about the gaps found in ③.
   Rules:
   - Ask 1–4 focused questions per round (AskUserQuestion limit)
   - Group related questions in one round
   - Run multiple rounds if needed (max 3 rounds)
   - Stop early if the user says "enough" or all gaps are filled
   - Don't ask about things that are already clear
   - Use concrete options when possible, not open-ended questions

⑤ Synthesize the refined SPEC
   Build a structured spec OBJECT — NOT a description rewrite. The human's original
   request stays in `description` and is NEVER overwritten; the refined spec is a
   separate first-class artifact (the `tasks.spec` shape). If PRIOR_CONTEXT exists,
   ground requirements in confirmed interfaces/file paths — not assumptions.

   The spec has three authored fields (the server assigns `version`):

   - goal:         1–2 sentences — what this task achieves and why.
   - requirements: string[] — the COMPLETE, testable set, each item a discrete
                   string. Describe WHAT, not HOW (no implementation hints/pseudo-code).
                   Use soft prefixes so intent is explicit (author convention, not
                   enforced by the API):
                     "REQ: …"                              core requirement
                     "AC: WHEN … THE SYSTEM SHALL …"       acceptance criterion (EARS)
                     "SCOPE(IN): …" / "SCOPE(OUT): …"      the in / "Not Included" boundary
                     "CONSTRAINT: …"                       technical constraint
                     "EDGE: …"                             edge case
   - qa:           {question, answer}[] — one entry per interview question asked in ④
                   (answer = the user's chosen value; null if a question went unanswered).

   Example:
   ```json
   {
     "goal": "Let admins invite members so teams can self-serve onboarding.",
     "requirements": [
       "REQ: An admin can send an invite by email from the members page.",
       "AC: WHEN an admin submits a valid email THE SYSTEM SHALL create an invite and email a signed link.",
       "SCOPE(OUT): bulk CSV invites are not included.",
       "EDGE: re-inviting an existing member returns 'already a member' without creating a duplicate."
     ],
     "qa": [{ "question": "Email or OAuth invites?", "answer": "Email only for v1" }]
   }
   ```

⑥ Present the refined SPEC to the user
   Show the spec in a readable form (goal, the requirements list, the Q&A).
   Ask user to confirm with AskUserQuestion:
   - "Approve & save" (write the spec)
   - "Edit more" (go back to interview)
   - "Cancel" (discard changes)

⑦ Save
   If approved:
   - **Mint ONE `correlation_id` for THIS save occasion**, before the spec write. The SAME
     value tags both the `/spec` write AND the Refiner `/activity` note below, so the board
     groups the spec snapshot + the Refiner note into one timeline stage. A re-refine is a
     new save → mint a fresh id (never cache/reuse it across saves; a re-refine = new id = a
     distinct grouped entry):
     ```bash
     CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')
     ```
   - **Write the SPEC via the dedicated endpoint** — the human `description` is NEVER touched.
     The CAS token is the TASK `version` (same token every write uses); read it immediately
     before writing. The endpoint writes `spec`, bumps `spec_version`, and emits the
     `kind='spec'` provenance row. `spec.version` is server-assigned, so omit it from the body.
     ```bash
     # Build the spec object from ⑤ (no `version` — the server stamps it).
     SPEC_JSON=$(jq -n --arg goal "$GOAL" \
       --argjson reqs "$REQUIREMENTS_JSON_ARRAY" --argjson qa "$QA_JSON_ARRAY" \
       '{goal:$goal, requirements:$reqs, qa:$qa}')
     VER=$(api GET /task/$ID?fields=version -q version)
     ERR=$(mktemp)
     RESP=$(api POST /task/$ID/spec \
       --json "$(jq -n --argjson spec "$SPEC_JSON" --argjson ev "$VER" --arg model "$MODEL_REFINER" --arg cid "$CORRELATION_ID" \
             '{spec:$spec, expected_version:$ev, actor:"Refiner", model:$model, correlation_id:$cid}')" 2>"$ERR")
     RC=$?
     # RC 0 → RESP = { success, version, spec_version }. RC 4 → board rejected: the stderr body
     # ($ERR) carries the board's 4xx — a 412 "Precondition failed" on a concurrent edit (re-read
     # `version` and retry ONCE; if it still 412s, surface to the user — don't loop) or a 400
     # malformed spec.
     # (On a 412 retry, KEEP the same $CORRELATION_ID — it's still the same save occasion.)
     rm -f "$ERR"
     ```
   - Update title/level/priority/tags ONLY if the interview changed them (PATCH — never `description`).
   - **Declare dependencies structurally**: if the interview surfaced that this task is blocked by
     another (#DEP), declare it via a `blocks` edge — NOT a `Depends on:` text line:
     ```bash
     # DEP blocks ID (ID is blocked_by DEP). `to` is an opaque <KEY>-<seq> id string — use --arg.
     # Server returns 409 on a cycle (surfaced, no pre-check).
     api POST /task/$DEP/relationships --json "$(jq -n --arg to "$ID" '{to:$to, type:"blocks"}')"
     ```
   - Append the short Refiner activity note (the `kind='spec'` row above carries the snapshot;
     this records the round count). Carry the SAME `$CORRELATION_ID` minted at the top of this
     step so the board threads this note with the spec snapshot into one timeline stage.
     POST /api/task/$ID/activity:
     { "actor": "Refiner", "model": "<MODEL_REFINER>", "message": "Requirements refined. N questions across M rounds.", "correlation_id": "$CORRELATION_ID" }
```

### Model Routing

Resolve `MODEL_PROVIDER` + the `read_model` helper per `../squad/shared.md` → **Model Resolution**, then:

```bash
MODEL_REFINER=$(read_model refiner)
```

### Coach (friction review of this run)

After step ⑦ Save completes (an approved refine), dispatch the **Coach** per `../squad/shared.md` → **Coach Dispatch** (reuse the Model Routing resolution above — `MODEL_PROVIDER` + helpers). Pass:
- `skill_name` = `squad-refine`
- `source_task` = `$ID`
- `run_summary` = `"squad-refine refined the requirements for task $ID."`
- `trajectory` = the interview Q/A rounds + the refined spec
- `friction_signals` = any board-API friction during the spec write (`POST /task/:id/spec`); `none` if clean

### Interview Tips

- If the user wrote "add login" → ask: OAuth/email? Session/JWT? Which pages need auth guards?
- If the user wrote "improve performance" → ask: Which page/API? Current latency? Target latency? Measurement method?
- If the user wrote "fix the UI" → ask: Which component? What's wrong now? Mockup/reference? Responsive?
- Prefer showing concrete options over open-ended "what do you want?"
