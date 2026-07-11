---
name: squad-gen-wiki
description: "Synthesizes project-level knowledge (architecture, goals, domain knowledge, key decisions) from the Squad board, project files, and code structure into a wiki/ directory. The first run generates the full wiki; 'update' regenerates only topics whose sources changed since the last generation. Never modifies source code. Use when the user wants the project's overall context organized into docs or an existing wiki refreshed; pass --interactive to confirm the topic structure before writing."
license: MIT
metadata:
  internal: true
---

> Shared context: `../squad/shared.md` (api bootstrap, config resolution, error rules).

## `/squad-gen-wiki` — generate · `/squad-gen-wiki update` — refresh

Synthesizes **project-level** knowledge (not per-card detail) into `wiki/`. Writes nothing outside `wiki/`.

### Sources (read-only)

| Source | What is read |
|--------|--------------|
| Squad project | metadata (purpose, brief, stack) + board summary (state counts, progress) |
| Squad cards (selective) | explore-report cards (full description) · done cards with a non-empty decision_log (decision_log only) · in-progress cards (title + priority, already in the summary) |
| Project files | CLAUDE.md, README.md, .claude/rules/, claudeos-core/standard/ (if present) |
| Code structure | top-level tree, package.json (or equivalent manifest), key configs |

**Card selection (never scan every card)**: one pass over the board summary collects (1) ids of cards tagged `explore-report`, (2) all done-card ids (decision_log is not in the summary — filter after the projected read), (3) in-progress titles/priorities with no per-card read. Typically only 20–30% of cards get a detail read.

### Output: `wiki/`

`INDEX.md` (entry point) · `architecture.md` · `goals.md` · `decisions.md` · `domains/{domain}.md` (varies per project). Frontmatter + per-file formats + completion tables: **read `references/wiki-format.md` before writing any wiki file**.

---

### Initial generation

```
① Collect context — run all independent reads IN PARALLEL (one batch):
   - api GET /projects/$PROJECT      → purpose, brief, stack, status, category
   - api GET /board?summary=true     → state counts, tags, done ids, in-progress titles
   - file reads: CLAUDE.md, README.md, .claude/rules/*, claudeos-core/standard/* (when present)
   - code scan: top-level listing (exclude node_modules etc.), manifest, key configs

   Then ONE selection pass over the board summary (explore-report ids + done ids),
   followed by ONE parallel batch of projected reads for only the selected cards:
   - api GET /task/$ID?fields=title,description,tags    (explore-report cards)
   - api GET /task/$ID?fields=title,decision_log        (done cards; drop when decision_log empty/null)

② Topic structure — default-proceed:
   Fixed topics: INDEX.md, architecture.md, goals.md, decisions.md.
   Domain topics: from route groups / component dirs / explore tags on cards;
   <3 domains → omit domains/ and merge into architecture.md; >8 → group related ones.
   Present the proposed topic list and CONTINUE immediately — pause for confirmation
   only if the user objects or --interactive was passed.

③ Write the files per references/wiki-format.md (INDEX, architecture, goals,
   decisions, domains/*).

④ Completion output — the generation table (file · sources · main sources), then:
   > Wiki generated: N files in `wiki/`. Run `/squad-gen-wiki update` after significant changes.
```

### Update

```
① Detect changes since $LAST_GENERATED (the `generated` frontmatter of existing wiki/ files) —
   in parallel: api GET /board?summary=true + file mtime checks (CLAUDE.md, README.md,
   .claude/rules/, key directory structure).
   Board deltas: done cards completed after $LAST_GENERATED (decision_log via the same
   projected-read batch as ①), new explore-report cards, project-brief changes.
   No changes → "No changes detected since {$LAST_GENERATED}. Wiki is up to date." → exit.

② Map changed sources → affected topics and tell the user which will be updated:
   brief → INDEX, goals · new decision_log / explore report → decisions · CLAUDE.md →
   architecture, INDEX · rules → architecture + that domain · new route/component dir →
   architecture + new domain topic · board state → goals.

③ Regenerate ONLY the affected topics — read the existing file, fold in the new sources,
   refresh the `generated` timestamp, preserve still-valid content (not a full rewrite).
   INDEX.md is always regenerated (topic table + board state).

④ Completion output — the update table (file · updated/unchanged · reason).
```

---

### Coach Dispatch (background — never blocks)

After ④ (both procedures), dispatch the Coach per `../squad/references/friction.md` → Coach dispatch, **launched in the background**; never block completion on it. Pass:
`skill_name` = `squad-gen-wiki` · `source_task` = `(wiki)` · `run_summary` = one line on what was generated/updated · `trajectory` = synthesis steps + the generated/updated file list · `friction_signals` = any board-read/source friction (`none` if clean).

### Guardrails

- Never modify anything outside `wiki/`; board reads via the API only (no direct DB access).
- Selective card reads only; never read implementation_notes, review_comments, or test_results.
- Synthesize, don't copy sources verbatim; on update leave unchanged topics untouched.
