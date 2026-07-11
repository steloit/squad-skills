#!/usr/bin/env python3
"""pipeline.py — the deterministic engine for the squad-run pipeline.

Run as a black box (`pipeline.py --help`); do not read this source into context.
Each subcommand collapses a multi-call orchestration step into one invocation.
All board I/O reuses api.py's resolution (auth, org, project, base URL) — the
token never appears in argv or output.

Subcommands
  preflight <ID>              Runnability bundle: refusals (epic/terminal),
                              dependency blockers, open sub-tasks, level/status.
  dispatch  <ID> [--agent X]  Entry PATCH + fresh correlation_id + fully rendered
                              agent prompt. Prints one META JSON line, then
                              '-----PROMPT-----', then the prompt text.
  record    <ID> --agent X --message M [--tokens N] --cid C
                              Agent-attributed step activity event; prints the
                              step verdict + proposed next status + breaker flag.
  advance   <ID> [--human-reject --reason R --cid C]
                              Read derived verdict -> compute move -> PATCH.
                              Handles override-review on human reject, consent-
                              gated user_steering emit, L3 approval snapshot.
                              When next status is done, prints action=finalize
                              and does NOT move (finalize owns the done path).
  normalize <ID>              Format-normalize changed files (repo format script
                              -> biome/ruff/black/gofmt/rustfmt/prettier), log a
                              note, re-stage. Best-effort; never blocks.
  finalize  <ID> [--approval-tree SHA]
                              Stale-approval recheck (L3), done PATCH, git commit
                              of pending changes, commit activity event.
  move      <ID> <status>     Validated status move with one self-correction
                              from the server's allowed[] on rejection.
  event     <ID> --actor A --message M [--model MODEL] [--cid C] [--tokens N]
                              Append one activity event (orchestrator notes).

Exit codes: 0 ok · 2 usage · 3 auth · 4 client/4xx · 5 server · 6 network.
JSON to stdout, diagnostics to stderr.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import api  # noqa: E402  (zero-dep sibling helper; owns auth/transport resolution)

TEMPLATES = HERE.parent / "templates"
MODELS_JSON = HERE.parent / "models.json"

AGENTS = {
    # nickname: (model key, template, status it runs at)
    "Planner":   ("planner",   "plan-agent.md",        "plan"),
    "Critic":    ("critic",    "review-agent.md",      "plan_review"),
    "Builder":   ("builder",   "worker-agent.md",      "impl"),
    "Shield":    ("shield",    "tdd-tester.md",        "impl"),
    "Inspector": ("inspector", "code-review-agent.md", "impl_review"),
    "Ranger":    ("ranger",    "test-runner.md",       "test"),
}
STATUS_AGENT = {"plan": "Planner", "plan_review": "Critic", "impl": "Builder",
                "impl_review": "Inspector", "test": "Ranger"}
# Per-agent projected fields (id/project/status always included by the API).
AGENT_FIELDS = {
    "Planner":   "title,description,spec,plan_review_comments",
    "Critic":    "title,description,spec,plan,decision_log,done_when",
    "Builder":   "title,description,spec,plan,done_when,plan_review_comments,review_comments",
    "Shield":    "title,description,spec,implementation_notes",
    "Inspector": "title,description,spec,plan,done_when,implementation_notes",
    "Ranger":    "title,implementation_notes",
}
# Dependency-context injection: agent -> [(field, char limit), ...]
DEP_CONTEXT = {
    "Planner":   [("decision_log", 500), ("implementation_notes", 500)],
    "Builder":   [("implementation_notes", 500)],
    "Inspector": [("decision_log", 300)],
}
VERDICT_FIELD = {"plan_review": "last_plan_review_status",
                 "impl_review": "last_review_status",
                 "test": "last_test_status"}
REVIEW_COUNT_FIELD = {"plan_review": "plan_review_count",
                      "impl_review": "impl_review_count"}
TERMINAL = {"done", "cancelled"}
# user_steering enums per reject gate (see references/observation.md).
STEERING = {
    "plan_review": ("evaluative", "negative", "planning", "moderate",
                    "violated_constraint", "rejected the plan"),
    "impl_review": ("evaluative", "negative", "verification", "moderate",
                    "violated_constraint", "requested implementation changes"),
    "test":        ("evaluative", "negative", "verification", "major",
                    "violated_constraint", "tests failed"),
}


def _req(method, path, body=None):
    """One board request via api.py's resolution. Returns (exit_code, parsed).
    On error, prints api.py-style diagnostics to stderr."""
    org = api.resolve_org()
    if not org:
        print("ERROR: SQUAD_ORG unset (env > .squadrc) — no request sent.", file=sys.stderr)
        return 2, None
    token = api.resolve_token()
    if not token:
        api.auth_guidance()
        return 3, None
    url = api.build_url(api.resolve_base_url(), org, path, api.resolve_project())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return 0, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        code = exc.code
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if code == 401:
            api.auth_guidance()
            return 3, None
        print(f"ERROR: board returned HTTP {code}.", file=sys.stderr)
        if raw:
            print(raw, file=sys.stderr)
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return (5 if code >= 500 else 4), parsed
    except urllib.error.URLError as exc:
        print(f"ERROR: network/transport failure: {exc.reason}", file=sys.stderr)
        return 6, None


def _die(code, parsed=None):
    sys.exit(code)


def _get(path):
    rc, parsed = _req("GET", path)
    if rc != 0:
        _die(rc)
    return parsed


def _out(obj):
    print(json.dumps(obj, indent=2))


def _models():
    cfg = json.loads(MODELS_JSON.read_text())
    provider = _provider(cfg)
    models = cfg["providers"][provider]
    efforts = cfg.get("reasoning_effort", {}).get(provider, {})
    return provider, models, efforts


def _provider(cfg):
    p = os.environ.get("SQUAD_MODEL_PROVIDER", "")
    if p:
        return p
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_CI"):
        return "codex"
    if os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CLAUDECODE"):
        return "claude"
    if pathlib.Path(".claude").is_dir():
        return "claude"
    if pathlib.Path(".codex").is_dir():
        return "codex"
    return cfg.get("default_provider", "claude")


def _truncate(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _spec_md(spec):
    """Render the Refiner spec JSON as the '## Refined Spec' markdown block."""
    if not spec:
        return ""
    out = ["## Refined Spec", ""]
    if spec.get("goal"):
        out += ["**Goal:** " + spec["goal"], ""]
    reqs = spec.get("requirements") or []
    if reqs:
        out += ["**Requirements:**"] + ["- " + r for r in reqs] + [""]
    qa = spec.get("qa") or []
    if qa:
        out.append("**Clarifications (Q&A):**")
        for item in qa:
            out.append("- Q: " + (item.get("question") or ""))
            ans = item.get("answer")
            out.append("  A: " + (ans if ans is not None else "(unanswered)"))
    return "\n".join(out).rstrip()


def _last_comment(arr):
    if isinstance(arr, list) and arr:
        return arr[-1].get("comment", "") or ""
    return ""


def _deps_context(task_id, agent):
    """Fetch blocked_by deps and build this agent's injection block."""
    fields = DEP_CONTEXT.get(agent)
    if not fields:
        return "", []
    rel = _get(f"/task/{task_id}/relationships")
    deps = rel.get("blocked_by") or []
    blocks = []
    for dep in deps:
        rc, d = _req("GET", f"/task/{dep['id']}?fields=title,status,decision_log,implementation_notes")
        if rc != 0 or not d or not d.get("id"):
            print(f"WARNING: dependency #{dep['id']} not readable — skipped", file=sys.stderr)
            continue
        lines = [f"### #{d['id']}: {d.get('title', '')} [{d.get('status', '')}]"]
        if d.get("status") not in TERMINAL:
            lines.append("[IN PROGRESS]")
        for field, limit in fields:
            label = "Decision Log" if field == "decision_log" else "Implementation Notes"
            val = _truncate(d.get(field) or "", limit)
            if val:
                lines += ["", f"**{label}:**", val]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), deps


