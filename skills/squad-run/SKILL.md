---
name: squad-run
description: 'Run the AI team pipeline for squad tasks — orchestration loop with 6 agents (Planner, Critic, Builder, Shield, Inspector, Ranger), single-step execution, and code review. Use /squad-run to execute tasks through the 7-column pipeline. AUTO-TRIGGER when: user says "implement task NNN" or any task ID + implement/build/do combination; or user confirms with "yes/ok/go/do it" after Claude proposes implementing a specific squad task.'
license: MIT
---

## Auto-Trigger Rules

**ALWAYS invoke this skill (without waiting for `/squad-run`) when:**

1. User mentions a squad task ID and requests implementation:
   - "implement task #NNN" / "build task NNN" / "do NNN" / "run NNN"
   - Any message pairing a task number with implement / build / work on / do

2. Claude has proposed implementing a specific squad task and the user confirms:
   - Pattern: Claude says "Shall I implement task #NNN [title]?" → User replies "yes", "ok", "go", "do it"
   - This confirmation **must** trigger `/squad-run <ID>` automatically — do not implement manually

3. User says "next task" / "continue" when a task is in progress:
   - Fetch board context first, identify next todo task, then run it

**When auto-triggered**: extract task ID and call `/squad-run <ID>` — never implement code manually and patch squad state afterward.

> Shared context: read `../squad/shared.md` for pipeline levels, status transitions, API endpoints, error handling, and agent context flow.
> Safety principles: read `../squad/principles.md` — **mandatory, not optional.**
> Schema: read `../squad/schema.md` for full DB schema, column descriptions, and JSON field formats.

## Commands

In Codex environments, this skill may be invoked directly as a slash command text such as `$squad-run <ID>` or `$squad-run <ID> --auto`.

### `/squad-run step <ID>` — Single Step

Execute only the next pipeline step then exit. Same logic as `/squad-run` but no loop.

### `/squad-run <ID> [--auto]` — Run Full Pipeline

**Default**: pause for user confirmation at Plan Review and Impl Review approvals.
**`--auto`**: fully automatic (circuit breaker still fires).

#### Orchestration Loop (Level-Aware)

```
Per-step contract (every agent step): record → gate → commit → side-effects.
The agent records its verdict (approved/reject | pass/fail + comment) by POSTing the matching
verdict endpoint; it does NOT move status. The orchestrator then: (1) reads the recorded
verdict, (2) gates (default mode: the card SITS in its review state until the user signal;
`--auto` skips the human gate only), (3) commits the move via the generic `PATCH /api/task/:id`
to the verdict-correct next status with `current_agent:null` and `actor:"Orchestrator"` (re-issuing a move that is already
applied is a safe no-op), (4) runs side-effects (git commit + note) AFTER the move.

L1 Quick:
  todo → orchestrator PATCH {status:impl, current_agent:Builder, actor:Orchestrator} → Worker(builder) implements
       → orchestrator PATCH {status:done, current_agent:null, actor:Orchestrator} → side-effects (commit + note)

L2 Standard:
  todo → [orchestrator: todo→plan, current_agent=Planner, actor:Orchestrator] → Plan Agent(planner) @plan
       → orchestrator PATCH {status:impl, current_agent:null, actor:Orchestrator} (skip plan_review)
  impl → Worker(builder) + TDD Tester(shield) → orchestrator PATCH {status:impl_review, current_agent:null, actor:Orchestrator}
  impl_review → Inspector returns verdict → orchestrator records → [user confirm] →
                orchestrator PATCH {status: done | impl, current_agent:null, actor:Orchestrator} → side-effects after done

L3 Full:
  todo → [orchestrator: todo→plan, current_agent=Planner, actor:Orchestrator] → Plan Agent(planner) @plan
       → orchestrator PATCH {status:plan_review, current_agent:null, actor:Orchestrator}
  plan_review → Critic returns verdict → orchestrator records → [user confirm] →
                orchestrator PATCH {status: impl (approve) | plan (reject), current_agent:null, actor:Orchestrator}
                (reject re-dispatches Planner with <critic_feedback>; plan→plan re-entry is idempotent)
  impl → Worker(builder) + TDD Tester(shield) → orchestrator PATCH {status:impl_review, current_agent:null, actor:Orchestrator}
  impl_review → Inspector returns verdict → orchestrator records → [user confirm] →
                orchestrator PATCH {status: test (approve) | impl (reject), current_agent:null, actor:Orchestrator}
  test → Ranger returns verdict → orchestrator records → [gate] →
         orchestrator PATCH {status: done (pass) | impl (fail), current_agent:null, actor:Orchestrator} → side-effects after done

Circuit breaker: plan_review_count > 3 OR impl_review_count > 3 → stop, ask user
  (counts are incremented when a verdict is recorded, not by the move PATCH)
```

