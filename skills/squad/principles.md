# Squad Safety-First Principles

**Speed is not the goal. Doing it right is the goal.** These apply to every Squad skill
and every pipeline agent — read them before planning or implementing a card.

---

## Codebase-First Exploration (before planning)

- Don't assume — read the relevant files and existing patterns before you plan. A wrong
  assumption early quietly contaminates everything downstream.
- Map the existing interfaces, file structure, and dependencies, then fix scope.
- Follow patterns already in the codebase rather than inventing new ones.
- "It's probably wired like this" is forbidden — plan only from facts confirmed in the code.

## Card-Split Criteria

Split a card (or send it back to `/squad-refine`) if **any** hold:

- Estimated implementation time exceeds ~1 hour
- The change spans two or more layers (DB / service / UI / …)
- Rollback on failure would be complex — prefer small, reversible changes
- One or more requirements are still uncertain

## Pre-Flight Check (before status → `impl`)

- Is the card's completion condition (`done_when`) clear and **verifiable**?
- Are in-scope and out-of-scope stated, so the work can't drift?
- If this card fails, are the other cards unaffected?

## Done Means Verified (not "looks done")

- "Looks done" is not done. A card is complete only when its `done_when` checks have
  actually **run and passed** — show the evidence (the command run and its output,
  test results, build exit).
- Run the gates before handing off: format, lint, typecheck, tests; fix what fails.
- Fix the **root cause, not the symptom** — never suppress an error to make a check pass.

## Forbidden

- Starting implementation without refining first
- "Just ship it and clean up later" progress
- Expanding a card's scope mid-implementation
- Fixing friction with Squad itself inline, or leaving your task to chase it — if you notice friction with
  Squad itself — the skills/board/orchestrator you work *with*, not the project you work *on* (an ambiguous skill instruction, an awkward board API, a clunky orchestrator
  step, a weak template, a bug), **report it, don't fix it**: file a `friction` report per
  shared.md → "Squad Friction Reports" and continue your actual task. The worked project's own bugs
  are NOT friction reports — those belong on that project's board.
- Planning from assumptions without reading the codebase
- **Weakening a safeguard to pass review** — deleting or skipping tests, suppressing
  errors, or lowering a check instead of fixing the code
