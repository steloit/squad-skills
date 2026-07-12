# Squad Execution Architecture — the model I'd build from scratch

Status: proposal · 2026-07-12 · supersedes the 6-role pipeline
Basis: three production-focused research sweeps (agentic loops, harness engineering, spec-driven development) + our own board data. This document argues for a specific architecture and is willing to conclude "cut it."

---

## 0. Thesis

**The code-writing path should be a single continuous agent loop wrapped in a thick deterministic harness — not a relay of fresh-context specialist agents.** The spec is the contract; verification is code, not an LLM; independent review is reserved for the ~14% of work that is genuinely high-stakes. Squad's durable value — the board as an attributable, reviewable Human+Agent record — is preserved by making the board the run's event log, not by keeping six agents.

This is a reversal of our current design, and the evidence for it is unusually one-sided.

---

## 1. Evidence base (condensed, cited)

### Execution loops — single-agent won for coding
- Every production coding agent examined runs a **single-threaded gather→act→verify loop over one flat context**: Claude Code, OpenAI Codex ("repeat until the model emits an assistant message instead of a tool call"), Devin, Amp's main thread, Aider, Cursor (interactive), SWE-agent. None ships a multi-agent relay as the per-task default.
- **Both labs agree coding is the wrong fit for multi-agent.** Anthropic (who shipped a *winning* multi-agent research system): "most coding tasks involve fewer truly parallelizable tasks… multi-agent breaks when agents share the same context or involve many dependencies." Cognition ("Don't Build Multi-Agents"): "use a single-threaded linear agent"; multi-agent produces conflicting implicit decisions.
- **Subagents are context-isolation firewalls, not pipeline stages.** Their job is to burn tokens on a bounded task in a separate window and return a distilled 1–2k-token result (Anthropic's own number). Amp: "multiplication of context windows." Advisory reasoning only (Amp's read-only Oracle) — "additional agents contribute intelligence, not actions."
- **Tools > orchestration.** SWE-agent tripled its score by improving only the agent-computer interface at a fixed model; Anthropic "spent more time optimizing our tools than the overall prompt." Claude Code is reported ~98% deterministic harness / ~2% model logic.
- **Serialize writes; parallelize only reads/exploration.** Amp states it operationally: "any edits that touch the same file(s) or mutate a shared contract must be ordered."
Sources: anthropic.com/engineering/{building-effective-agents, multi-agent-research-system, writing-tools-for-agents, effective-context-engineering-for-ai-agents}; cognition.com/blog/{dont-build-multi-agents, devin-sonnet-4-5-lessons-and-challenges}; openai.com/index/unrolling-the-codex-agent-loop; SWE-agent ACI (arxiv 2405.15793); ampcode.com/manual; aider.chat.

### Harness engineering — reliability is manufactured, not sampled
- **Harness = the product.** SWE-agent 3× from the interface alone; LangChain moved 30th→5th on Terminal-Bench by optimizing only the harness, model unchanged. Agent = Model + Harness.
- **Verify with code; judge with a model only when you must.** Every system gates on deterministic test/build/lint execution (SWE-bench fail-to-pass; Jules "verifies changes work before opening a PR"; Codex runs validation in-loop). SWE-agent pushes it to the edit granularity (a linter rejects a syntactically-invalid edit before it lands).
- **Durable, event-sourced execution.** The run is a replayable log; completed steps return cached results on resume → "you pay for each LLM call exactly once" (Inngest). A checkpoint is not durability without automatic failure detection + resumption (Diagrid).
- **Sandbox per run** at a pinned SHA; **never share a working tree** between concurrent runs (Cursor uses a git worktree per parallel agent). Phased network (open for setup, off during the agent phase — Codex).
- **Deterministic/probabilistic dividing line:** code owns state transitions, git ops, verification execution + gate, retries/breakers, persistence/replay, tool dispatch; the model owns the plan, the edit content, and judgment. Cognition's MapReduce is the exemplar — "the agent authors selectors; the deterministic pass produces a finite work queue; coverage is guaranteed by construction."
- **Stop-conditions:** no-progress detection (2–3 identical tool calls), a hard step ceiling, terminate-and-escalate after ~3 consecutive same-step failures — *not* blind retry.
Sources: openai.com/index/harness-engineering; faros.ai/blog/harness-engineering; cognition.com/blog/{devin-fusion, testing-development}, devin.ai/blog/agentic-map-reduce; swe-agent.com/1.0/background/aci; inngest.com/blog/durable-execution-key-to-harnessing-ai-agents; diagrid.io (checkpoints-are-not-durable-execution); factory.ai; Codex cloud env docs.

