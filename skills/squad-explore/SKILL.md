---
name: squad-explore
description: Codebase exploration skill for uncertain implementation direction. Deeply explores the codebase, produces a direction report, and creates phased squad tasks. Use when you don't know exactly how to implement something. NOT for direct implementation.
license: MIT
---

> Shared context: read `../squad/shared.md` for project config & auth, pipeline levels, status transitions, API endpoints, and error handling.
> Safety principles: read `../squad/principles.md` — **mandatory, not optional.**

## `/squad-explore [topic]` — Explore & Plan

**When to use**: You have a vague idea or problem but don't know *how* to implement it.
This skill explores first, reports direction, then seeds the squad board with phased tasks.
**This skill does NOT write code.**

---

### Procedure

```
① Receive and validate topic

   If topic is missing (no argument):
   → Immediately enter the clarification interview (skip to ①-B).

   ①-A Check for missing context (NOT word count):
   A topic lacks context if ANY of these are true:
   - No indication of which part of the codebase is involved
   - The "why" is completely absent (what problem does this solve?)
   - The scope is unbounded ("improve everything", "refactor")

   If context is missing → ①-B
   If the topic is self-sufficient (e.g. "add dark mode toggle to settings page") → skip to ②

   ①-B Clarification (one round, max 2 questions via AskUserQuestion):
   - "What problem are you trying to solve or what outcome do you want?"
   - "Is there a specific area of the codebase you suspect is involved, or is it unknown?"
   Do NOT ask more than 2 questions in this round.

② Deep codebase exploration (Task → Explore agent)

   Launch a Task subagent with subagent_type="Explore".
   Pass the following prompt — fill in <TOPIC> and <PROJECT> before launching:

   ───────────────────────────────────────────────
   You are performing a pre-implementation exploration for the topic: "<TOPIC>"
   Project: <PROJECT>
   Thoroughness: very thorough

   Investigate the following areas IN ORDER and report findings for each:

   A. PROJECT STRUCTURE
      - List top-level directories and their roles (1 line each)
      - Identify main entry files (main.ts, index.ts, app.ts, server.ts, etc.)
      - Read key config files: package.json (dependencies), tsconfig, vite.config or equivalent

   B. TOPIC-RELEVANT CODE
      - Find all files, modules, and components directly related to "<TOPIC>"
      - Identify existing patterns used for similar features (search by keyword)
      - Trace the data flow: where does data enter, how does it move, where does it exit?
      - Note any existing abstractions that could be extended vs. replaced

   C. PAIN POINTS & GAPS
      - Identify missing abstractions, obvious duplication, or inconsistent patterns
      - List all modules that "<TOPIC>" would need to touch
      - Identify potential conflicts with existing code or dependencies

   D. TECHNOLOGY CONSTRAINTS
      - Which libraries are already in use that are relevant? (from package.json)
      - What patterns does the framework enforce? (routing, state, DI, etc.)
      - What is the test/build/lint setup?

   Return your findings as a structured report with section headers A–D.
   For every claim, cite the exact file path and line number if possible.
   If you cannot find evidence for something, say "not found" — do not guess.
   ───────────────────────────────────────────────

② ½ Architecture planning (Agent → Plan subagent)

   Save the Explore agent's output as $EXPLORE_FINDINGS.
   Launch a second Agent subagent with subagent_type="Plan".
   Pass the following prompt — fill in <TOPIC>, <PROJECT>, and <EXPLORE_FINDINGS>:

   ───────────────────────────────────────────────
   You are performing architecture planning for the topic: "<TOPIC>"
   Project: <PROJECT>

   ## Codebase Findings (from Explore agent)
   <EXPLORE_FINDINGS>

   ## Your Task
   Based on the above codebase findings, produce the following three sections:

   ### 1. Possible Directions (2–3 options, only genuinely distinct ones)
   For each direction:
   - **Name**: concise label
   - **Approach**: 1–2 sentences, concrete not abstract
   - **Pros**: bulleted list
   - **Cons**: bulleted list
   - **Estimated complexity**: Low / Medium / High
   - **Files likely touched**: list specific files cited in the findings
   - **Risk**: any architectural risks or unknowns

   ### 2. Recommended Direction
   State which direction you recommend and WHY, citing specific file paths from the codebase findings.
   If only one direction makes sense, say so — do not fabricate alternatives.

   ### 3. Phased Task Breakdown (for the recommended direction)
   3–7 tasks in logical implementation order. Each task must be completable independently.
   The last task must always be E2E tests ("Add E2E tests for <topic>").

   For each task:
   - **Title**: concise imperative phrase
   - **Phase**: sequential number
   - **Rationale**: 1 sentence — why this step at this phase
   - **Files**: specific files this task will touch (from findings)
   - **Complexity**: Low / Medium / High

   Honesty rules:
   - Every claim must reference a file path from the Explore findings.
   - If something is unclear from the codebase, say "unclear — needs investigation".
   - Do not invent patterns that were not found in the codebase.
   ───────────────────────────────────────────────

   Save this output as $PLAN_OUTPUT.

③ Write the Exploration Report

   Using $EXPLORE_FINDINGS (Explore agent) and $PLAN_OUTPUT (Plan agent), write the following report.
   This report will be stored permanently in the squad board.

   ┌─────────────────────────────────────────────┐
   ## Exploration Report: <topic>
   *Explored: <ISO timestamp> | Project: <PROJECT>*

   ### Current State
   [2–4 sentences: what exists today that is directly relevant to this topic.
    Reference specific files.]

   ### Key Findings
   - <finding> (`path/to/file.ts:line`)
   - <finding> (`path/to/file.ts:line`)
   - ... (list all significant findings)

   ### Possible Directions

   [Copy from $PLAN_OUTPUT § "Possible Directions" — do not paraphrase or rewrite]

   ### Recommended Direction
   [Copy from $PLAN_OUTPUT § "Recommended Direction" — do not paraphrase or rewrite]
   └─────────────────────────────────────────────┘

   Honesty rules:
   - Directions and recommendation come verbatim from the Plan agent's output.
   - If the Plan agent said "only one direction makes sense", present one. Do not fabricate alternatives.
   - If the codebase gives no signal on something, say "unclear from codebase".

④ Present report + ask user to choose direction

   Print the full Exploration Report to the user.

   Then use AskUserQuestion:
   - One option per direction (e.g. "Direction A: <name>")
   - "Cancel — save report only, don't create tasks"

   If user selects Cancel → jump to ⑥-Cancel.

⑤ Generate phased squad tasks

   ⑤-A Use the task breakdown from $PLAN_OUTPUT.
   The Plan agent already produced a phased task list — use it directly.
   Re-derive tasks only if the user selected a direction other than the Plan agent's recommendation.

   Map each task to squad fields:
   - title: from Plan output (already imperative verb phrase)
   - phase: sequential number (1, 2, 3…) — used as a tag
   - priority: high (phase 1–2), medium (phase 3–4), low (phase 5+)
   - level: L2 or L3 based on complexity from Plan output
   - tags: ["explore-<topic-slug>", "phase:<N>", "<module-tag>"]  (JSON array — the canonical stored format)

   **The LAST task must always be an E2E test task.**
   Title format: "Add E2E tests for <topic>"
   Description should cover: key user flows to verify, happy path + edge cases,
   which pages/endpoints to test, and acceptance criteria.
   Priority: medium, Level: L2, extra tag: "e2e-test"

   ⑤-B Create the epic anchor FIRST.
   This special **epic card** (`card_type:'epic'`) anchors the topic and stores the full
   exploration report. It is a structured container — implementation tasks are attached to it via
   `parent` edges (below), NOT via an `epic:` tag (that convention is retired — see
   `../squad/shared.md` → **Task Relationships & Epics**).

   card_type: "epic"
   title: "[Explore] <topic>"
   priority: low
   tags: ["explore-<topic-slug>", "explore-report"]   (no `epic:` tag)
   description:
     <full Exploration Report from ③>

     ---
     ## Task Index
     *(populated after all tasks are created — see below)*

   Save the returned ID as $REPORT_ID (this is the epic id).

   ⑤-C Create implementation tasks in phase order.
   For each task, include this block at the bottom of the description:

     ---
     ## Exploration Context
     *Auto-generated by /squad-explore on <timestamp>*
     **Explore report**: #$REPORT_ID
     **Direction chosen**: <Direction name>
     **Phase**: <N> of <total>
     **Rationale**: <1–2 sentences: why this step at this phase>

   Save each returned ID in order: $IDS = [id1, id2, ...]

   After creating each implementation task, attach it to the epic via a structured parent edge
   (single-parent → 400 on a second parent, surfaced not pre-checked):
   ```bash
   api POST /task/$CHILD_ID/relationships --json "$(jq -n --arg to "$REPORT_ID" '{to:$to, type:"parent"}')"
   ```

   ⑤-D Patch the report anchor task with the task index.
   After all tasks are created, PATCH $REPORT_ID description to append:

     ## Task Index
     | Phase | ID   | Title              | Priority | Level |
     |-------|------|--------------------|----------|-------|
     | 1     | #id1 | Add X              | high     | L3    |
     | 2     | #id2 | Refactor Y         | medium   | L2    |
     ...

   Use API:
   ```bash
   # Create the epic anchor (⑤-B) — card_type:"epic"
   api POST /task --json "{\"title\": \"[Explore] <topic>\", \"project\": \"$PROJECT\", \"card_type\": \"epic\",
          \"priority\": \"low\", \"description\": \"...\", \"tags\": [\"explore-<topic-slug>\", \"explore-report\"]}"

   # Create an implementation task (⑤-C) — no epic: tag
   api POST /task --json "{\"title\": \"...\", \"project\": \"$PROJECT\", \"priority\": \"high\",
          \"level\": 3, \"description\": \"...\", \"tags\": [\"explore-<topic-slug>\", \"phase:<N>\"]}"

   # Attach the implementation task to the epic via a structured parent edge
   api POST /task/$CHILD_ID/relationships --json "$(jq -n --arg to "$REPORT_ID" '{to:$to, type:"parent"}')"

   # Patch report anchor (epic) description with the task index
   api PATCH /task/$REPORT_ID --json "{\"description\": \"<updated description with task index>\"}"
   ```

⑥ Output final summary

   Print:

   | Phase | ID           | Title              | Priority | Level |
   |-------|--------------|--------------------|----------|-------|
   | —     | #$REPORT_ID  | [Explore] <topic>  | low      | L1    |
   | 1     | #id1         | Add X              | high     | L3    |
   | 2     | #id2         | Refactor Y         | medium   | L2    |
   ...

   Then print:
   > Exploration complete. N tasks created in `todo` for project `<PROJECT>`.
   > Full report stored in task #$REPORT_ID.
   > Run `/squad-refine <ID>` on any task to add more detail before starting.
   > Run `/squad-run <ID>` when ready to execute.

   ⑥-Cancel (user chose Cancel):
   Create only the report anchor task (⑤-B) with the full report, no implementation tasks.
   Print:
   > Report saved to task #$REPORT_ID. No implementation tasks created.
   > Run `/squad-explore <topic>` again to generate tasks when you're ready.
```

#### → Coach (friction review of this run)

After the final summary (⑥ or ⑥-Cancel), dispatch the **Coach** per `../squad/shared.md` → **Coach Dispatch**. This skill does not resolve a provider during its own work, so resolve `MODEL_PROVIDER` + the `read_model` / `read_effort` helpers per `../squad/shared.md` → **Model Resolution** first, then pass:
- `skill_name` = `squad-explore`
- `source_task` = `$REPORT_ID`
- `run_summary` = `"squad-explore generated an exploration report and phased tasks."`
- `trajectory` = Explore-agent findings + Plan-agent output
- `friction_signals` = any agent errors / empty-result retries; `none` if clean

---

### Guardrails

- **No implementation**: This skill must NOT write, edit, or create source files.
- **No assumptions**: If the codebase has no clear pattern for something, say so explicitly.
- **Evidence-based**: Every claim in the report must cite a file path or code pattern found.
- **Honest about uncertainty**: If there is only one sensible direction, present one — do not fabricate alternatives.
- **Task granularity**: Each task should be completable independently in one pipeline run. Split tasks that touch more than 3 unrelated files.
- **Report is permanent**: The exploration report MUST be saved to the squad board (report anchor task) regardless of whether the user proceeds to task creation.
