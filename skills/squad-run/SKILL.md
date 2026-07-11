---
name: squad-run
description: 'Run the AI team pipeline for squad tasks — 6 agents (Planner, Critic, Builder, Shield, Inspector, Ranger) orchestrated by a deterministic engine script. Use /squad-run <ID> for the full pipeline, /squad-run step <ID> for one step. AUTO-TRIGGER when: the user pairs a task ID with implement/build/do/run ("implement task NNN"); or the user confirms ("yes/ok/go/do it") after Claude proposed implementing a specific squad task; or the user says "next task"/"continue" with a task in progress. When triggered, run this skill — never implement manually and patch squad state afterward.'
license: MIT
---

> Read `../squad/shared.md` (bootstrap + levels + errors) and `../squad/principles.md` first.

The engine script owns every deterministic step — status moves, correlation ids, prompt rendering, verdict reads, format normalization, snapshots, the done-commit. Use it as a black box (`--help` for details); do not read its source:

```bash
pipe() { python3 ../squad/scripts/pipeline.py "$@"; }
```

In Codex environments this skill may be invoked as `$squad-run <ID> [--auto]`.

## `/squad-run <ID> [--auto]` — Full Pipeline

**Default**: pause for the user at the `plan_review`, `impl_review`, and `test` gates. **`--auto`**: auto-accept gates (circuit breaker still fires).

### 1. Preflight (once)

```bash
pipe preflight $ID
```

Act on the JSON verdict:
- `runnable:false` — epic → list its children and stop; terminal status → say "reopen to run" and stop; `blockers` non-empty → default mode: AskUserQuestion confirm/cancel; `--auto`: refuse `"blocked by incomplete dependency #N"` and abort.
- `open_subtasks` non-empty (soft nudge, only when runnable): default mode ask confirm/cancel ("usually run those first"); `--auto` proceed and log via `pipe event $ID --actor Orchestrator --message "--auto proceeded past N open sub-task(s)"`.

### 2. Step loop (repeat until done)

Each pipeline step is: **dispatch → launch agent → record → gate → advance.**

```bash
pipe dispatch $ID                 # impl 2nd sub-step: pipe dispatch $ID --agent shield
```

Output = one META JSON line (`agent`, `model`, `effort`, `provider`, `correlation_id`), then `-----PROMPT-----`, then the rendered agent prompt. Launch the agent with the Task tool:

- claude: `Task(subagent_type="general-purpose", model=META.model, prompt=<prompt>)`
- codex: same + `model_reasoning_effort=META.effort`

When the Task completes, record the step (one line summarizing what the agent did; `--tokens` only if your runtime reported per-subagent usage — never estimate):

```bash
pipe record $ID --agent <META.agent> --cid <META.correlation_id> --message "<summary>" [--tokens N]
```

`record` prints `{verdict, proposed_next, circuit_breaker}`.

**Gate** (only at `plan_review` / `impl_review` / `test`, default mode): show the agent's verdict and AskUserQuestion accept/reject. On reject, a mandatory non-empty reason is required (re-prompt until given).

**Advance:**

```bash
pipe advance $ID --cid <META.correlation_id>                      # accept / --auto / non-gate steps
pipe advance $ID --human-reject --reason "<reason>" --cid <cid>   # human reject (even after agent approved)
```

`advance` records the human override server-side (a 403 = PAT lacks `task:override-review` — surface it, never silently fix in place), emits consent-gated steering on rejects, computes and issues the move, and prints:
- `circuit_breaker:true` — stop, tell the user the review count exceeded 3; only continue with `--force` after they decide.
- `approval_tree` (L3 impl_review→test) — save it for finalize.
- `action:"finalize"` — the next status is done; run finalize (below) instead of another loop pass.
- `moved:true, to:<status>` — loop: dispatch the next column's agent. Reject moves re-dispatch the sent-back column's agent with fresh feedback (dispatch injects it automatically).

**Impl step ordering**: dispatch Builder → Task → record; then dispatch Shield (`--agent shield`) → Task → record; then `pipe normalize $ID` (best-effort formatter over changed files); then advance.

### 3. Finalize

```bash
pipe finalize $ID [--approval-tree <sha>]
```

Runs the L3 stale-approval recheck (tree changed since Inspector approval → prints `stale_approval:true` and does NOT move — re-enter the loop at `impl_review` with a fresh dispatch), then moves to done, commits pending changes (`feat: <title> [squad #ID]`), and records the commit event.

### 4. Coach (background, after done)

Dispatch the Coach per `../squad/references/friction.md` with `skill_name=squad-run`, `source_task=$ID`, a one-line `run_summary`, the run's `trajectory` (activity events + verdicts), and `friction_signals` (reject loops / breaker trips; `none` if clean). Launch in the background — do not block; surface only if it filed friction.

## `/squad-run step <ID>` — Single Step

One pass of the step loop (dispatch → Task → record → gate → advance), then exit.

## `/squad-run review <ID>` — Code Review Only

For a task already in `impl_review`: run the step loop once (it dispatches the Inspector).

## Errors

- Agent Task failure → retry once; 2nd failure → keep status, `pipe event $ID --actor Orchestrator --message "<what failed>"`, notify the user.
- Any 4xx/5xx from `pipe` is printed with the server body — surface it; never bypass the API or fall back to direct DB access.
