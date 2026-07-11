# Subagent Prompts

Render each prompt by filling the `<PLACEHOLDERS>`; pass the rest verbatim.

## Explore prompt (fill `<TOPIC>`, `<PROJECT>`)

```
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
```

## Plan prompt (fill `<TOPIC>`, `<PROJECT>`, `<EXPLORE_FINDINGS>`)

```
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
```
