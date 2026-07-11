# Skill Evaluation Framework — Redesign

Status: proposal · 2026-07-11 · supersedes the architecture described in EVALS.md
Scope: evaluation of individual Skills (SKILL.md packages), not multi-agent orchestration.

---

## 1. Critique of the current approach

### What the current harness gets right (keep these)

- **Two-axis scoring** — deterministic board-truth as the hard gate, LLM rubric as a
  quality signal — matches the field-wide "grader ladder" (deterministic where possible,
  LLM where necessary). The board-state check is exactly tau-bench's objective-grading
  pattern: final DB state + required substrings, no judge needed for correctness.
- **Git-versioned `history.jsonl`** as the local, diffable result store; no SaaS coupling.
- **Floor + Welch's t-test** regression gating is more statistical rigor than most
  in-house harnesses have.
- **Keyless judge chain** (API key → Ollama → CLI login) keeps evals runnable anywhere.
- **Snapshot-diff cleanup** of the live board after every trial.

### What is broken (evidence from the 2026-07-11 A/B run + code reading)

1. **Scenario contracts are stale — they test retired wire behavior.** All refine
   scenarios gate on `description_contains_any: ["## Goal", …]`, but refine (old AND
   new) writes the structured `spec` field and never touches `description`. These
   scenarios can never pass; main scored 0/3 on them for reasons unrelated to skill
   quality. This is the SWE-bench lesson: 68.3% of unverified instances had to be
   filtered because the task or the grader was wrong. **A failing eval whose grader is
   wrong is worse than no eval — it trains everyone to ignore red.**
2. **Prompts play the user.** `"At the ⑥ confirmation gate … choose Apply"` tells the
   agent which gates exist and what to answer — the eval steers the skill instead of
   simulating a user. Interactive skills (refine) then fail headless anyway (4–8.6 min,
   22–28 tool calls, 0% pass on both old and new skills): the scenario measures
   "degradation with nobody answering," while its expectation assumes success.
3. **Coverage is inverted.** The most expensive skill (squad-run) has zero coverage —
   its scenario is `--heavy` and hangs under headless `claude -p`. The suite measures
   the cheap CRUD skills well and the flagship not at all.
4. **No with/without-skill baseline.** Nothing demonstrates a skill earns its context
   window — the single most decision-relevant number per Anthropic's own skill-creator
   benchmark (pass_rate/time/tokens, with vs without, ±stddev).
5. **Efficiency was invisible until this week.** Duration was added mid-session; tokens
   and cost are still not captured even though `claude -p --output-format stream-json`
   emits usage in its result event.
6. **No scenario QA loop.** No burn-in for new scenarios, no discrimination analysis
   (does this assertion ever distinguish anything?), no quarantine lane, no gold-run
   self-check ("run a known-good transcript through the grader; it must score 100%").
7. **Statistically thin where it gates.** n=3 trials, means (one 179s network outlier
   dominated a scenario), unpaired comparisons, no pass^k reliability view.
8. **Scenario identity couples to development history** (`sqd-590-*` ids) rather than a
   behavior taxonomy, and scenarios live in one growing YAML file — neither scales to
   hundreds of skills.
9. **Board flakiness reads as skill failure.** Two eval runs died on a transient 20s
   board timeout in harness setup code (fixed with retry this week) — the CORE-Bench
   lesson (42%→95% after harness fixes): treat the harness as code under test.

---

## 2. Proposed architecture

### 2.1 The four-layer grader ladder

```
L0  Contract unit tests      pytest, board stubbed          free      every commit
L1  Scenario runs            real agent, real board,        $         PR smoke tier /
    (outcome-graded)         deterministic final-state                nightly full tier
    + budget assertions      + efficiency ceilings
L2  Quality rubric           constrained LLM judge,         $         nightly
    (informational)          calibrated, binary verdicts
L3  Lift benchmark           paired with/without-skill      $$        release + on skill
    (with vs without)        runs, per-scenario deltas               creation/major edit
```

**Why each layer exists**

- **L0** exists because the skills were re-architected around deterministic engine
  scripts (`pipeline.py` etc.) — transitions, gates, overrides, formatting are plain
  unit tests with `_req` stubbed. Regressions in orchestration mechanics should never
  need an LLM to detect. (Already implemented: 561 tests.)
