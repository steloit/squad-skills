---
name: squad-kickstart
description: "Runs the full project pipeline from idea to rolling implementation: SRS → implementation plan → skeleton task creation (one batch call) → ordered Rolling Wave loop (refine → implement → verify, one task at a time). Use when starting a new project or a large feature (3+ tasks) that needs end-to-end structure. Flags: --auto (skip confirmation gates), --plan-only (stop after ordering), --big-bang (legacy all-upfront refinement, ≤3 independent tasks only)."
license: MIT
metadata:
  internal: true
---

# `/squad-kickstart [topic]` — Full Project Pipeline

> Shared context: `../squad/shared.md` (api bootstrap, config resolution, pipeline levels, JSON safety, error rules).

**Rolling Wave (default)**: plan near-term work in detail, keep future work high-level — refine task N+1 only after task N is implemented and verified, so each refinement is grounded in real code, not stale assumptions.

```
① SRS → ② Plan → ③ Create skeleton tasks (one batch) → ④ Lock order → ⑤ refine(N) → implement(N) → verify(N) → …
```

## ① SRS

1. Only if the topic is ambiguous (unclear goal, multiple plausible scopes), ask 1–2 clarifying questions first; otherwise start directly.
2. Explore the codebase if needed.
3. Write the SRS using the section headings in `references/srs-template.md`; save as `docs/srs-{project-slug}.md`.
4. **Approval gate**: present a summary and get user approval before continuing.

## ② Implementation Plan

Write `docs/implementation-plan-{project-slug}.md`: epic/story structure, dependency graph, phase order, estimated size.

## ③ Create skeleton tasks — one batch call

Skeleton only: title + 1–2-line goal per child; Acceptance Criteria stay blank until Refine. Levels per shared.md. Add one E2E validation task at the end of each epic (required).

Create the epic + all children + all edges with ONE call (single-quoted heredoc — board text is data, never code):

```bash
python3 ../squad/scripts/create_tasks.py <<'EOF'
{"epic": {"title": "<epic title>", "description": "Container for the <name> epic.", "priority": "high", "tags": ["phase:1"]},
 "tasks": [
   {"title": "<task 1>", "description": "## Goal\n...\n\n## Scope\n- In: ...\n- Out: ...", "level": 2, "priority": "high", "tags": ["phase:1"]},
   {"title": "<task 2>", "description": "...", "level": 2, "blocked_by": [0]},
   {"title": "E2E validation: <epic>", "description": "...", "level": 3, "blocked_by": [0, 1]}
 ]}
EOF
```

- `blocked_by` ints are indexes of earlier tasks in the same batch (strings = existing board ids) — ordering the array by execution order yields the dependency DAG directly.
- The script creates the epic container (`card_type: "epic"`) and wires every edge via `POST /task/$ID/relationships` — `{type: "parent"}` child→epic, `{type: "blocks"}` for dependencies. Never encode hierarchy in tags (`phase:` tags remain valid; `epic:` tags are retired).
- It prints the created id table (epic + children + edge results) — report that list, with order, to the user.

Edge/epic semantics on demand: `../squad/references/epics.md`.

## ④ Lock execution order

Write `docs/execution-order-{project-slug}.md` (phases + per-task dependency notes) from the plan's dependency graph. Confirm the order with the user — skip this confirmation under `--auto`.

## ⑤ Rolling Wave loop

For each task N in execution order:

- **A. Refine(N)** — read task N-1's actual implementation from the codebase plus its board record (`api GET /task/$PREV?fields=implementation_notes,decision_log`), then call `/squad-refine #N` to write the spec grounded in the confirmed interfaces/schema (the human `description` stays untouched — never PATCH it).
  Split during Refine when any: >5 acceptance criteria, >5 expected files, multiple layers at once (DB + API + UI), >1 session (~30–60 min) of work → break into 2–3 sub-cards, insert into the order, report, continue automatically.
- **B. Implement(N)** — run `/squad-run #N`.
- **C. Verify(N)** — one git check to confirm what actually landed (`git log --oneline -1 && git diff HEAD~1 --stat`, or `git status --short && git diff --stat` when uncommitted), then one event recording the impact:
  `python3 ../squad/scripts/pipeline.py event $ID --actor Orchestrator --message "Impact on next tasks: ..."` (appends a `POST /task/$ID/activity` note). Adjust downstream task descriptions if the implementation changed assumptions.

Loop exceptions: blocker → report to the user and pause · E2E task fails → review that epic's tasks · review-loop circuit breaker per shared.md.

## Options

| Flag | Effect |
|------|--------|
| (default) | Rolling Wave; L2/L3 pause at plan_review / impl_review for user confirmation |
| `--auto` | auto-approve implement stages AND skip the ④ order confirmation; Refine + Verify always run |
| `--plan-only` | run ①–④ only; the user later triggers each task manually (refine → `/squad-run #N`) |
| `--big-bang` | legacy all-upfront: refine everything, then batch execute — only for ≤3 tasks with no inter-task dependencies |

## Guardrails

- Never create tasks without an approved SRS; every epic gets an E2E test task.
- Refine N+1 only after N is verified — always against the prior card's real implementation.
- Run `/squad-init` first if the project is not registered.

## Output

Print one progress line per step, e.g.:

```
✅ ① SRS: docs/srs-project.md (12 requirements)
✅ ③ Tasks: epic + 8 children created (1 batch)
  ✅ Refine #201 — scope locked from codebase
  ✅ Impl  #201 — done (commit: a1b2c3d)
  ✅ Verify #201 — confirmed: POST /api/items interface
  ⏳ Refine #202 — in progress...
```