def _render(template_name, replacements):
    """Template render: inject templates/_shared.md at <shared_rules>, then
    replace <key> placeholders (model/effort keys resolved from models.json)."""
    content = (TEMPLATES / template_name).read_text()
    shared = TEMPLATES / "_shared.md"
    if "<shared_rules>" in content and shared.exists():
        content = content.replace("<shared_rules>", shared.read_text().strip())
    provider, models, efforts = _models()
    for key, mkey in [("MODEL_" + k.upper(), k) for k in models]:
        replacements.setdefault(key, models[mkey])
    for key, ekey in [("EFFORT_" + k.upper(), k) for k in models]:
        replacements.setdefault(key, efforts.get(ekey, ""))
    for k, v in replacements.items():
        content = content.replace(f"<{k}>", v if v is not None else "")
    return content


def _utc_now():
    return subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
                          capture_output=True, text=True).stdout.strip()


def _tree_hash():
    """Deterministic content hash of the whole working tree (tracked + untracked)
    via a throwaway temp index. Never touches the real index/stash."""
    import tempfile
    fd, tmp = tempfile.mkstemp()
    os.close(fd)
    os.unlink(tmp)  # git must create the temp index itself
    env = dict(os.environ, GIT_INDEX_FILE=tmp)
    try:
        subprocess.run(["git", "add", "-A"], env=env, check=True, capture_output=True)
        out = subprocess.run(["git", "write-tree"], env=env, check=True,
                             capture_output=True, text=True)
        return out.stdout.strip()
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _emit_steering(task_id, status, cid):
    """Consent-gated, best-effort user_steering emit via observe.py. Never fails
    the caller."""
    enums = STEERING.get(status)
    if not enums:
        return
    try:
        gate = subprocess.run([sys.executable, str(HERE / "observe.py"), "gate"],
                              capture_output=True)
        if gate.returncode != 0:
            return
        modality, valence, target, severity, attributability, comment = enums
        subprocess.run([sys.executable, str(HERE / "observe.py"), "emit", str(task_id),
                        "--modality", modality, "--valence", valence,
                        "--target", target, "--severity", severity,
                        "--attributability", attributability,
                        "--comment", comment, "--correlation-id", cid or ""],
                       capture_output=True)
    except Exception:
        pass


