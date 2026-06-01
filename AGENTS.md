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
| **Claude Code** | `/plugin marketplace add steloit/squad-skills` → `/plugin install squad@steloit` (auto-updates) |
| **Codex / open-standard tools** | `git clone` this repo, then `scripts/install.sh` (symlinks into `~/.agents/skills`; `git pull` to update) |
| **Any tool, manual** | point the tool's skills dir at `plugins/squad/skills/` |

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
