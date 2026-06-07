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
Per-step contract (every agent step): decide → record → gate → commit → side-effects.
The agent RETURNS a verdict (approved/reject | pass/fail + comment); it does NOT move
status and does NOT post its own verdict. The orchestrator: (1) records the verdict via
the record-only endpoint (#223: POST /plan-review|/review|/test-result — appends comment +
bumps the circuit-breaker count, NO status move), (2) gates (default mode: card SITS in its
review state until the user signal; --auto skips the human gate only), (3) commits the move
via the generic PATCH to the verdict-correct next status with current_agent:null (idempotent,
#216), (4) does side-effects (git commit + note) AFTER the move.

> ⚠️ Release unit: ship #217 ONLY with #218 (templates) + #223 (record-only endpoints).
> Until #223 deploys, the verdict endpoints still auto-advance status; #216 idempotency keeps
> the orchestrator's move a safe no-op during the window. Do NOT deploy #217's orchestrator
> changes alone.

L1 Quick:
  todo → orchestrator PATCH {status:impl, current_agent:Builder} → Worker(builder) implements
       → orchestrator PATCH {status:done, current_agent:null} → side-effects (commit + note)

L2 Standard:
  todo → [orchestrator: todo→plan, current_agent=Planner] → Plan Agent(planner) @plan
       → orchestrator PATCH {status:impl, current_agent:null} (skip plan_review)
  impl → Worker(builder) + TDD Tester(shield) → orchestrator PATCH {status:impl_review, current_agent:null}
  impl_review → Inspector returns verdict → orchestrator records → [user confirm] →
                orchestrator PATCH {status: done | impl, current_agent:null} → side-effects after done

L3 Full:
  todo → [orchestrator: todo→plan, current_agent=Planner] → Plan Agent(planner) @plan
       → orchestrator PATCH {status:plan_review, current_agent:null}
  plan_review → Critic returns verdict → orchestrator records → [user confirm] →
                orchestrator PATCH {status: impl (approve) | plan (reject), current_agent:null}
                (reject re-dispatches Planner with <critic_feedback>; plan→plan re-entry is idempotent)
  impl → Worker(builder) + TDD Tester(shield) → orchestrator PATCH {status:impl_review, current_agent:null}
  impl_review → Inspector returns verdict → orchestrator records → [user confirm] →
                orchestrator PATCH {status: test (approve) | impl (reject), current_agent:null}
  test → Ranger returns verdict → orchestrator records → [gate] →
         orchestrator PATCH {status: done (pass) | impl (fail), current_agent:null} → side-effects after done

Circuit breaker: plan_review_count > 3 OR impl_review_count > 3 → stop, ask user
  (counts incremented by the record-only verdict endpoints, NOT by the move PATCH)
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
# 1. Read current task state (status + level only)
# Stateless: re-read (status, level) every loop; NEVER cache status across a gate.
TASK=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=status,level")
STATUS=$(echo "$TASK" | jq -r '.status')
LEVEL=$(echo "$TASK" | jq -r '.level')

# Compute the Planner's level-aware exit status (used by step ④ / render helper):
#   L3 → plan_review, L2 → impl. (L1 never reaches the Planner.)
if [ "$LEVEL" = "3" ]; then PLAN_NEXT=plan_review; else PLAN_NEXT=impl; fi

# 2. Pipeline-entry / dispatch (see Agent Dispatch below)
#    When STATUS == todo:
#      L1  → ONE PATCH {"status":"impl","current_agent":"Builder"}, then dispatch Builder.
#      L2/L3 → ONE PATCH {"status":"plan","current_agent":"Planner"} (the todo→plan entry
#              move), then dispatch the Planner. The card is in the PLAN column before the
#              Planner begins — step ② below is this same single level-aware entry PATCH.
#    When STATUS == plan (fresh entry OR Critic-reject re-entry via plan_review→plan):
#      dispatch the Planner WITHOUT re-moving status. plan→plan is not a legal transition
#      and MUST NOT be attempted (idempotent re-entry). Set current_agent:"Planner" only.
#    All other statuses: dispatch the column's agent (see Agent Dispatch table).
# 3. After agent: append to agent_log (see schema.md for format)
# 4. RECORD verdict (record-only endpoint) → GATE (default) → COMMIT move (generic PATCH,
#    current_agent:null) → SIDE-EFFECTS (git commit + note, only after a done commit).
#    See "Per-Step Transition Contract" below for the full ordering + mapping.
# 5. Re-read state, loop until done or circuit breaker
```

#### Per-Step Transition Contract (orchestrator owns every move)

The orchestrator — never the agent — issues every status transition. Each agent step runs
in strict order:

1. **Decide** — dispatch the agent; it RETURNS a verdict (approved/reject | pass/fail +
   comment) and writes its own output fields. It does NOT move status and does NOT post its
   own verdict.
2. **Record** — the orchestrator persists the verdict via the matching record-only endpoint.
3. **Gate** (default mode) — the card SITS in its review state until the user signal.
4. **Commit** — the orchestrator issues the single validated generic PATCH to the next status
   with `current_agent:null`.
5. **Side-effects** — git commit + commit note, only AFTER the move is committed.

> ⚠️ Release unit: ship #217 ONLY with #218 (templates) + #223 (record-only endpoints).
> Until #223 deploys, the verdict endpoints still auto-advance status; #216 idempotency keeps
> the orchestrator's move a safe no-op during the window. Do NOT deploy #217's orchestrator
> changes alone.

**Record step** — the orchestrator POSTs the agent's returned verdict to the matching endpoint
(shapes from `../squad/shared.md`):

```bash
# Critic verdict @ plan_review
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/plan-review?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer": "Critic", "model": "<MODEL_CRITIC>", "status": "approved", "comment": "..."}'
# Inspector verdict @ impl_review
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/review?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"reviewer": "Inspector", "model": "<MODEL_INSPECTOR>", "status": "approved", "comment": "..."}'
# Ranger verdict @ test
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/test-result?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"tester": "Ranger", "status": "pass", "lint": "...", "build": "...", "tests": "...", "comment": "..."}'
```

> Record-only under #223 — this POST appends the comment and bumps `plan_review_count` /
> `impl_review_count` but does NOT move status; the orchestrator must NOT read or rely on any
> `newStatus` in the response. The next status is computed locally from the verdict (table below).

**Gate step** — default mode: `AskUserQuestion` accept/reject runs BEFORE the move PATCH.
`--auto`: skip the human prompt but still issue the move. The move PATCH MUST come after the gate.

**Verdict → next status** (the orchestrator computes this; mirrors `getTransitions`). Every row
is issued via the single validated generic PATCH `{status:<next>, current_agent:null}`:

| Agent @ status | Verdict | Generic PATCH move |
|---|---|---|
| Planner @ plan | (done) | L3 → plan_review · L2 → impl |
| Critic @ plan_review | approve / reject | impl / plan |
| Builder+Shield @ impl | (both done) | impl_review |
| Inspector @ impl_review | approve / reject | (L2 → done · L3 → test) / impl |
| Ranger @ test | pass / fail | done / impl |
| done finalize | — | done (idempotent no-op if already done) |

> Every move is the single validated generic PATCH `{status:<next>, current_agent:null}`;
> #216 makes a same-state move a harmless 200 no-op (the rollout safety net). Reject loops
> (plan_review→plan, impl_review→impl, test→impl) re-dispatch the column's agent; plan→plan
> re-entry sets `current_agent` only (no illegal status move).

**Release unit & deploy order**: gate-before-move only fully holds once #223 (record-only
endpoints) + #218 (agents return verdict, stop self-moving) ship in the SAME release. #216
(idempotent generic PATCH, already deployed) is the safety net during rollout — a double-move
is a harmless 200 no-op. Deploy order (Fowler ParallelChange): Expand (#216, shipped) →
Migrate+Contract cutover (#217+#218+#223).

**Verification reality**: #217 standalone verification is STATIC (grep/consistency, see
`done_when`). The live gate-before-move test requires #223 in the same release and is exercised
in the cutover, not here.

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
| `Planner` | `title,description,plan_review_comments` |
| `Critic` | `title,description,plan,decision_log,done_when` |
| `Builder` | `title,description,plan,done_when,plan_review_comments,review_comments` |
| `Shield` | `title,description,implementation_notes` |
| `Inspector` | `title,description,plan,done_when,implementation_notes` |
| `Ranger` | `title,implementation_notes` |

**Dispatch procedure — execute in this order for every agent:**

```
⓪ Fetch project brief (once per pipeline run, cache for all agents)
   PROJECT_DATA = curl GET /api/projects/$PROJECT
   PROJECT_BRIEF = extract .brief field (empty string if null or project not found)
   This is injected into every agent template via <project_brief> placeholder.

