# Squad v2 Architecture: Local-First Redesign (July 2026)

**Status:** Research + recommendation. Produced against the frozen squad-skills repo (commit `1768cd6`).
**Question:** Should the Squad system keep its backend service, or move to a local-first architecture — and what should happen to each skill?
**Answer in one line:** Remove the backend from the developer workflow entirely. Tasks, specs, and decisions become Markdown files in the target repo, synced by git; the pipeline collapses onto native agent primitives; 2 of 9 skills survive (in reduced form).

---

## 1. Review of the Current Architecture

### What exists

- **9 instruction-only skills** (~4,600 lines of SKILL.md prose) that any agent executes by driving `curl`-equivalent calls through `api.py` against a hosted board (Cloud Run + PostgreSQL, org-scoped `/api/orgs/<org>/...`, user-scoped PATs minted in a web UI).
- **A 6-agent, 7-column pipeline** (Planner → Critic → Builder → Shield → Inspector → Ranger) orchestrated by `squad-run` — a 937-line state machine *interpreted by an LLM*, with verdict endpoints, derived-status reads, correlation-id threading, optimistic-concurrency versions, approval-tree content hashes, consent-gated telemetry emits, and an embedded shell-injection-defense doctrine.
- **A 2,400-line Python helper layer** (`api.py`, `observe.py`, `refine_ledger.py`, `render_agent_prompt.py`, `plan_batch.py` + smokes).
- **~37 pytest files whose subject is the markdown itself** — regex/contract tests that assert the instruction prose stays consistent with a vendored OpenAPI snapshot, plus a Vale style linter banning sales prose, plus a DeepEval behavioral eval harness.
- **The FREEZE (2026-07-13):** the repo is already declared a historical record; execution moved to `steloit/squad-engine`; skills are being "rediscovered from scratch."

### Structural assessment

**The backend is load-bearing for almost nothing the workflow needs.** Partitioning the state (verified against `shared.md`, `schema.md`, the OpenAPI snapshot):

- *Genuinely server-only:* multi-tenant org scoping, PAT minting/scopes, web-UI drag-and-drop, presigned attachment URLs, consent management, server-side stats `GROUP BY`, concurrent-writer guards (`version`/412, transition legality, acyclicity CTEs).
- *Trivially file-representable:* everything the agents actually read and write — `description`, `spec`, `plan`, `decision_log`, `done_when`, `implementation_notes`, `status`, `level`, `tags`, dependencies, review verdicts, activity notes.

Every hard server-side feature exists to protect **shared mutable state** — and the shared mutable state exists because the architecture chose a central database. It is circular: remove the central DB and the concurrency machinery, tenancy, PAT lifecycle, consent gates, and 401/403 error taxonomy all become unnecessary, not unsolved.

**Complexity inventory caused by the backend + LLM-as-state-machine choices:**

| Complexity | Root cause |
|---|---|
| PAT/org/tenant resolution ladder, 401 vs 403 doctrine, secret-safety deny-rules | Central multi-tenant service |
| Optimistic concurrency (`version`, `expected_version`, 412 retry), record-vs-move split, derived verdict fields | Multiple writers on shared rows |
| Shell-safety injection doctrine (repeated in 3 files), out-of-band JSON assembly, heredoc capture rules | LLM assembling HTTP bodies in bash |
| Correlation-id minting/threading, agent-attributed activity events, token-honesty rules | Reconstructing a timeline the terminal/git already has |
| Observation consent gate, abstraction rubric, leak filters, `user_steering` enums | Telemetry to a server; locally this is a non-problem |
| 37 contract tests + Vale + OpenAPI refresh scripts | Keeping 4,600 lines of prose in sync with a wire contract |

**The pipeline itself is misaligned with 2026 evidence.** The 6 agents are decomposed by *role* (planner/critic/builder/reviewer), which Anthropic's Jan-2026 guidance explicitly calls the wrong axis — decompose by *context boundary*, not work-type; role-chains cost 3–10× tokens and Anthropic teams found "improved prompting on a single agent achieved equivalent results." Cognition's "Don't Build Multi-Agents" makes the same argument from context-fragmentation. Meanwhile the host harnesses grew native plan mode, subagents, background tasks, checkpoints/rewind, todo lists, and session resume — `squad-run` re-implements a worse version of features the runtime now ships.

### What is genuinely good (worth carrying forward)

