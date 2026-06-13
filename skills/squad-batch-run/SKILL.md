---
name: squad-batch-run
description: Run multiple squad tasks end-to-end in Rolling Wave order — refine each task based on the prior card's actual implementation, then implement, then verify, then refine the next. Use for epic-level batch execution. --big-bang flag disables rolling wave for simple independent tasks.
license: MIT
metadata:
  internal: true
---

# Squad Batch Run

> Safety principles: read `../squad/principles.md` — **mandatory, not optional.**

Execute several squad tasks as one orchestrated batch using **Rolling Wave Planning** by default.

Default loop per task:
```
refine(N) → implement(N) → verify(N) → refine(N+1) → implement(N+1) → ...
```

This skill is an orchestrator, not a shortcut. Every implement step hands off to `squad-run`. Every refine step hands off to `squad-refine`.

## Codex Invocation Rule

When running inside Codex, if a dedicated Skill tool is not available, invoke the inner runners by issuing slash command text directly:

- `$squad-run <ID>` / `$squad-run <ID> --auto`
- `$squad-refine <ID>`

Treat these as the Codex-native equivalent of `Skill(skill="squad-run", ...)` and `Skill(skill="squad-refine", ...)`.
Do not re-implement either pipeline manually when this command path is available.

---

## Commands

### `/squad-batch-run <selector> [--auto] [--big-bang]`

Run all tasks matching the selector in dependency order.

- **Default (Rolling Wave)**: refine(N) → implement(N) → verify(N) → repeat. L2/L3 tasks pause at review checkpoints for user confirmation.
- **`--auto`**: auto-approve all review checkpoints inside `squad-run`. Refine and Verify always run.
- **`--big-bang`**: skip rolling wave — implement tasks directly without pre-refine or verify steps. Use only when tasks are fully refined upfront and independent.

### `/squad-batch-run resume <start-ID> [--auto]`

Resume a stopped batch from the given task ID. Skips all tasks before `<start-ID>`. Resumes with the same mode (rolling wave unless `--big-bang` was set).

---

## Inputs

- Accept task selectors: `500-504`, `500~504`, `500,501,504`, or whitespace-separated IDs.
- Reverse ranges like `504-500` are normalized to ascending order.
- Read `../squad/shared.md` before any API call.
- Invoke `squad-run` and `squad-refine` for each task via the Skill tool when available.
- In Codex environments without the Skill tool, invoke via `$squad-run ...` / `$squad-refine ...` directly.
- Do not emulate or re-implement either pipeline.

## Resources

- Use `scripts/plan_batch.py` to normalize selectors, fetch task metadata, and produce phase-ordered candidates.
- Read `references/parallel-rules.md` when deciding whether tasks are safe to run in parallel.

## Metadata Hints

**Dependencies are structural**, read from the relationships API — NOT text-parsed from descriptions
(the `Depends on:` convention is retired; see `../squad/shared.md` → **Task Relationships & Epics**):

- `GET /api/task/:id/relationships` → `.blocked_by` (the deps that must be `done` first)

Other strong signals still come from task descriptions:

- `Parallel-safe: yes` / `Parallel-safe: no`
- `Touches: browse-data, header-nav`

Fall back to conservative inference from phase, tags, title, and description when hints are absent.

---

## Workflow

### 0. Pre-flight checks

```bash
curl -sf "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true" > /dev/null
```

- If the board is unreachable: report the error (check `base_url` / auth) and stop.
- If `plan_batch.py` fails: report error and stop.

### 1. Resolve project

Read the project name from `.squadrc` (`SQUAD_PROJECT=`) — see `squad/shared.md` for the full resolution.

### 2. Plan

```bash
python3 scripts/plan_batch.py --project "$PROJECT" --tasks "<selector>" --base-url "$BASE_URL" --auth-token "$AUTH_TOKEN"
```

### 3. Read plan

Read the returned task list and proposed groups.

### 4. Validate ordering

- Respect `phase:N` tags when present; prefer phase order over user order if they conflict.
- **Epics are containers, not runnable**: skip any `card_type:'epic'` card with a note (e.g. `⚠ #520 skipped — epic container, run its children`). Epics never enter the runnable set.
- **Non-todo tasks**: skip with a warning line (e.g. `⚠ #502 skipped — status is impl`). If all tasks skipped, stop and report.
- `resume <start-ID>`: skip tasks before that ID silently.

### 5. Decide execution mode per group

- Default: sequential.
- Parallel only if **all** of these are true:
  - Same phase or no phase tag
  - No `blocks` relationship edge between tasks in the group (`.blocked_by` / `.blocking` from the relationships API)
  - Titles/tags/descriptions point to distinct modules or surfaces
  - Failure in one would not invalidate another's work
- If any doubt remains, stay sequential.
- **Rolling wave + parallel**: run refine steps for a parallel group concurrently, then implement concurrently. Verify sequentially.

### 6. Execute — Rolling Wave Loop (default)

For each task N in order:

```
A. Refine(N)
   - Skill(skill="squad-refine", args="<ID>")  [Codex: $squad-refine <ID>]
   - squad-refine auto-detects the prior card via the relationships API (`.blocked_by`) or asks one question.
   - Reads N-1's implementation_notes + actual codebase to ground N's description.
   - First task in the batch (no prior card): regular user interview.

   Card split check (before invoking squad-refine):
   - If scope exceeds limits (AC > 5, files > 5, multi-layer), split first:
     1. Create sub-cards via squad API
     2. Declare any blocks dependency between sub-cards via `POST /api/task/:id/relationships {to, type:"blocks"}` (NOT a `Depends on:` text line; 409 on a cycle is surfaced, no pre-check)
     3. Replace N in execution order with N-a, N-b, N-c
     4. Report split to user, continue automatically

B. Implement(N)
   - Invoke squad-run (level-aware, see Inner Task Contract)

C. Verify(N)
   - Check actual implementation: git diff, created/modified files, test results
   - Record an activity event: curl POST /api/task/$ID/activity {actor:"Orchestrator", model:"system", message:"Verified: [confirmed interface/schema]"}
   - Note anything that will affect N+1's refinement scope

→ Move to N+1
```

