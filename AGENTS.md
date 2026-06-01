# Steloit Squad — Agent Skills

This repository packages the Steloit Squad skill set as portable
[Agent Skills](https://agentskills.io) (`SKILL.md` format), usable by any
compatible agent — Claude Code, Codex, Cursor, Gemini CLI, and 30+ others.

Canonical skills live in **`plugins/squad/skills/<skill>/SKILL.md`** (single source
of truth). The `.claude-plugin/` manifests expose the same skills to Claude Code as
a plugin; the open `SKILL.md` format makes them portable to every other tool.

## Install

| Tool | How |
|------|-----|
| **Any agent** (Codex, Cursor, Copilot, Gemini, …) | `npx skills add steloit/squad-skills` — auto-detects installed agents, symlinks to a canonical copy. Update with `npx skills update`. |
| **Claude Code** (native) | `/plugin marketplace add steloit/squad-skills` → `/plugin install squad@steloit` (auto-updates) |

`npx skills add steloit/squad-skills -a codex` targets one agent; add `-g` to install globally (user-wide) instead of project-local.

## Configure

All skills talk to the Squad board over HTTP:

```bash
KANBAN_BASE_URL=https://<your-squad-board>
KANBAN_AUTH_TOKEN=<shared-token>
```

## Develop

- Add a skill: create `plugins/squad/skills/<name>/SKILL.md` with `name` + `description` frontmatter.
- Validate: `bash scripts/validate-skills.sh` (also runs in CI on every push/PR).
- Release: bump `version` in `.claude-plugin/marketplace.json` and `plugins/squad/.claude-plugin/plugin.json`.