1. **The refine discipline** — the gap-ledger interview with a script-owned stop gate (`refine_ledger.py`), VoI-gated questions, EARS acceptance criteria, spec-separate-from-description. This is real IP and is 95% backend-free.
2. **Verifiable `done_when` + review-before-done gates + circuit breakers** — the *policy*, not the machinery.
3. **Rolling-wave planning** (refine N+1 only after verifying N) — one paragraph of genuinely earned insight.
4. **Command Resolution ladder + principles.md** (portable, stack-agnostic, safety-first) — good rules content.
5. **Spec precedence, card-split criteria, epics-as-containers** — good conventions that port directly to frontmatter.

---

## 2. Web-Research Findings (July 2026)

Full citation-rich reports are in the session record; the load-bearing findings:

1. **Files-in-repo won.** Every first-party memory system is local files: `CLAUDE.md` + auto-memory markdown (Claude Code), `AGENTS.md` (Codex, donated to the Linux Foundation's Agentic AI Foundation, 60k+ projects, 20+ tools), `.cursor/rules/*.mdc` (Cursor; `.cursorrules` deprecated), `GEMINI.md` (Gemini CLI). No vendor recommends a hosted backend for single-dev/small-team project memory. Anthropic's own long-running-agent harness guidance persists state as **files + git** (progress log, JSON feature list, git history for recovery).
2. **Agent Skills became the cross-agent standard** (agentskills.io; adopted by Codex, Cursor, Gemini CLI, Copilot, Amp, ~45 clients; `npx skills` installer). The distribution layer this repo bet on was the right bet — it's the payload that aged.
3. **Task-tracker storage evidence:**
   - **beads** (Yegge, ~18.7k★): SQLite cache + JSONL-in-git → migrated to embedded Dolt; its daemon was the #1 user complaint; hash IDs to survive parallel agents. Lesson: DB queryability matters at *fleet* scale; daemons breed distrust.
   - **Backlog.md** (~6.2k★): one markdown file per task with YAML frontmatter, plain git sync, CLI+MCP optional. "One task = one context window = one PR." File-per-task ≈ conflict-free.
   - **claude-task-master** (~28k★): single `tasks.json` → forced file-locking, and *abandoned git-sync for a hosted service* for teams. Lesson: one shared JSON file is the worst git citizen.
   - **vibe-kanban:** local server + SQLite; had to move agent logs out of SQLite into JSONL files ("Don't do it!"); out-of-repo state blocked team sync.
   - **spec-kit / OpenSpec:** spec-driven markdown in-repo; OpenSpec deliberately has *no MCP, no keys* — delta-specs to stay token-cheap.
   - **Committing raw SQLite to git is a non-starter** (binary blob; sqlite.org itself documents why).
4. **ADRs are having an agent-driven renaissance** — decision logs are repeatedly called the highest-leverage agent context per token; Backlog.md and spec-kit both bake a decisions/constitution file in.
5. **What went obsolete in ~18 months:** vector-DB memory for code (replaced by agentic grep), elaborate MCP memory servers (a well-kept CLAUDE.md beats them; MCP schema overhead is measured and large), custom slash-command frameworks (native skills), `.cursorrules`-era per-tool dialects, hand-rolled planner/checkpoint/todo/subagent harnesses (now native), and static role-chain multi-agent pipelines (evidence above).
6. **Teams:** git-as-sync is the default recommendation for small teams (fluado deleted Jira: "Jira was a copy nobody maintained… we deleted the copy and put a window on the original"). Hosted trackers re-enter only for cross-team permissions/notifications — and then as GitHub Issues via `gh`, which every model already knows, not a bespoke board.

---

## 3. Comparison Matrix

Scale assumption: 1 developer (occasionally a small team), multiple repos, agents doing most writes. Scored ✅ good / ⚠️ workable / ❌ poor.

| Architecture | Simplicity | Maintain | Perf | Portability | Agent-friendly | Git-friendly | Team sharing | Verdict |
|---|---|---|---|---|---|---|---|---|
| **A. Hosted backend (status quo)** | ❌ (service+DB+auth+web UI) | ❌ (you maintain a product) | ⚠️ (network hop per read) | ⚠️ (needs PAT + reachability) | ⚠️ (curl through api.py; agents can't grep it) | ❌ (state outside repo) | ✅ | Justified only for real multi-user/web needs |
| **B. Local server/daemon + SQLite** | ❌ | ⚠️ | ✅ | ❌ (daemon per machine) | ⚠️ | ❌ (state out of repo) | ❌ | beads-daemon & vibe-kanban lessons: avoid |
| **C. SQLite committed in repo** | ⚠️ | ⚠️ | ✅ | ⚠️ | ❌ (opaque to grep/Read) | ❌ (binary merges) | ❌ | Ruled out by evidence |
| **D. JSONL in git + SQLite cache (beads)** | ⚠️ | ⚠️ (sync layer to own) | ✅ | ⚠️ (CLI required everywhere) | ✅ (`--json` CLI) | ✅ | ✅ | Right at 100s-of-tasks / multi-agent-fleet scale |
| **E. Markdown file-per-task + YAML frontmatter** | ✅ | ✅ | ✅ (grep scale is fine <~1k tasks) | ✅ (any agent, any editor) | ✅ (native Read/Edit/grep) | ✅ (file-per-task ≈ no conflicts) | ⚠️ (git push/pull) | **Recommended baseline** |
| **F. E + derived index + tiny CLI (hybrid)** | ⚠️ | ⚠️ | ✅ | ✅ (CLI optional, files still truth) | ✅ | ✅ | ⚠️ | The escape hatch if E shows query pain |
| **G. GitHub Issues via `gh`** | ✅ | ✅ | ⚠️ (network, rate limits) | ⚠️ (GitHub-only) | ✅ (models know `gh` natively) | ⚠️ (outside worktree) | ✅ | The team-visibility bridge, not the core store |
| **H. git-native objects (git-bug)** | ⚠️ | ⚠️ | ✅ | ❌ (special tooling) | ❌ (invisible to file tools) | ✅ | ✅ | Elegant, ignored by the ecosystem |

**Why Markdown is sufficient (E):** agents read/write it with first-class tools; humans edit it anywhere; file-per-task sidesteps merge conflicts; frontmatter gives structure without a parser dependency; grep is the query engine the 2026 agents were literally optimized for. The known weaknesses — dependency queries and staleness at scale — don't bite below several hundred open tasks, which is far above this system's observed scale.

**Why not SQLite:** committed → binary merge disaster; local-cache → you've rebuilt beads' sync layer (their hardest, most-complained-about component) for a queryability need you don't yet have; app-data → state leaves the repo and team sync dies (vibe-kanban's open issue).

**Why the hybrid (F) is deferred, not rejected:** markdown-as-truth + derived index (Basic Memory pattern) is the clean upgrade path. Adopt it *when* a measured pain appears (e.g., "ready-task" queries across 300+ open tasks), never before. The migration is additive — no format change.

---

## 4. Recommendation

**Adopt a local-first, git-native architecture. Remove the backend from the developer loop.**

1. **Store:** one Markdown file per task in `.squad/tasks/`, YAML frontmatter for machine fields, body for spec/plan/notes/log. Decisions in `docs/decisions/` (MADR-lite). Project context in `AGENTS.md` (with `CLAUDE.md` → `@AGENTS.md` import).
2. **Sync:** git. Task state travels with the branch; history/audit *is* git log; blame is attribution.
3. **Orchestration:** native primitives — plan mode for planning, the main agent for implementation, one reviewer subagent (or `/code-review`) for the gate, tests for verification. Keep the *policies* (verifiable done_when, review-before-done, circuit-breaker, rolling wave) as a short skill; delete the state machine.
4. **Interface:** direct file edits by agents, with a small validation script. No daemon. A CLI and/or a read-only local board viewer are optional later additions (fluado pattern: the viewer is a window onto files, never a store).
5. **Team visibility (when needed):** git push/pull first; a `gh` bridge to GitHub Issues second. A hosted board is re-justified only if there are multiple concurrent human editors on a shared kanban — the one case the research still supports, and it should then be GitHub Issues, not a self-run service.

### Task file format (proposal)

```markdown
---
id: SQD-042
title: Add invite-by-email to members page
status: todo          # todo | doing | review | done | cancelled
priority: high
level: 2              # 1 quick · 2 standard · 3 full (keeps the level rubric)
epic: SQD-040         # optional parent
blocked_by: [SQD-041] # dependency edges, machine-readable
tags: [auth]
created: 2026-07-15
updated: 2026-07-15
---

## Request            ← the human's original words; never rewritten
## Spec               ← refine output: goal, REQ:/AC:/SCOPE:/EDGE: lines, Q&A
## Plan               ← plan-mode output (L2/L3)
## Done when          ← verifiable checklist
## Log                ← append-only: decisions, review verdicts, commit hashes
```

The 8-status pipeline collapses to 5: `plan/plan_review/impl/impl_review/test` were columns because six different agents needed a place to stand; with one agent + one reviewer, `doing` and `review` suffice, and the level (L1/L2/L3) governs how much ceremony happens inside them.

---

## 5. Skills Audit — every skill, challenged

| Skill (lines) | What it really is | Verdict |
|---|---|---|
| **squad** (268) | CRUD wrapper over REST | **Replace with a format doc + file edits.** `/squad add` = create a file; `move/complete/cancel` = edit frontmatter; `stats` = a 5-line script; `context` = read the tasks dir. Not a skill — a convention. |
| **squad-init** (166) | Backend registration + `.squadrc` | **Unnecessary.** Local-first init = `mkdir .squad/tasks` + drop a template. One paragraph in the format doc. |
| **squad-run** (937) | LLM-interpreted 6-agent state machine | **Obsolete as designed — replaced by built-ins.** Plan mode + main-agent implement + one reviewer subagent + tests covers L1–L3. Salvage the *policies* into a ~100-line workflow skill: level rubric, done_when gate, review-before-done, circuit breaker, commit-per-task. The role-chain, verdict endpoints, correlation ids, approval-tree hashing, format-normalization seam: delete. |
| **squad-refine** (334) | Gap-ledger requirements interview | **KEEP — the crown jewel.** Port the output target from `POST /spec` to the task file's `## Spec` section. `refine_ledger.py` (stop-gate) survives as the skill's bundled script. Drop the observation emits. |
| **squad-explore** (312) | Explore+Plan subagents → report → phased tasks | **Mostly replaced by built-ins** (native Explore/Plan agent types, plan mode). Keep a thin residue: write the direction report to `docs/`, seed phased task files. Could fold into the workflow skill. |
| **squad-batch-run** (302) | Orchestration of orchestration | **Unnecessary.** "Run ready tasks in order, refine N+1 after verifying N" is one paragraph of guidance plus native looping. `plan_batch.py` (597 lines) deletes with it. |
| **squad-kickstart** (268) | SRS → plan → skeleton tasks → rolling wave | **Replace with the spec-driven-markdown flow.** It already writes local `docs/*.md` — the board parts were the only non-local parts. Either adopt OpenSpec/spec-kit conventions or keep a slim greenfield skill. |
| **squad-heartbeat** (335) | Staleness cron over the API | **Not a skill — a one-liner.** `updated:` frontmatter older than N days is a grep/`find` script, runnable from a hook or cron. |
| **squad-gen-wiki** (342) | Synthesize wiki/ from board+code | **Mostly unnecessary.** Local-first inverts it: decisions live in `docs/decisions/` as they're made; AGENTS.md is maintained in-flow; `/init`-style refresh is native. If a synthesis pass proves useful, it's an occasional prompt, not a 342-line skill. |

**Shared layer:** `shared.md` (976 lines) — ~90% evaporates (auth, endpoints, move protocol, consent, model resolution); the Command Resolution ladder and Spec Precedence survive as short rules. `principles.md` — keep nearly verbatim (it's good, portable content). `schema.md` → replaced by the frontmatter format doc. `templates/` (7 agent prompts) → delete; if a reviewer subagent is kept, it becomes one `.claude/agents/reviewer.md`. Scripts: keep `refine_ledger.py`; delete `api.py`, `observe.py`, `render_agent_prompt.py`, `plan_batch.py`, all smokes.

---

## 6. Obsolete Components to Remove

**Infrastructure:** the hosted board service + PostgreSQL + Cloud Run deploy, web UI (or demote to read-only viewer), PAT minting/scopes/org tenancy, `.squadrc`/`~/.squad/*` config chain, attachments bucket + presigned URLs.
**Client machinery:** `api.py`, `observe.py` + the entire observation/consent/`user_steering` apparatus, `render_agent_prompt.py`, `plan_batch.py`, `models.json` provider routing (native per-subagent model selection exists), smoke scripts.
**Skills:** squad, squad-init, squad-run (as-is), squad-batch-run, squad-kickstart (as-is), squad-heartbeat, squad-gen-wiki.
**Meta-apparatus:** the 37 markdown-contract pytest files, the vendored OpenAPI snapshot + refresh scripts, the Vale instruction-only ruleset (fold its doctrine into a 5-line CONTRIBUTING note), the Coach/run-audit telemetry loop.
**Pipeline concepts:** verdict endpoints, derived `last_*_status`, correlation ids, `version`/CAS, approval-tree hashing, the 6 nicknames, the 7-column state machine, agent-attributed token accounting.
**Also reconsider:** `steloit/squad-engine` — if it re-hosts the deterministic 6-role pipeline, the same role-chain evidence applies to it; the deterministic-runtime instinct is right, but the thing worth making deterministic is *gates and validation*, not agent choreography.

## 7. Proposed New Structure

```
your-project/                      # any repo using the system
├── AGENTS.md                      # project context (CLAUDE.md: "@AGENTS.md")
├── .squad/
│   ├── FORMAT.md                  # the task-file convention (replaces schema.md+shared.md)
│   ├── tasks/
│   │   ├── SQD-041-invite-api.md
│   │   └── SQD-042-invite-ui.md
│   └── scripts/validate.py        # frontmatter lint + staleness + ready-list (~100 lines)
├── docs/decisions/                # ADRs (MADR-lite), agent- and human-authored
└── .claude/agents/reviewer.md     # optional: the one reviewer subagent

squad-skills-v2/                   # the new skills repo (installable via npx skills)
├── skills/
│   ├── squad-refine/              # ported gap-ledger interview + refine_ledger.py
│   └── squad-work/                # ~100 lines: level rubric, done_when gate,
│                                  # review-before-done, circuit breaker, rolling wave
├── templates/                     # task-file + ADR + AGENTS.md starters
└── README.md
```

Two skills, one format doc, one validation script, zero services, zero tokens/auth, zero daemons.

## 8. Phased Roadmap

**Phase 0 — Export & freeze (half a day).** Write a one-off exporter: `GET /board` (full) per project → one markdown file per task (frontmatter from fields, body from description/spec/plan/notes/log). Commit into each repo. Stop writing to the board. The board stays up read-only as an archive until Phase 3.

**Phase 1 — Format + refine (1–2 days).** Author `FORMAT.md` + `validate.py`. Port **squad-refine** to write `## Spec` into task files (delete observe emits, keep the ledger gate). Port `principles.md` + Command Resolution into a short rules file. Start using it on real work immediately — the format earns changes only from use.

**Phase 2 — Workflow skill (2–3 days).** Write **squad-work**: pick ready task (`blocked_by` all done) → L1: implement+test; L2/L3: plan mode → implement → reviewer subagent gate → tests → flip status, append log, commit `[SQD-042]`. Rolling-wave paragraph for batches. Delete nothing yet; run both mentally side-by-side for a week of tasks.

**Phase 3 — Decommission (1 day + cooldown).** Archive the board (final DB dump), tear down Cloud Run/Postgres, remove PAT guidance from global CLAUDE.md, mark squad-skills v1 README as superseded with a pointer. Retarget the eval harness at the two surviving skills later, only if regressions actually appear.

**Phase 4 — Optional, evidence-gated.** Only on measured pain: (a) tiny `squad` CLI (`ready`/`list`/`stats`) over the files; (b) read-only local board viewer (fluado pattern); (c) `gh` Issues bridge for team visibility; (d) derived SQLite index if grep-scale is ever exceeded. Each waits for its trigger; none changes the format.

---

## Appendix: key sources

- Anthropic: memory & skills docs (code.claude.com/docs/en/memory, /skills, /sub-agents); "Effective harnesses for long-running agents"; "When to use multi-agent systems (and when not to)" (Jan 2026); "Code execution with MCP".
- Cognition: "Don't Build Multi-Agents" (June 2025).
- AGENTS.md standard (agents.md; Linux Foundation / Agentic AI Foundation donation, Dec 2025). Agent Skills standard (agentskills.io; vercel-labs/skills).
- beads (github.com/steveyegge/beads + Yegge's Medium essays; Dolt migration docs; daemon-backlash HN threads 46487580, 46709872). Backlog.md (github.com/MrLesk/Backlog.md). claude-task-master (github.com/eyaltoledano/claude-task-master). spec-kit (github.com/github/spec-kit). OpenSpec (github.com/Fission-AI/OpenSpec). Basic Memory (github.com/basicmachines-co/basic-memory). vibe-kanban SQLite-logs post-mortem (vibekanban.com/blog/goodbye-sqlite-for-logs). fluado "Jira for AI agents" (dev.to/yvg/jira-for-ai-agents-humans-282a). git-bug. ADR renaissance: blog.thestateofme.com (2025-07-10), catio.tech.
- SQLite-in-git: sqlite.org/whynotgit.html, ongardie.net/blog/sqlite-in-git.
