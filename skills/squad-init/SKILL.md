---
name: squad-init
description: "Register the current project on the Squad board so /squad commands target it. Usage: /squad-init or /squad-init my-project-name. Run with /squad-init."
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
SQUAD_ORG=<ORG_LABEL>          # OPTIONAL — only when the user supplies an org label (multi-org machines)
```

**`.squadrc` holds the project name and an OPTIONAL org label** (both non-secret → safe to commit). Write the `SQUAD_ORG=<label>` line **only when the user supplies a label** — from the mint dialog's `SQUAD_ORG=<slug>` line or an explicit init arg. Single-org users supply nothing → no `SQUAD_ORG` line → the bare `SQUAD_AUTH_TOKEN=` default is used (zero friction). The label is **never** auto-derived from the board (the project API exposes no org slug today — a noted follow-up). The token never lives in `.squadrc`; it lives in `~/.squad/auth` as a per-org `SQUAD_AUTH_TOKEN_<label>=` line or the bare default.

Use the Write tool to create `.squadrc` (include the `SQUAD_ORG=` line only when a label was supplied).

### 2b. Detect auth (no token store here)

The token is resolved org-scoped via the shared.md chain (env > per-org line > bare default). squad-init **never** stores a token, **never** echoes/cats it, and **never** asks for a pasted one — the token-store command lives **only** at the web mint UI — Settings → API Keys (the single place the real token + org slug exist). On no token, squad-init just prints a one-line POINTER to that UI:

```bash
# Resolve the token (env > per-org line > bare default) straight into the header — never echo it.
SQUAD_ORG="${SQUAD_ORG:-}"
[ -z "$SQUAD_ORG" ] && [ -f .squadrc ] && SQUAD_ORG=$(grep '^SQUAD_ORG=' .squadrc | cut -d= -f2-)
AUTH_TOKEN="${SQUAD_AUTH_TOKEN:-}"; AUTH_SOURCE=$([ -n "$AUTH_TOKEN" ] && echo env || echo none)
if [ -z "$AUTH_TOKEN" ] && [ -f "$HOME/.squad/auth" ]; then
  if [ -n "$SQUAD_ORG" ]; then
    AUTH_TOKEN=$(grep "^SQUAD_AUTH_TOKEN_${SQUAD_ORG}=" "$HOME/.squad/auth" | cut -d= -f2-)
    [ -n "$AUTH_TOKEN" ] && AUTH_SOURCE="org:$SQUAD_ORG"
  fi
  if [ -z "$AUTH_TOKEN" ]; then
    AUTH_TOKEN=$(grep '^SQUAD_AUTH_TOKEN=' "$HOME/.squad/auth" | cut -d= -f2-)
    [ -n "$AUTH_TOKEN" ] && AUTH_SOURCE=default
  fi
fi
AUTH_HEADER=(); [ -n "$AUTH_TOKEN" ] && AUTH_HEADER=(-H "Authorization: Bearer $AUTH_TOKEN")

if [ -z "$AUTH_TOKEN" ]; then
  echo "No Squad key for org '${SQUAD_ORG:-this board}' — mint one at $BASE_URL/api-keys and run the store command it shows."
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

# Infer purpose + stack from CLAUDE.md (best-effort)
PURPOSE=""; STACK=""
if [ -f "CLAUDE.md" ]; then
  PURPOSE=$(grep -v '^#' CLAUDE.md | grep -v '^---' | grep -v '^[[:space:]]*$' | head -1 | cut -c1-300)
  STACK=$(grep -iE 'stack|tech|typescript|javascript|python|react|vue|next|node|vite' CLAUDE.md | head -1 | cut -c1-200)
fi
REPO_URL=$(git remote get-url origin 2>/dev/null || echo "")

# Build the payload safely with jq — never interpolate file/user text into code (see shared.md "JSON Safety").
PROJ_PAYLOAD=$(jq -n \
  --arg id "$PROJECT" --arg name "$PROJECT" --arg category "$CATEGORY" \
  --arg purpose "$PURPOSE" --arg stack "$STACK" --arg repo_url "$REPO_URL" \
  '{id: $id, name: $name, category: $category,
    purpose:  (if $purpose  == "" then null else $purpose  end),
    stack:    (if $stack    == "" then null else $stack    end),
    repo_url: (if $repo_url == "" then null else $repo_url end)}')
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
  Org:     <ORG_LABEL>   (or "(default key)" when no SQUAD_ORG label was supplied)
  DB:      PostgreSQL (shared central DB)
  Board:   <BASE_URL>/?project=<PROJECT_NAME>
  Auth:    org-scoped API key — SQUAD_AUTH_TOKEN env / ~/.squad/auth (global secret; configured / empty, value-free)

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
- Tokens are **org-scoped, scoped API keys** stored globally in `~/.squad/auth` (mode 600) — per-org `SQUAD_AUTH_TOKEN_<label>=` lines plus an optional bare `SQUAD_AUTH_TOKEN=` default — or the `SQUAD_AUTH_TOKEN` env var; NEVER in `.squadrc`. This keeps secrets out of git and lets one machine serve multiple orgs.
- `.squadrc` carries only the project name + an optional non-secret `SQUAD_ORG=<label>` selector. squad-init writes `SQUAD_ORG` solely from a user-supplied label — it is **not** board-derived (the project API exposes no org slug; auto-derive + verify is a noted follow-up).
- squad-init **never stores or prompts for a token**: minting + the store command live only at the web mint UI — Settings → API Keys (`$BASE_URL/api-keys`). On no token it prints a one-line pointer to that UI.
- For remote private boards, mint an org-scoped key at `$BASE_URL/api-keys` and run the store command it prints (writes `~/.squad/auth`, mode 600), or set `SQUAD_AUTH_TOKEN` in the shell before running `/squad-init`.
