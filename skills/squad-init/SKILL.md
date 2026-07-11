---
name: squad-init
description: "Registers the current project on the Squad board so /squad commands target it — writes the committed .squadrc (project name + org slug), detects auth presence, and registers the project via the board API. Use when a repo is not yet connected to the board, when /squad reports an unknown project, or when pointing a repo at a different board project, org, or deployment URL. Usage: /squad-init [project-name] [board-url]."
license: MIT
---

Registers the current project on the shared Squad board (one central server — no per-project database) and writes the local `.squadrc` that targets it.

## Run

Map the slash-command args, then run the script — name/org resolution, `.squadrc`, auth detection, and board registration all happen inside. It registers **the repo you run it in** (writes `.squadrc` there); pass `--dir` to target another. It refuses to run against a skill directory, so run it from the user's project — do not `cd` into the skill folder.

```bash
# /squad-init [name] [url] — an https?:// arg is --base-url; any other token is --project.
python3 ../squad-init/scripts/init.py --dir . [--project NAME] [--org SLUG] [--base-url URL] [--force]
```

| Flag | Meaning | Default |
|------|---------|---------|
| `--dir REPO` | the project repo to register (writes `.squadrc` there) | current directory |
| `--project NAME` | project name (leading dashes stripped) | existing `.squadrc` > target directory name |
| `--org SLUG` | org slug — REQUIRED overall; every board call is org-scoped | env `SQUAD_ORG` > existing `.squadrc` |
| `--base-url URL` | custom board deployment (must be http(s)); persisted to `~/.squad/config` | standard resolution (`../squad/shared.md`) |
| `--force` | overwrite an existing `.squadrc` | refuse conflicting values, print current ones |

The script prints one JSON summary: `project`, `org`, `base_url`, `squadrc` (written/updated/kept/overwritten), `auth` (env/file/none), `registered`, `board_url`.

- No resolvable org → exit 2 with `ERROR: SQUAD_ORG is not set` — take the slug from the mint dialog's `SQUAD_ORG=<slug>` line and re-run with `--org`. It never registers without one.
- Registration goes through the shared helper (`api POST /projects`) and is best-effort: a board failure is a warning, init still succeeds locally.
- The token is never stored, prompted for, or printed; `.squadrc` holds only the non-secret project + org (safe to commit).

## Existing config

Exit 2 with "differs from the requested values" means `.squadrc` already exists. Ask the user — default is keep:

1. **Keep** (default) — re-run without the conflicting flag (existing values are used).
2. **Overwrite** — re-run with `--force`.

## Tell the user

- ✅ Project '<project>' registered — board: `<board_url>` · config: `.squadrc` (committed) · add tasks with `/squad add <title>`.
- `auth: "none"` → relay: mint a Personal Access Token in the board web UI (**Settings → Personal Access Tokens**) and run the store command it shows. Never ask for the token to be pasted here.