⓪ʙ Resolve dependencies & review feedback (once per pipeline run, cache for all agents)

   **Parse dependencies from description:**
   ```bash
   # Extract dependency IDs from description (case-insensitive)
   DESCRIPTION=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=description" | jq -r '.description // ""')
   DEP_IDS=$(echo "$DESCRIPTION" | grep -ioP 'Depends on:\s*\K#\d+(?:,\s*#\d+)*' | grep -oP '\d+' || true)
   ```

   **Circular dependency check:**
   If `$ID` (current task) appears in any dependency's own `Depends on:` line, emit error and abort:
   ```bash
   for DEP_ID in $DEP_IDS; do
     DEP_TASK=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$DEP_ID?project=$PROJECT&fields=title,status,description,decision_log,implementation_notes")
     HTTP_CODE=$(echo "$DEP_TASK" | jq -r '.id // empty')
     if [ -z "$HTTP_CODE" ]; then
       echo "WARNING: dependency #$DEP_ID not found (404), skipping"
       continue
     fi
     DEP_DESC=$(echo "$DEP_TASK" | jq -r '.description // ""')
     if echo "$DEP_DESC" | grep -iqP "Depends on:.*#$ID\\b"; then
       echo "ERROR: circular dependency detected — #$ID ↔ #$DEP_ID. Aborting."
       exit 1
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
   If dep status != `done`: prepend `[IN PROGRESS]` warning to that dep's block.
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
   TASK = curl GET /api/task/$ID?project=$PROJECT&fields=title,description,plan_review_comments
   # Critic
   TASK = curl GET /api/task/$ID?project=$PROJECT&fields=title,description,plan,decision_log,done_when
   # Builder
   TASK = curl GET /api/task/$ID?project=$PROJECT&fields=title,description,plan,done_when,plan_review_comments,review_comments
   # Shield
   TASK = curl GET /api/task/$ID?project=$PROJECT&fields=title,description,implementation_notes
   # Inspector
   TASK = curl GET /api/task/$ID?project=$PROJECT&fields=title,description,plan,done_when,implementation_notes
   # Ranger
   TASK = curl GET /api/task/$ID?project=$PROJECT&fields=title,implementation_notes
   Extract only the fields listed above for each agent

② Enter the agent's column + mark it active — ONE level-aware PATCH
   The entry status move and current_agent assignment are a SINGLE PATCH (never a
   separate/third call). Pick the body by the agent being dispatched:
     • Planner from `todo` (L1): not applicable — L1 dispatches Builder, see below.
     • Planner from `todo` (L2/L3):  { "status": "plan", "current_agent": "Planner" }
     • Builder from `todo` (L1):     { "status": "impl", "current_agent": "Builder" }
     • Planner already at `plan` (fresh entry handled above, OR Critic-reject
       re-entry via plan_review→plan):  { "current_agent": "Planner" }  (NO status move —
       plan→plan is illegal; idempotent re-dispatch)
     • Any agent already in its own column (Critic@plan_review, Inspector@impl_review,
       Ranger@test, Shield@impl): { "current_agent": "<Nickname>" }  (no status change)
   curl PATCH /api/task/$ID  →  <body above>

③ Read template file
   Read tool: ../squad/templates/<agent>.md

④ Fill placeholders in template
   Replace every occurrence of:
     <ID>                     → actual task ID
     <PROJECT>                → actual project name
     <project_brief>          → project brief from step ⓪ (empty string if not set)
     <title>                  → task title
     <description>            → task description (requirements)
     <plan>                   → plan field value
     <decision_log>           → decision_log field value
     <done_when>              → done_when field value
     <implementation_notes>   → implementation_notes field value
     <plan_review_comments>   → plan_review_comments field value
     <dependencies_context>   → per-agent dep context from step ⓪ʙ (empty string if none)
     <critic_feedback>        → latest plan_review_comments comment (empty if first run)
     <plan_next_status>       → $PLAN_NEXT (plan_review for L3, impl for L2)
     <inspector_feedback>     → latest review_comments comment (empty if first run)
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
     --set plan="$PLAN" \
     --set decision_log="$DECISION_LOG" \
     --set done_when="$DONE_WHEN" \
     --set implementation_notes="$IMPLEMENTATION_NOTES" \
     --set plan_review_comments="$PLAN_REVIEW_COMMENTS" \
     --set dependencies_context="$DEPS_CONTEXT" \
     --set critic_feedback="$CRITIC_FEEDBACK" \
     --set plan_next_status="$PLAN_NEXT" \
     --set inspector_feedback="$INSPECTOR_FEEDBACK" \
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

⑥ After Task completes — append signed entry to agent_log
   (use schema.md › "Appending to agent_log" snippet,
    set agent=<Nickname>, model=<model>, message=<summary>)
```