def _next_status(status, level, verdict):
    """Verdict -> next status (mirrors the board's transitions)."""
    if status == "todo":
        return "impl" if level == 1 else "plan"
    if status == "plan":
        return "plan_review" if level == 3 else "impl"
    if status == "plan_review":
        return "impl" if verdict == "approved" else "plan"
    if status == "impl":
        return "done" if level == 1 else "impl_review"
    if status == "impl_review":
        if verdict == "approved":
            return "test" if level == 3 else "done"
        return "impl"
    if status == "test":
        return "done" if verdict == "pass" else "impl"
    return None


# ---------------------------------------------------------------- subcommands

def cmd_preflight(args):
    t = _get(f"/task/{args.id}?fields=status,level,card_type,title,"
             "plan_review_count,impl_review_count")
    status, level = t.get("status"), t.get("level")
    card_type = t.get("card_type") or "task"
    rel = _get(f"/task/{args.id}/relationships")
    blockers = [{"id": d["id"], "status": d["status"]}
                for d in (rel.get("blocked_by") or [])
                if d.get("status") not in TERMINAL]
    open_children = [c["id"] for c in (rel.get("children") or [])
                     if c.get("status") not in TERMINAL]
    runnable, reason = True, None
    if card_type == "epic":
        runnable, reason = False, "epic is a container — run its children"
    elif status in TERMINAL:
        runnable, reason = False, f"{status} is terminal — reopen to run"
    elif blockers:
        runnable, reason = False, "blocked by incomplete dependency"
    _out({"id": t.get("id"), "title": t.get("title"), "status": status,
          "level": level, "card_type": card_type,
          "runnable": runnable, "reason": reason,
          "blockers": blockers, "open_subtasks": open_children,
          "children": rel.get("children") or [],
          "children_progress": rel.get("children_progress"),
          "plan_review_count": t.get("plan_review_count"),
          "impl_review_count": t.get("impl_review_count")})


