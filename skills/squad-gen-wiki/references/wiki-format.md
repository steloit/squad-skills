# Wiki file formats

## Every wiki file

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

## INDEX.md

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

## Per-topic content guides

- **architecture.md** — sources: CLAUDE.md architecture sections, standards dirs, code scan. Content: system diagram (text), directory structure + roles, dependency direction, tech stack details.
- **goals.md** — sources: project brief, board state, in-progress card titles. Content: project purpose, current milestone / in-progress work, completed major work, next steps (inferred from todo cards).
- **decisions.md** — sources: exploration report cards + decision_log of done cards. Content: sorted chronologically; each decision = date, context, decision, rationale; exploration reports as a "direction selection" section; architecture level only (exclude minor implementation decisions).
- **domains/{domain}.md** — sources: the domain's code structure, relevant CLAUDE.md/rules parts, related cards. Content: domain purpose, key files/components, data flow, constraints/forbidden patterns (from rules).

## Completion output tables

Initial generation:

| File | Sources | Main sources |
|------|---------|-----------|
| INDEX.md | — | Full synthesis |
| architecture.md | N | CLAUDE.md, standards, package.json |
| goals.md | N | project brief, the board |
| decisions.md | N | exploration reports, decision_logs |
| domains/{domain}.md | N | {domain dirs} |

Update:

| File | State | Reason for change |
|------|------|-----------|
| INDEX.md | updated | board state refreshed |
| goals.md | updated | 3 new done cards |
| architecture.md | unchanged | — |
