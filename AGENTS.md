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

**Shipped `skills/**` is the installed product surface** — it is installed on users' devices
(`npx skills add`) and executed by AI coding agents against the user's *own* repo, in any language.
Hold these constraints on **every** change:

- **Instruction-only.** A shipped skill file tells the agent *what to do* — nothing else. NO design
  rationale, decisions-not-taken ("deliberately" / "out of scope" / "we decided"), references to
  features that don't exist, or sales prose ("future-proofs at zero cost", "language-agnostic by
  construction"). Design rationale belongs on the board (the card's `decision_log`), never in the
  installed payload.
- **Language / tool / framework portable.** Skills run against any stack — Go, Rust, Java, Python,
  TS, Elixir, … NEVER hardcode a toolchain (`pnpm` / `vitest` / `biome` / `cargo` / `go test`).
  Resolve a repo's real build/lint/test/format commands via the ladder in
  `skills/squad/templates/_shared.md` → **Command resolution**: the loaded project context (AGENTS.md canonical /
  CLAUDE.md / GEMINI.md / `.cursor/rules` / `.github/copilot-instructions.md`) → the repo task runner
  (make / just / Taskfile / mise / npm scripts) → auto-detect by language. Tool names appear only as
  *examples*, never as THE command.
- **No internal IDs / backend internals.** `skills/**` carry NO internal board IDs (the team's
  `<KEY>-NNN` tickets) or backend source paths — describe the feature and reference only the REST API
  wire contract. Enforced by `tests/test_no_internal_ids_in_skills.py`. (`tests/` itself is dev-only —
  not installed — so these two rules apply to `skills/**` only.)

Mechanics:

- Add a skill: create `skills/<name>/SKILL.md` with `name` + `description` frontmatter (`name` must match the directory).
- Validate: `bash scripts/validate-skills.sh` (also runs in CI on every push/PR).
- Release: tag the repo (`npx skills` tracks the git tree / tags for updates).

**Runtime token-usage capability (maintainer note).** The step-⑥ `tokens` field is intentionally
OPTIONAL / best-effort because per-subagent usage is not portably readable, so the shipped skill
populates it only from whatever usage the host runtime itself reports. Empirically, Claude Code
exposes per-subagent usage on **background** Task completions (undocumented, observed — not a
supported contract), but **not** in the documented **foreground** Task result; Codex is unverified.
The portable target this field aligns to is the OpenTelemetry GenAI usage model (`gen_ai.usage.*` —
provider-sourced, best-effort population), so a future supported source drops in cleanly. Pursuing a
supported per-subagent usage interface (file Claude Code feedback for a documented exposure; wire
`gen_ai.usage.*` when available) is a separate follow-up, not built here. This detail stays here —
never in shipped `skills/**`, which must remain portable and free of runtime-specific field names.
