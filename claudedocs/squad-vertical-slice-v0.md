# Vertical Slice v0 — Issue → Verified PR, Run recorded

> **HISTORICAL DESIGN RECORD** (frozen — see [claudedocs/README.md](./README.md)).
> Implemented 2026-07-12 as **steloit/squad-engine**; the engine's `ARCHITECTURE.md`
> describes the system as built (including deltas from this spec).

Status: spec · 2026-07-12 · implements the three-layer architecture (see
`squad-execution-architecture.md`, ADR 2026-07-12). This spec is written spec-first,
with EARS acceptance criteria — dogfooding the workflow it builds.

## Goal

Prove the wedge end-to-end **and** stand up the system-of-record's first execution-native
object (the *run*). One command takes a GitHub issue to a verified pull request, entirely
via a local-first engine, and records the run on the platform as an observer.

`objective`: from a GitHub issue, produce a spec-in-repo, implement it with a single
Builder loop, verify it with a deterministic test gate, open a PR with Human+Agent
attribution, and emit the run to the platform.
`non_goals`: Linear/Jira integration; multi-agent orchestration; governance/approvals/
memory; a hosted sandbox service; durable crash-resume; any board task-management UI.

## The flow

```
GitHub Issue #N
    │  (1) ingest: gh issue view → normalized work item
    ▼
Spec-in-repo  .squad/specs/<slug>.md   (2) EARS criteria + done_when, git-committed
    │
    ▼
git worktree @ base SHA                 (3) isolation — never the primary tree
    │
    ▼
Single Builder loop                     (4) plan inline → implement → write tests → run
    │
    ▼
Deterministic verify gate               (5) resolve repo test cmd → run → gate on exit code
    │  pass
    ▼
GitHub PR  (branch, commit, gh pr create)   (6) attribution: co-author + links to issue/spec/run
    │
    ├───────────── async, best-effort, OFF the critical path ─────────────┐
    ▼                                                                       ▼
(done — works fully offline)                             Platform: POST /runs  (7) the RUN object
```

Layer 3 (step 7) is *observe-only*: the slice completes fully with the platform offline.

## Components & interfaces

| # | Component | Mechanism (v0, no new heavy infra) | Deterministic? |
|---|---|---|---|
| 1 | **Ingest** | `gh issue view <N> --json title,body,number,url,labels` → work item | yes |
| 2 | **Spec gen** | agent turns the issue into `.squad/specs/<slug>.md` (schema below); `git add` | model authors, code commits |
| 3 | **Worktree** | `git worktree add .squad/work/<run_id> <base_sha>` | yes |
| 4 | **Builder loop** | one agent (Task tool / Claude Code) in the worktree: plan → impl → tests → run | model-driven inside |
| 5 | **Verify gate** | `engine verify`: resolve test cmd (AGENTS.md Commands → task runner → detect) → run → exit-code gate | **yes** |
| 6 | **PR** | `git commit` (co-author trailer) → `gh pr create` body links issue + spec + run_id | yes |
| 7 | **Run record** | `POST /orgs/<org>/runs` with the run object; async, `|| true` | yes |

The engine is a single script surface (`engine <subcommand>`) — the descendant of
`pipeline.py`, re-scoped: `spec`, `verify`, `pr`, `record`. Command-resolution and the
event model transfer directly.

## Schema — the in-repo spec (`.squad/specs/<slug>.md`)

Front-matter + markdown, git-versioned beside the code (kills spec drift):

```yaml
id: <slug>
source: https://github.com/<org>/<repo>/issues/<N>
objective: <one sentence>
non_goals: [ ... ]
criticality: low | standard | high      # routes effort (L1/L2/L3)
size_estimate: xs | s | m | l
acceptance_criteria:                     # EARS; each maps 1:1 to a test
  - id: AC1
    ears: "WHEN <trigger> THE SYSTEM SHALL <response>"
    category: happy | edge | failure
done_when:                               # executable checklist; the completion gate
  - "<concrete check, names the test/assertion>"
```

