---
name: squad-batch-run
description: 'Runs multiple squad tasks end-to-end as one orchestrated batch in dependency order — Rolling Wave by default (refine each task from the prior card''s actual implementation, then implement, then verify), or --big-bang for fully-refined independent tasks. Use for epic-level batch execution: "/squad-batch-run <selector>", "run the whole epic", "batch-run these tasks".'
license: MIT
metadata:
  internal: true
---

> Read `../squad/shared.md` (bootstrap + levels + errors) and `../squad/principles.md` first.

```bash
api()  { python3 ../squad/scripts/api.py "$@"; }
pipe() { python3 ../squad/scripts/pipeline.py "$@"; }
```

This skill is an orchestrator: every implement step hands off to `squad-run`, every refine step to `squad-refine` — never re-implement or emulate either pipeline, and never implement a task freehand and patch board state afterward.

**Codex invocation rule**: when no Skill tool is available, invoke the inner runners as slash text — `$squad-run <ID> [--auto]` and `$squad-refine <ID>` — the Codex-native equivalent of `Skill(skill="squad-run", …)` / `Skill(skill="squad-refine", …)`.

## Commands

- `/squad-batch-run <selector> [--auto] [--big-bang]` — Rolling Wave default: refine(N) → implement(N) → verify(N) → next. `--auto` auto-approves the review checkpoints inside `squad-run` (refine and verify still run). `--big-bang` skips refine/verify — implement only.
- `/squad-batch-run resume <start-ID> [--auto]` — skip tasks before `<start-ID>`, same mode as the original batch.

Task ids are opaque `<KEY>-<seq>` display strings — never positional integers; numeric ranges are rejected. For the full selector syntax (`--tasks` id list and/or composable `--status` / `--tag` / `--phase` / `--epic` filters) see `python3 scripts/plan_batch.py --help`.

## Workflow

### 1. Preflight + plan

```bash
api GET /board?summary=true >/dev/null                              # non-zero exit (auth/transport) → stop
python3 ../squad/scripts/observe.py gate >/dev/null 2>&1; OBSERVE_OK=$?  # 0 = emit steering, else skip
export SQUAD_ORG   # plan_batch.py reads SQUAD_ORG from the env ONLY — export it from the shared.md resolution
python3 scripts/plan_batch.py --project "$PROJECT" --tasks "<KEY>-42 <KEY>-43"   # or --epic/--status/--tag/--phase
```

Dependencies are structural: a `.blocked_by` dep is resolved once its status is terminal — `done` or `cancelled` — and the planner orders around these edges.

`plan_batch.py` is the single planner and its output is authoritative: consume `ordered_tasks`, `skipped_epics`, and `candidate_groups` as-is — no re-ordering, no epic re-checks, no re-derivation of parallel groups. Consult `references/parallel-rules.md` only if you must override a grouping. A planner failure → report and stop.

Present the resolved plan before executing: ordered task list, groups + mode (Rolling Wave / Big Bang), one-line reason per group, skipped epics (an epic is a container, never runnable). Skip non-`todo` tasks with a warning line; if everything is skipped, stop and report. `resume`: silently drop tasks before `<start-ID>`.

### 2. Rolling Wave loop (default)

For each task N in `ordered_tasks`:

**A. Refine** — `Skill(skill="squad-refine", args="<ID>")`. It detects prior context via the relationships API itself; no extra args. Before invoking, split if scope exceeds limits (AC > 5, files > 5, multi-layer): create sub-cards, declare their ordering via `blocks` edges (`api POST /task/$DEP/relationships --json "$(jq -n --arg to "$SUB" '{to:$to, type:"blocks"}')"`; a 409 cycle is surfaced, not pre-checked), replace N with the sub-cards in the order, report, continue.

**B. Implement** — invoke `squad-run` level-aware:

| Level | default | `--auto` |
|-------|---------|----------|
| L1 | `squad-run <ID> --auto` | same |
| L2 / L3 | `squad-run <ID>` (pauses at review gates) | `squad-run <ID> --auto` |

**C. Verify** — one worktree check, one status check, one event:

```bash
git status --porcelain                               # inspect what the run actually changed
STATUS=$(api GET /task/$ID?fields=status -q status)  # expect "done"
pipe event $ID --actor Orchestrator --message "Verified: <confirmed interfaces/schemas + worktree state>"
```

- `done` → note anything that affects N+1's scope, move to N+1.
- Any other status → the inner run stopped (circuit breaker, rejection, pending review) → stop the batch and report the resume point.
- Unexpected design deviation found during Verify → queue a re-refine for the affected downstream tasks (writes a new spec; never patch their `description`), report, and emit once (best-effort; rubric: `../squad/references/observation.md`):

```bash
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$ID" --modality corrective \
  --valence negative --target scope --severity major --attributability violated_constraint \
  --comment "verify found a design deviation" || true
```

**Parallel groups** (from `candidate_groups`): run the group's refines concurrently, then its implements concurrently — multiple Skill calls in one message (Codex: concurrent `$squad-run` only if the runtime supports it, else sequential) — then verify sequentially.

### 3. Big Bang mode (`--big-bang`)

Invoke `squad-run` per task — sequentially in order, or concurrently per candidate group. Run the step-2C Verify status check after each task or group. After a parallel group additionally:

```bash
git diff --check   # conflict markers → stop, report which tasks conflicted
```

### 4. Stop conditions

- Requirement ambiguity needing user input · circuit breaker inside `squad-run` · conflicting code changes between parallel tasks · a task leaves the normal path and needs a product decision.
- Parallel partial failure: let in-flight tasks finish, then stop; report succeeded vs failed.
- Early-stop report: completed IDs, the blocker and which task caused it, and `Resume with: /squad-batch-run resume <next-ID>`.

### 5. Completion summary

Completed IDs in order · which groups ran in parallel · key interfaces/schemas confirmed during Verify steps · resulting commits.

### 6. Coach (background, batch level)

Dispatch the Coach per `../squad/references/friction.md` with `skill_name=squad-batch-run`, `source_task` = the first ID completed this run, `run_summary="squad-batch-run completed a batch of tasks in rolling-wave order."`, `trajectory` = the batch record (completed order, grouping decisions, verify notes), `friction_signals` = ordering reworks / stale-assumption refines / stop-condition trips (`none` if clean). The per-task Coach already fired inside each `squad-run` — this one judges the batch loop. Launch in the background — do not block completion; surface only if it filed friction.

## Execution notes

- Be conservative: sequential is the default; treat shared routes, server loaders, types, and top-level navigation as dependency hotspots.
- Re-check the worktree between tasks.
- Never skip Refine in Rolling Wave mode — prior implementation context may change scope.

## Output style

```
Refine  <ID> — scope locked (prior: POST /api/items interface confirmed)
Impl    <ID> — done (commit: a1b2c3)
Verify  <ID> — confirmed: items table schema, POST /api/items → {id, name}
```

End with the completion summary, or the early-stop report + resume point.
