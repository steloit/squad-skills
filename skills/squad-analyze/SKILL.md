---
name: squad-analyze
description: Read-only pre-implementation audit of a squad task — checks coverage (every acceptance criterion maps to a plan step), ambiguity, consistency, and principle alignment. Reports severity-tagged findings; never modifies the board. Run before /squad-run on a planned task.
license: MIT
---

> Shared context: read `../squad/shared.md` for project config & auth and the API endpoints.
> Safety principles: read `../squad/principles.md`.

## `/squad-analyze <ID>` — Consistency & Coverage Gate

A **read-only** audit of a task's artifacts *before* it goes to `impl`. It catches the
defects a holistic plan review tends to miss — uncovered acceptance criteria, contradictions
between the spec and the plan, unquantified terms, and principle violations. **It never
modifies the board** — it prints a findings report and a recommendation.

### Inputs

```bash
# the task's artifacts
curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=title,description,plan,done_when,tags"
```
Plus the rules to check against: `../squad/principles.md`, and `docs/decisions.md` if the repo has one.

### Build the inventory first (do this before judging)

- **Requirements** = the acceptance criteria / requirements in `description` (e.g. `## Acceptance Criteria`, `## Requirements`, "must" statements).
- **Plan steps** = the discrete steps in `plan`.
- **Completion checks** = the items in `done_when`.

### Detection passes

- **Coverage (bidirectional traceability)** — every requirement maps to ≥1 plan step **and** a
  `done_when` check. Flag any requirement with **no plan step** (gap) and any plan step / `done_when`
  item with **no source requirement** (orphan). (This is the RTM rule: no uncovered requirements, no orphans.)
- **Ambiguity** — vague, unquantified terms (`fast`, `scalable`, `secure`, `simple`, `robust`) and
  placeholders (`TODO`, `???`, `<…>`) in description / plan / done_when.
- **Consistency** — contradictions between description, plan, and `done_when`; terminology drift
  (same concept named differently); ordering contradictions.
- **Principle alignment** — any plan step that violates `../squad/principles.md` or a `docs/decisions.md`
  entry. **Principle/decision violations are automatically CRITICAL.**

### Severity

- **CRITICAL** — a principle/decision violation, or a requirement with zero plan coverage that blocks the task.
- **HIGH** — a contradiction, an untestable acceptance criterion, an ambiguous security/perf attribute.
- **MEDIUM** — terminology drift, a missing `done_when` check, an underspecified edge case.
- **LOW** — wording, minor redundancy.

### Output (print only — never PATCH the board)

```
## Analysis — task #<ID>

| ID | Category | Severity | Where | Finding | Fix |
|----|----------|----------|-------|---------|-----|
| C1 | Coverage | CRITICAL | description AC-3 | no plan step implements it | add a plan step / re-plan |

Coverage: <covered>/<total> requirements have a plan step · orphans: <n> · CRITICAL: <n>
```

### Gate

- **Any CRITICAL** → recommend resolving before `/squad-run` (re-plan, or `/squad-refine` if the spec itself is the problem).
- **Only LOW/MEDIUM** → safe to proceed; list improvements.
- Optionally offer concrete remediation, but **never apply it** (read-only).

### Rules

- **Read-only**: never PATCH the board or write files.
- **Don't hallucinate** missing sections — report what's actually absent.
- **Cite specific instances** (which AC, which plan step), not generic patterns.
- **Deterministic**: the same task should yield the same findings.