- **L1** is the correctness gate. Grade the **outcome, never the path**: agents
  regularly find valid approaches eval authors didn't anticipate. The board is our
  execution environment, so grading = API reads of final board state + file artifacts +
  required substrings in the final message — the tau-bench pattern, fully objective.
  Trajectory data (tool calls, turns) is recorded but used only for efficiency budgets
  and invariant checks, not correctness.
- **L2** exists only for qualities that deterministic checks can't express (is the spec
  *good*, is the triage reasoning *specific*). It never gates PRs (judge noise: GPT-4
  G-Eval correlates ~0.51 Spearman with humans on summarization; position/verbosity
  biases are documented). Judges use enumerated verdicts, CoT-before-verdict, binary
  pass/fail (never 1–5 Likert), and are calibrated against ~30 human-labeled examples
  tracking TPR/TNR separately.
- **L3** answers "does this skill improve the model?" — paired runs on identical
  scenarios with the skill installed vs absent, reporting per-scenario paired deltas of
  pass rate, duration, tokens, tool calls, cost (Anthropic error-bars rec #4: paired
  per-question differences, not independent means; skill-creator does exactly this).

### 2.2 Skill contracts (what scenarios are allowed to assert)

Every skill ships `evals/contracts/<skill>.yaml` — its **promised, stable, observable
behavior**. Scenarios may only assert contract items; anything else is implementation
detail and forbidden (this is what rotted the refine scenarios).

```yaml
# evals/contracts/squad-refine.yaml
skill: squad-refine
version: 2            # bump on any promised-behavior change; scenarios pin ≤ version
mutations:            # board effects the skill promises
  - field: spec               # structured spec object written via POST /task/:id/spec
    when: user approves
  - field: level              # only via the approval gate, never silently
invariants:           # things that must NEVER happen (always-gate, any tier)
  - never_writes: description        # human field, never rewritten
  - never_writes: comments           # human channel
  - never_moves: status              # refine does not transition the card
  - org_scoped: true                 # no cross-org access
artifacts: []         # files the skill promises to create (none)
exit:                 # observable terminal conditions
  - saved: spec non-null AND Refiner activity event with shared correlation_id
  - cancelled: no board writes
interaction:          # what the skill may ask a user (drives the user-sim layer)
  gates: [interview_rounds, approve_save, level_change]
```

Contracts double as documentation and as the L0 test source: invariants compile
directly into unit assertions against the engine scripts and into runtime checks the
L1 grader applies to every trial (an invariant violation fails the trial regardless of
outcome).

### 2.3 Scenario specification

One directory per skill; one file per scenario; immutable versioned ids
(OpenAI-Evals registry pattern: `refine.vague-input.v2` — bump version instead of
editing semantics in place).

```yaml
# evals/scenarios/squad-refine/vague-input.yaml
id: refine.vague-input
version: 2
contract: squad-refine@2          # scenario asserts only this contract
tier: full                        # smoke | full | nightly-only
class: happy-path                 # happy-path | edge | invalid-input | large-input |
                                  # failure-mode | regression (provenance: prod replay)
setup:
  create_task: {title: "[[eval]] vague: improve onboarding", level: 2,
                description: "make onboarding better"}
user:                             # the user-simulation layer (see §2.4)
  mode: canned
  answers:
    - match: "scope|priority"     # regex on the question
      reply: "Keep it small: only the signup flow. Medium priority."
    - match: "approve"
      reply: "Approve & save"
  default_reply: "Use your best judgment."
  max_rounds: 4                   # exceeding = trial failure (runaway interview)
expect:
  board_task:
    spec.goal: nonempty                    # contract mutation, not description text
    spec.requirements: {min_items: 3}
    description: unchanged                 # invariant, auto-injected from contract
  output_contains_any: ["saved", "spec"]
budget:                           # efficiency ceilings — gate at p50 over k trials
  max_duration_s: 120
  max_tool_calls: 12
  max_clarification_rounds: 4
rubric:                           # L2 only, nightly, informational
  pass_criteria: >
    Requirements are testable and specific to onboarding; at least one edge case
    or ambiguity from the original is surfaced. Binary: pass/fail with evidence.
```

