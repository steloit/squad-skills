#!/usr/bin/env python3
"""stats.py — render /squad stats: board column counts + per-actor token usage.

Two board reads (summary + activity/stats), rendered as markdown tables.
Run as a black box; exit codes follow api.py's taxonomy.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
COLUMNS = ["todo", "plan", "plan_review", "impl", "impl_review", "test", "done", "cancelled"]


def _api(path):
    run = subprocess.run([sys.executable, str(HERE / "api.py"), "GET", path],
                         capture_output=True, text=True)
    if run.returncode != 0:
        sys.stderr.write(run.stderr)
        sys.exit(run.returncode)
    return json.loads(run.stdout)


def main():
    board = _api("/board?summary=true")
    stats = _api("/activity/stats")

    counts = {c: len(board.get(c, [])) for c in COLUMNS}
    print("## Column Counts\n")
    print("| Status | Count |")
    print("|--------|-------|")
    for c in COLUMNS:
        print(f"| {c} | {counts[c]} |")
    print(f"| **total** | **{sum(counts.values())}** |")

    rows = stats.get("stats", [])
    totals = stats.get("totals", {})
    print("\n## Agent Token Usage\n")
    if not rows:
        print("No token data")
        return
    print("| Actor | Events | Tokens | Coverage |")
    print("|-------|--------|--------|----------|")
    for r in sorted(rows, key=lambda r: r.get("actor", "")):
        events = r.get("events", 0)
        tok = r.get("tokens")
        reported = r.get("reported")
        tok_cell = "—" if tok is None else f"{tok:,}"
        if reported is None:
            cov = "—"
        elif reported < events:
            cov = f"{reported}/{events} (partial)"
        else:
            cov = f"{reported}/{events}"
        print(f"| {r.get('actor', 'unknown')} | {events} | {tok_cell} | {cov} |")
    tot = totals.get("tokens")
    print(f"| **Total** | **{totals.get('events', 0)}** | **{'—' if tot is None else f'{tot:,}'}** | |")


if __name__ == "__main__":
    main()
