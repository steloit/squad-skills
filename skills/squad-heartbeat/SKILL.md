---
name: squad-heartbeat
description: Scan squad boards for stagnant tasks and optionally mark them. Detects tasks with no agent activity for N days (default 3), outputs a markdown report table, and appends Heartbeat activity events unless --dry-run.
license: MIT
metadata:
  internal: true
---

> Shared context: read `../squad/shared.md` for pipeline levels, status transitions, API endpoints, error handling, and agent context flow.
> Schema: read `../squad/schema.md` for full DB schema, column descriptions, and JSON field formats.

## `/squad-heartbeat [--project X] [--days N] [--dry-run]` -- Stagnant Task Detection

Scan all active projects (or a single project) for tasks that have had no agent activity for N days. Output a markdown table of stagnant tasks and optionally append a Heartbeat warning event to each task's `activity` stream.

**Defaults**: `--days 3`, all active projects, writes a Heartbeat `activity` event per stagnant task.
**`--dry-run`**: report only, no `activity` writes.

### Procedure

```
① Auth & Argument Setup

   Board access goes through the `api.py` helper, which owns auth (single token: env
   `SQUAD_AUTH_TOKEN` > bare `SQUAD_AUTH_TOKEN=` in `~/.squad/auth`), `BASE_URL`, the
   `/api/orgs/<org>/` prefix, and `Content-Type`. This is a maintainer tool with no per-repo
   `.squadrc`, so `SQUAD_ORG` comes from the env only and must be exported so the helper (a
   subprocess) sees it; set `SQUAD_ORG` before running to target a specific org:

   SQUAD_ORG="${SQUAD_ORG:-}"
   if [ -z "$SQUAD_ORG" ]; then
     echo "ERROR: SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...)." >&2
     echo "Export SQUAD_ORG=<slug> (from the mint dialog) before running the heartbeat." >&2
     exit 1
   fi
   export SQUAD_ORG   # api.py (a subprocess) reads the org from the env
   api() { python3 ../squad/scripts/api.py "$@"; }

   Parse CLI arguments:
   - --project X  → scan only project X (default: all active projects)
   - --days N     → stagnation threshold in days (default: 3)
   - --dry-run    → report only, do not write activity events

② Fetch Projects

   If --project X specified:
     Validate project exists:
     api GET /projects/$X
     If 404 → print error "Project '$X' not found." and exit.
     PROJECTS=("$X")

   Else (all projects):
     ALL=$(api GET /projects)
     Extract active projects:
     PROJECTS = jq '.projects[] | select(.status == "active") | .id' from ALL

③ Fetch Board per Project (full view)

   For each project P in PROJECTS:
     BOARD=$(api GET /board?project=$P)

     Collect tasks from columns: todo, plan, plan_review, impl, impl_review, test
     SKIP the done column entirely.

     If project has 0 tasks across all active columns → skip silently, continue.

④ Extract Last Activity Timestamp per Task

   The board list does NOT carry the activity stream, so read each task's events from the
   dedicated activity reader (newest event's `created_at`), falling back to `created_at`:

     # Newest event's created_at (events come back chronological ASC → take the last one).
     api GET /task/$ID/activity?project=$P

     python3 -c "
     import json, sys
     resp = json.loads(sys.stdin.read())
     events = resp.get('activity') or []
     stamps = [e.get('created_at', '') for e in events if isinstance(e, dict)]
     stamps = [t for t in stamps if t]
     if stamps:
         print(max(stamps))
     else:
         # No events → caller falls back to created_at from the board row.
         print('')
     "

     If the activity read fails or returns no events, fall back to the task's `created_at`.

     Store: task ID, project, status, title, last_activity_ts

⑤ Compute Stagnation

   NOW = current UTC timestamp
   THRESHOLD = NOW - N days

   For each task:
     Parse last_activity_ts as datetime
     days_stagnant = (NOW - last_activity_ts).days
     If days_stagnant >= N → mark as stagnant

   If no stagnant tasks across all projects:
     Print "No stagnant tasks found."
     Exit.

⑥ Output Markdown Table

   Sort stagnant tasks by days_stagnant descending.

   Print:

   | ID | Project | Status | Days | Title |
   |----|---------|--------|------|-------|
   | 2100 | cpet.db | impl | 12 | Add export feature |
   | 2055 | today.bike | plan | 5 | Refactor route module |

   Print summary line:
   "**Heartbeat: X stagnant tasks found across Y projects.**"
   If --dry-run: append " (dry-run, no activity events written)"

⑦ Write Heartbeat activity events (skip if --dry-run)

   For each stagnant task, append ONE activity event — a single atomic POST, no read-modify-write:

     python3 -c "
     import subprocess, json, sys

     task_id = sys.argv[1]
     project = sys.argv[2]
     days = int(sys.argv[3])
     status = sys.argv[4]
     last_ts = sys.argv[5]

     # api.py owns auth + BASE_URL + the org prefix + Content-Type (SQUAD_ORG from the env).
     body = json.dumps({
         'actor': 'Heartbeat',
         'model': 'system',
         'message': f'⚠️ Stagnant {days} days in {status}. Last activity: {last_ts}',
     })
     subprocess.run(
         ['python3', '../squad/scripts/api.py', 'POST',
          f'/task/{task_id}/activity?project={project}',
          '--json', body],
         capture_output=True
     )
     print(f'  Heartbeat written to task #{task_id}')
     " "$TASK_ID" "$PROJECT" "$DAYS" "$STATUS" "$LAST_TS"

   Print: "Heartbeat activity events written for X tasks."
```

