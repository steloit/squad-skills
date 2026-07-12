> **FROZEN (2026-07-13).** This repository is now the historical record of the
> Squad skills era: architecture research (`claudedocs/`), and Skills v1 as
> published (installable and functional, but no longer developed). Execution
> moved to the deterministic runtime (**steloit/squad-engine**); what skills
> want to become without execution responsibilities is being rediscovered from
> scratch in a new repository, one production-proven skill at a time.

<p align="center">
  <strong>Steloit Squad</strong> — AI-team kanban pipeline + code-review skills
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/Agent_Skills-open_standard-8A2BE2" alt="Agent Skills" />
</p>

Squad runs your tasks through an AI-team pipeline (Planner → Critic → Builder → Shield → Inspector → Ranger) on a shared kanban board, plus intent-aware PR review skills. Portable [Agent Skills](https://agentskills.io) (`SKILL.md`) — works with Claude Code, Codex, Cursor, Gemini CLI, and 50+ other agents.

## Install

One command for any agent — the [`skills`](https://github.com/vercel-labs/skills) CLI auto-detects your installed agents (Claude Code, Codex, Cursor, …) and installs to each:

```bash
npx skills add steloit/squad-skills          # the 5 core skills, to detected agents
npx skills add steloit/squad-skills -a codex -g   # one agent, global (user-wide)
npx skills update                            # update installed skills later
```

You get the **5 core skills**: `squad` (board), `squad-init` (register a project), `squad-run` (run the pipeline), `squad-refine` (refine requirements), `squad-explore` (scope work).

### Maintainers — internal skills

The repo also ships specialized skills (`squad-batch-run`, `squad-gen-wiki`, `squad-heartbeat`, `squad-kickstart`) flagged `metadata.internal: true`, so they stay hidden from the install above. To pull them too:

```bash
INSTALL_INTERNAL_SKILLS=1 npx skills add steloit/squad-skills
```

## Configure

The skills default to the deployed board and authenticate with a **Personal Access Token (PAT)** scoped to the user (minted in the board UI — Settings → Personal Access Tokens: name + scopes + expiry → copy once → run the printed store command). The token is read tool-agnostically. The mint command is the **single source** for the token — skills never echo, cat, or store it.

> **NOTE:** the mint UI requires the board running current code — redeploy the board first if Settings → Personal Access Tokens is missing.

**Store the token** — a single `SQUAD_AUTH_TOKEN`, via env or the credential file:

```bash
# Option A — environment variable (works for every agent: Claude Code, Codex, Cursor)
export SQUAD_AUTH_TOKEN='<your Personal Access Token>'   # add to ~/.zshrc or ~/.profile to persist

# Option B — credential file (mode 600; keeps the secret out of your shell profile)
mkdir -p ~/.squad && printf 'SQUAD_AUTH_TOKEN=%s\n' '<your Personal Access Token>' > ~/.squad/auth && chmod 600 ~/.squad/auth
```

**Selecting the org** — the tenant is set separately from the token. Each repo picks its org via a non-secret `SQUAD_ORG=<slug>` line in `.squadrc` (`<slug>` = the org slug from the mint dialog, reused verbatim):

```
SQUAD_ORG=acme
```

Resolution: token = `SQUAD_AUTH_TOKEN` env > bare `SQUAD_AUTH_TOKEN=` (`~/.squad/auth`); `SQUAD_ORG` = env > `.squadrc` (**required** — every board call is org-scoped `/api/orgs/<org>/...`). The same PAT works across every org you can access; `SQUAD_ORG` only selects the path, never the token.

**Auth errors:** `401` = no/invalid/expired token → mint or refresh a **Personal Access Token** in the web UI (Settings → Personal Access Tokens). `403 FORBIDDEN` = valid token but missing scope → mint a PAT **with the needed scopes** (Settings → Personal Access Tokens).

`SQUAD_BASE_URL` is optional — it defaults to the deployed board; set it (env, or `~/.squad/config`) only to point at a self-hosted board. Then register a project from its directory:

```
/squad-init
```

### Recommended: a secret-safe CLAUDE.md deny-rule

The token must never enter an agent's context. Add this to your global `~/.claude/CLAUDE.md` (or your agent's equivalent) so the agent won't read or relay the credential store:

```markdown
## Squad secrets — never expose
- Never Read, `cat`, `echo`, or relay the contents of `~/.squad/*` (auth/config files).
- Never run `env` / `printenv` or otherwise print `SQUAD_AUTH_TOKEN*`.
- Resolve the token straight into the `Authorization` header; never use `curl -v` / header logging.
```

## Commands

| Command | What it does |
|---------|--------------|
| `/squad` | View / manage the board |
| `/squad-init` | Register the current project |
| `/squad-refine` | Turn a rough task into a concrete spec |
| `/squad-run` | Run the AI-team pipeline on a task |
| `/squad-batch-run` | Rolling-wave batch execution across tasks |
| `/squad-explore` | Codebase exploration → phased task plan |
| `/squad-gen-wiki` | Synthesize a project wiki |
| `/squad-heartbeat` | Detect stagnant tasks |

## Testing & evals

Two tiers — full detail in **[EVALS.md](EVALS.md)**:

- **`tests/` — deterministic** (pytest): the non-LLM logic — selector parsing, grouping/parallel rules, auth resolution, prompt rendering. No keys, runs on every PR.
  ```bash
  pip install -r tests/requirements.txt && python -m pytest tests/ -q
  ```
- **`evals/` — behavioral** (DeepEval): runs the real agent headless against a `squad-eval` board project (**N trials/scenario**), scored on **board-state ground truth + a GEval rubric**. Records to a git-versioned `history.jsonl` and flags **regressions vs a trailing baseline** (Welch's t-test) + writes an HTML trend dashboard. Uses your **Claude Code login — no API key needed locally** (+ a board token); on-demand/nightly (costs tokens/credits).
  ```bash
  pip install -r evals/requirements.txt && python evals/run_evals.py --trials 3
  ```

### Known gap

`ToolCorrectnessMetric` is **intentionally not wired in yet**. While the skills talk to the board over `Bash(curl)`, every tool call is just "Bash" — there's nothing meaningful to score. It becomes valuable **after an MCP migration** exposes typed `squad_*` tools; the harness is structured so it drops in then without rework.

## License

MIT — see [LICENSE](LICENSE). Derived from prior MIT-licensed work; see [NOTICE](NOTICE) for attribution.
