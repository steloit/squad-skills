<p align="center">
  <strong>Steloit Squad</strong> — AI-team kanban pipeline + code-review skills for Claude Code
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License" />
  <img src="https://img.shields.io/badge/Claude_Code-plugin-8A2BE2" alt="Claude Code Plugin" />
  <img src="https://img.shields.io/badge/version-0.1.0-orange" alt="v0.1.0" />
</p>

Squad runs your tasks through an AI-team pipeline (Planner → Critic → Builder → Shield → Inspector → Ranger) on a shared kanban board, plus intent-aware PR review skills.

## Install

Squad is distributed as a Claude Code plugin. Install once and it auto-updates as this repo is updated.

```
/plugin marketplace add steloit/squad-skills
/plugin install squad@steloit
```

## Configure

The skills talk to a Squad board over HTTP. Point them at your board and supply the shared token:

```bash
# ~/.claude/squad-auth  (shared across your projects; never commit)
KANBAN_BASE_URL=https://<your-squad-board-url>
KANBAN_AUTH_TOKEN=<your-shared-token>
```

Then register a project from its directory:

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