**Loop exceptions:**
- Split triggered during Refine → insert sub-cards, continue
- Circuit breaker or blocker during Implement → stop, report resume point
- Unexpected design change during Verify → update downstream task descriptions; report to user

### 6b. Execute — Big Bang mode (`--big-bang`)

Invoke `squad-run` directly per task. No refine or verify steps.
Use only when all tasks were fully refined before the batch started.

**Sequential**: invoke for each task in order.

**Parallel**: invoke for all tasks in the group concurrently.
- Claude: multiple Skill tool calls in one message.
- Codex: multiple `$squad-run ...` only if runtime supports concurrent execution; otherwise sequential.

After parallel group:
```bash
git status --porcelain
git diff --check
```
If conflict markers found: stop, report which tasks conflicted.

After each task or group: re-read task status from API before continuing.

### 7. Stop conditions

- Requirement ambiguity requiring user input
- Repeated review/test failure (circuit breaker inside `squad-run`)
- Conflicting code changes between parallel tasks
- Task exits normal path and needs a product decision
- Parallel group partial failure: wait for in-progress tasks to finish, then stop. Report succeeded vs. failed.

### 8. Early stop summary

- Completed task IDs
- Current blocker and which task caused it
- Resume point: `Resume with: /squad-batch-run resume <next-ID>`

### 9. Completion summary

- Completed IDs in order
- Whether any groups were parallelized
- Key interfaces/schemas confirmed during verify steps (useful for next epic)
- Resulting commits

### 10. Coach (batch-level friction review)

After the completion summary, dispatch the **Coach** at the **batch level** per `../squad/shared.md` → **Coach Dispatch** — judging the batch loop itself (the per-task Coach already fired inside each `squad-run`). batch-run has no model block of its own, so resolve `MODEL_PROVIDER` + the `read_model` / `read_effort` helpers per `../squad/shared.md` → **Model Resolution** first, then pass its batch framing:
- `skill_name` = `squad-batch-run`
- `source_task` = the first batch ID completed this run
- `run_summary` = `"squad-batch-run completed a batch of tasks in rolling-wave order."`
- `trajectory` = batch loop record: completed IDs in order, parallelization decisions, verify-step notes
- `friction_signals` = ordering reworks / stale-assumption refines / stop-condition trips; `none` if clean

---

## Execution Notes

- Be conservative. This skill is for throughput, not shortcuts.
- Never implement a task freehand and patch squad state afterward — drive every task through `squad-run`.
- Treat shared routes, server loaders, types, and top-level navigation as dependency hotspots — keep sequential.
- Re-check the worktree between tasks.
- Only parallelize when the batch planner can justify it in one sentence.
- Rolling wave adds refine+verify overhead per task, but prevents rework from stale assumptions — net faster for epics with inter-task dependencies.

---

## Inner Task Contract

### Refine invocation

```
Skill(skill="squad-refine", args="<ID>")   # Claude
$squad-refine <ID>                          # Codex fallback
```

squad-refine handles prior context detection internally. No extra args needed.

### Implement invocation (level-aware)

| Level | Claude default | Claude `--auto` | Codex default | Codex `--auto` |
|-------|---------------|-----------------|---------------|----------------|
| L1 | `Skill("squad-run", "<ID> --auto")` | same | `$squad-run <ID> --auto` | same |
| L2 | `Skill("squad-run", "<ID>")` | `Skill("squad-run", "<ID> --auto")` | `$squad-run <ID>` | `$squad-run <ID> --auto` |
| L3 | `Skill("squad-run", "<ID>")` | `Skill("squad-run", "<ID> --auto")` | `$squad-run <ID>` | `$squad-run <ID> --auto` |

In default mode, L2/L3 tasks pause for user confirmation at review checkpoints.

### Result verification

```bash
STATUS=$(curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=status" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
```

| Status | Interpretation | Action |
|--------|---------------|--------|
| `done` | Completed successfully | Continue to Verify, then next task |
| `todo`, `plan`, `impl` | Circuit breaker or rejection | Stop batch, report blocker |
| `plan_review`, `impl_review` | Review pending (unexpected in `--auto`) | Stop batch, report |

### Rules

- Never re-implement `squad-run` or `squad-refine`. Always invoke via Skill tool or Codex `$` command fallback.
- Never skip Refine in rolling wave mode — prior implementation context may change scope.
- If a task blocks, status check surfaces it — stop and report exact resume task.
- For parallel groups, issue multiple invocations in a single message.

---

## Output Style

Start with the resolved plan:
- Ordered task list, proposed grouping, mode (Rolling Wave or Big Bang), one-line reason per group, skipped tasks

During execution:
```
Refine  #201 — scope locked (prior: POST /api/items interface confirmed)
Impl    #201 — done (commit: a1b2c3)
Verify  #201 — confirmed: items table schema, POST /api/items → {id, name}
Refine  #202 — scope updated: builds on items table from #201
Impl    #202 — done (commit: d4e5f6)
Verify  #202 — confirmed: ItemCard component at src/components/ItemCard.tsx
...
```

End with batch summary and resume point if stopped early.