def cmd_dispatch(args):
    t = _get(f"/task/{args.id}?fields=status,level")
    status, level = t["status"], t.get("level")
    if args.agent:
        agent = args.agent.capitalize()
    elif status == "todo":
        agent = "Builder" if level == 1 else "Planner"
    else:
        agent = STATUS_AGENT.get(status)
    if agent not in AGENTS:
        print(f"ERROR: no agent for status '{status}'.", file=sys.stderr)
        sys.exit(2)
    model_key, template, _ = AGENTS[agent]

    # Entry PATCH — one level-aware call; plan re-entry sets current_agent only.
    if status == "todo":
        body = {"status": "impl" if level == 1 else "plan",
                "current_agent": agent, "actor": "Orchestrator"}
        status = body["status"]
    else:
        body = {"current_agent": agent, "actor": "Orchestrator"}
    rc, _p = _req("PATCH", f"/task/{args.id}", body)
    if rc != 0:
        _die(rc)

    task = _get(f"/task/{args.id}?fields=" + AGENT_FIELDS[agent])
    project = api.resolve_project()
    rc, proj = _req("GET", f"/projects/{project}")
    brief = (proj or {}).get("brief") or "" if rc == 0 else ""
    deps_ctx, _deps = _deps_context(args.id, agent)
    cid = str(uuid.uuid4())
    provider, models, efforts = _models()

    repl = {
        "ID": str(args.id), "PROJECT": project, "project_brief": brief,
        "title": task.get("title") or "", "description": task.get("description") or "",
        "spec": "" if agent == "Ranger" else _spec_md(task.get("spec")),
        "plan": task.get("plan") or "", "decision_log": task.get("decision_log") or "",
        "done_when": task.get("done_when") or "",
        "implementation_notes": task.get("implementation_notes") or "",
        "plan_review_comments": json.dumps(task.get("plan_review_comments"))
            if isinstance(task.get("plan_review_comments"), (list, dict))
            else (task.get("plan_review_comments") or ""),
        "dependencies_context": deps_ctx,
        "critic_feedback": _last_comment(task.get("plan_review_comments")),
        "inspector_feedback": _last_comment(task.get("review_comments")),
        "correlation_id": cid, "TIMESTAMP": _utc_now(),
        "API_HELPER": str(HERE / "api.py"),
    }
    prompt = _render(template, repl)
    meta = {"agent": agent, "model": models[model_key],
            "effort": efforts.get(model_key, ""), "provider": provider,
            "correlation_id": cid, "status": status, "level": level}
    print(json.dumps(meta))
    print("-----PROMPT-----")
    sys.stdout.write(prompt)


def cmd_record(args):
    agent = args.agent.capitalize()
    if agent not in AGENTS:
        print(f"ERROR: unknown agent '{args.agent}'.", file=sys.stderr)
        sys.exit(2)
    _prov, models, _efforts = _models()
    model = models[AGENTS[agent][0]]
    body = {"actor": agent, "model": model, "message": args.message}
    if args.cid:
        body["correlation_id"] = args.cid
    if args.tokens:
        body["tokens"] = args.tokens
    rc, _p = _req("POST", f"/task/{args.id}/activity", body)
    if rc != 0:
        _die(rc)
    # Report the step verdict so the orchestrator can gate without extra reads.
    t = _get(f"/task/{args.id}?fields=status,level,last_plan_review_status,"
             "last_review_status,last_test_status,plan_review_count,impl_review_count")
    status, level = t["status"], t.get("level")
    verdict = t.get(VERDICT_FIELD.get(status, ""), None) if status in VERDICT_FIELD else None
    count_field = REVIEW_COUNT_FIELD.get(status)
    count = t.get(count_field) if count_field else None
    _out({"status": status, "level": level, "verdict": verdict,
          "proposed_next": _next_status(status, level, verdict),
          "review_count": count,
          "circuit_breaker": bool(count and count > 3)})


