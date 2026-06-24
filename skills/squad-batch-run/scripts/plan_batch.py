#!/usr/bin/env python3
"""squad-batch-run planning helper.

SQUAD_ORG EXPORT CONTRACT: ``main`` reads ``SQUAD_ORG`` from the ENVIRONMENT
only — it does NOT parse ``.squadrc``. The calling skill (squad-batch-run) MUST
resolve ``.squadrc``'s ``SQUAD_ORG=`` line and ``export SQUAD_ORG`` before
launching this script, because every board call targets the ``/api/orgs/<org>/``
path. ``SQUAD_ORG`` selects the tenant (the path), not the token.

ORG-IN-PATH: every board call targets the org-scoped surface
``{base_url}/api/orgs/{org}/...`` (org in the path, ``project`` in the query).
``SQUAD_ORG`` is therefore REQUIRED — ``main`` fails fast with an actionable
``SystemExit`` if it is unset. ``fetch_task`` is a GET, which ``urllib`` follows
across a former-slug 308 redirect (the analogue of ``curl -L``); if a redirect is
not followed, update ``.squadrc`` to the canonical slug.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency
    certifi = None


PHASE_RE = re.compile(r"(?:^|,)\s*phase:(\d+)\s*(?:,|$)")
PARALLEL_RE = re.compile(r"(?im)^parallel-safe:\s*(.+)$")
TOUCHES_RE = re.compile(r"(?im)^touches:\s*(.+)$")

GENERIC_TAG_PREFIXES = ("phase:", "explore-", "sprint")
GENERIC_TAGS = {"ui", "feature", "maintenance", "data", "ux"}
HOTSPOT_HINTS = {
    "app/",
    "route",
    "routes",
    "navigation",
    "header",
    "layout",
    "shell",
    "loader",
    "types",
    "schema",
    "migration",
    "api",
}


def load_squad_auth() -> dict[str, str]:
    """Resolve auth tool-agnostically: env vars take priority, then the bare
    ``SQUAD_AUTH_TOKEN=`` line — both from ~/.squad/auth; ~/.squad/config
    supplies the optional URL.

    Precedence for the token: ``SQUAD_AUTH_TOKEN`` env > bare ``SQUAD_AUTH_TOKEN=``
    (file), matching the bash chain in ``skills/squad/shared.md``.
    """
    result: dict[str, str] = {}
    for f in (pathlib.Path.home() / ".squad" / "auth",
              pathlib.Path.home() / ".squad" / "config"):
        if not f.is_file():
            continue
        try:
            for line in f.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result.setdefault(key.strip(), value.strip())
        except OSError:
            pass
    # Env override: SQUAD_AUTH_TOKEN / SQUAD_BASE_URL from the environment win
    # over the bare values read from the file.
    for key in ("SQUAD_AUTH_TOKEN", "SQUAD_BASE_URL"):
        if os.environ.get(key):
            result[key] = os.environ[key]
    return result


def build_ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def expand_selector(raw: str) -> list[int]:
    parts = [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]
    ids: list[int] = []
    seen: set[int] = set()

    for part in parts:
        if "-" in part or "~" in part:
            separator = "-" if "-" in part else "~"
            start_raw, end_raw = part.split(separator, 1)
            start = int(start_raw)
            end = int(end_raw)
            step = 1 if end >= start else -1
            for value in range(start, end + step, step):
                if value not in seen:
                    seen.add(value)
                    ids.append(value)
            continue

        value = int(part)
        if value not in seen:
            seen.add(value)
            ids.append(value)

    return ids


def fetch_task(
    base_url: str,
    org: str,
    project: str,
    task_id: int,
    auth_token: str = "",
    ssl_context: ssl.SSLContext | None = None,
) -> dict:
    # Org-scoped board surface: org in the path, project stays in the query.
    url = (
        f"{base_url}/api/orgs/{urllib.parse.quote(org)}/task/{task_id}"
        f"?project={urllib.parse.quote(project)}"
    )
    auth_state = "present" if auth_token else "missing"
    request = urllib.request.Request(url)
    if auth_token:
        request.add_header("Authorization", f"Bearer {auth_token}")
    try:
        with urllib.request.urlopen(request, timeout=10, context=ssl_context) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"failed to fetch task {task_id} from {url}: HTTP {exc.code} "
            f"(auth_token={auth_state})"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"failed to connect to {url}: {exc.reason} (auth_token={auth_state})\n"
            "Is the Squad board reachable at the configured base_url? Check the URL and auth token."
        ) from exc


def parse_phase(tags: str | None) -> int | None:
    if not tags:
        return None
    match = PHASE_RE.search(tags)
    if not match:
        return None
    return int(match.group(1))


def extract_blocked_by(task: dict) -> list[int]:
    """Structured dependency ids from the embedded relationships object
    (`.relationships.blocked_by`). The `Depends on:` text convention is retired —
    dependencies are typed `blocks` edges, read from the relationships API."""
    rel = task.get("relationships") or {}
    return [int(dep["id"]) for dep in (rel.get("blocked_by") or []) if dep.get("id") is not None]


def parse_parallel_safe(description: str | None) -> bool | None:
    if not description:
        return None

    match = PARALLEL_RE.search(description)
    if not match:
        return None

    normalized = match.group(1).strip().lower()
    if normalized in {"yes", "true", "y", "safe"}:
        return True
    if normalized in {"no", "false", "n", "unsafe"}:
        return False
    return None


def parse_touches(description: str | None) -> list[str]:
    if not description:
        return []

    match = TOUCHES_RE.search(description)
    if not match:
        return []

    return [
        token.strip().lower()
        for token in match.group(1).split(",")
        if token.strip()
    ]


def extract_tag_modules(tags: str | None) -> list[str]:
    if not tags:
        return []

    modules: list[str] = []
    for token in tags.split(","):
        normalized = token.strip().lower()
        if not normalized:
            continue
        if normalized in GENERIC_TAGS:
            continue
        if normalized.startswith(GENERIC_TAG_PREFIXES):
            continue
        modules.append(normalized)
    return modules


def infer_task(task: dict) -> dict:
    description = task.get("description") or ""
    phase = parse_phase(task.get("tags"))
    touches = parse_touches(description)
    tag_modules = extract_tag_modules(task.get("tags"))
    modules = sorted(set(touches + tag_modules))

    return {
        "id": int(task["id"]),
        "title": task.get("title"),
        "status": task.get("status"),
        "priority": task.get("priority"),
        "level": task.get("level"),
        "card_type": task.get("card_type") or "task",
        "phase": phase,
        "tags": task.get("tags"),
        "depends_on": extract_blocked_by(task),
        "parallel_safe": parse_parallel_safe(description),
        "module_hints": modules,
    }


def task_sort_key(task: dict, input_order: dict[int, int]):
    phase = task.get("phase")
    return (
        phase if phase is not None else 10_000,
        input_order[int(task["id"])],
    )


def has_hotspot_overlap(group_tasks: list[dict], candidate: dict) -> bool:
    candidate_hints = set(candidate.get("module_hints") or [])
    for hint in candidate_hints:
        if any(hotspot in hint for hotspot in HOTSPOT_HINTS):
            return True

    for task in group_tasks:
        for hint in task.get("module_hints") or []:
            if any(hotspot in hint for hotspot in HOTSPOT_HINTS):
                return True

    return False


def can_parallelize_with_group(group_tasks: list[dict], candidate: dict) -> tuple[bool, str]:
    if candidate.get("status") != "todo":
        return False, f"task #{candidate['id']} is not in todo"

    if candidate.get("parallel_safe") is False:
        return False, f"task #{candidate['id']} explicitly says Parallel-safe: no"

    group_ids = {task["id"] for task in group_tasks}
    if any(dep in group_ids for dep in candidate.get("depends_on") or []):
        return False, f"task #{candidate['id']} depends on another task in the group"

    for task in group_tasks:
        if task.get("status") != "todo":
            return False, f"task #{task['id']} is not in todo"
        if task.get("parallel_safe") is False:
            return False, f"task #{task['id']} explicitly says Parallel-safe: no"
        if candidate["id"] in (task.get("depends_on") or []):
            return False, f"task #{task['id']} depends on task #{candidate['id']}"

    if has_hotspot_overlap(group_tasks, candidate):
        return False, "shared hotspot modules make the boundary unsafe"

    candidate_modules = set(candidate.get("module_hints") or [])
    group_modules = {
        hint
        for task in group_tasks
        for hint in (task.get("module_hints") or [])
    }

    if candidate.get("parallel_safe") is True and all(
        task.get("parallel_safe") is True for task in group_tasks
    ):
        return True, "explicit Parallel-safe: yes on all tasks and no dependency edges"

    if candidate_modules and group_modules and candidate_modules.isdisjoint(group_modules):
        return True, "same phase, no dependency edges, distinct module hints"

    return False, "module boundaries are shared or unclear"


def build_groups(tasks: list[dict]) -> list[dict]:
    groups: list[dict] = []

    for task in tasks:
        if not groups:
            groups.append(
                {
                    "mode": "sequential",
                    "phase": task.get("phase"),
                    "task_ids": [task["id"]],
                    "reason": "first task in ordered batch",
                }
            )
            continue

        last_group = groups[-1]
        last_phase = last_group.get("phase")
        current_phase = task.get("phase")

        if current_phase != last_phase:
            reason = (
                f"phase {current_phase} follows phase {last_phase}"
                if current_phase is not None and last_phase is not None
                else "phase boundary changed or missing"
            )
            groups.append(
                {
                    "mode": "sequential",
                    "phase": current_phase,
                    "task_ids": [task["id"]],
                    "reason": reason,
                }
            )
            continue

        group_tasks = [existing for existing in tasks if existing["id"] in last_group["task_ids"]]
        can_parallelize, reason = can_parallelize_with_group(group_tasks, task)
        if can_parallelize:
            last_group["mode"] = "parallel_candidate"
            last_group["task_ids"].append(task["id"])
            last_group["reason"] = reason
            continue

        groups.append(
            {
                "mode": "sequential",
                "phase": current_phase,
                "task_ids": [task["id"]],
                "reason": reason,
            }
        )

    return groups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--tasks", required=True, help="e.g. 500-504 or 500,501,504")
    parser.add_argument("--base-url")
    parser.add_argument("--auth-token")
    args = parser.parse_args()

    squad_auth = load_squad_auth()
    ssl_context = build_ssl_context()
    base_url = (
        args.base_url
        or os.environ.get("SQUAD_BASE_URL")
        or squad_auth.get("SQUAD_BASE_URL")
        or "https://squad-api-285415501393.asia-south1.run.app"
    )
    auth_token = (
        args.auth_token
        if args.auth_token is not None
        else os.environ.get("SQUAD_AUTH_TOKEN")
        or squad_auth.get("SQUAD_AUTH_TOKEN")
        or ""
    )

    # Every board call is org-scoped (/api/orgs/<org>/...). SQUAD_ORG is required;
    # the calling skill resolves .squadrc and exports it before launching this script.
    org = os.environ.get("SQUAD_ORG") or ""
    if not org:
        raise SystemExit(
            "SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...).\n"
            "Set it from the mint dialog's `SQUAD_ORG=<slug>` line — add `SQUAD_ORG=<slug>` to "
            ".squadrc or export SQUAD_ORG=<slug>. Resolution order: env > .squadrc."
        )

    task_ids = expand_selector(args.tasks)
    if not task_ids:
        raise SystemExit("no task ids resolved")

    input_order = {task_id: index for index, task_id in enumerate(task_ids)}
    raw_tasks = [
        fetch_task(base_url, org, args.project, task_id, auth_token, ssl_context)
        for task_id in task_ids
    ]
    inferred = [infer_task(task) for task in raw_tasks]
    # Epics are containers, not runnable — exclude them from the batch selection.
    skipped_epics = [t["id"] for t in inferred if t.get("card_type") == "epic"]
    tasks = [t for t in inferred if t.get("card_type") != "epic"]
    ordered = sorted(tasks, key=lambda task: task_sort_key(task, input_order))

    payload = {
        "project": args.project,
        "base_url": base_url,
        "task_ids": task_ids,
        "skipped_epics": skipped_epics,
        "ordered_tasks": ordered,
        "candidate_groups": build_groups(ordered),
    }

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