Builder and Shield each RETURN their output (no self-move). Once both complete, the orchestrator
issues the impl→impl_review **commit** move:
```bash
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/task/$ID?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"status": "impl_review", "current_agent": null}'
```

**Default mode**: at `plan_review`, `impl_review`, and `test` (the L3 Ranger gate), the contract order is explicit — the agent
RETURNS a verdict → the orchestrator RECORDS it via the record-only endpoint (no status move) →
**gate** (`AskUserQuestion` accept/reject) → the orchestrator COMMITS the move via the generic
PATCH with `current_agent:null`. The gate PRECEDES the move PATCH; the move is never the verdict endpoint.
**Auto mode (`--auto`)**: same order, but auto-accept at the gate (orchestrator still issues the move PATCH).

#### → Done Transition (all levels)

```bash
# 1. Move to done (single validated generic PATCH, idempotent) — clears current_agent.
#    #216 makes done→done a no-op, so re-running is safe.
curl -s "${AUTH_HEADER[@]}" -X PATCH "$BASE_URL/api/task/$ID?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d '{"status": "done", "current_agent": null}'

# 2. Side-effects AFTER the state commit — commit pending changes.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  git add -A
  git commit -m "feat: <TITLE> [squad #<ID>]"
fi
COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "no-git")

# 3. Record commit hash in notes
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task/$ID/note?project=$PROJECT" \
  -H 'Content-Type: application/json' \
  -d "{\"content\": \"Commit: $COMMIT_HASH\"}"
```

If no commits yet, skip note or record `"Commit: (none)"`.

### `/squad-run review <ID>` — Code Review

Trigger Code Review agent for a task in `impl_review` status (same as impl_review step).