def cmd_advance(args):
    t = _get(f"/task/{args.id}?fields=status,level,version,plan_review_count,"
             "impl_review_count,last_plan_review_status,last_review_status,last_test_status")
    status, level = t["status"], t.get("level")

    if args.human_reject:
        if status not in VERDICT_FIELD:
            print(f"ERROR: --human-reject only applies at a review gate, not '{status}'.",
                  file=sys.stderr)
            sys.exit(2)
        if not args.reason:
            print("ERROR: --human-reject requires --reason (server rejects empty).",
                  file=sys.stderr)
            sys.exit(2)
        body = {"gate": status, "reason": args.reason,
                "expected_version": t.get("version")}
        if args.cid:
            body["correlation_id"] = args.cid
        rc, _p = _req("POST", f"/task/{args.id}/override-review", body)
        if rc != 0:
            # Surface (403 = PAT lacks task:override-review); never fix in place.
            _die(rc)
        t = _get(f"/task/{args.id}?fields=status,level,plan_review_count,"
                 "impl_review_count,last_plan_review_status,last_review_status,last_test_status")

    verdict = t.get(VERDICT_FIELD[status]) if status in VERDICT_FIELD else None
    count_field = REVIEW_COUNT_FIELD.get(status)
    count = t.get(count_field) if count_field else None
    if count and count > 3 and not args.force:
        _out({"moved": False, "circuit_breaker": True, "status": status,
              "verdict": verdict, "review_count": count,
              "note": "review count > 3 — ask the user; re-run with --force to continue"})
        return
    nxt = _next_status(status, level, verdict)
    if nxt is None:
        print(f"ERROR: no transition from '{status}'.", file=sys.stderr)
        sys.exit(4)

    is_reject = status in VERDICT_FIELD and verdict in ("changes_requested", "fail")
    if is_reject:
        _emit_steering(args.id, status, args.cid)

    if nxt == "done":
        # finalize owns the done move (commit side-effects + stale recheck).
        _out({"moved": False, "status": status, "verdict": verdict,
              "next": "done", "action": "finalize"})
        return

    rc, _p = _req("PATCH", f"/task/{args.id}",
                  {"status": nxt, "current_agent": None, "actor": "Orchestrator"})
    if rc != 0:
        _die(rc)
    result = {"moved": True, "from": status, "to": nxt, "verdict": verdict}
    if level == 3 and status == "impl_review" and nxt == "test":
        result["approval_tree"] = _tree_hash()
    _out(result)


FORMATTERS = [
    # (probe fn, command list builder) — first match wins; format mode only.
    (lambda: pathlib.Path("package.json").is_file()
     and '"format"' in pathlib.Path("package.json").read_text(),
     lambda: (["pnpm", "run", "format"] if pathlib.Path("pnpm-lock.yaml").is_file()
              else ["yarn", "format"] if pathlib.Path("yarn.lock").is_file()
              else ["bun", "run", "format"] if pathlib.Path("bun.lockb").is_file()
              else ["npm", "run", "format"])),
    (lambda: any(pathlib.Path(m).is_file() and any(l.startswith("format:")
                 for l in pathlib.Path(m).read_text().splitlines())
                 for m in ("Makefile", "makefile")),
     lambda: ["make", "format"]),
    (lambda: pathlib.Path("justfile").is_file()
     and any(l.startswith("format") for l in pathlib.Path("justfile").read_text().splitlines()),
     lambda: ["just", "format"]),
    (lambda: pathlib.Path("biome.json").is_file() or pathlib.Path("biome.jsonc").is_file(),
     lambda: ["biome", "format", "--write"]),
    (lambda: pathlib.Path("pyproject.toml").is_file()
     and "[tool.ruff]" in pathlib.Path("pyproject.toml").read_text(),
     lambda: ["ruff", "format"]),
    (lambda: _have("black") and any(pathlib.Path(".").glob("*.py")),
     lambda: ["black"]),
    (lambda: _have("gofmt") and _git_has("*.go"), lambda: ["gofmt", "-w"]),
    (lambda: _have("rustfmt") and _git_has("*.rs"), lambda: ["rustfmt"]),
    (lambda: pathlib.Path(".prettierrc").is_file() or pathlib.Path(".prettierrc.json").is_file()
     or pathlib.Path("prettier.config.js").is_file(),
     lambda: ["prettier", "--write"]),
]


def _have(tool):
    import shutil
    return shutil.which(tool) is not None


def _git_has(glob):
    out = subprocess.run(["git", "ls-files", glob], capture_output=True, text=True)
    return bool(out.stdout.strip())


def cmd_normalize(args):
    diff = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True)
    changed = sorted(set(diff.stdout.split()) | set(untracked.stdout.split()))
    if not changed:
        _out({"normalized": False, "reason": "no changed files"})
        return
    cmd = None
    for probe, build in FORMATTERS:
        try:
            if probe():
                cmd = build()
                break
        except OSError:
            continue
    if cmd is None:
        _req("POST", f"/task/{args.id}/activity",
             {"actor": "Orchestrator", "model": "system",
              "message": "format-normalize: no formatter resolved — skipped"})
        _out({"normalized": False, "reason": "no formatter resolved (clean skip)"})
        return
    run = subprocess.run(cmd + changed, capture_output=True, text=True)
    if run.returncode != 0:
        _req("POST", f"/task/{args.id}/activity",
             {"actor": "Orchestrator", "model": "system",
              "message": f"format-normalize: formatter ({' '.join(cmd)}) exited non-zero — continued best-effort"})
    subprocess.run(["git", "add"] + changed, capture_output=True)
    _out({"normalized": True, "formatter": " ".join(cmd), "files": len(changed),
          "formatter_exit": run.returncode})


