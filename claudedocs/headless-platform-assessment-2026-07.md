# Does the platform survive without the board? (2026-07-13)

Question: with the board eliminated from product strategy and GitHub as the
execution surface, does a headless platform — AI operations, governance,
compliance, policy, analytics, cost, model governance, evidence aggregation —
have unique product value? Challenged in both directions.

## The case AGAINST (steelmanned first)

GitHub already ships: Checks (per-PR evidence surface), rulesets (policy
gates), org audit log, code scanning, Actions usage reporting. The dossier
wedge needs none of our platform. If every question a customer asks is
answerable per-PR, the platform is architectural symmetry, not product.

## Where GitHub structurally stops (the case FOR)

GitHub can only represent what happens ON GitHub, per-repo, per-PR. The
following are invisible or unaggregatable there — and all of them already
exist in our run record schema:

1. **Runs that never reach GitHub.** A baseline-abort, a review-reject, a
   crashed run — no PR, no trace. In our own production history, 5 of 12
   phase-1 runs and both SQD-1037 attempts produced no merged artifact:
   under a GitHub-only lens, ~40% of AI engineering activity (and spend)
   never happened.
2. **Model + cost provenance.** Which model, which reviewer, what it cost,
   per agent per run — vendors bill in aggregate, GitHub knows nothing.
   No unified per-task/per-repo/per-team AI cost view exists anywhere in
   the market landscape we surveyed.
3. **Cross-run, cross-repo, cross-time questions.** "Post-merge revert rate
   by model." "False-reject trend since the prompt change." "Who overrode
   L1 and what happened." "Security-floor fire rate by repo." These are
   JOIN-shaped questions over run records; GitHub has no schema for them.
4. **Model governance.** Lifecycle stages, org allow-lists, evidence-gated
   default changes, spend caps per model — structurally impossible for
   vendor agents to offer neutrally (they are the vendor) and absent from
   GitHub.
5. **Compliance-grade export.** Structured, immutable, SIEM-ingestable logs
   of AI-system actions (the 2026 enterprise checklist; EU AI Act era).
   GitHub's audit log covers GitHub actions, not agent internals.

**And the strongest evidence is internal:** the subsystem evidence ledger —
the document steering every decision we've made this month — IS this
product, performed by hand. The operator has hand-aggregated run logs with
ad-hoc scripts six-plus times in three days to answer exactly the questions
above. We are already the platform's first user; we've been running it
manually.

## Verdict: the platform earns existence — but smaller than the ambition

Unique value: **the aggregation plane over run records** — the "run as the
primitive" thesis from the 2026-07-12 ADR survives intact; only the board
died. Of the nine proposed capabilities, the smallest platform keeps four
and defers five:

**In (v1 — "the flight recorder for AI engineering"):**
1. **Run ingest + org-wide runs ledger** — every run, including the ~40%
   GitHub never sees; the existing `recordToPlatform` client is already
   built and waiting.
2. **Cost reporting** — per repo/model/task-class/time; the data is already
   in every run record; CFO-legible; no incumbent.
3. **Model scorecard** — measured sound-rate/cost/latency per model per
   repo; operationalizes the lifecycle policy we already govern by hand.
4. **Structured export** (JSONL/SIEM) — nearly free at ingest time; opens
   the enterprise conversation later without building for it now.

**Out (deferred until a customer question demands them):** policy
management as a service (in-repo config wins until multi-team), analytics
dashboards beyond the three views, "cross-repository intelligence" (vague —
cut until it names a question), compliance certifications, anything
issue/task/board-shaped (permanently, per strategy).

**Reuse, don't rebuild:** the existing platform api already has the hard
parts — multi-tenant orgs, PAT auth, RLS-enforced isolation, deploy
pipeline. The minimal platform is roughly one `/runs` ingest route + three
query views on proven infrastructure. Removing "the platform entirely"
would discard a validated multi-tenant foundation the minimal version needs.

## Build gate (freeze-compliant)

Not now. Order stands: production burn-down → dossier validation → dossier
+ iteration build (if validated). The runs-ledger build gate: **when the
dossier ships** (each PR then links a run record that must live somewhere
customer-visible) **or when hand-aggregation for the ledger happens three
more times** — whichever first. Board: maintenance mode as internal tooling;
no further product investment.
