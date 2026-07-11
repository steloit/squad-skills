#!/usr/bin/env python3
"""init.py — register the current project on the Squad board in one shot.

Run as a black box. Resolves the project name and org, writes/updates the
committed .squadrc, detects auth presence (never printing the token), persists
a custom base URL, and best-effort registers the project on the board
(POST /projects via the shared board-request core).

Usage:
  init.py [--project NAME] [--org SLUG] [--base-url URL] [--force]

Resolution (first match wins):
  project   --project (leading dashes stripped) > existing .squadrc > directory name
  org       --org > env SQUAD_ORG > existing .squadrc  — REQUIRED; exits 2 if unresolvable
  base URL  --base-url > env SQUAD_BASE_URL > ~/.squad/config > deployed default

.squadrc: created when absent; missing keys are appended. An existing value is
never overwritten without --force — conflicting explicit flags print the
current values and exit 2.

Output: one JSON summary on stdout:
  {"project", "org", "base_url", "squadrc", "auth", "registered", "board_url"}
  squadrc ∈ {written, updated, kept, overwritten} · auth ∈ {env, file, none}
  (the token value is never read into the summary, echoed, or logged).

Exit codes: 0 success (a missing token or a failed board registration is a
stderr warning, not fatal) · 2 usage error / SQUAD_ORG unresolvable /
refused .squadrc overwrite.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

SQUAD_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "squad" / "scripts"
sys.path.insert(0, str(SQUAD_SCRIPTS))
import api  # noqa: E402  (shared resolution: base URL, keyed-line reads, token key)
import pipeline  # noqa: E402  (shared board-request core)

SQUADRC = pathlib.Path(".squadrc")


def _read_squadrc():
    return (SQUADRC.is_file(),
            api._read_keyed_line(SQUADRC, "SQUAD_PROJECT="),
            api._read_keyed_line(SQUADRC, "SQUAD_ORG="))


def _write_squadrc(exists, force, cur_proj, cur_org, project, org):
    """Returns the squadrc state: written | overwritten | updated | kept."""
    content = f"SQUAD_PROJECT={project}\nSQUAD_ORG={org}\n"
    if not exists:
        SQUADRC.write_text(content)
        return "written"
    if force:
        SQUADRC.write_text(content)
        return "overwritten"
    if cur_proj and cur_org:
        print(f"Kept existing .squadrc (SQUAD_PROJECT={cur_proj}, SQUAD_ORG={cur_org}); "
              "use --force to overwrite.", file=sys.stderr)
        return "kept"
    # File exists but a key is missing — append only what's absent.
    body = SQUADRC.read_text().rstrip("\n")
    add = []
    if not cur_proj:
        add.append(f"SQUAD_PROJECT={project}")
    if not cur_org:
        add.append(f"SQUAD_ORG={org}")
    SQUADRC.write_text((body + "\n" if body else "") + "\n".join(add) + "\n")
    return "updated"


def _detect_auth():
    """env | file | none — presence only; the token value is never surfaced."""
    if os.environ.get("SQUAD_AUTH_TOKEN"):
        return "env"
    if api._read_keyed_line(pathlib.Path.home() / ".squad" / "auth", api.TOKEN_KEY):
        return "file"
    return "none"


def _persist_base_url(base_url):
    cfg = pathlib.Path.home() / ".squad" / "config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    lines = [ln for ln in (cfg.read_text().splitlines() if cfg.is_file() else [])
             if not ln.startswith("SQUAD_BASE_URL=")]
    lines.append(f"SQUAD_BASE_URL={base_url}")
    cfg.write_text("\n".join(lines) + "\n")


def _infer_metadata(project):
    """Best-effort category / purpose / stack / repo_url from the local checkout."""
    category = "personal"
    if re.search(r"skill|squad", project, re.IGNORECASE):
        category = "skills"
    if re.search(r"tool|api|cli", project, re.IGNORECASE):
        category = "tools"

    purpose = stack = ""
    claude_md = pathlib.Path("CLAUDE.md")
    if claude_md.is_file():
        try:
            for line in claude_md.read_text(errors="replace").splitlines():
                s = line.strip()
                if not purpose and s and not s.startswith("#") and not s.startswith("---"):
                    purpose = s[:300]
                if not stack and re.search(
                        r"stack|tech|typescript|javascript|python|react|vue|next|node|vite",
                        line, re.IGNORECASE):
                    stack = s[:200]
                if purpose and stack:
                    break
        except OSError:
            pass

    try:
        repo_url = subprocess.run(["git", "remote", "get-url", "origin"],
                                  capture_output=True, text=True).stdout.strip()
    except OSError:
        repo_url = ""
    return category, purpose, stack, repo_url


def main():
    parser = argparse.ArgumentParser(
        description="Register the current project on the Squad board: write the "
                    "committed .squadrc (project + org), detect auth presence, and "
                    "register the project via POST /projects (best-effort).")
    parser.add_argument("--project", help="project name (default: existing .squadrc > directory name)")
    parser.add_argument("--org", help="org slug (default: env SQUAD_ORG > existing .squadrc); "
                                      "required — every board call is org-scoped")
    parser.add_argument("--base-url", help="custom board URL; persisted to ~/.squad/config when non-default")
    parser.add_argument("--force", action="store_true", help="overwrite an existing .squadrc")
    args = parser.parse_args()

    exists, cur_proj, cur_org = _read_squadrc()
    arg_proj = (args.project or "").lstrip("-")

    if exists and not args.force:
        conflicts = []
        if arg_proj and cur_proj and arg_proj != cur_proj:
            conflicts.append(f"SQUAD_PROJECT: current '{cur_proj}' vs requested '{arg_proj}'")
        if args.org and cur_org and args.org != cur_org:
            conflicts.append(f"SQUAD_ORG: current '{cur_org}' vs requested '{args.org}'")
        if conflicts:
            print(".squadrc already exists and differs from the requested values:", file=sys.stderr)
            for c in conflicts:
                print(f"  {c}", file=sys.stderr)
            print("Re-run with --force to overwrite, or drop the conflicting flag to keep "
                  "the current values. Nothing was written or registered.", file=sys.stderr)
            return 2

    project = arg_proj or cur_proj or pathlib.Path.cwd().name
    org = args.org or os.environ.get("SQUAD_ORG", "") or cur_org
    if not org:
        print("ERROR: SQUAD_ORG is not set. Every board call is org-scoped (/api/orgs/<org>/...).",
              file=sys.stderr)
        print("Fix: pass --org <slug> (from the mint dialog's SQUAD_ORG=<slug> line), export "
              "SQUAD_ORG for this shell, or add SQUAD_ORG=<slug> to .squadrc. Nothing was "
              "written or registered.", file=sys.stderr)
        return 2

    squadrc = _write_squadrc(exists, args.force, cur_proj, cur_org, project, org)

    auth = _detect_auth()
    if auth == "none":
        print("No Squad Personal Access Token configured — mint one in the board web UI "
              "(Settings -> Personal Access Tokens) and run the store command it shows.",
              file=sys.stderr)

    if args.base_url:
        # Never persist a non-URL to the global config — a mispassed path/garbage
        # would silently poison board access for every project on this machine.
        if not args.base_url.startswith(("http://", "https://")):
            print(f"ERROR: --base-url must be an http(s) URL, got: {args.base_url!r}. "
                  "Not written or registered.", file=sys.stderr)
            return 2
        os.environ["SQUAD_BASE_URL"] = args.base_url
        if args.base_url != api.DEFAULT_BASE_URL:
            _persist_base_url(args.base_url)
    base_url = api.resolve_base_url()

    # The request core resolves org/project from the env — hand it what we resolved.
    os.environ["SQUAD_ORG"] = org
    os.environ["SQUAD_PROJECT"] = project

    registered = False
    if auth == "none":
        print("Skipping board registration (no token). Re-run after storing a token.", file=sys.stderr)
    else:
        category, purpose, stack, repo_url = _infer_metadata(project)
        payload = {"id": project, "name": project, "category": category}
        for key, value in (("purpose", purpose), ("stack", stack), ("repo_url", repo_url)):
            if value:
                payload[key] = value
        rc, _resp = pipeline._req("POST", "/projects", payload)
        registered = rc == 0
        if rc == 4:
            print("NOTE: board declined the create (project may already be registered) — "
                  "existing registration left as-is.", file=sys.stderr)
        elif rc != 0:
            print("WARNING: board registration failed (diagnostics above) — init still "
                  "succeeded locally; re-run later to register.", file=sys.stderr)

    print(json.dumps({
        "project": project,
        "org": org,
        "base_url": base_url,
        "squadrc": squadrc,
        "auth": auth,
        "registered": registered,
        "board_url": f"{base_url}/?project={project}",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