Read the task's `level` field first to determine which steps to execute.

#### Model Routing (Provider-Aware)

Resolve real model names from `../squad/models.json` using provider:

- `SQUAD_MODEL_PROVIDER` env var if set (`claude` or `codex`)
- else `codex` when `CODEX_*` env is present
- else `claude` when `CLAUDE_*` env is present
- else `claude` when `.claude/` exists
- else `codex` when `.codex/` exists
- else `default_provider` from `models.json`

For Codex, the router should prefer the higher-capability entries in `models.json` for the full `squad-run` pipeline.

First resolve `MODEL_PROVIDER` and the `read_model` / `read_effort` helpers per `../squad/shared.md` → **Model Resolution**, then look up each agent's model:

```bash
MODEL_PLANNER=$(read_model planner)
MODEL_CRITIC=$(read_model critic)
MODEL_BUILDER=$(read_model builder)
MODEL_SHIELD=$(read_model shield)
MODEL_INSPECTOR=$(read_model inspector)
MODEL_RANGER=$(read_model ranger)
EFFORT_PLANNER=$(read_effort planner)
EFFORT_CRITIC=$(read_effort critic)
EFFORT_BUILDER=$(read_effort builder)
EFFORT_SHIELD=$(read_effort shield)
EFFORT_INSPECTOR=$(read_effort inspector)
EFFORT_RANGER=$(read_effort ranger)
```

#### Implementation

```bash
# 1. Read current task state (status + level + card_type).
# Stateless: re-read (status, level) every loop; NEVER cache status across a gate.
TASK=$(api GET /task/$ID?fields=status,level,card_type)
STATUS=$(echo "$TASK" | jq -r '.status')
LEVEL=$(echo "$TASK" | jq -r '.level')
CARD_TYPE=$(echo "$TASK" | jq -r '.card_type // "task"')

# 1a. Pipeline-exclusion: an epic is a CONTAINER, not runnable. Refuse and list its children.
#     (See ../squad/shared.md → Task Relationships & Epics.)
if [ "$CARD_TYPE" = "epic" ]; then
  REL=$(api GET /task/$ID/relationships)
  KIDS=$(echo "$REL" | jq -r '(.children // []) | if length == 0 then "(no children yet)" else (.[] | "  #\(.id) \(.title) [\(.status)]") end')
  PROG=$(echo "$REL" | jq -r '"\(.children_progress.done)/\(.children_progress.total)"')
  echo "Epic #$ID is a container — run its children ($PROG done):"
  echo "$KIDS"
  exit 0   # abort before dispatch
fi

# 1a-bis. Cancelled is a TERMINAL status — not runnable. Refuse before dispatch; reopen to run.
#         (See ../squad/shared.md → Move Protocol: cancelled is reachable from any status and is
#          left only via POST /task/:id/reopen — cancelled → todo.)
if [ "$STATUS" = "cancelled" ]; then
  echo "Task #$ID is cancelled (terminal) — reopen to run."
  exit 0   # abort before dispatch
fi

# 1a-ter. Done is a TERMINAL status — not runnable. Refuse before dispatch; reopen to re-run.
#         A `done` card is terminal regardless of HOW it got there — a gated pipeline finalize OR an
#         administrative POST /task/:id/complete both land on the same `done`, so one branch covers both.
#         (See ../squad/shared.md → Move Protocol: done has no forward transition; left only via reopen.)
if [ "$STATUS" = "done" ]; then
  echo "Task #$ID is done (terminal) — reopen to re-run."
  exit 0   # abort before dispatch
fi

# 1b. Sub-task readiness nudge (SOFT — NOT a block; the dep hard-block in ⓪ʙ takes precedence).
#     A `task` with incomplete .children → warn "usually run those first".
#     Default mode: AskUserQuestion confirm/cancel. --auto: proceed + log an Orchestrator activity note.
REL=$(api GET /task/$ID/relationships)
OPEN_KIDS=$(echo "$REL" | jq -r '[(.children // [])[] | select(.status != "done" and .status != "cancelled")] | length')
if [ "$OPEN_KIDS" -gt 0 ]; then
  echo "Task #$ID has $OPEN_KIDS open sub-task(s) — usually run those first (nudge, not a block)."
  # --auto: proceed and log:
  #   POST /api/task/$ID/activity {actor:"Orchestrator", model:"system",
  #     message:"--auto proceeded past $OPEN_KIDS open sub-task(s)"}
  # default: AskUserQuestion confirm/cancel before dispatch.
fi

# The Planner's level-aware exit status — the orchestrator moves plan → $PLAN_NEXT after the
# Planner finishes: L3 → plan_review, L2 → impl. (L1 never reaches the Planner.)
if [ "$LEVEL" = "3" ]; then PLAN_NEXT=plan_review; else PLAN_NEXT=impl; fi

# 2. Pipeline-entry / dispatch (see Agent Dispatch below)
#    When STATUS == todo:
#      L1  → ONE PATCH {"status":"impl","current_agent":"Builder","actor":"Orchestrator"}, then dispatch Builder.
#      L2/L3 → ONE PATCH {"status":"plan","current_agent":"Planner","actor":"Orchestrator"} (the todo→plan entry
#              move), then dispatch the Planner. The card is in the PLAN column before the
#              Planner begins — step ② below is this same single level-aware entry PATCH.
#    When STATUS == plan (fresh entry OR Critic-reject re-entry via plan_review→plan):
#      dispatch the Planner WITHOUT re-moving status. plan→plan is not a legal transition
#      and MUST NOT be attempted (idempotent re-entry). Set current_agent:"Planner" only.
#    All other statuses: dispatch the column's agent (see Agent Dispatch table).
# 3. After agent: append one activity event via POST /activity (see schema.md for format)
# 4. The agent records its verdict; orchestrator READS it → GATE (default) → COMMIT move
#    (generic PATCH, current_agent:null) → SIDE-EFFECTS (git commit + note, only after a done commit).
#    See "Per-Step Transition Contract" below for the full ordering + mapping.
# 5. Re-read state, loop until done or circuit breaker
```

