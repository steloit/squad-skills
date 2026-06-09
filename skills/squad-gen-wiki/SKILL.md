---
name: squad-gen-wiki
description: Synthesizes the project's overall architecture, goals, and key decisions into a wiki/ directory. The first run generates everything; update reflects only the changes. Organizes project-level knowledge rather than per-card knowledge.
license: MIT
metadata:
  internal: true
---

> Shared context: read `../squad/shared.md` for project config, API endpoints, auth, and error handling.

## `/squad-gen-wiki` — Initial project wiki generation

**When to use**: When you want to organize the project's full context (architecture, goals, domain knowledge, key decisions) into a `wiki/` directory.
This synthesizes **project-level knowledge**, not individual Squad cards.
**This skill does not modify source code.**

## `/squad-gen-wiki update` — Reflect changes

**When to use**: When `wiki/` already exists and you want to reflect code or board changes that happened since.

---

### Sources (read-only — the raw material for synthesis)

The wiki is synthesized by reading the 4 sources below. The sources themselves are not modified.

| Source | What is read | Why |
|------|---------|-----|
| **Squad project** | project metadata (purpose, brief, stack) + board summary (todo/done ratio, milestones) | Current goals and progress |
| **Squad cards (selective)** | cards tagged as exploration reports + done cards that have a decision_log | Major architecture decisions only (excluding implementation details) |
| **Project files** | CLAUDE.md, README.md, .claude/rules/, claudeos-core/standard/ (if present) | Coding rules, architecture definitions |
| **Code structure** | directory tree, package.json, key config files | Tech stack, dependencies |

### Card selection criteria (noise prevention)

Do **not** scan every card on the board. Read only cards that match the conditions below:

1. **Exploration report**: `tags` includes `explore-report` → read the full description
2. **Done cards with major decisions**: done cards whose `decision_log` is not empty → read only the decision_log (ignore impl_notes, review_comments)
3. **In-progress cards**: cards in todo/plan/impl state → read only title + priority (to understand current direction)

With these criteria you typically end up reading only 20-30% of all cards.

---

### Output structure: `wiki/`

```
wiki/
├── INDEX.md                 # Entry point — project overview + topic links
├── architecture.md          # System architecture, tech stack, data flow
├── goals.md                 # Current goals, milestones, roadmap (based on board state)
├── decisions.md             # History of major architecture decisions (synthesized from explorations + decision_log)
└── domains/                 # Per-domain knowledge (varies per project)
    ├── {domain-1}.md        # e.g., courses.md, auth.md, upload.md
    ├── {domain-2}.md
    └── ...
```

### File format

Every wiki file follows the format below:

```markdown
---
topic: {topic name}
generated: {ISO timestamp}
sources: {source count}
---

# {topic name}

## Summary
{2-3 paragraphs. Reading this file alone should be enough to understand the topic.}

## {topic-specific section}
{Content synthesized from the sources. Concrete facts + file path citations.}

## Open Questions
{Items not yet decided or still uncertain.}

## Sources
- CLAUDE.md
- squad #ID: {exploration report title}
- README.md
```

---

### Procedure: Initial generation (`/squad-gen-wiki`)

```
① Collect project context

   ①-A Read Squad project metadata:
   ```bash
   curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/projects/$PROJECT"
   ```
   → extract purpose, brief, stack, status, category

   ①-B Read the board summary:
   ```bash
   curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true"
   ```
   → determine card counts per state and overall progress

   ①-C Read selected cards (noise prevention):

   Find exploration report cards:
   From the board summary, extract the IDs of cards whose tags include "explore-report".
   Read the full description of each card:
   ```bash
   curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=title,description,tags"
   ```

   Find major decision cards:
   Only done cards whose decision_log is not empty.
   Since decision_log is omitted from the board summary, first extract the list of done card IDs,
   then read only the decision_log field for each:
   ```bash
   curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/task/$ID?project=$PROJECT&fields=title,decision_log"
   ```
   If decision_log is null or an empty string, skip it.

   In-progress cards:
   Use only the title + priority of todo/plan/impl state cards from the board summary.

   ①-D Read project files:
   - CLAUDE.md (project root)
   - README.md (if present)
   - all of .claude/rules/ (if present)
   - all of claudeos-core/standard/ (if present)

   ①-E Scan the code structure:
   - top-level directory listing (`ls` — excluding node_modules etc.)
   - package.json (dependencies, scripts)
   - key configs (tsconfig.json, next.config.ts, etc.)

② Decide the topic structure

   Decide the wiki topic structure based on the collected sources.

   Fixed topics (all projects):
   - INDEX.md — overall overview
   - architecture.md — system architecture
   - goals.md — current goals + milestones
   - decisions.md — history of major decisions

   Domain topics (determined automatically per project):
   - extract domains from route groups under app/, subdirectories under components/, or
     the explore tags on Squad cards
   - if there are fewer than 3 domains, omit the domains/ directory and merge into architecture.md
   - if there are more than 8 domains, group related ones (e.g., upload + storage → data-pipeline)

   Present the topic structure to the user for confirmation (AskUserQuestion):
   "I'll generate the wiki with the following structure. Are there any topics you'd like to change?"
   - show the topic list
   - choose "Proceed as is" / "Edit topics"

③ Generate the wiki files

   Create the wiki/ directory, then write each topic file.

   ③-A Write INDEX.md:
   ```markdown
   ---
   topic: Project overview
   generated: {ISO timestamp}
   sources: {total source count}
   ---

   # {project name} Wiki

   > Last generated: {date} | Topics: {N} | Sources: {N}

   ## Project overview
   {2-3 paragraphs based on project purpose + brief}

   ## Tech stack
   {stack info table}

   ## Topics
   | Topic | Description | Sources |
   |------|------|---------|
   | [architecture](architecture.md) | System structure, data flow | N |
   | [goals](goals.md) | Current goals, progress | N |
   | [decisions](decisions.md) | Major architecture decisions | N |
   | [{domain}](domains/{domain}.md) | {one-line description} | N |

   ## Current state (Squad)
   | State | Card count |
   |------|---------|
   | todo | N |
   | in progress | N |
   | done | N |
   ```

   ③-B Write architecture.md:
   Sources: the architecture section of CLAUDE.md + claudeos-core/standard/00.core/ + code structure scan
   - system diagram (text)
   - directory structure + roles
   - dependency direction
   - tech stack details

   ③-C Write goals.md:
   Sources: project brief + board state + in-progress card titles
   - project purpose (why it was built)
   - current milestone / in-progress work
   - completed major work (meaningful items among done cards)
   - next steps (inferred from todo cards)

   ③-D Write decisions.md:
   Sources: exploration report cards + decision_log of done cards
   - sorted chronologically
   - each decision: date, context, decision content, rationale
   - include exploration reports as a "direction selection" section
   - exclude minor implementation decisions (architecture level only)

   ③-E Write domains/{domain}.md (one per domain):
   Sources: the domain's code structure + relevant parts of CLAUDE.md/rules + related Squad cards
   - domain purpose
   - key files/components
   - data flow
   - constraints/forbidden patterns (from rules)

④ Completion output

   Show the list of generated files + the source count for each:

   | File | Sources | Main sources |
   |------|---------|-----------|
   | INDEX.md | — | Full synthesis |
   | architecture.md | N | CLAUDE.md, standard/, package.json |
   | goals.md | N | project brief, the board |
   | decisions.md | N | exploration reports, decision_logs |
   | domains/courses.md | N | app/courses/, components/courses/ |

   > Wiki generated: N files in `wiki/`.
   > Run `/squad-gen-wiki update` after significant changes to refresh.

⑤ Coach — run the shared **Coach dispatch** below (friction review of this run).
```

