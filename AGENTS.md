# Steloit Squad — Agent Skills

This repository packages the Steloit Squad skill set as portable
[Agent Skills](https://agentskills.io) (`SKILL.md` format), usable by any
compatible agent — Claude Code, Codex, Cursor, Gemini CLI, and 30+ others.

Skills live in **`skills/<skill>/SKILL.md`** — a flat, open-standard layout, no
plugin/marketplace wrapper.

## Install

One command for any agent (Claude Code, Codex, Cursor, Gemini, …) — the
[`skills`](https://github.com/vercel-labs/skills) CLI auto-detects installed agents and
symlinks the skills to a canonical copy:

```bash
npx skills add steloit/squad-skills          # detected agents, project-local
npx skills add steloit/squad-skills -a codex -g   # one agent, global
npx skills update                            # update
```

## Configure

All skills talk to the Squad board over HTTP:

```bash
SQUAD_BASE_URL=https://<your-squad-board>
SQUAD_AUTH_TOKEN=<shared-token>
```

## Develop

- Add a skill: create `skills/<name>/SKILL.md` with `name` + `description` frontmatter (`name` must match the directory).
- Validate: `bash scripts/validate-skills.sh` (also runs in CI on every push/PR).
- Release: tag the repo (`npx skills` tracks the git tree / tags for updates).