#### SQD-936 observation gate-seam (consent before any `user_steering` emit)

Before the orchestrator emits any `user_steering` observation event it MUST pass the **consent gate** — `../squad/scripts/observe.py` (read-only; see `../squad/shared.md` → **Observation & Consent**). Resolve it **ONCE at run start** and cache the exit code for the whole run (observe.py is stateless — one `GET /consent` per call):

```bash
# Resolve once per run; cache the decision. 0 = emit, non-zero = skip (no parsing).
python3 ../squad/scripts/observe.py gate >/dev/null 2>&1; OBSERVE_OK=$?
# … later, per correction, reuse the cached decision — do NOT re-resolve:
#   [ "$OBSERVE_OK" = 0 ] && <emit user_steering>   # else skip
```

Local kill-switches (`DO_NOT_TRACK` / `SQUAD_OBSERVE_DISABLED` / `CI`) hard-off the gate with no network; otherwise it reads server consent and **fails closed** on any error. A mid-run web opt-out takes effect on the **next** run; any straggler emit is 403'd server-side (SQD-937). The emission itself is SQD-936; this gate is the seam it calls.

#### Per-Step Transition Contract (orchestrator owns every move)

The orchestrator — never the agent — issues every status transition. Each agent step runs
in strict order:

1. **Record** — the agent does its work, writes its output fields, and records
   its verdict (approved/reject | pass/fail + comment) by POSTing the matching verdict endpoint
   (Critic → `/plan-review`, Inspector → `/review`, Ranger → `/test-result`). The agent does NOT
   change status.
2. **Read** — the orchestrator reads the server-derived `last_plan_review_status` /
   `last_review_status` / `last_test_status` field for the current stage. The next status is computed
   locally from the verdict (table below) — never from a `newStatus` in the POST response.
3. **Gate** (default mode) — `AskUserQuestion` accept/reject runs BEFORE the move. `--auto` skips
   the human prompt but still issues the move.
4. **Commit** — the orchestrator issues the single validated generic `PATCH /api/task/:id` to the
   next status with `current_agent:null` and `actor:"Orchestrator"`.
5. **Side-effects** — git commit + commit note, only AFTER a `done` move is committed.

**Read the verdict** — the server-derived status for the current review stage:

```bash
# The orchestrator reads the server-derived verdict for the current review stage:
#   plan_review → last_plan_review_status · impl_review → last_review_status · test → last_test_status
case "$STATUS" in
  plan_review) VFIELD=last_plan_review_status ;;
  impl_review) VFIELD=last_review_status ;;
  test)        VFIELD=last_test_status ;;
esac
VERDICT=$(api GET /task/$ID?fields=$VFIELD \
  | VFIELD="$VFIELD" python3 -c "import sys,json,os; print(json.load(sys.stdin).get(os.environ['VFIELD']) or '')")
```

**Verdict → next status** (computed locally; mirrors `getTransitions`). Every row is issued via the
single validated generic PATCH `{status:<next>, current_agent:null, actor:"Orchestrator"}`. The verdict is the literal value
read from the derived field — reviews are `approved` / `changes_requested`, the test stage is `pass` / `fail`:

| Agent @ status | Verdict | Generic PATCH move |
|---|---|---|
| Planner @ plan | (done) | L3 → plan_review · L2 → impl |
| Critic @ plan_review | approved / changes_requested | impl / plan |
| Builder+Shield @ impl | (both done) | impl_review |
| Inspector @ impl_review | approved / changes_requested | (L2 → done · L3 → test) / impl |
| Ranger @ test | pass / fail | done / impl |
| done finalize | — | done |

Reject loops (plan_review→plan, impl_review→impl, test→impl) re-dispatch the column's agent; a
`plan→plan` re-entry sets `current_agent` only (no illegal status move). Re-issuing a move that is
already applied is a safe no-op.

**Human gate-override write-through (default mode, SQD-958).** At the step-3 gate a human may
**reject** — *including after the agent recorded `approved`* (the derived `$VERDICT` still reads
`approved`, so the table above would compute a FORWARD move). The human's send-back is not a
terminal-scrollback note: it is recorded SERVER-SIDE as a durable, attributable override BEFORE the
move. On a human reject (default mode only — `--auto` never rejects), record the override, then
**re-read** the now-flipped `$VERDICT` and fall through to the SAME verdict→move table — which now
computes the backward move SQD-955 made legal (`plan_review→plan` / `impl_review→impl` / `test→impl`):

```bash
# Runs ONLY when the human REJECTS at the step-3 AskUserQuestion gate (incl. post-`approved`).
# $STATUS = the review stage (= the override `gate`); $VFIELD/$CID as set above.
if [ "$GATE_DECISION" = reject ]; then
  # 1. Mandatory reason — a follow-up AskUserQuestion / free-text. Empty reason ⇒ server 400,
  #    so re-prompt until non-empty (mirrors the GitHub mandatory dismiss-reason).
  REASON="<the human's reason — required, non-empty>"
  # 2. Current version (optimistic-concurrency guard against a concurrent override).
  VER=$(api GET /task/$ID?fields=version | jq -r '.version')
  # 3. Record the SUPERSEDING override over the run's user-scoped PAT. The server stamps
  #    executed_by=<PAT> + on_behalf_of=<owner>; the body carries actor_kind=human (delegation,
  #    not impersonation). Record-only: it flips last_*_status, never moves status.
  ERR=$(mktemp)
  api POST /task/$ID/override-review \
    --json "{\"gate\": \"$STATUS\", \"reason\": \"$REASON\", \"expected_version\": $VER, \"correlation_id\": \"$CID\"}" 2>"$ERR"
  RC=$?   # 4 = 4xx (403 missing task:override-review scope · 400 empty reason · 409 stale version)
  if [ "$RC" -ne 0 ]; then
    # SURFACE the failure to the user — a 403 means the run PAT lacks the elevated
    # task:override-review scope. NEVER silently downgrade to a fix-in-place (the SQD-957
    # anti-pattern this card fixes); the server record is the single source of truth.
    echo "ERROR: could not record human override on $ID (exit $RC): $(grep -v '^ERROR:' "$ERR" 2>/dev/null || cat "$ERR")"
    rm -f "$ERR"
    return 1 2>/dev/null || exit 1   # halt the gate; do not move, do not fix in place
  fi
  rm -f "$ERR"
  # 4. Re-read the now-flipped derived verdict; fall through to the verdict→move table above
  #    (it now computes the backward reject move). The user_steering emit below also fires.
  VERDICT=$(api GET /task/$ID?fields=$VFIELD \
    | VFIELD="$VFIELD" python3 -c "import sys,json,os; print(json.load(sys.stdin).get(os.environ['VFIELD']) or '')")
fi
```

**Emit `user_steering` on a correction (SQD-936).** When a review verdict is a **reject** (Critic
`changes_requested`→plan, Inspector `changes_requested`→impl, Ranger `fail`→impl) — or, in default
mode, the human rejects at the `AskUserQuestion` gate (step 3) — emit ONE abstracted `user_steering`
event, gated by the cached `OBSERVE_OK` from the run-start seam (above) and BEST-EFFORT (`|| true`).
Enums come from the gate per `../squad/shared.md` → **Abstraction Rubric** (the per-gate mapping
table); the `--comment` is an abstracted pattern (leak-filtered → `(redacted)` on any hit). Use the
step's `correlation_id` so the event threads with the step. Routine **approvals emit nothing**; a
reject-loop re-dispatch is a NEW occurrence (fresh `correlation_id`), not a duplicate.

