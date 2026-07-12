# Skills v2 — designed from first principles (2026-07-13)

Premise: the runtime owns ALL execution. Skills are not orchestration, not
pipelines, not board glue. The design question is exactly one: **what work
still exists before and after autonomous execution?** Every skill must name
the human work it accelerates and the production evidence that the work is
real. Same bar as the runtime: evidence or it doesn't exist.

## 1. The work that actually remains (from our own production history)

**Before execution:**
- *Deciding what to build* — ambiguity resolution, tradeoffs, scoping.
  Irreducibly human+agent collaborative; no gate can replace it.
- *Making work runnable* — the single largest measured failure of the entire
  program was a BAD ISSUE (#61/SQD-1034: mis-diagnosis from correlated log
  noise; three arms of spend produced faithful non-fixes). No runtime
  component can fix a wrong card; the leverage is entirely upstream.
- *Deciding what is engine-ready* — every batch, the operator manually
  filtered cards (autonomously runnable? underdetermined semantics? needs
  browser verification? epic-sized?). Repeated manual procedure = skill.
- *Keeping repos legible to the engine* — F13/F14: command resolution
  failed or mis-resolved where AGENTS.md was absent/prose-y; the verify
  gate's trustworthiness starts at the repo's declared commands.

**After execution:**
- *Reviewing agent PRs* — the market's loudest pain (reviewer fatigue,
  >1-in-5 reviews involve an agent) and the place our own evidence says
  human judgment stays load-bearing (risk, intent, accountability).
- *Triaging failed runs* — the operator's most-repeated activity this month;
  it has a learned procedure (artifacts FIRST, then the step log — a lesson
  from misdiagnosing a baseline failure) that deserves encoding.
- *Learning from incidents* — the 7-step incident protocol produced the
  highest-value artifacts of the program (postmortem → A11 → observability).

## 2. Verdict on every existing skill

| v1 skill | Verdict | Reasoning |
|---|---|---|
| squad-run (6-role pipeline) | **KILL** | Duplicates the runtime wholesale; loses on every measured axis |
| squad-batch-run | **KILL** | Same |
| squad (board CRUD/shared plumbing) | **KILL** | Board is out of product strategy; trackers own tasks |
| squad-init (board onboarding) | **KILL, one idea survives** | Board-specific; the "make the repo ready" idea moves to `repo-ready` |
| squad-refine | **REBUILD as `refine`** | The purpose (ambiguity → contract) survives; the target changes from board cards to tracker issues; prompt glue trimmed |
| squad-explore | **KILL** | Was pipeline-feeding research; generic agents do this natively now |
| stats/board-view flows | **KILL** | The Run Console and (later) the flight recorder own this deterministically |
| coach/friction capture | **KILL** | Meta-process for the dead pipeline; the incident protocol replaced it with something better |
| PR-review skills | **REBUILD as `review`** | Real problem (market + our evidence), survives re-scoped to agent-PR interrogation |

Honest classification: roughly 70% of v1 was execution orchestration and
board glue — prompt-shaped workarounds for the absence of a runtime. The
runtime exists now. That code served its purpose: it was the research that
taught us what to build deterministically.

## 3. Skills v2 — five skills, each evidence-anchored

| Skill | The human work it accelerates | Evidence it's real | What it is NOT |
|---|---|---|---|
| **`issue`** | Turn a complaint/idea into a RUNNABLE issue: demand a repro command (feeds the runtime's red-green repro gate), separate observation from hypothesis (the #61 lesson, verbatim), EARS-style acceptance criteria, engine-readiness verdict | The costliest failure of the program was an unrunnable issue | Not a board writer; outputs a tracker-native issue |
| **`refine`** | Interactive scoping: split epics into engine-sized issues, resolve underdetermined semantics BEFORE spend (the exact card class where the spec ablation showed contracts pay 2×) | Ablation pair 1; epic-topology open question | Not a planner role in a pipeline |
| **`review`** | Help a HUMAN interrogate an agent PR: what would falsify this diff, which ACs lack tests, what the dossier says vs what the diff does | Review burden = market pain #1; humans keep risk/intent/accountability | Not a gate (the runtime's reviewer is the gate); this is reviewer augmentation |
| **`triage`** | Walk a failed run to root cause: artifacts first, then step log, then worktree; classify per the failure taxonomy | The operator's most-repeated manual procedure; the artifacts-first lesson is encoded knowledge | Not monitoring (the Run Console shows; triage reasons) |
| **`repo-ready`** | Audit/generate the repo's engine legibility: declared commands (AGENTS.md), env-file traps (the SQD-1037 class), hermeticity red flags | F13, F14, SQD-1037 — three real findings in the "engine can't trust this repo" class | Not scaffolding; an audit with fixes |
| *(candidate)* `postmortem` | Run the 7-step incident protocol on any production incident | Our own highest-value practice | Held until someone outside us wants it |

Non-duplication check against the runtime: none of the five executes,
verifies, reviews-as-gate, or touches git state. They all produce either
better inputs to the runtime (issue, refine, repo-ready) or better human
decisions after it (review, triage).

Distribution unchanged: portable SKILL.md via `npx skills` — the channel is
the one part of v1 that was validated as-is.

## 4. What deliberately does not exist in v2

No orchestrator, no pipeline, no board client, no stats, no memory system,
no "agent team" roleplay, no execution of any kind. If the runtime later
grows a capability gap, the answer is a runtime change through its playbook
— never a skill that papers over it (that is how v1 accumulated 70% glue).