---

### Procedure: Update (`/squad-gen-wiki update`)

```
① Detect changes

   ①-A Read the generated timestamp from the current wiki/ files (frontmatter)
   → $LAST_GENERATED

   ①-B Identify changed sources:

   Board changes:
   ```bash
   # Cards completed since the last generation
   curl -s "${AUTH_HEADER[@]}" "$BASE_URL/api/board?project=$PROJECT&summary=true"
   ```
   → done cards with completed_at > $LAST_GENERATED that have a decision_log
   → newly created exploration report cards
   → whether the project brief changed

   File changes:
   → CLAUDE.md, README.md with mtime > $LAST_GENERATED
   → whether .claude/rules/ changed
   → changes to key directory structure (new route, new component directory)

   ①-C If there are no changes:
   "No changes detected since {$LAST_GENERATED}. Wiki is up to date."
   → exit

② Determine affected topics

   Map changed sources → which topics are affected:

   | Changed source | Affected topics |
   |-----------|-------------|
   | project brief changed | INDEX.md, goals.md |
   | new done card (decision_log) | decisions.md |
   | new exploration report | decisions.md |
   | CLAUDE.md changed | architecture.md, INDEX.md |
   | .claude/rules/ changed | architecture.md, the relevant domain |
   | new route/component directory | architecture.md, create a new domain topic |
   | board state changed | goals.md |

   Show the change summary to the user:
   "I'll update the following topics:"
   - goals.md (3 new done cards, brief updated)
   - decisions.md (1 new exploration report)

③ Selective regeneration

   Regenerate only the affected topics.
   Leave unchanged topics as they are.

   When regenerating:
   - read the existing file content
   - update it to reflect the new source content
   - refresh the generated timestamp
   - preserve the parts of the existing content that are still valid (not a full rewrite)

   INDEX.md is always regenerated (refresh the topic table and board state).

④ Completion output

   | File | State | Reason for change |
   |------|------|-----------|
   | INDEX.md | updated | board state refreshed |
   | goals.md | updated | 3 new done cards |
   | decisions.md | updated | 1 new exploration report |
   | architecture.md | unchanged | — |
   | domains/courses.md | unchanged | — |

   > Wiki updated: N files changed, M unchanged.

⑤ Coach — run the shared **Coach dispatch** below (friction review of this run).
```

---

### Coach dispatch (friction review of this run)

After `④ Completion output` (BOTH procedures — initial and update) close, dispatch the **Coach** per `../squad/shared.md` → **Coach Dispatch**. gen-wiki is fully inline (no provider resolution today), so resolve `MODEL_PROVIDER` + the `read_model` / `read_effort` helpers per `../squad/shared.md` → **Model Resolution** first, then pass:
- `skill_name` = `squad-gen-wiki`
- `source_task` = `(wiki)`
- `run_summary` = `"squad-gen-wiki generated/updated the project wiki."`
- `trajectory` = the synthesis steps + the generated/updated file list
- `friction_signals` = any board-read / source friction; `none` if clean

---

### Guardrails

- **Do not modify source code**: this skill only creates/modifies the `wiki/` directory
- **Do not scan every card**: read only what matches the selection criteria (exploration report, done cards with a decision_log, in-progress titles)
- **Exclude implementation details**: do not read implementation_notes, review_comments, or test_results
- **Synthesize, don't copy**: do not copy sources verbatim — synthesize them at the project level
- **Preserve the existing wiki**: on update, don't touch topics that haven't changed
- **Board API only**: always read board data via the HTTP API (no direct DB access)
- **User confirmation**: confirm the topic structure with the user during initial generation