### Full Implementation (Copy-Paste Script)

The executing agent should run this as a single Python script for reliability.

> **SQUAD_ORG export contract:** this script reads `SQUAD_ORG` from the **env only** (no `.squadrc` — it's a maintainer tool). To target a specific org (the `/api/orgs/<org>/` path), `export SQUAD_ORG=<slug>` before running. The token is the single `SQUAD_AUTH_TOKEN` (env > bare `SQUAD_AUTH_TOKEN=` in `~/.squad/auth`).

```bash
python3 - "$@" <<'PYEOF'
import subprocess, json, sys, datetime, re

# ── Parse arguments ──────────────────────────────────────────────
args = sys.argv[1:]
project_filter = None
days_threshold = 3
dry_run = False

i = 0
while i < len(args):
    if args[i] == "--project" and i + 1 < len(args):
        project_filter = args[i + 1]; i += 2
    elif args[i] == "--days" and i + 1 < len(args):
        days_threshold = int(args[i + 1]); i += 2
    elif args[i] == "--dry-run":
        dry_run = True; i += 1
    else:
        i += 1

# ── Board access via api.py (it owns auth, BASE_URL, the /api/orgs/<org>/ prefix, Content-Type) ──
# SQUAD_ORG must be in the ENV (this tool has no per-repo .squadrc); the caller resolves .squadrc
# and exports SQUAD_ORG before launching this script — api.py reads it (and the PAT) from the env.
import os

# Every board call is org-scoped (/api/orgs/<org>/...). SQUAD_ORG is REQUIRED.
org = os.environ.get("SQUAD_ORG", "")
if not org:
    raise SystemExit(
        "SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...). "
        "Export SQUAD_ORG=<slug> (from the mint dialog) before running the heartbeat."
    )

API = ["python3", "../squad/scripts/api.py"]

def api_get(path):
    r = subprocess.run(API + ["GET", path], capture_output=True, text=True)
    return json.loads(r.stdout)

def api_post(path, payload):
    subprocess.run(API + ["POST", path, "--json", json.dumps(payload)], capture_output=True)

# ── Fetch projects ───────────────────────────────────────────────
if project_filter:
    try:
        proj_data = api_get(f"/projects/{project_filter}")
        if "error" in proj_data:
            print(f"Error: Project '{project_filter}' not found.")
            sys.exit(1)
        projects = [project_filter]
    except Exception:
        print(f"Error: Project '{project_filter}' not found.")
        sys.exit(1)
else:
    all_proj = api_get("/projects")
    projects = [p["id"] for p in all_proj.get("projects", []) if p.get("status") == "active"]

if not projects:
    print("No active projects found.")
    sys.exit(0)

# ── Scan boards ──────────────────────────────────────────────────
now = datetime.datetime.now(datetime.timezone.utc)
active_columns = ["todo", "plan", "plan_review", "impl", "impl_review", "test"]
stagnant_tasks = []

for proj in projects:
    try:
        board = api_get(f"/board?project={proj}")
    except Exception:
        print(f"Warning: failed to fetch board for project '{proj}', skipping.", file=sys.stderr)
        continue

    for col in active_columns:
        tasks = board.get(col, [])
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            task_id = task.get("id")
            title = task.get("title", "(untitled)")
            status = task.get("status", col)
            created_at = task.get("created_at", "")

            # Extract last activity timestamp from the dedicated activity reader
            # (the board list does not carry the activity stream). Newest event's created_at.
            last_ts = None
            read_error = False
            try:
                resp = api_get(f"/task/{task_id}/activity?project={proj}")
                events = resp.get("activity") if isinstance(resp, dict) else None
                if isinstance(events, list) and events:
                    stamps = [e.get("created_at", "") for e in events if isinstance(e, dict)]
                    stamps = [t for t in stamps if t]
                    if stamps:
                        last_ts = max(stamps)
            except (json.JSONDecodeError, TypeError, OSError):
                read_error = True

            if last_ts is None:
                last_ts = created_at
                if read_error:
                    print(f"Warning: task #{task_id} activity read failed, falling back to created_at", file=sys.stderr)

            if not last_ts:
                print(f"Warning: task #{task_id} has no timestamp at all, skipping", file=sys.stderr)
                continue

            # Parse timestamp and compute days
            try:
                # Normalize: drop fractional seconds + map 'Z' → '+00:00' (fromisoformat is strict pre-3.11),
                # then coerce to UTC-aware so it compares with `now` (also UTC-aware).
                clean_ts = re.sub(r"(T\d\d:\d\d:\d\d)\.\d+", r"\1", last_ts.strip()).replace("Z", "+00:00")
                ts_dt = datetime.datetime.fromisoformat(clean_ts)
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=datetime.timezone.utc)
            except (ValueError, AttributeError):
                print(f"Warning: task #{task_id} has unparseable timestamp '{last_ts}', skipping", file=sys.stderr)
                continue

            days_stagnant = (now - ts_dt).days
            if days_stagnant >= days_threshold:
                stagnant_tasks.append({
                    "id": task_id,
                    "project": proj,
                    "status": status,
                    "days": days_stagnant,
                    "title": title,
                    "last_ts": last_ts,
                })

# ── Output ───────────────────────────────────────────────────────
if not stagnant_tasks:
    print("No stagnant tasks found.")
    sys.exit(0)

# Sort by days descending
stagnant_tasks.sort(key=lambda t: t["days"], reverse=True)

# Markdown table
print("")
print("| ID | Project | Status | Days | Title |")
print("|----|---------|--------|------|-------|")
for t in stagnant_tasks:
    print(f"| {t['id']} | {t['project']} | {t['status']} | {t['days']} | {t['title']} |")
print("")

project_set = set(t["project"] for t in stagnant_tasks)
summary = f"**Heartbeat: {len(stagnant_tasks)} stagnant tasks found across {len(project_set)} projects.**"
if dry_run:
    summary += " (dry-run, no activity events written)"
print(summary)

# ── Write Heartbeat activity events ───────────────────────────────
if dry_run:
    sys.exit(0)

print("")
written = 0
for t in stagnant_tasks:
    try:
        # One atomic POST per task \u2014 no read-modify-write.
        api_post(
            f"/task/{t['id']}/activity?project={t['project']}",
            {
                "actor": "Heartbeat",
                "model": "system",
                "message": f"\u26a0\ufe0f Stagnant {t['days']} days in {t['status']}. Last activity: {t['last_ts']}",
            },
        )
        print(f"  Heartbeat written to task #{t['id']}")
        written += 1
    except Exception as e:
        print(f"  Error writing to task #{t['id']}: {e}", file=sys.stderr)

print(f"\nHeartbeat activity events written for {written} tasks.")
PYEOF
```
