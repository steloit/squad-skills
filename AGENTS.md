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

All skills talk to the Squad board over HTTP and authenticate with a **Personal Access Token (PAT)** scoped to the user (minted in the board UI → Settings → Personal Access Tokens). The tenant is selected separately via `SQUAD_ORG`:

```bash
SQUAD_BASE_URL=https://<your-squad-board>      # optional; defaults to the deployed board
SQUAD_AUTH_TOKEN=<your Personal Access Token>  # single PAT (env or bare line in ~/.squad/auth)
# Each repo selects its org with a non-secret SQUAD_ORG=<slug> line in .squadrc (env wins over .squadrc).
```

Resolution: token = `SQUAD_AUTH_TOKEN` env > bare `SQUAD_AUTH_TOKEN=` (`~/.squad/auth`); `SQUAD_ORG` = env > `.squadrc` (**required** — every board call is org-scoped `/api/orgs/<org>/...`). **Secret-safe:** skills never echo/cat/Read the token or `~/.squad/auth`, never use `curl -v`, and resolve the token straight into the `Authorization` header. The mint UI (Settings → Personal Access Tokens) is the only place the token is shown/stored.

## Develop

- Add a skill: create `skills/<name>/SKILL.md` with `name` + `description` frontmatter (`name` must match the directory).
- No internal IDs in shipped files: `skills/**` files carry NO internal board IDs (the team's `<KEY>-NNN` tracking tickets) or backend source paths — describe the feature and reference only the REST API wire contract. Enforced by `tests/test_no_internal_ids_in_skills.py`.
- Validate: `bash scripts/validate-skills.sh` (also runs in CI on every push/PR).
- Release: tag the repo (`npx skills` tracks the git tree / tags for updates).
