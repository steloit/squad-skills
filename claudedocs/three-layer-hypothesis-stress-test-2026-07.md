# Stress-testing the three-layer hypothesis (2026-07-13)

Hypothesis under attack: *skills = knowledge layer · engine = deterministic
execution runtime · platform = governance/observability layer*, with
GitHub/Linear/Jira/Slack as the collaboration system of record.

Verdict up front: **the layer CUT is right; two of the three labels are
wrong, and one layer as currently built does not survive its own evidence.**

## Layer-by-layer interrogation

### Engine = deterministic execution runtime — HOLDS (the only clean claim)
Unique responsibility, no duplication, measured: A1–A12, 12/12 guarantee
holds across models, 3 reviewer catches, production PRs. Nothing else in the
family can do this job; nothing in this job is done elsewhere. KEEP as-is.

### Skills = "knowledge layer" — LABEL IS WRONG
Where does durable knowledge actually live? Repo conventions in each target
repo's AGENTS.md; execution contracts (prompts, spec format, policies) in
the engine + playbook; architecture history in this repo's claudedocs. None
of that is the installed skills. What the skills uniquely are:
1. **The interactive front-door** — human-in-the-loop flows (refine,
   plan-gate, review-assist) inside whatever chat agent the user already
   runs, and
2. **A distribution channel** (`npx skills` into 50+ agents) that no other
   layer has.
That is an **interface layer**, not a knowledge layer. And half of today's
skills content — the 6-role squad-run execution pipeline — is DUPLICATED
with the engine and loses on every measured axis (verification integrity,
work-destruction risk, enforcement, cost). Verdict: **KEEP, radically
narrowed**: deprecate the execution-orchestration skills; re-scope the rest
to "refine work, gate plans, and hand execution to the engine."

### Platform = "governance/observability layer" — ASPIRATION, NOT FACT
The evidence is harsh:
- The governance that exists today is PLAYBOOK.md + engine code. The
  platform enforces none of it.
- The observability that exists today is `.squad/runs/` local logs. The
  platform's `/runs` endpoint is unbuilt; `recordToPlatform` returned false
  in all 30+ production runs.
- The platform's actual built surface — the kanban board — is a
  COLLABORATION UI, which the hypothesis itself hands to GitHub/Linear/Jira/
  Slack. Our own dogfooding already voted: every engine run bypassed the
  board for GitHub issues.
So as currently built, the platform is mostly the layer the hypothesis
eliminates, and barely the layer the hypothesis names. Verdict: the
governance/observability layer is a **legitimate future claim with zero
current implementation** — and its first competitor is GitHub itself
(Checks API = evidence surface; rulesets = policy gates; audit log = audit).
It earns construction only where GitHub structurally can't go: cross-repo,
cross-tracker, cross-agent aggregation; org-level policy spanning systems;
the run as a queryable first-class object over time. That need is real in
the mid-size+ segment and absent below it.

## Duplication register

| Responsibility | Duplicated where | Resolution |
|---|---|---|
| Execution orchestration | skills squad-run pipeline vs engine | Engine wins on evidence; deprecate the skills pipeline, rewire its entry point to invoke the engine |
| Task record | board cards vs GitHub/Linear issues | Tracker wins (hypothesis assumption + our bypass behavior); board demoted |
| Governance policy | playbook file vs platform (unbuilt) | File-based wins for single-org; platform earns it only multi-team, later |
| Audit | local run logs vs platform records (unbuilt) vs GitHub Checks | Ship evidence to GitHub surfaces first; platform aggregation gated on demand |
| Review | skills PR-review flows vs engine review gate | Different jobs (interactive assist vs deterministic gate); acceptable overlap |

## Can a layer be eliminated?

- **Engine**: no.
- **Skills**: as pipeline — yes, eliminate (superseded, measured). As
  interface + distribution — no; it is the only human front-door and the
  only installed channel. Narrow it.
- **Platform**: as board product — **yes, eliminate from the strategy** (the
  hypothesis's own assumption plus our bypass evidence). As headless
  governance/observability service — not eliminated but **demoted to a
  gated hypothesis**: build nothing until the GitHub-native evidence surface
  is shipped and customers hit its limits (that moment, if it comes, is the
  platform's evidence gate).

## The smallest product that delivers the measured differentiated value

**Engine + GitHub surface.** Concretely: the engine as-is; the evidence
dossier rendered as a PR comment + Check Run; PR-comment iteration feeding
the loop; policy as in-repo config. No board. No platform service. Skills
optional as the chat front-door. This ships the three things the product
assessment identified (evidence dossier, iteration loop, policy/audit) using
GitHub as the surface for all three.

## Is three-layers coherent long-term?

Yes — **as responsibilities, not as the current repos**:
*interface (skills, narrowed) → runtime (engine) → governance/observability
(headless, gated, currently GitHub-native config+checks).* Each has a unique
job; together they are stronger than any alone because the interface feeds
the runtime and the runtime's records feed governance. But coherence was
achieved by renaming one layer, demoting another, and deleting the board
from the product path — the hypothesis as originally worded was one-third
right, one-third mislabeled, one-third aspirational.

Supersedes-in-part: vault ADR 2026-07-12 (three-layer execution runtime) —
Layer 3 "platform as system of record" is revised to "governance layer,
GitHub-native first, standalone service gated on demand evidence."
