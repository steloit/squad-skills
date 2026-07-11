#!/usr/bin/env python3
"""create_tasks.py — batch-create board tasks (+ optional epic) with edges.

Run as a black box. Reads one JSON object on stdin, creates everything in
order, wires parent/blocks edges, prints the created id table as JSON.

Input shape:
  {
    "epic": {"title": "...", "description": "...", "priority": "medium",
             "tags": ["..."], "level": 3},                # optional container
    "tasks": [
      {"title": "...", "description": "...", "level": 2, "priority": "medium",
       "tags": ["phase:1"],
       "blocked_by": [0, "KEY-42"],   # ints = index of an earlier task in THIS
                                      # batch; strings = existing board ids
       "parent": "KEY-10"}            # optional explicit epic id; defaults to
                                      # the batch epic when one is given
    ]
  }

Output: {"epic": {"id", "title"} | null,
         "tasks": [{"index", "id", "title", "level"}],
         "edges": [{"from", "to", "type", "ok"}]}

Exit codes follow api.py's taxonomy (0/2/3/4/5/6). A failed edge write is
reported in "edges" with ok:false (creation already succeeded); a failed task
create aborts with the ids created so far printed to stderr.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pipeline  # noqa: E402  (reuses the shared board-request core)


def _create(payload):
    rc, resp = pipeline._req("POST", "/task", payload)
    if rc != 0:
        return rc, None
    return 0, (resp or {}).get("id")


def main():
    try:
        spec = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"ERROR: stdin is not valid JSON: {exc}", file=sys.stderr)
        return 2

    created = []
    edges = []

    epic_id = None
    epic = spec.get("epic")
    if epic:
        payload = {"title": epic["title"], "card_type": "epic",
                   "priority": epic.get("priority", "medium"),
                   "level": epic.get("level", 3)}
        for key in ("description", "tags"):
            if epic.get(key) is not None:
                payload[key] = epic[key]
        rc, epic_id = _create(payload)
        if rc != 0:
            print("ERROR: epic create failed — nothing else attempted.", file=sys.stderr)
            return rc

    tasks = spec.get("tasks") or []
    ids = []
    for i, t in enumerate(tasks):
        payload = {"title": t["title"], "priority": t.get("priority", "medium"),
                   "level": t.get("level", 2)}
        for key in ("description", "tags", "card_type"):
            if t.get(key) is not None:
                payload[key] = t[key]
        rc, tid = _create(payload)
        if rc != 0 or tid is None:
            print(f"ERROR: create failed for task index {i} ({t['title']!r}). "
                  f"Created so far: {json.dumps(ids)}", file=sys.stderr)
            return rc or 5
        ids.append(tid)
        created.append({"index": i, "id": tid, "title": t["title"],
                        "level": payload["level"]})

    # Edges after all creates so intra-batch blocked_by indices resolve.
    for i, t in enumerate(tasks):
        parent = t.get("parent") or epic_id
        if parent:
            rc, _ = pipeline._req("POST", f"/task/{ids[i]}/relationships",
                                  {"to": str(parent), "type": "parent"})
            edges.append({"from": str(ids[i]), "to": str(parent),
                          "type": "parent", "ok": rc == 0})
        for dep in t.get("blocked_by") or []:
            dep_id = ids[dep] if isinstance(dep, int) else dep
            # dep blocks this task: POST on the BLOCKER with to=<this task>.
            rc, _ = pipeline._req("POST", f"/task/{dep_id}/relationships",
                                  {"to": str(ids[i]), "type": "blocks"})
            edges.append({"from": str(dep_id), "to": str(ids[i]),
                          "type": "blocks", "ok": rc == 0})

    print(json.dumps({"epic": ({"id": epic_id, "title": epic["title"]} if epic_id else None),
                      "tasks": created, "edges": edges}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