```bash
# After reading $VERDICT (and before/with the reject move). $CID = the step's correlation_id.
if [ "$OBSERVE_OK" = 0 ]; then
  case "$STATUS:$VERDICT" in
    plan_review:changes_requested)
      python3 ../squad/scripts/observe.py emit "$ID" --modality evaluative --valence negative \
        --target planning --severity moderate --attributability violated_constraint \
        --comment "rejected the plan" --correlation-id "$CID" || true ;;
    impl_review:changes_requested)
      python3 ../squad/scripts/observe.py emit "$ID" --modality evaluative --valence negative \
        --target verification --severity moderate --attributability violated_constraint \
        --comment "requested implementation changes" --correlation-id "$CID" || true ;;
    test:fail)
      python3 ../squad/scripts/observe.py emit "$ID" --modality evaluative --valence negative \
        --target verification --severity major --attributability violated_constraint \
        --comment "tests failed" --correlation-id "$CID" || true ;;
  esac
fi
```

#### Agent Nicknames & Identity

Each agent has a fixed **nickname** used consistently across all records. The task card becomes a work log — every field and every log entry is signed.

| Nickname | Role | Model Key | Reasoning Effort (codex) | Status trigger |
|----------|------|-------|---------------------------|----------------|
| `Planner` | Plan Agent | `planner` | `high` | `plan` |
| `Critic` | Plan Review Agent | `critic` | `medium` | `plan_review` |
| `Builder` | Worker Agent | `builder` | `high` | `impl` (step 1) |
| `Shield` | TDD Tester | `shield` | `medium` | `impl` (step 2) |
| `Inspector` | Code Review Agent | `inspector` | `medium` | `impl_review` |
| `Ranger` | Test Runner | `ranger` | `medium` | `test` |

> See `../squad/schema.md` for JSON formats and the Signature Header Rule.

#### Agent Dispatch

Template files are at `../squad/templates/`.

| Status | Template | Nickname | Model Key |
|--------|----------|----------|-------|
| `plan` | `templates/plan-agent.md` | `Planner` | `planner` |
| `plan_review` | `templates/review-agent.md` | `Critic` | `critic` |
| `impl` step 1 | `templates/worker-agent.md` | `Builder` | `builder` |
| `impl` step 2 | `templates/tdd-tester.md` | `Shield` | `shield` |
| `impl_review` | `templates/code-review-agent.md` | `Inspector` | `inspector` |
| `test` | `templates/test-runner.md` | `Ranger` | `ranger` |

**Agent minimum fields (fetch only what each agent needs):**

| Nickname | Required Fields |
|----------|----------------|
| `Planner` | `title,description,spec,plan_review_comments` |
| `Critic` | `title,description,spec,plan,decision_log,done_when` |
| `Builder` | `title,description,spec,plan,done_when,plan_review_comments,review_comments` |
| `Shield` | `title,description,spec,implementation_notes` |
| `Inspector` | `title,description,spec,plan,done_when,implementation_notes` |
| `Ranger` | `title,implementation_notes` |

**Dispatch procedure — execute in this order for every agent:**