def cmd_finalize(args):
    t = _get(f"/task/{args.id}?fields=title,level,status")
    if args.approval_tree:
        current = _tree_hash()
        if current != args.approval_tree:
            _out({"finalized": False, "stale_approval": True,
                  "note": "working tree changed after impl_review approval — "
                          "re-dispatch the Inspector (impl_review re-entry)"})
            return
    rc, _p = _req("PATCH", f"/task/{args.id}",
                  {"status": "done", "current_agent": None, "actor": "Orchestrator"})
    if rc != 0:
        _die(rc)
    commit = "no-git"
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if dirty.returncode == 0 and dirty.stdout.strip():
        subprocess.run(["git", "add", "-A"], capture_output=True)
        msg = f"feat: {t.get('title', '')} [squad #{args.id}]"
        subprocess.run(["git", "commit", "-m", msg], capture_output=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True)
    if head.returncode == 0:
        commit = head.stdout.strip()
    subject = subprocess.run(["git", "log", "-1", "--format=%s"],
                             capture_output=True, text=True).stdout.strip() or "no-git"
    _req("POST", f"/task/{args.id}/activity",
         {"actor": "Orchestrator", "model": "system",
          "message": f"Committed {commit}: {subject} [squad #{args.id}]"})
    _out({"finalized": True, "commit": commit})


def cmd_move(args):
    rc, parsed = _req("PATCH", f"/task/{args.id}", {"status": args.status})
    if rc == 4 and isinstance(parsed, dict) and parsed.get("allowed"):
        alt = parsed["allowed"][0]
        rc2, _p = _req("PATCH", f"/task/{args.id}", {"status": alt})
        if rc2 == 0:
            _out({"moved": True, "to": alt, "self_corrected_from": args.status})
            return
        _die(rc2)
    if rc != 0:
        _die(rc)
    _out({"moved": True, "to": args.status})


def cmd_event(args):
    body = {"actor": args.actor, "model": args.model, "message": args.message}
    if args.cid:
        body["correlation_id"] = args.cid
    if args.tokens:
        body["tokens"] = args.tokens
    rc, _p = _req("POST", f"/task/{args.id}/activity", body)
    if rc != 0:
        _die(rc)
    _out({"recorded": True})


def main():
    p = argparse.ArgumentParser(prog="pipeline.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("preflight", help="runnability bundle for a task")
    s.add_argument("id")

    s = sub.add_parser("dispatch", help="entry PATCH + rendered agent prompt")
    s.add_argument("id")
    s.add_argument("--agent", help="override (e.g. shield for the impl 2nd step)")

    s = sub.add_parser("record", help="agent step event + verdict readout")
    s.add_argument("id")
    s.add_argument("--agent", required=True)
    s.add_argument("--message", required=True)
    s.add_argument("--tokens", type=int)
    s.add_argument("--cid")

    s = sub.add_parser("advance", help="verdict -> move (handles human reject)")
    s.add_argument("id")
    s.add_argument("--human-reject", action="store_true")
    s.add_argument("--reason")
    s.add_argument("--cid")
    s.add_argument("--force", action="store_true",
                   help="proceed past the review-count circuit breaker")

    s = sub.add_parser("normalize", help="format-normalize changed files")
    s.add_argument("id")

    s = sub.add_parser("finalize", help="done move + git commit + commit event")
    s.add_argument("id")
    s.add_argument("--approval-tree", help="L3 stale-approval recheck hash")

    s = sub.add_parser("move", help="validated move with one self-correction")
    s.add_argument("id")
    s.add_argument("status")

    s = sub.add_parser("event", help="append one activity event")
    s.add_argument("id")
    s.add_argument("--actor", required=True)
    s.add_argument("--message", required=True)
    s.add_argument("--model", default="system")
    s.add_argument("--cid")
    s.add_argument("--tokens", type=int)

    args = p.parse_args()
    {"preflight": cmd_preflight, "dispatch": cmd_dispatch, "record": cmd_record,
     "advance": cmd_advance, "normalize": cmd_normalize, "finalize": cmd_finalize,
     "move": cmd_move, "event": cmd_event}[args.cmd](args)


if __name__ == "__main__":
    main()
