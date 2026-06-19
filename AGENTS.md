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

All skills talk to the Squad board over HTTP and authenticate with an **org-scoped, scoped API key** (minted in the board UI → Settings → API Keys). One machine can serve multiple orgs:

```bash
SQUAD_BASE_URL=https://<your-squad-board>      # optional; defaults to the deployed board
SQUAD_AUTH_TOKEN=<org-scoped key>              # single-org bare default (env or ~/.squad/auth)
# Multi-org: ~/.squad/auth holds per-org SQUAD_AUTH_TOKEN_<label>= lines + an optional bare default,
# each repo selecting its org via SQUAD_ORG=<label> in .squadrc.
```

Resolution: `SQUAD_AUTH_TOKEN` env > `SQUAD_AUTH_TOKEN_<SQUAD_ORG>` (`~/.squad/auth`) > bare `SQUAD_AUTH_TOKEN=` (`~/.squad/auth`); `SQUAD_ORG` = env > `.squadrc`. **Secret-safe:** skills never echo/cat/Read the token or `~/.squad/auth`, never use `curl -v`, and resolve the token straight into the `Authorization` header. The mint UI is the only place the token is shown/stored.

## Develop

- Add a skill: create `skills/<name>/SKILL.md` with `name` + `description` frontmatter (`name` must match the directory).
- Validate: `bash scripts/validate-skills.sh` (also runs in CI on every push/PR).
- Release: tag the repo (`npx skills` tracks the git tree / tags for updates).