```
⓪ Fetch project brief (once per pipeline run, cache for all agents)
   PROJECT_DATA = api GET /projects/$PROJECT
   PROJECT_BRIEF = extract .brief field (empty string if null or project not found)
   This is injected into every agent template via <project_brief> placeholder.

⓪ʙ Resolve dependencies & review feedback (once per pipeline run, cache for all agents)

   **Resolve dependencies via the relationships API** (see `../squad/shared.md` → **Task Relationships & Epics**).
   The `blocks` dependency edges are read from `GET /api/task/:id/relationships` → `.blocked_by` — NOT
   text-parsed from the description. (The `Depends on:` text convention and the old dependencies
   endpoint are both retired — see `../squad/shared.md`.)
   ```bash
   # Read structured blocks edges; .blocked_by = the deps this task is blocked by.
   REL=$(api GET /task/$ID/relationships)
   DEP_IDS=$(echo "$REL" | jq -r '.blocked_by[]?.id')
   ```

   **Readiness gate (HARD BLOCK):**
   A dep is **resolved** when its status is `done` **or** `cancelled` (the two terminal statuses).
   If any `.blocked_by[].status` is not in `{done, cancelled}`, the task is not ready:
   - **Default mode**: `AskUserQuestion` — surface the incomplete dep(s) and confirm before proceeding.
   - **`--auto` mode**: refuse with `"blocked by incomplete dependency #N"` and abort the pipeline.
   This is the **hard block** and takes precedence over the soft sub-task nudge (① below).
   An **epic** used as a blocker is unblocked by `/complete`-ing it (→ `done`); readiness stays
   **status-based** — the derived epic `complete` rollup is display-only and does NOT satisfy a dep.
   The jq below is **unchanged** — `done` is already in the resolved set `{done, cancelled}`.
   ```bash
   BLOCKERS=$(echo "$REL" | jq -r '.blocked_by[]? | select(.status != "done" and .status != "cancelled") | "#\(.id) (\(.status))"')
   if [ -n "$BLOCKERS" ]; then
     # --auto: refuse + abort. default: AskUserQuestion confirm/cancel.
     echo "blocked by incomplete dependency $BLOCKERS"
   fi
   ```

   > No client-side circular-dependency check. The server enforces acyclicity at write time
   > (in-transaction CTE) and returns **409** on a cycling `POST /relationships`; that 409 is surfaced
   > from the write path (in declaration skills), never pre-validated here.

   **Fetch per-dep context** (for cached injection): for each id in `DEP_IDS`, fetch the context fields.
   A `404` warns + skips that dep and continues.
   ```bash
   for DEP_ID in $DEP_IDS; do
     DEP_TASK=$(api GET /task/$DEP_ID?fields=title,status,decision_log,implementation_notes)
     if [ -z "$(echo "$DEP_TASK" | jq -r '.id // empty')" ]; then
       echo "WARNING: dependency #$DEP_ID not found (404), skipping"
       continue
     fi
     # Cache: DEPS[$DEP_ID] = { title, status, decision_log, implementation_notes }
   done
   ```

   **Build per-agent dependency context string:**
   For each cached dependency, assemble context based on the current agent:

   - **Planner**: `decision_log` (500 chars) + `implementation_notes` (500 chars)
   - **Builder**: `implementation_notes` (500 chars)
   - **Inspector**: `decision_log` (300 chars)

   Truncation: if field length > limit, take first N chars + `...[truncated]`.
   If dep status is not in `{done, cancelled}`: prepend `[IN PROGRESS]` warning to that dep's block.
   A `done` **OR** `cancelled` dep is resolved — no `[IN PROGRESS]` marker.
   If no dependencies: `DEPS_CONTEXT=""` (empty string — placeholder removed cleanly).

   Format per dependency:
   ```
   ### #<DEP_ID>: <title> [<status>]
   [IN PROGRESS]

   **Decision Log:**
   <truncated decision_log>

   **Implementation Notes:**
   <truncated implementation_notes>
   ```

   **Extract review feedback for re-runs:**
   ```bash
   # Critic feedback (for Planner re-run)
   CRITIC_FEEDBACK=""
   PLAN_REVIEW_COMMENTS=$(echo "$TASK" | jq -r '.plan_review_comments // ""')
   if [ -n "$PLAN_REVIEW_COMMENTS" ] && [ "$PLAN_REVIEW_COMMENTS" != "null" ]; then
     CRITIC_FEEDBACK=$(echo "$PLAN_REVIEW_COMMENTS" | python3 -c "
   import sys, json
   data = json.load(sys.stdin)
   if isinstance(data, list) and len(data) > 0:
     print(data[-1].get('comment', ''))
   ")
   fi

   # Inspector feedback (for Builder re-run)
   INSPECTOR_FEEDBACK=""
   REVIEW_COMMENTS=$(echo "$TASK" | jq -r '.review_comments // ""')
   if [ -n "$REVIEW_COMMENTS" ] && [ "$REVIEW_COMMENTS" != "null" ]; then
     INSPECTOR_FEEDBACK=$(echo "$REVIEW_COMMENTS" | python3 -c "
   import sys, json
   data = json.load(sys.stdin)
   if isinstance(data, list) and len(data) > 0:
     print(data[-1].get('comment', ''))
   ")
   fi
   ```

① Read task fields (use per-agent fields to minimize token usage)
   # Planner
   TASK = api GET /task/$ID?fields=title,description,spec,plan_review_comments
   # Critic
   TASK = api GET /task/$ID?fields=title,description,spec,plan,decision_log,done_when
   # Builder
   TASK = api GET /task/$ID?fields=title,description,spec,plan,done_when,plan_review_comments,review_comments
   # Shield
   TASK = api GET /task/$ID?fields=title,description,spec,implementation_notes
   # Inspector
   TASK = api GET /task/$ID?fields=title,description,spec,plan,done_when,implementation_notes
   # Ranger
   TASK = api GET /task/$ID?fields=title,implementation_notes
   Extract only the fields listed above for each agent

② Enter the agent's column + mark it active — ONE level-aware PATCH
   Mint a FRESH per-step correlation id for THIS dispatch occurrence — never cache or
   reuse one across the loop. Every dispatch gets a new id, including every reject
   re-dispatch (plan_review→plan, impl_review→impl, test→impl): each occurrence is a
   distinct step and gets its own id.
   ```bash
   CORRELATION_ID=$(python3 -c 'import uuid;print(uuid.uuid4())')
   ```
   This SAME `$CORRELATION_ID` is threaded into BOTH the agent template (step ④,
   `--set correlation_id=`) AND the orchestrator's activity POST for this step (step ⑥),
   so the board groups the step's record-results write + the agent_log into one timeline
   entry. (For the impl step, Builder and Shield are two writes within one logical step —
   the single impl-step `$CORRELATION_ID` covers the Builder PATCH, the Shield PATCH, and
   the orchestrator's impl-step activity event.)

   The entry status move and current_agent assignment are a SINGLE PATCH (never a
   separate/third call). Pick the body by the agent being dispatched:
     • Planner from `todo` (L1): not applicable — L1 dispatches Builder, see below.
     • Planner from `todo` (L2/L3):  { "status": "plan", "current_agent": "Planner", "actor": "Orchestrator" }
     • Builder from `todo` (L1):     { "status": "impl", "current_agent": "Builder", "actor": "Orchestrator" }
     • Planner already at `plan` (fresh entry handled above, OR Critic-reject
       re-entry via plan_review→plan):  { "current_agent": "Planner" }  (NO status move —
       plan→plan is illegal; idempotent re-dispatch)
     • Any agent already in its own column (Critic@plan_review, Inspector@impl_review,
       Ranger@test, Shield@impl): { "current_agent": "<Nickname>" }  (no status change)
   api PATCH /task/$ID --json <body above>

③ Read template file
   Read tool: ../squad/templates/<agent>.md

④ Fill placeholders in template
   Replace every occurrence of:
     <ID>                     → actual task ID
     <PROJECT>                → actual project name
     <project_brief>          → project brief from step ⓪ (empty string if not set)
     <title>                  → task title
     <description>            → task description (the human's original request)
     <spec>                   → rendered Refiner spec (Planner/Critic/Builder only): "## Refined Spec\n\n…" or "" if no spec (see SPEC_MD below)
     <plan>                   → plan field value
     <decision_log>           → decision_log field value
     <done_when>              → done_when field value
     <implementation_notes>   → implementation_notes field value
     <plan_review_comments>   → plan_review_comments field value
     <dependencies_context>   → per-agent dep context from step ⓪ʙ (empty string if none)
     <critic_feedback>        → latest plan_review_comments comment (empty if first run)
     <inspector_feedback>     → latest review_comments comment (empty if first run)
     <correlation_id>         → $CORRELATION_ID (the fresh per-step id minted in step ②)
     <TIMESTAMP>              → current UTC time (ISO 8601)
     <MODEL_PLANNER>          → $MODEL_PLANNER
     <MODEL_CRITIC>           → $MODEL_CRITIC
     <MODEL_BUILDER>          → $MODEL_BUILDER
     <MODEL_SHIELD>           → $MODEL_SHIELD
     <MODEL_INSPECTOR>        → $MODEL_INSPECTOR
     <MODEL_RANGER>           → $MODEL_RANGER
     <EFFORT_PLANNER>         → $EFFORT_PLANNER
     <EFFORT_CRITIC>          → $EFFORT_CRITIC
     <EFFORT_BUILDER>         → $EFFORT_BUILDER
     <EFFORT_SHIELD>          → $EFFORT_SHIELD
     <EFFORT_INSPECTOR>       → $EFFORT_INSPECTOR
     <EFFORT_RANGER>          → $EFFORT_RANGER

   **Spec render (Planner/Critic/Builder only)** — render the fetched `spec` JSON → markdown for
   `<spec>`. Empty string when the task has no spec (legacy/un-refined), so `<spec>` collapses
   cleanly and `## Original Request` (`<description>`) carries the requirements. (Inline python,
   mirrors the `CRITIC_FEEDBACK` pattern — no new script.)
   ```bash
   SPEC_MD=$(echo "$TASK" | python3 -c "
   import sys, json
   d = json.load(sys.stdin); spec = d.get('spec')
   if not spec: print('', end=''); sys.exit(0)
   out = ['## Refined Spec', '']
   if spec.get('goal'): out += ['**Goal:** ' + spec['goal'], '']
   reqs = spec.get('requirements') or []
   if reqs: out += ['**Requirements:**'] + ['- ' + r for r in reqs] + ['']
   qa = spec.get('qa') or []
   if qa:
       out += ['**Clarifications (Q&A):**']
       for it in qa:
           out += ['- Q: ' + (it.get('question') or '')]
           out += ['  A: ' + (it['answer'] if it.get('answer') is not None else '(unanswered)')]
   print('\n'.join(out).rstrip())
   ")
   # Planner/Critic/Builder + Shield/Inspector all consume the spec. Ranger does NOT
   # (mechanical lint/build/test only) → pass SPEC_MD="" for Ranger.
   ```

   Recommended helper script:
   ```bash
   PROMPT=$(python3 ../squad/scripts/render_agent_prompt.py \
     --template ../squad/templates/<agent>.md \
     --models ../squad/models.json \
     --provider "$MODEL_PROVIDER" \
     --set ID="$ID" \
     --set PROJECT="$PROJECT" \
     --set project_brief="$PROJECT_BRIEF" \
     --set title="$TITLE" \
     --set description="$DESCRIPTION" \
     --set spec="$SPEC_MD" \
     --set plan="$PLAN" \
     --set decision_log="$DECISION_LOG" \
     --set done_when="$DONE_WHEN" \
     --set implementation_notes="$IMPLEMENTATION_NOTES" \
     --set plan_review_comments="$PLAN_REVIEW_COMMENTS" \
     --set dependencies_context="$DEPS_CONTEXT" \
     --set critic_feedback="$CRITIC_FEEDBACK" \
     --set inspector_feedback="$INSPECTOR_FEEDBACK" \
     --set correlation_id="$CORRELATION_ID" \
     --set TIMESTAMP="$TIMESTAMP")
   ```
   If a field is missing, pass empty string (`--set key=""`).
   Use `--strict` only when every unresolved `<...>` token should be treated as an error.

⑤ Launch Task tool with filled prompt
   If MODEL_PROVIDER is `codex`:
   Task(
     subagent_type         = "general-purpose",
     model                 = "<resolved model from models.json>",
     model_reasoning_effort= "<resolved effort from models.json>",
     prompt                = <filled template content>
   )

   Otherwise (`claude`):
   Task(
     subagent_type = "general-purpose",
     model         = "<resolved model from models.json>",
     prompt        = <filled template content>
   )

⑥ After Task completes — append one signed activity event
   POST /api/task/$ID/activity {actor:<Nickname>, model:<model>, message:<summary>, tokens?:<est>, correlation_id:$CORRELATION_ID}
   (use schema.md › "Appending an event (orchestrator)" snippet — single atomic POST, no read-modify-write)
   `correlation_id` is the SAME `$CORRELATION_ID` minted in step ② and passed to the
   agent template in step ④ — the agent's record-results write and this activity event
   carry one id, so the board groups them into a single timeline entry for the step.
```

Builder and Shield each RETURN their output (no self-move). Once both complete, the orchestrator
issues the impl→impl_review **commit** move:
```bash
api PATCH /task/$ID --json '{"status": "impl_review", "current_agent": null, "actor": "Orchestrator"}'
```

**Default mode**: at `plan_review`, `impl_review`, and `test` (the L3 Ranger gate), the contract order is explicit — the agent
records its verdict → the orchestrator reads it → **gate** (`AskUserQuestion` accept/reject) →
the orchestrator COMMITS the move via the generic PATCH with `current_agent:null`. The gate
PRECEDES the move PATCH; the move is always the generic PATCH, never the verdict endpoint.
A human **reject** at the gate — *including after the agent recorded `approved`* — first records a
durable, attributable **override** (`POST /task/$ID/override-review`, mandatory `reason`) that flips
the derived verdict, THEN the normal read→move computes the backward send-back (SQD-958, above); a
403 (PAT lacks `task:override-review`) is surfaced to the user, never a silent fix-in-place.
**Auto mode (`--auto`)**: same order, but auto-accept at the gate (orchestrator still issues the move PATCH).

#### → Done Transition (all levels)

```bash
# 1. Move to done (single validated generic PATCH) — clears current_agent.
#    Re-issuing when already done is a safe no-op.
api PATCH /task/$ID --json '{"status": "done", "current_agent": null, "actor": "Orchestrator"}'

# 2. Side-effects AFTER the state commit — commit pending changes.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  git add -A
  git commit -m "feat: <TITLE> [squad #<ID>]"
fi
COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "no-git")

# 3. Record commit hash as an activity event (machine event, actor=Orchestrator/system)
SUBJECT=$(git log -1 --format=%s 2>/dev/null || echo "no-git")
BODY=$(jq -n --arg msg "Committed $COMMIT_HASH: $SUBJECT [squad #$ID]" \
  '{actor: "Orchestrator", model: "system", message: $msg}')
api POST /task/$ID/activity --json "$BODY"
```

If no commits yet, skip the event or record `message:"Committed (none) [squad #$ID]"`.

#### → Coach (friction review of this run)

Once the card is `done` and committed, dispatch the **Coach** per `../squad/shared.md` → **Coach Dispatch** (`MODEL_PROVIDER` + helpers are already resolved above in step ⑤). Pass:
- `skill_name` = `squad-run`
- `source_task` = `$ID`
- `run_summary` = `"squad-run pipeline completed task $ID to done."`
- `trajectory` = the task's activity events (all 6 agents, in order) + implementation_notes + review verdicts
- `friction_signals` = reject loops / circuit-breaker trips / agent retries recorded this pass; `none` if clean

### `/squad-run review <ID>` — Code Review

Trigger Code Review agent for a task in `impl_review` status (same as impl_review step).
