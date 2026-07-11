#!/usr/bin/env python3
"""heartbeat.py — scan Squad boards for stagnant tasks and mark them.

Run as a black box. Scans all active projects (or one via --project) for tasks
in the active columns (todo, plan, plan_review, impl, impl_review, test) whose
newest activity event is older than N days (default 3; falls back to the
task's created_at when it has no events). Prints a markdown table of stagnant
tasks sorted by days stagnant, a summary line, then appends ONE Heartbeat
activity event per stagnant task (skipped with --dry-run).

Usage:
  heartbeat.py [--project X] [--days N] [--dry-run]

All board I/O goes through the shared board-request core (auth, org, base URL
resolved per the standard chain; SQUAD_ORG required — env > .squadrc).

Exit codes: 0 success (including "No stagnant tasks found.") · 2 usage /
SQUAD_ORG unresolvable · 3 auth · 4 project not found / client error ·
5 server error · 6 network failure.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

SQUAD_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "squad" / "scripts"
sys.path.insert(0, str(SQUAD_SCRIPTS))
import pipeline  # noqa: E402  (reuses the shared board-request core)

ACTIVE_COLUMNS = ["todo", "plan", "plan_review", "impl", "impl_review", "test"]


def main():
    parser = argparse.ArgumentParser(
        description="Detect stagnant Squad tasks (no activity for N days) across active "
                    "projects; report a markdown table and append one Heartbeat activity "
                    "event per stagnant task unless --dry-run.")
    parser.add_argument("--project", help="scan only this project (default: all active projects)")
    parser.add_argument("--days", type=int, default=3,
                        help="stagnation threshold in days (default: 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report only; write no activity events")
    args = parser.parse_args()
    days_threshold = args.days

    # ── Fetch projects ───────────────────────────────────────────────
    if args.project:
        rc, proj_data = pipeline._req("GET", f"/projects/{args.project}")
        if rc in (2, 3, 6):
            return rc  # config/auth/network diagnostics already on stderr
        if rc != 0 or not isinstance(proj_data, dict) or "error" in proj_data:
            print(f"Error: Project '{args.project}' not found.", file=sys.stderr)
            return 4
        projects = [args.project]
    else:
        rc, all_proj = pipeline._req("GET", "/projects")
        if rc != 0:
            return rc
        projects = [p["id"] for p in (all_proj or {}).get("projects", [])
                    if p.get("status") == "active"]

    if not projects:
        print("No active projects found.")
        return 0

    # ── Scan boards ──────────────────────────────────────────────────
    now = datetime.datetime.now(datetime.timezone.utc)
    stagnant_tasks = []

    for proj in projects:
        rc, board = pipeline._req("GET", f"/board?project={proj}")
        if rc != 0 or not isinstance(board, dict):
            print(f"Warning: failed to fetch board for project '{proj}', skipping.", file=sys.stderr)
            continue

        for col in ACTIVE_COLUMNS:
            tasks = board.get(col, [])
            if not isinstance(tasks, list):
                continue
            for task in tasks:
                task_id = task.get("id")
                title = task.get("title", "(untitled)")
                status = task.get("status", col)
                created_at = task.get("created_at", "")

                # Last activity = newest event from the dedicated activity reader
                # (the board list does not carry the activity stream).
                last_ts = None
                rc, resp = pipeline._req("GET", f"/task/{task_id}/activity?project={proj}")
                read_error = rc != 0
                events = resp.get("activity") if isinstance(resp, dict) else None
                if isinstance(events, list) and events:
                    stamps = [e.get("created_at", "") for e in events if isinstance(e, dict)]
                    stamps = [t for t in stamps if t]
                    if stamps:
                        last_ts = max(stamps)

                if last_ts is None:
                    last_ts = created_at
                    if read_error:
                        print(f"Warning: task #{task_id} activity read failed, "
                              "falling back to created_at", file=sys.stderr)

                if not last_ts:
                    print(f"Warning: task #{task_id} has no timestamp at all, skipping",
                          file=sys.stderr)
                    continue

                # Parse timestamp and compute days
                try:
                    # Normalize: drop fractional seconds + map 'Z' → '+00:00'
                    # (fromisoformat is strict pre-3.11), then coerce to UTC-aware.
                    clean_ts = re.sub(r"(T\d\d:\d\d:\d\d)\.\d+", r"\1",
                                      last_ts.strip()).replace("Z", "+00:00")
                    ts_dt = datetime.datetime.fromisoformat(clean_ts)
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=datetime.timezone.utc)
                except (ValueError, AttributeError):
                    print(f"Warning: task #{task_id} has unparseable timestamp "
                          f"'{last_ts}', skipping", file=sys.stderr)
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
        return 0

    stagnant_tasks.sort(key=lambda t: t["days"], reverse=True)

    print("")
    print("| ID | Project | Status | Days | Title |")
    print("|----|---------|--------|------|-------|")
    for t in stagnant_tasks:
        print(f"| {t['id']} | {t['project']} | {t['status']} | {t['days']} | {t['title']} |")
    print("")

    project_set = set(t["project"] for t in stagnant_tasks)
    summary = (f"**Heartbeat: {len(stagnant_tasks)} stagnant tasks found "
               f"across {len(project_set)} projects.**")
    if args.dry_run:
        summary += " (dry-run, no activity events written)"
    print(summary)

    # ── Write Heartbeat activity events ──────────────────────────────
    if args.dry_run:
        return 0

    print("")
    written = 0
    for t in stagnant_tasks:
        # One atomic POST per task — no read-modify-write.
        rc, _ = pipeline._req(
            "POST", f"/task/{t['id']}/activity?project={t['project']}",
            {
                "actor": "Heartbeat",
                "model": "system",
                "message": f"⚠️ Stagnant {t['days']} days in {t['status']}. "
                           f"Last activity: {t['last_ts']}",
            },
        )
        if rc == 0:
            print(f"  Heartbeat written to task #{t['id']}")
            written += 1
        else:
            print(f"  Error writing to task #{t['id']} (see diagnostics above)", file=sys.stderr)

    print(f"\nHeartbeat activity events written for {written} tasks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
