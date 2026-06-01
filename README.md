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
npx skills add steloit/squad-skills          # install to detected agents (project-local)
npx skills add steloit/squad-skills -a codex -g   # one agent, global (user-wide)
npx skills update                            # update installed skills
```

## Configure

The skills default to the deployed board, so you only supply the shared token — read tool-agnostically, so set it whichever way suits you:

```bash
# Option A — environment variable (works for every agent: Claude Code, Codex, Cursor)
export SQUAD_AUTH_TOKEN='<your-shared-token>'        # add to ~/.zshrc or ~/.profile to persist

# Option B — credential file (mode 600; keeps the secret out of your shell profile)
mkdir -p ~/.squad && printf 'SQUAD_AUTH_TOKEN=%s\n' '<your-shared-token>' > ~/.squad/auth && chmod 600 ~/.squad/auth
```

`SQUAD_BASE_URL` is optional — it defaults to the deployed board; set it (env, or `~/.squad/config`) only to point at a self-hosted board. Then register a project from its directory:

```
/squad-init
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
| `/squad-review-pr` | PR code review (auto-detects backend/frontend/PLC) |

## License

MIT — see [LICENSE](LICENSE). Derived from prior MIT-licensed work; see [NOTICE](NOTICE) for attribution.
