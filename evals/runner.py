"""Headless-agent runner + board helpers for the behavioral eval suite.

Invokes Claude Code in headless mode (`claude -p --output-format stream-json`) so a
scenario runs the *real* skills against a live board, then reads board state as the
deterministic ground truth. Token/URL resolve exactly like the skills do.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = (os.environ.get("SQUAD_BASE_URL")
            or "https://squad-api-285415501393.asia-south1.run.app").rstrip("/")


def org() -> str:
    """The org slug — every board call is org-scoped (/api/orgs/<org>/...). Resolved
    from SQUAD_ORG (env); fails fast when unset, exactly like the skills do."""
    o = os.environ.get("SQUAD_ORG", "").strip()
    if not o:
        raise SystemExit(
            "SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...). "
            "Export SQUAD_ORG=<slug> (from the mint dialog) before running the evals."
        )
    return urllib.parse.quote(o)


def _orgp(resource: str) -> str:
    """Build an org-scoped API path: _orgp('board?project=x') → /api/orgs/<org>/board?project=x."""
    return f"/api/orgs/{org()}/{resource}"


def token() -> str:
    t = os.environ.get("SQUAD_AUTH_TOKEN", "")
    if not t:
        f = pathlib.Path.home() / ".squad" / "auth"
        if f.is_file():
            for line in f.read_text().splitlines():
                if line.startswith("SQUAD_AUTH_TOKEN="):
                    t = line.split("=", 1)[1].strip()
    return t


def have_agent() -> bool:
    """Behavioral evals need the `claude` CLI. Auth comes from the user's Claude Code
    login (subscription) OR ANTHROPIC_API_KEY — either works for `claude -p`, so no
    separate API key is required."""
    return bool(shutil.which("claude"))


def claude_text(prompt: str, timeout: int = 180) -> str:
    """A plain headless turn (no tools) — used as a keyless LLM judge via the CLI login."""
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        capture_output=True, text=True, timeout=timeout,
    )
    return (proc.stdout or "").strip()


def have_board() -> bool:
    return bool(token())


# ── Agent invocation ─────────────────────────────────────────────────────────
def run_agent(prompt: str, cwd: str | None = None, timeout: int = 600) -> dict:
    """Run one headless turn; return {output, tools, returncode}.

    On timeout the run is recorded as a FAILED trial (returncode -1) rather than
    crashing the suite — headless `claude -p` can hang on parallel sub-agent
    fan-out under a non-TTY parent (claude-code#56540), so heavy multi-agent
    scenarios must fail-soft and let the gate flag them.
    """
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
             "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        stdout, returncode = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout if isinstance(e.stdout, str) else (
            e.stdout.decode(errors="replace") if e.stdout else "")
        returncode = -1
    output, tools = "", []
    for line in (stdout or "").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    output += block["text"]
                elif block.get("type") == "tool_use":
                    tools.append(block.get("name", "?"))
        elif ev.get("type") == "result" and ev.get("result"):
            output = ev["result"]  # final assembled result wins
    return {"output": output.strip(), "tools": tools, "returncode": returncode}


# ── Board API (Authorization: Bearer) ────────────────────────────────────────
def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token()}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode(errors="replace")}


def board_tasks(project: str) -> list[dict]:
    board = _api("GET", _orgp(f"board?project={urllib.parse.quote(project)}&summary=true"))
    cols = ["todo", "plan", "plan_review", "impl", "impl_review", "test", "done"]
    return [t for c in cols for t in (board.get(c) or [])]


def get_task(project: str, task_id: int) -> dict:
    return _api("GET", _orgp(f"task/{task_id}?project={urllib.parse.quote(project)}"))


def create_task(project: str, title: str, priority: str = "medium",
                level: int = 1, description: str = "") -> dict:
    res = _api("POST", _orgp("task"),
               {"title": title, "project": project, "priority": priority,
                "level": level, "description": description})
    return res.get("task", res)


def delete_task(project: str, task_id: int) -> None:
    _api("DELETE", _orgp(f"task/{task_id}?project={urllib.parse.quote(project)}"))


def delete_tasks_by_title(project: str, marker: str) -> int:
    n = 0
    for t in board_tasks(project):
        if marker in (t.get("title") or ""):
            delete_task(project, t["id"])
            n += 1
    return n


# ── Projects (squad-init creates one; need read/delete for cleanup) ────────────
def list_projects() -> list[dict]:
    res = _api("GET", _orgp("projects"))
    if isinstance(res, list):
        return res
    return res.get("projects", []) if isinstance(res, dict) else []


def get_project(project: str) -> dict:
    return _api("GET", _orgp(f"projects/{urllib.parse.quote(project)}"))


def delete_project(project: str) -> None:
    _api("DELETE", _orgp(f"projects/{urllib.parse.quote(project)}"))