**Scenario QA (the SWE-bench Verified lesson, budgeted from day one):**

- **Burn-in**: a new/edited scenario runs 5× against the current skill before joining
  the scored suite (Spotify's Flakybot pattern). Flaky → quarantine lane + ticket.
- **Discrimination audit** (skill-creator's taxonomy, run quarterly): classify each
  assertion as always-passes / always-fails / discriminates / flaky; delete or fix the
  first two, quarantine the last.
- **Gold self-check**: each scenario ships a known-good reference transcript; the
  grader must score it 100% (`--predictions gold` idea from SWE-bench). A grader change
  that breaks gold runs is a grader bug, not a skill regression.
- **Quarantine lane**: flaky scenarios still run nightly, report, never gate; a
  quarantined scenario without a fix in 30 days is deleted (Chromium's disable-first +
  mandatory bug rule).

### 2.4 Interactive skills — the user-simulation ladder

Never again let the task prompt play the user. Three modes, cheapest first:

1. **`mode: none`** — non-interactive skills (add-task, board-view, init, heartbeat).
   Current single-turn headless runner unchanged.
2. **`mode: canned`** — scripted replies (OpenHands `fake_user_response_fn`). The
   runner drives the conversation via the Agent SDK (not `claude -p` single-shot):
   when the agent calls `AskUserQuestion` / ends its turn with a question, the driver
   matches the question against the scenario's `answers` regex table and replies; the
   conversation continues until the skill's exit condition or `max_rounds`. This is
   deterministic, cheap, and covers refine/kickstart/explore approval gates.
3. **`mode: simulated`** — tau-bench-style LLM user for the few scenarios where
   disclosure order and negotiation matter: a separate cheap model seeded with
   persona + goal + revelation rules + hidden constraints, unable to see tool traffic,
   ending on a sentinel. Grading stays objective (final board state) — the simulator
   affects the path, never the grade. Reserve for nightly; validate each simulated
   scenario with ~20 burn-in runs (tau-bench validated with >40).

**squad-run** gets measurable two ways, neither requiring the hung headless whole-run:
- **Per-step scenarios**: one pipeline step per scenario (dispatch → single agent →
  record → advance) — no parallel fan-out, so the non-TTY hang does not trigger. Grade
  the board transition + written field, budget the step.
- **Production telemetry** (§2.7) for whole-run wall-clock/reject-rate — real dogfood
  runs are the truest benchmark for the pipeline and cost nothing per measurement.

### 2.5 Metrics

Captured per trial (all from the runner; tokens parsed from the stream-json `result`
event's usage block — the "only opportunity to capture" boundary, per skill-creator):

| Metric | Source | PR gate? |
|---|---|---|
| deterministic pass (per contract assertion) | board/file reads | **yes — hard** |
| invariant violation | board reads + transcript scan | **yes — hard, any tier** |
| pass^k (all k trials pass) | k trials | **yes** (k=2 smoke, k=3 nightly) |
| duration_s | runner clock | **yes — vs scenario budget (median)** |
| tool_calls | stream-json count | **yes — vs budget** |
| clarification_rounds | user-sim driver | **yes — vs budget** |
| input/output/total tokens | stream-json usage | nightly gate vs budget; PR informational |
| cost ($) | tokens × price table | informational, always displayed next to score |
| retries / agent non-zero exits | runner | informational; feeds flake tracking |
| judge quality verdict + evidence | L2 | informational, never gates |
| board ops count | api.py call log | informational |

Gating philosophy: **hard gates are things that are deterministically wrong**
(contract violated, invariant broken, budget blown by >50% at the median). Judge
scores and small efficiency drifts inform; statistics (§2.6) decide when drift is real.

### 2.6 Regression detection

Keep `history.jsonl` + floors; upgrade the statistics:

- **Paired, per-scenario comparison** against a pinned baseline experiment (the last
  green main run), not run-mean vs run-mean. Same scenarios, per-scenario deltas,
  sign-test/Wilcoxon on the paired deltas (Anthropic 2411.00640 rec #4).
- **Medians and P95 for durations** (never means — one network stall poisoned a mean in
  our own A/B); MLPerf-style trimmed scoring for timing metrics.
- **pass^k for reliability claims**: pass@1 75% is pass^3 ≈ 42% — report both.
- **Cluster variance by scenario family** (scenarios generated from one template are
  correlated; naive SEs understate up to 3×).
- **Thresholds**: pass-rate drop >5 points on the paired set OR any invariant/contract
  hard-fail OR median duration/tokens regression >20% sustained across 2 consecutive
  runs → gate fails. Single-run efficiency drift → warn only.
- **Flake protocol** (Google/GitHub): retries only for scenarios *labeled* flaky (never
  blanket); a gate failure requires the failure to reproduce (fail 2 of 2 rerun trials);
  auto-quarantine at >10% flake rate with a filed ticket.

### 2.7 Production telemetry → evals

The board already instruments itself — use it:

- **Metrics mining** (no new infra): per-column elapsed time, reject-loop counts,
  tokens per actor from `activity` events + `correlation_id` threading; run-level
  outcomes from `run-audits`. A weekly job appends these to a `telemetry.jsonl` trend —
  this is the real-world benchmark for squad-run.
- **Failure replay**: every friction report / circuit-breaker trip / run-audit
  `friction` row is a candidate scenario. A quarterly triage promotes the top real
  failures into `class: regression` scenarios (Anthropic guidance: "20–50 simple tasks
  drawn from real failures" beats invented ones).
- **Gold dataset growth**: approved specs, accepted plans, and passing runs become
  reference transcripts for grader self-checks.
- Consent boundary: telemetry mining uses the org's own board data (dogfood org);
  nothing leaves the board; the existing observation-consent gate continues to govern
  `user_steering` capture.

### 2.8 CI/CD tiers

| Stage | What runs | Budget |
|---|---|---|
| every commit (pre-merge) | L0 contract/unit tests + skill validation | <2 min, free |
| PR touching `skills/**` | smoke tier: 1 scenario/skill-touched (changed skills only + shared-core changes → all), k=2, canned users, no judge | ~10 min, ~$1 |
| nightly | full tier: all scenarios, k=3, judge on, paired vs pinned baseline, flake audit | ~1–2 h |
| release / skill creation or major edit | L3 with/without-skill benchmark on that skill's scenarios, k=5; discrimination audit | on demand |
| weekly | telemetry mining job; quarantine review | cron |

Test selection rule (Develocity): never skip scenarios for *new/changed/recently-flaky*
skills; shared-core changes (`skills/squad/**`) select the full smoke tier.

### 2.9 Scalability to hundreds of skills

- **Data/code separation**: scenarios and contracts are declarative YAML; the grader is
  a small assertion library (~6 assertion types cover everything above); adding a skill
  adds zero harness code (OpenAI Evals' registry lesson).
- **Plugin runner contract** (OpenHands): a scenario family needing special setup
  implements `setup(instance) / instruction(instance) / grade(instance, result)` in one
  module; the shared driver owns parallelism, retries, cleanup, and the result schema.
- **Parallel workers + project-per-worker isolation**: each worker gets its own board
  project (`squad-eval-w{n}`) so trials never share mutable state; scenario cleanup
  stays snapshot-diff.
- **One uniform result row** (`EvalOutput`-style) per trial in `history.jsonl`;
  dashboards and stats read one schema forever.
- **Cost control**: budget-based selection (PR runs are O(changed skills), not O(all
  skills)); judge caching keyed on (transcript hash, rubric version); `--sample N`
  smoke subsets.

---

## 3. Comparison with industry practice (what we adopted from where)

| Idea | Source | Where it lands here |
|---|---|---|
| Final-state DB grading + required substrings, no judge for correctness | tau-bench | L1 grader |
| Scripted user hook → LLM persona ladder | OpenHands `fake_user_response_fn`, tau-bench | §2.4 |
| pass_rate + time + tokens, with/without skill, ±stddev | Anthropic skill-creator | L3 benchmark |
| Assertion discrimination taxonomy + eval-of-evals | skill-creator analyzer/grader | Scenario QA |
| Registry of immutable versioned scenario ids, data-only | OpenAI Evals | §2.3 |
| Pinned baseline experiment + per-case paired diffs | LangSmith / Braintrust | §2.6 |
| Trial repetitions with stddev surfaced; input-hash case identity | Braintrust / LangSmith | §2.5–2.6 |
| Fail-to-pass AND pass-to-pass (fix works, nothing broke) | SWE-bench | contract mutations + invariants |
| Task/grader validation before trusting the suite; gold self-check | SWE-bench Verified, GAIA | Scenario QA |
| Answer-contract simplifies grading (push format into the task) | GAIA | `[[eval]]` markers, typed expects |
| Enumerated verdicts, CoT-first, binary, calibrated judges | MT-Bench, Hamel Husain | L2 |
| Paired per-question stats, clustered SEs, power awareness | Anthropic error-bars | §2.6 |
| Closed/Open divisions; no benchmark detection; seed rules | MLPerf | L3 protocol |
| Burn-in, labeled-flaky-only retries, auto-quarantine + ticket | Google/GitHub/Spotify/Chromium | Flake protocol |
| Few E2E tests, many cheap ones ("5, not 500") | Spotify | tier sizing |

---

## 4. Migration plan

1. **Freeze** `scenarios.yaml` (read-only); new work lands in `evals/scenarios/<skill>/`.
2. **Fix the graders that are wrong today**: refine expectations → `spec` field;
   delete/rewrite the `sqd-590-*` ids into behavior-named scenarios.
3. **Port the 10 existing scenarios** into the new format (mechanical; contracts first
   for squad, squad-init, squad-refine).
4. **Runner upgrades in place** (keep runner.py/scoring.py/baseline.py): token capture,
   SDK-driver for `mode: canned`, per-worker projects, result-row schema.
5. **Retire** the in-prompt user-steering text from all scenario prompts.
6. **Keep `history.jsonl`** — old rows remain readable (schema is additive).

## 5. Project structure

```
evals/
  contracts/<skill>.yaml          # promised behavior (one per skill)
  scenarios/<skill>/<name>.yaml   # one scenario per file, versioned ids
  gold/<scenario-id>/             # reference transcripts for grader self-checks
  harness/
    driver.py                     # parallel trial driver (workers, retries, cleanup)
    user_sim.py                   # canned + LLM user simulation
    grade.py                      # assertion library (board/file/output/invariant)
    metrics.py                    # stream-json usage parsing, budgets
    stats.py                      # paired tests, pass^k, medians/P95 (evolves baseline.py)
  runner.py  scoring.py  judge.py report.py   # retained, upgraded in place
  history.jsonl                   # append-only results (committed)
  telemetry.jsonl                 # weekly production mining (committed)
  quarantine.yaml                 # flaky scenarios + ticket links
```

## 6. Dashboard

Extend the existing self-contained HTML report (no SaaS): per-skill scorecard
(pass^k, median duration, tokens, cost, trend sparklines), paired-delta table vs
pinned baseline (green/red per scenario — the LangSmith regression view), L3
with/without lift table per skill, quarantine list with age. Data source stays
`history.jsonl` + `telemetry.jsonl`.

## 7. Roadmap

**Immediate (this week)**
1. Fix stale refine graders (spec-field assertions) — the suite must stop lying.
2. Token + cost capture from stream-json; medians/P95 in the report.
3. Gold self-check for every deterministic assertion type.
4. Scenario budgets (duration/tool-calls) as informational columns.

**Short-term (2–4 weeks)**
5. Contracts for all 9 skills; invariant auto-assertions in the grader.
6. New scenario layout + port; behavior-named versioned ids; burn-in rule.
7. Canned-user SDK driver → refine/kickstart/explore evaluated properly.
8. Per-step squad-run scenarios (dispatch/advance transitions with one real agent).
9. Paired-baseline regression gate (replaces run-mean Welch on the gate path);
   pass^k reporting; PR smoke tier wired to changed-skill selection.

**Long-term (quarter)**
10. L3 with/without benchmark harness + release gate on new skills.
11. LLM user simulator for negotiation-class scenarios (burn-in validated).
12. Telemetry mining job + failure-replay scenario promotion.
13. Discrimination audits + quarantine automation; judge calibration set (~30 labeled
    examples, TPR/TNR tracked).