## Schema — the RUN object (system-of-record's first primitive)

`POST /orgs/<org>/runs` — the platform's *execution-native* object (not a task):

```json
{
  "run_id": "uuid",
  "source": {"kind": "github_issue", "url": "...", "repo": "...", "number": N},
  "base_sha": "…", "head_sha": "…", "branch": "…",
  "spec_ref": ".squad/specs/<slug>.md@<sha>",
  "level": "L2",
  "actor": {"agent": "Builder", "model": "…",
            "executed_by": "<PAT>", "on_behalf_of": "<human>"},
  "steps": [{"phase": "spec|build|verify|pr", "status": "…", "ts": "…", "tokens": N}],
  "verify": {"command": "…", "exit_code": 0, "passed": true},
  "artifacts": {"pr_url": "…", "commit": "…"},
  "cost": {"tokens": N, "usd": 0.0},
  "outcome": "merged_pending | verified | failed",
  "created_at": "…"
}
```

This is the seed of Layer 3: run history, execution graph (steps), attribution, cost —
all things a tracker structurally cannot hold. Everything else (approvals, governance,
memory) accretes onto this object later.

## Routing (effort by spec)

`criticality`/`size` on the spec picks the path — the same dial, now local:
- **L1** (low/xs): Builder loop → verify → PR. No separate spec ceremony, no review.
- **L2** (standard): spec + Builder loop → verify → independent review *iff* risk signal
  (files-touched > k, or `criticality: high`) → PR.
- **L3** (high): full EARS spec → human design gate → Builder loop → verify → review →
  human sign-off → PR.
v0 implements L1 + L2; L3's human gate is a follow-up.

## Acceptance criteria (this slice, EARS — dogfood)

- AC1 — WHEN `engine run <issue-url>` is invoked on a clean repo THE SYSTEM SHALL create
  `.squad/specs/<slug>.md` with ≥1 EARS acceptance criterion and a non-empty `done_when`.
- AC2 — WHEN the Builder loop completes THE SYSTEM SHALL have produced changes in an
  isolated worktree, never the primary working tree.
- AC3 — WHEN verify runs THE SYSTEM SHALL execute the repo's resolved test command and
  gate on its exit code (pass → PR; fail → loop back or stop, never PR on red).
- AC4 — WHEN verify passes THE SYSTEM SHALL open a GitHub PR whose body links the issue,
  the committed spec, and the `run_id`, and whose commit carries a co-author trailer.
- AC5 — IF the platform is unreachable THEN the run SHALL still complete and open the PR
  (record is async, best-effort).
- AC6 — WHEN the run finishes THE SYSTEM SHALL emit one RUN object with the schema above
  (or log-and-continue on platform error).

`done_when`:
- Running the slice on a seeded test repo issue produces a green-tests PR (dogfood on the
  `slugify` smoke task first — it already passed the old pipeline).
- Verify refuses to open a PR when tests fail (negative test).
- With `SQUAD_BASE_URL` pointing nowhere, the PR still opens (AC5 proven).

## Build tasks (ordered)

1. `engine verify` — deterministic command resolution + run + exit-code gate (this is the
   Ranger replacement; smallest, highest-value, testable in isolation).
2. `engine spec` — issue → `.squad/specs/<slug>.md` (EARS + done_when), git-committed.
3. Worktree lifecycle — `add` at base SHA, `cleanup` on done.
4. Builder loop wiring — one agent in the worktree (plan+impl+tests), consuming the spec.
5. `engine pr` — commit (co-author) + `gh pr create` with the linked body.
6. `POST /runs` endpoint (platform, thin) + `engine record` (async emit).
7. Tests: verify gate (pass/fail), worktree isolation, offline-still-PRs, run-object shape.

## Out of scope (explicit, deferred)

Linear/Jira; multi-agent; sandbox service (E2B/Modal) — local worktree suffices for v0;
durable crash-resume; Layer-3 governance/approvals/memory/cost-dashboards; the board's
task UI. Each earns its place later against the "trackers can't do this" test.
