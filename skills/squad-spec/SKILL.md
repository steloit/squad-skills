---
name: squad-spec
description: Turn vague intent into a precise, executable spec through 5 structured phases, then optionally create a squad task. Use when starting something new that needs proper scoping before refinement. Complements /squad-refine (which refines existing tasks).
license: MIT
---

> Shared context: read `../squad/shared.md` for project config, auth, and task creation format.
> Safety principles: read `../squad/principles.md` — **mandatory, not optional.**

## `/squad-spec [title]` — New Feature Spec

Turns a rough idea into a structured spec through 5 phases, then optionally creates a squad task.

**When to use this vs `/squad-refine`:**
- `/squad-spec` — Starting from scratch. No task exists yet. Idea is vague.
- `/squad-refine <ID>` — Task already exists in backlog. Needs requirement clarification.

---

### Phase 1 — Problem Framing

**Goal**: Understand the real problem before discussing solutions.

Ask the user:
1. What user pain or business need is this solving?
2. Who experiences this problem? (user type, frequency)
3. What happens today without this feature? (workaround or nothing?)
4. Why now — what's prompting this? (deadline, user feedback, blocker?)

Extract and record:
```
PROBLEM_STATEMENT = one sentence: "[User type] can't [do X] because [root cause], causing [impact]"
```

If the user can't articulate a clear problem, probe further before proceeding. Do not move to Phase 2 until the problem is clear.

---

### Phase 2 — Scope Definition

**Goal**: Draw a hard boundary around what's in and out.

Ask:
1. What is the minimal version of this that solves the problem? (MVP scope)
2. What would be nice but is NOT required for this task?
3. Does this replace or extend existing functionality?
4. Any hard constraints? (deadline, tech stack, team size, API limits)

Record:
```
SCOPE_IN  = bulleted list of what's included
SCOPE_OUT = bulleted list of explicit exclusions
CONSTRAINTS = technical, time, or team constraints
```

Call out scope creep early: if the user mentions a "nice to have" that doubles the work, flag it and suggest splitting into a separate task.

---

### Phase 3 — Success Metrics

**Goal**: Define what "done and working" looks like from the user's perspective.

Ask:
1. How will you know this is working? (observable outcome)
2. Is there a measurable target? (latency, conversion rate, error rate, etc.)
3. What's the minimum bar for the first version? What would make it great?

Record:
```
METRICS = list of observable, preferably measurable outcomes
```

At least one metric must be verifiable — "it works" is not a metric.

---

### Phase 4 — Edge Cases & Risks

**Goal**: Surface the 20% of cases that cause 80% of bugs.

Based on the scope defined, identify:
- **Empty states**: What if there's no data? First-time user?
- **Error states**: What if an external dependency fails?
- **Boundary conditions**: Limits, maximums, empty inputs
- **Concurrent access**: Multiple users, race conditions
- **Rollback**: Can this be undone? What's the data impact?
- **Security**: Does this handle untrusted input? Auth required?

Ask the user to confirm edge cases are understood, or add any you've missed.

Record: `EDGE_CASES = list of identified edge cases`

---

### Phase 5 — Acceptance Criteria

**Goal**: Write the checklist that Builder and Shield will use to verify completion.

Synthesize everything from phases 1–4 into verifiable criteria:

```
## Acceptance Criteria
- [ ] [Functional: behavior visible to user]
- [ ] [Error handling: specific edge case is handled]
- [ ] [Performance: if metric defined]
- [ ] [Security: if auth/input involved]
- [ ] [Regression: existing behavior preserved]
```

Rules:
- Each criterion must be independently verifiable
- Use active voice: "User can X" not "X is implemented"
- No vague items like "works correctly" or "handles errors"
- 3–8 criteria is the right range; more than 8 means scope is too broad

---

### Output: Full Spec

Present the complete spec to the user:

```markdown
## Spec: [title]

### Problem
[PROBLEM_STATEMENT]

### Scope
**In:**
[SCOPE_IN]

**Out:**
[SCOPE_OUT]

**Constraints:** [CONSTRAINTS or "None identified"]

### Success Metrics
[METRICS]

### Edge Cases
[EDGE_CASES]

### Acceptance Criteria
[ACCEPTANCE_CRITERIA]
```

Ask the user: `[c] Create squad task / [e] Edit spec / [x] Discard`

---

### Create Squad Task (if user selects `[c]`)

Ask two final questions via AskUserQuestion:
1. Priority: critical / high / medium / low
2. Level: L1 (quick, <1h) / L2 (standard, <1d) / L3 (complex, multi-day)

Then resolve project config & auth (see `../squad/shared.md` → Project Config & Auth) and create the task via the board API. Build the body safely with `jq` so the multi-line description can't break the JSON (see `../squad/shared.md` → JSON Safety):

```bash
DESCRIPTION=$(printf '## Goal\n%s\n\n## Scope\n**In:**\n%s\n\n**Out:**\n%s\n\n## Acceptance Criteria\n%s\n\n## Edge Cases\n%s' \
  "$PROBLEM_STATEMENT" "$SCOPE_IN" "$SCOPE_OUT" "$ACCEPTANCE_CRITERIA" "$EDGE_CASES")

PAYLOAD=$(jq -n \
  --arg title "$TITLE" \
  --arg project "$PROJECT" \
  --arg priority "$PRIORITY" \
  --argjson level "$LEVEL" \
  --arg description "$DESCRIPTION" \
  '{title: $title, project: $project, priority: $priority, level: $level, description: $description}')

TASK_ID=$(curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/task" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" | jq -r '.id')
```

`LEVEL` is the integer 1/2/3. Output: "✅ Task #$TASK_ID created: $TITLE  → Run `/squad-refine $TASK_ID` to sharpen details, or `/squad-run $TASK_ID` to implement."
