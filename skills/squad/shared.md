# Squad Shared Context

All projects share one Squad board (PostgreSQL behind an HTTP API). Every call goes through the `api.py` helper — it owns auth (PAT), transport (base URL + `/api/orgs/<org>/` prefix + `project=` merge), JSON encoding, and error mapping, internally and opaquely. Never hand-assemble `curl`, headers, or the token.

## Bootstrap (run once per session)

**Working directory matters: `.squadrc` and the project are read from the current directory.** Run squad commands from the user's repo so the project resolves from *its* `.squadrc` — if you resolve a relative script path by `cd`-ing into the skill directory, board reads target the wrong project. Scripts that write to the repo (squad-init) take an explicit target and refuse to run against a skill directory.

```bash
api() { python3 ../squad/scripts/api.py "$@"; }   # api <GET|POST|PATCH|DELETE> <path> [--json <@file|inline|->] [-q dotted.path]
PROJECT="${SQUAD_PROJECT:-}"
[ -z "$PROJECT" ] && [ -f .squadrc ] && PROJECT=$(grep '^SQUAD_PROJECT=' .squadrc | cut -d= -f2-)
[ -z "$PROJECT" ] && PROJECT=$(basename "$(pwd)")

api GET /board?summary=true                                   # example read
api POST /task/$ID/activity --json "$BODY"                    # example write (body built safely — see JSON safety)
```

| Key | Resolution (first match wins) |
|-----|-------------------------------|
| Base URL | env `SQUAD_BASE_URL` > `~/.squad/config` > deployed default |
| Org (tenant) | env `SQUAD_ORG` > committed `.squadrc` — **required**; api.py fail-fasts with the fix if unset |
| Project | env `SQUAD_PROJECT` > `.squadrc` > directory name (no `.squadrc` → suggest `/squad-init`) |
| Auth token | env `SQUAD_AUTH_TOKEN` > `~/.squad/auth` — **never** `.squadrc`, never echoed/cat/Read |

Exit codes: `0` ok · `2` usage/org-unset · `3` auth · `4` client 4xx · `5` server · `6` network. On **401**: the human mints/refreshes a PAT in the board web UI (Settings → Personal Access Tokens) and stores the printed `SQUAD_AUTH_TOKEN=` line — the token is never pasted to the agent. On **403**: the PAT lacks the required scope — a wider-scoped PAT is needed; don't retry until stored. Connectivity check without mutating: `python3 ../squad/scripts/api_smoke.py`.

## Pipeline levels

| Level | Path | Use case |
|-------|------|----------|
| L1 Quick | todo → impl → done | cleanup, config, typos |
| L2 Standard | todo → plan → impl → impl_review → done | feature edits, bug fixes |
| L3 Full | todo → plan → plan_review → impl → impl_review → test → done | new features, architecture |

Statuses: `todo, plan, plan_review, impl, impl_review, test` + the two reopenable terminals `done, cancelled`. Reject loops: `plan_review→plan`, `impl_review→impl`, `test→impl`. `cancelled` is reachable from any status via `/cancel`; `done` via the pipeline or `/complete`; both leave only via `/reopen` (→ todo).

## JSON safety (injection defense)

Board/user text (titles, plans, specs, reasons, any markdown) is **data, never code** — the OWASP OS-command-injection defense is to parameterize, not to escape. Never inline it into a shell string, `--json "{…}"` literal, or `python3 -c "…"` text — backticks/`$(…)` in content command-substitute, the failure is SILENT (the body is corrupted and the payload has already run), and untrusted card content makes it an injection vector. Pass values **out-of-band**: `jq --arg` / `jq -n`, or python `json.dumps` reading from env/stdin/`@file`. Capture is a sink too — a plain double-quoted `VAR="<free text>"` substitutes at the assignment; capture orchestrator-literal free text with single-quoted heredocs (`VAR=$(cat <<'EOF' … EOF)`). A later `"$VAR"` expansion is inert.

## Error handling

- API failure → debug the request and retry; **never** fall back to direct DB access (there is none).
- Agent step failure → 1 retry; on the 2nd failure keep status, record via `POST /task/:id/activity` (actor `Orchestrator`), notify the user.
- Review loops: `plan_review_count > 3` or `impl_review_count > 3` → circuit breaker — stop and ask the user (fires in `--auto` too).
- Mid-run crash → preserve current status, record an activity event, notify the user.

## References (load only when the task needs them)

| File | When to read |
|------|--------------|
| `references/api.md` | full endpoint catalog: tasks, lifecycle, verdicts, activity, attachments, projects, concurrency |
| `references/epics.md` | `blocks`/`parent` edges, epics, readiness/rollup semantics |
| `references/observation.md` | consent gate + `user_steering` emit rubric |
| `references/friction.md` | friction reports, run audit, Coach dispatch |
| `schema.md` | full DB column schema + JSON field formats |
| `principles.md` | safety principles (pipeline skills load this) |
