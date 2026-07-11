---
name: squad-explore
description: 'Explores a codebase when the implementation direction is uncertain — an Explore subagent then a Plan subagent produce a direction report, the user picks a direction, and an epic plus phased tasks are created on the squad board. Use when the user does not know how to implement something: "/squad-explore <topic>", "explore how to …", "figure out an approach for …", "not sure how to build …". NOT for direct implementation — this skill never writes code.'
license: MIT
---

> Read `../squad/shared.md` (bootstrap + levels + errors) and `../squad/principles.md` first.

```bash
api() { python3 ../squad/scripts/api.py "$@"; }
```

## `/squad-explore [topic]` — Explore & Plan

### 0. Setup (once)

```bash
python3 ../squad/scripts/observe.py gate >/dev/null 2>&1; OBSERVE_OK=$?  # 0 = emit steering, else skip
CID=$(python3 -c 'import uuid;print(uuid.uuid4())')
```

Steering emits below are best-effort — guard with the cached gate and `|| true` (rubric: `../squad/references/observation.md`).

### 1. Validate the topic

A topic lacks context (word count is irrelevant) if ANY hold: no indication of which part of the codebase is involved; the "why" is absent; the scope is unbounded ("improve everything"). Missing topic or missing context → one clarification round, max 2 AskUserQuestion questions ("What problem / outcome?", "Which area of the codebase, or unknown?"). Self-sufficient topic → proceed.

### 2. Explore subagent

Render the **Explore prompt** from `references/prompts.md` (fill `<TOPIC>`, `<PROJECT>`) and launch `Task(subagent_type="Explore", prompt=…)`. Save the output as `$EXPLORE_FINDINGS`.

### 3. Plan subagent (sequential — it consumes the findings)

Render the **Plan prompt** from `references/prompts.md` (fill `<TOPIC>`, `<PROJECT>`, `<EXPLORE_FINDINGS>`) and launch `Task(subagent_type="Plan", prompt=…)`. Save the output as `$PLAN_OUTPUT`.

### 4. Write the Exploration Report

This is the ONLY place the Plan output is transcribed; later steps reference it, never re-print it.

```
## Exploration Report: <topic>
*Explored: <ISO timestamp> | Project: <PROJECT>*

### Current State
[2–4 sentences on what exists today, citing specific files]

### Key Findings
- <finding> (`path/to/file.ts:line`) …

### Possible Directions
[verbatim from $PLAN_OUTPUT § 1 — do not paraphrase]

### Recommended Direction
[verbatim from $PLAN_OUTPUT § 2 — do not paraphrase]
```

If the codebase gives no signal on something, say "unclear from codebase".

### 5. Present + choose direction

Print the report, then AskUserQuestion:

- One option per direction, marking the Plan agent's recommendation, plus "Cancel — save report only".
- If the Plan output has a single sensible direction, present it as the recommended default: "Proceed with <name> (recommended)" / "Pick a different approach" / "Cancel — save report only".

Choosing the recommended direction emits nothing. After the epic exists (step 6 or 6-Cancel), emit for the other outcomes:

```bash
# non-recommended direction chosen:
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$EPIC_ID" --modality corrective \
  --valence negative --target planning --severity moderate --attributability latent_preference \
  --comment "chose a non-recommended direction" --correlation-id "$CID" || true
# Cancel:
[ "$OBSERVE_OK" = 0 ] && python3 ../squad/scripts/observe.py emit "$EPIC_ID" --modality corrective \
  --valence negative --target planning --severity trivial --attributability ambiguous \
  --comment "cancelled before creating tasks" --correlation-id "$CID" || true
```

### 6. Create the epic + phased tasks — one script call

Map the Plan breakdown to board fields (re-derive the breakdown only if the user picked a non-recommended direction):

- title: imperative phrase from the Plan output · tags: `["explore-<topic-slug>", "phase:<N>"]` (JSON array) · priority: high (phase 1–2), medium (3–4), low (5+) · level: 2 or 3 from the Plan complexity.
- Each description ends with an `## Exploration Context` block: direction chosen, phase N of M, 1–2 sentence rationale.
- The LAST task is always "Add E2E tests for <topic>" (key flows, happy path + edge cases, acceptance criteria; priority medium, level 2, extra tag `"e2e-test"`).
- `blocked_by`: the index/indices of the previous phase's task(s) in this batch — phase order becomes dependency edges. The script wires all edges itself: each task to the epic via a `type:"parent"` relationship, each `blocked_by` entry via `type:"blocks"`.

Create everything with ONE call (stdin JSON per the script's `--help`; build it with `jq`/python, never inline board text into shell strings):

```bash
python3 ../squad/scripts/create_tasks.py <<'EOF'
{"epic": {"title": "[Explore] <topic>", "priority": "low",
          "tags": ["explore-<topic-slug>", "explore-report"],
          "description": "<full Exploration Report from step 4>\n\n---\n## Task Index\n*(appended after creation)*"},
 "tasks": [{"title": "…", "description": "…", "level": 3, "priority": "high",
            "tags": ["explore-<topic-slug>", "phase:1"]},
           {"title": "…", "level": 2, "priority": "high",
            "tags": ["explore-<topic-slug>", "phase:2"], "blocked_by": [0]}]}
EOF
```

The output is the created-id table (`epic`, `tasks[]`, `edges[]`); `$EPIC_ID` = `epic.id`. Then ONE PATCH appending the Task Index to the epic description:

```bash
api PATCH /task/$EPIC_ID --json "$(jq -n --arg d "<description + | Phase | ID | Title | Priority | Level | table>" '{description:$d}')"
```

**6-Cancel** (user chose Cancel): create only the report anchor —

```bash
api POST /task --json "$(jq -n --arg t "[Explore] <topic>" --arg d "<full report>" --arg p "$PROJECT" \
  '{title:$t, project:$p, card_type:"epic", priority:"low", description:$d, tags:["explore-<topic-slug>","explore-report"]}')"
```

Print: `Report saved to #$EPIC_ID. No implementation tasks created. Re-run /squad-explore <topic> to generate tasks later.`

### 7. Final summary

Show only the created-id table from the `create_tasks.py` output (epic row + one row per task: phase, id, title, priority, level), then:

> Exploration complete. N tasks created in `todo` for `<PROJECT>`; report stored in #$EPIC_ID.
> `/squad-refine <ID>` to add detail · `/squad-run <ID>` when ready to execute.

### 8. Coach (background)

Dispatch the Coach per `../squad/references/friction.md` with `skill_name=squad-explore`, `source_task=$EPIC_ID`, `run_summary="squad-explore generated an exploration report and phased tasks."`, `trajectory` = Explore findings + Plan output, `friction_signals` = agent errors / empty-result retries (`none` if clean). Launch in the background — do not block completion; surface only if it filed friction.

### Guardrails

- Never write, edit, or create source files.
- Every report claim cites a file path or found pattern; no clear pattern → say so explicitly.
- Only one sensible direction → present one; do not fabricate alternatives.
- Each task must be completable independently in one pipeline run; split tasks touching more than 3 unrelated files.
- The report is always saved to the board (the epic anchor), even on Cancel.