### Spec-driven development — spec replaces the prompt, criteria become the gate
- Convergent shape (Spec Kit, Kiro, OpenSpec, Claude Code): **Requirements (what + acceptance criteria) → Design/Plan (how) → Tasks (atomic, criterion-linked) → Implement → Verify.**
- **The spec replaces the ambiguous prompt, not the planner.** Kiro and Spec Kit keep a distinct design/plan gate — the architecture-coherence review is the cheapest place to catch an error.
- **Acceptance criteria in EARS format** (`WHEN <trigger> THE SYSTEM SHALL <response>`, + IF/WHILE/WHERE/ubiquitous) map 1:1 onto tests (precondition=setup, trigger=act, SHALL=assert). `done_when` as an executable checklist per task turns criteria into the completion gate — this **replaces open-ended "does this look right?" review with criterion-conformance checking** (but not human sign-off on whether the spec itself is right — "confidently-wrong spec" is the deepest failure mode).
- **Strongest human gate at design approval, not final code review.** Review moves upstream and narrows.
- **Route spec depth by size/criticality.** The #1 criticism is ceremony on trivial work (Kiro turned a one-line bug into 4 stories + 16 criteria — "a sledgehammer to crack a nut"). Skip SDD for trivial; full SDD for complex/critical/high-blast-radius.
Sources: github/spec-kit; kiro.dev/docs/specs; EARS (Mavin, RE'09); Fowler "SDD 3 tools"; Allegro SDD best-practices; Addy Osmani "good spec"; Sean Grove "The New Code".

### Our own board data (226 done tasks)
- Levels: L1=21, L2=93, **L3=112** — over-weighted to the heaviest path.
- **LLM gates reject 12.3% (Critic) / 14.2% (Inspector); rubber-stamp ~86%.** Matches RouteLLM's finding that routing ~14% of work to the strong path recovers 95% quality at 85% cost cut. The 12–14% *is* the natural hard fraction. Pushing gates to "catch more" buys false positives (LLM reviewers wrongly flag correct code 22–40% of the time).
- The pipeline is **agent-bound**: wall-clock is dominated by sequential agent invocations, so the only structural speed lever is *fewer agents on the common path*.

---

## 2. What the current architecture gets wrong

| Current | Verdict | Why |
|---|---|---|
| Planner → Critic → Builder → Shield → Inspector → Ranger, each **fresh-context**, relaying partial state | **The multi-agent-relay anti-pattern for coding** | 4 agents each re-ingest the repo; none sees the others' trace; conflicting implicit decisions; ~15× token cost for a sequential-dependent task |
| Shield as a **separate test-author** agent | **Cut** | Resolve-rate change from a separate test-author is statistically insignificant (all p>0.05); generic separate-TDD *raised* regressions to 9.94% |
| Ranger as an **LLM test-runner** | **Cut** | Re-runs tests the Builder already ran; value is the test *result*, which is deterministic — an LLM adds tokens/latency for zero signal |
| Gates applied at **L2/L3 by default** (112 of 226 tasks were L3) | **Over-applied** | 86% rubber-stamp; effort must be *routed*, not uniform |
| Runs share **one git working tree** | **Known bug** (we wiped uncommitted work once) | Research mandates worktree/sandbox per run |
| Verification is an **LLM judgment** (Ranger) | **Wrong layer** | Verify with code (exit codes), judge with a model only for subjective quality |

What it gets **right** (keep): `pipeline.py` as a deterministic spine; the correlation-id activity stream as an event log; role-boundary (a reviewer records a verdict and edits nothing); the spec (from refine) as a contract; levels as an effort dial.

---

## 3. The architecture I'd build from scratch

### Principle: one agent writes; the harness owns everything else.

```
                          ┌─────────────────── deterministic harness (pipeline.py) ───────────────────┐
  spec (contract) ──▶ │  preflight → worktree(SHA) → dispatch ONE Builder loop → verify(gate) →   │
  done_when (EARS)     │  [review @ high stakes] → finalize(commit) → event-log(board) → coach     │
                          └── durable/resumable · circuit-breaker · git ops · all deterministic ─────┘
```

### 3.1 One continuous Builder loop (replaces Planner+Builder+Shield)

A **single agent, continuous context** that: reads the spec → gathers context (repo map/search) → writes its plan to the board (the audit artifact) → implements → writes its own tests → runs the real suite → iterates until green or the breaker trips. No hand-off, no context re-ingestion, no lost trace. This is the loop every production system converged on.

- **Plan-then-build without a hand-off.** The plan is still an artifact (written to the board's `plan`/`decision_log`/`done_when` for the audit trail and the high-stakes gate), but it is produced *inside the Builder's own continuous context* — not by a separate Planner agent that then hands a cold repo to a separate Builder. At L3, a gate reviews the plan *before the same Builder proceeds* (the cheapest correction point).
- **Tests are the Builder's job** (fold in Shield). The evidence says a separate test-author moves nothing; the Builder writing tests inline is as good and cheaper.

### 3.2 Deterministic verify gate (replaces Ranger)

A new harness step — `pipeline.py verify` — that **resolves the repo's real test/lint/build command** (AGENTS.md Commands → task runner → language detect, the existing ladder) and **runs it, gating on exit code**. No LLM. This is the reliable external-feedback signal every system uses. The Builder's `done_when` (EARS acceptance criteria) is the checklist; verify proves it.

### 3.3 Independent review — only at high stakes, boundary-enforced

One fresh-context reviewer (the Inspector, kept) that records a verdict and **edits nothing** (Factory's rule: "prevents the review droid from silently patching its own complaints"). Applied at L3, and at L2 only when a risk signal fires (files-touched / criticality). Lean prompt (verbose review prompts manufacture false positives). This is the one LLM gate the data says earns its ~14%.

### 3.4 Levels become genuine effort routing

| Level | Path | For |
|---|---|---|
| **L1 Quick** | Builder loop → verify → done | one-file fixes, config, field adds, docs |
| **L2 Standard** | Builder loop (plan+impl+tests) → verify → [review if risk signal] → done | features, bug fixes, refactors |
| **L3 Full** | refine→spec (EARS criteria) → **design gate** (human/Critic) → Builder loop → verify → **independent review** → human sign-off | high blast-radius, critical (auth/data/migrations), unattended |

Agent invocations on the common path drop from **{L1:1, L2:4, L3:6}** to **{L1:1, L2:1–2, L3:2–3}**. Defaults shift *down* (today's L3-heavy distribution should invert). This is where the real, structural pipeline speed-and-cost win comes from — fewer agents, the thing that dominates wall-clock.

### 3.5 The harness becomes a durable, isolated engine

Extend `pipeline.py` (it is already the spine) with the production patterns:

- **Worktree/sandbox per run.** Each run gets its own `git worktree` at a pinned SHA (fixes the shared-tree bug; enables safe parallelism — the only place multi-agent helps coding is *infrastructure-isolated* parallel runs, Cursor-style).
- **Durable/resumable.** The board activity stream is already an event log with correlation ids; make the run resumable from the last recorded step (completed steps return their recorded result; a crash resumes without re-running an LLM call). This is our version of Inngest/Temporal replay, using the board as the event store.
- **Circuit breaker, generalized.** Keep the review-count breaker; add no-progress detection (repeated identical tool calls) and a step ceiling; terminate-and-escalate, not blind retry.
- **Deterministic ownership:** state transitions, git ops, verify execution + gate, retries, persistence, worktree lifecycle — all code. The model owns only the plan, the edits, and review judgment.

### 3.6 Spec schema upgrade (drives everything downstream)

Refine already produces a spec. Upgrade it to be maximally useful downstream (Kiro + Spec Kit + Allegro + Osmani):

- `objective` + `non_goals` (prevents over-broad implementations).
- `acceptance_criteria[]` in **EARS format**, each with a stable `criterion_id`, tagged happy/edge/failure (forces coverage).
- `done_when[]` — executable checklist, each item naming the concrete check; the **completion gate**.
- **Traceability**: `requirement_refs` / `criterion_id` so an analyzer can prove every criterion has a test (the `squad-analyze` audit is exactly this).
- `criticality` + `size_estimate` → **the routing signal** for L1/L2/L3 (the fix for SDD-ceremony-on-trivial-work).

Spec depth routes by size/criticality: trivial → thin objective+criterion, no refine ceremony; complex/critical → full EARS spec + design gate.

---

## 4. What stays uniquely Squad (not thrown out)

The research is about *coding agents*; Squad is a **Human+Agent task-board platform**. The board is the durable, attributable record — and that value is model-independent. So:

- The **board is the run's event log** (plan, decision_log, done_when, verdicts, activity, correlation ids) — now doubling as the durable-execution store.
- **Human+Agent attribution** (actor kind, delegation chain) — kept; it's the platform's differentiator.
- **The audit trail is a feature, not overhead** — it's what makes unattended agent work reviewable. Independent review + human sign-off at high stakes stays.

We are not becoming a bash-loop CLI. We are fixing the *execution model inside* a board platform to match what actually works.

---

## 5. Migration (nothing released → no compat shims)

1. **Collapse roles**: `pipeline.py` dispatches ONE Builder (plan+impl+tests) instead of Planner→Builder→Shield. Delete `tdd-tester.md`; fold test-authoring into `worker-agent.md`. Update `models.json` (drop `shield`, `ranger`).
2. **Deterministic verify**: implement `pipeline.py verify` (command resolution + run + exit-code gate); delete `test-runner.md` and the Ranger dispatch.
3. **Worktree isolation**: `pipeline.py` creates a per-run worktree at a pinned SHA; finalize commits there; cleanup on done.
4. **Routing**: `criticality`/`size` on the spec drives level; shift defaults down; L2 review becomes conditional on a risk signal.
5. **Spec schema**: extend the refine output (EARS criteria, criterion_id, done_when checklist, criticality).
6. **Resumability**: add resume-from-last-recorded-step to `pipeline.py` using the activity log.
7. **Tests**: rewrite the Shield/Ranger contract tests as verify-gate + single-Builder-loop tests; keep role-boundary tests for the Inspector.

Roles: **6 LLM agents → 2 core (Builder, Inspector) + Planner/Critic folded into the Builder-with-a-gate + Refiner for L3 specs.** Deterministic verify replaces Ranger; the Builder absorbs Shield.

---

## 6. Honest open questions

1. **How much of durable-execution to build now** vs later — full resume-from-crash is real engineering; the board already gives us the event log, but leases/idempotency for concurrent recovery is non-trivial. Recommend: worktree isolation + verify gate now; full durable-resume as a fast-follow.
2. **The design gate at L3** — human-owned (Squad is Human+Agent, so a human at the intent gate is the natural "confidently-wrong-spec" backstop) or a Critic agent? Evidence favors human at intent; Critic as an optional assist.
3. **Where the Builder loop actually runs** — in-session via the Task tool (works today) vs a real sandbox service (E2B/Modal/Daytona) for unattended/parallel runs. Recommend: Task tool + worktree now; sandbox service when we do unattended batch.
4. **Verify command resolution in code** — `pipeline.py` needs a robust resolver (AGENTS.md → task runner → detect). Clean to build; must handle the no-tests-declared case gracefully.

---

## 7. The deeper question: is the hosted board the right abstraction?

With all constraints removed, the honest analysis has to challenge the board itself. There are two separable questions, and conflating them is the current design's original sin.

- **Q1 — Execution model** (how an agent builds code): settled by the evidence. Single loop + deterministic harness + git-centric. Not in doubt.
- **Q2 — Product abstraction** (where the durable artifacts live and what coordinates the work): a hosted multi-tenant board, or a local-first, git-versioned, spec-kit-style workflow?

### The surprising finding: every production system for this is local-first

**Not one** of the production SDD/coding-agent systems is a hosted board. GitHub Spec Kit, Amazon Kiro, OpenSpec, Tessl — all put the spec/plan/tasks as **files in the repo, versioned in git**. Aider, Claude Code, Codex-CLI — repo-local. The async cloud systems (Codex-cloud, Google Jules, Devin) execute in a **local sandbox** (git clone at a SHA); their hosted surface is a *dashboard/queue where humans kick off and review*, not a store the agent reads/writes on every tool call. The market has voted: **coding artifacts live in the repo; the hosted layer, if any, observes.**

Two hard architectural consequences for our current board-as-driver design:

1. **Network is in the hot loop.** Every pipeline step is a REST round-trip. We felt this all session — 8s writes, timeouts, a full outage. A local-first core has *zero* network in the critical path. Simpler, faster, more reliable — by construction.
2. **The spec is divorced from git.** SDD's central discipline is that the spec is co-versioned with the code ("update the spec after every change," versioned in git alongside it). Storing the spec in Postgres, separated from the repo's history, *builds in* the spec-drift failure mode. The durable spec belongs in the repo.

### But the board solves a different problem than Spec Kit

Spec Kit is not Linear. The production coding tools solve *"one dev + agents in one repo."* Squad's stated pitch is *"a Human+Agent **team** coordinating work across a shared board"* — cross-actor attribution, delegation chains, multi-project, persistent shared state. Local files don't coordinate a team. That's a real, different product — Linear/Jira for Human+Agent teams — **and it's only valuable if (a) that's the product bet and (b) there's actually a team.** Today the project's own record says sole dev; the team-coordination value is ~zero *right now* and entirely future/bet-contingent.

### The resolution: separate execution from coordination, and invert the dependency

The current design conflates them and points the arrow the wrong way: **the board drives execution.** Every production system does the opposite: **execution is local and git-centric; it emits to a coordination surface that observes.**

```
  ┌──────────────────────────────────────────────────────────┐
  │  Layer 1 — LOCAL EXECUTION CORE (the foundation)          │   must be local-first
  │  spec-in-repo (EARS, git-versioned) → single Builder loop │   (all evidence)
  │  → deterministic verify gate → worktree/sandbox → git     │   zero network in the loop
  │  run trace = local event log (.squad/runs, git-committed) │
  └───────────────────────────┬──────────────────────────────┘
                              │  emits events (async, best-effort, OFF the critical path)
                              ▼
  ┌──────────────────────────────────────────────────────────┐
  │  Layer 2 — COORDINATION / ATTRIBUTION SURFACE (optional)  │   valuable IFF team
  │  the board, DEMOTED to observer: cross-actor attribution, │   never drives execution
  │  cross-project view, delegation chains, async queue       │   a run completes with it offline
  └──────────────────────────────────────────────────────────┘
```

This fixes everything at once: network leaves the hot loop; the spec co-versions with code; execution matches every production system; and the team-coordination bet survives as a *thin upper layer we invest in when a team materializes* — not as a fat orchestrator in the critical path.

### Correction: local-first execution ≠ local-only product

An earlier draft of this section slid from "execution should be local-first" (evidence-backed) to "don't own a platform" (an overreach). Those are two different claims. The evidence constrains *where execution runs* (local/sandbox, git-centric). It does **not** say the product is local-only. The dominant shape of durable developer-tool businesses is exactly the opposite: a **commoditized local engine + a platform that holds the value on top of it.**

- git (local, free) → **GitHub** (collaboration + system of record = the moat)
- Docker (local) → **Docker Hub**
- Terraform (local) → **Terraform Cloud** (governance)
- k8s (local cluster) → **Rancher / OpenShift** (management)

In every case the local tool commoditizes and the platform wins, because the platform does what the local tool structurally can't: history, collaboration, governance, org-level state. And the production tell: **Devin ships a web UI not to manage tasks (GitHub exists) but to *observe execution*.** Once a run takes hours you need somewhere to watch, approve, and audit it. The platform primitive is the **run**, not the task — and a tracker cannot be a run.

### The three-layer architecture (moat is the top layer)

```
1. LOCAL EXECUTION ENGINE   spec-driven · single loop · deterministic verify · worktree/sandbox · git-centric · offline
   (git/docker/terraform)   → table stakes, commoditizing; must be excellent, not the moat
                                        │ artifacts: PR + run trace
2. INTEGRATION              GitHub Issues/PRs · Linear · Jira   → the wedge + distribution; meet teams where they are
                                        │ emits run events (async, best-effort, OFF the hot path)
3. AI EXECUTION RUNTIME /   run history · execution graph · agent transcripts · verdicts · approvals · governance/policy ·
   SYSTEM OF RECORD         cost · org memory · reusable specs — Human+Agent attribution is the core IP
   (github/dockerhub/tf-cloud)  → the MOAT: solves what trackers structurally can't; "OS for AI employees"
```

### The discipline that keeps Layer 3 from becoming Jira

The real failure mode is not "having a platform" — it is the platform **drifting back into task management.** Guardrail on every platform feature: *"Can GitHub or Linear already do this? If yes, don't build it."* The platform earns its place only by solving AI-execution problems (observe runs, govern autonomous agents, remember across runs), never by re-implementing columns / drag-drop / CRUD. Start minimal (run history + observation + audit) and accrete governance/memory/coordination as execution *volume* creates the need.

### Honest scope: re-conceive the surface, keep the foundation

The *current* board is built on **task primitives** (columns, priority, CRUD — Jira DNA). The execution runtime needs **run primitives** (run, execution graph, transcript, verdict, approval, spec-version, cost, memory). So this is bigger than demote-and-keep: **keep the hard infrastructure** (multi-tenancy, auth, RLS, the event model, Human+Agent attribution) and **rebuild the product surface around the run, not the task.** The reusable engine pieces (`pipeline.py`, command resolution, the event model, the spec/refine concept, the attribution model) all transfer.

### Recommendation & sequencing

The moat is the *later* layer, so the build order follows git-before-GitHub:

1. **Now — Local execution engine + GitHub Issues integration** (the wedge): issue → spec-in-repo → single-loop verified build → PR with attribution. Runs offline; zero platform dependency in the hot path.
2. **Concurrent but thin — Platform records the run** as its first execution-native primitive (the system-of-record's first object). Observe + audit only.
3. **As volume grows — deepen Layer 3** into governance, approvals, org memory, multi-agent coordination — each feature passing the "trackers can't do this" test.

**Rejected:** the current board-driven model (network in the hot loop, spec off-git, no production precedent) and "own a Jira clone." **Adopted:** local-first execution + integration for distribution + a platform whose job is the runtime and system of record for AI work.

