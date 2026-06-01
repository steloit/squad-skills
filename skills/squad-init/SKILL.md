---
name: squad-init
description: "Register and initialize the current project in PostgreSQL squad. Usage: /squad-init or /squad-init my-project-name. Run with /squad-init."
license: MIT
---

Registers the current project in **PostgreSQL** (shared central DB) and creates a local config so `/squad` knows which project to use.
No per-project DB file is created — the central PostgreSQL server handles storage for all projects automatically.

## Usage

```
/squad-init                                      — project name = basename of current directory, board = https://steloit-squad.vercel.app
/squad-init my-project-name                      — explicit project name, board = https://steloit-squad.vercel.app
/squad-init my-project-name https://board.example.com
                                                 — explicit project name + custom board URL
/squad-init https://board.example.com           — current directory name + custom board URL
```

If a URL argument is present, treat it as `base_url`. Strip any leading dashes from the project token: `squad-init -unahouse.finance` → project `unahouse.finance`.

## Procedure

### 1. Determine project name and board URL

```bash
# Split raw args
set -- $ARG
ARG1="${1:-}"
ARG2="${2:-}"

# Accept either:
#   /squad-init my-project
#   /squad-init my-project https://board.example.com
#   /squad-init https://board.example.com
if printf '%s' "$ARG1" | grep -Eq '^https?://'; then
  PROJECT=$(basename "$(pwd)")
  BASE_URL="$ARG1"
else
  PROJECT=$(printf '%s' "$ARG1" | sed 's/^-*//')
  [ -z "$PROJECT" ] && PROJECT=$(basename "$(pwd)")
  BASE_URL="${ARG2:-https://steloit-squad.vercel.app}"
fi
```

### 2. Write local project config

Create **one** tool-agnostic file at the **current project root**, committed to git so the whole team's agents target the same board project:

`.squadrc`
```
SQUAD_PROJECT=<PROJECT_NAME>
```

**`.squadrc` holds ONLY the project name** (non-secret → safe to commit). The token lives in `SQUAD_AUTH_TOKEN` / `~/.squad/auth`; the board URL defaults to the deployed board.

Use the Write tool to create `.squadrc`.

### 2b. Set up global auth (if not configured)

The token is resolved from `SQUAD_AUTH_TOKEN` (env) or `~/.squad/auth`. If neither is set, tell the user how to configure it — never invent a token or write one into a project file:

```bash
if [ -z "${SQUAD_AUTH_TOKEN:-}" ] && [ ! -f "$HOME/.squad/auth" ]; then
  echo "No Squad token found. Set it once (shared across all projects):"
  echo "  export SQUAD_AUTH_TOKEN='<token>'      # add to ~/.zshrc to persist"
  echo "  …or: mkdir -p ~/.squad && printf 'SQUAD_AUTH_TOKEN=%s\\n' '<token>' > ~/.squad/auth && chmod 600 ~/.squad/auth"
fi

# Persist a custom (non-default) board URL only — to ~/.squad/config
if [ -n "$BASE_URL" ] && [ "$BASE_URL" != "https://steloit-squad.vercel.app" ]; then
  mkdir -p "$HOME/.squad"
  grep -q '^SQUAD_BASE_URL=' "$HOME/.squad/config" 2>/dev/null || printf 'SQUAD_BASE_URL=%s\n' "$BASE_URL" >> "$HOME/.squad/config"
fi
```

### 2c. Auto-register project in projects table

After writing the config, upsert the current project to the projects table via POST /api/projects.
Infer project metadata from the local environment:

```bash
# Category defaults to "personal"; change it on the board if needed.
CATEGORY="personal"
echo "$PROJECT" | grep -qiE 'skill|squad' && CATEGORY="skills"
echo "$PROJECT" | grep -qiE 'tool|api|cli'  && CATEGORY="tools"

# Infer purpose from CLAUDE.md (first non-heading, non-empty line)
PURPOSE=""
if [ -f "CLAUDE.md" ]; then
  PURPOSE=$(grep -v '^#' CLAUDE.md | grep -v '^---' | grep -v '^\s*$' | head -1 | cut -c1-300)
fi

# Infer stack from CLAUDE.md
STACK=""
if [ -f "CLAUDE.md" ]; then
  STACK=$(grep -iE 'stack|tech|typescript|javascript|python|react|vue|next|node|vite' CLAUDE.md | head -1 | cut -c1-200)
fi

# Infer repo_url from git remote
REPO_URL=$(git remote get-url origin 2>/dev/null || echo "")

# Upsert project
PROJ_PAYLOAD=$(python3 -c "
import json
print(json.dumps({
  'id': '$PROJECT',
  'name': '$PROJECT',
  'purpose': '''$PURPOSE''' if '''$PURPOSE''' else None,
  'stack': '''$STACK''' if '''$STACK''' else None,
  'category': '$CATEGORY',
  'repo_url': '$REPO_URL' if '$REPO_URL' else None,
}))
")
curl -s "${AUTH_HEADER[@]}" -X POST "$BASE_URL/api/projects" \
  -H 'Content-Type: application/json' \
  -d "$PROJ_PAYLOAD" > /dev/null 2>&1 || true
```

This is best-effort — if the API call fails (e.g., board unreachable), init still succeeds.

### 3. Output confirmation

Output:
```
✅ Project '<PROJECT_NAME>' registered in squad.

  Config:  .squadrc (committed)
  DB:      PostgreSQL (shared central DB)
  Board:   <BASE_URL>/?project=<PROJECT_NAME>
  Auth:    SQUAD_AUTH_TOKEN env / ~/.squad/auth (global secret)

Add tasks with /squad add <title>
```

## Notes

### Existing config detection

If `.squadrc` already exists, read `SQUAD_PROJECT` and ask before overwriting:

```
.squadrc already exists:
  Current project: "<name>"

Options:
1. Overwrite — update SQUAD_PROJECT
2. Keep as-is — leave .squadrc unchanged
```

- `/squad-init` defaults to `https://steloit-squad.vercel.app` unless you provide another deployment URL.
- The token is stored globally (`SQUAD_AUTH_TOKEN` env or `~/.squad/auth`), NOT in `.squadrc`. This prevents token duplication across repos and keeps secrets out of git.
- For remote private boards, set `SQUAD_AUTH_TOKEN` in the shell before running `/squad-init`, or write `~/.squad/auth` (mode 600).
