"""Mechanical enforcement of the skill authoring standard (AGENTS.md → Authoring standard).

The standard is engine-first + progressive disclosure. These guards enforce the parts a
regex can hold so the standard can't silently erode:

1. SKILL.md body ≤ 200 lines (common-path-only; detail belongs in references/).
2. Frontmatter description ≤ 1024 chars, non-empty, not first-person.
3. References are one level deep: a references/*.md never points into another references/.
4. Scripts are black boxes: no shipped .md instructs reading a script's source.
5. Scripts expose --help (argparse or explicit handling) and are zero-dependency
   (stdlib imports only, plus sibling script modules).

Hermetic: reads committed files only.
"""
import pathlib
import re
import sys

import pytest

SKILLS = None  # populated by fixtures


def _skill_dirs(repo_root):
    return sorted(p for p in (repo_root / "skills").iterdir()
                  if p.is_dir() and (p / "SKILL.md").exists())


def _frontmatter(text):
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


MAX_SKILL_LINES = 200


def test_skill_md_line_budget(repo_root):
    over = []
    for d in _skill_dirs(repo_root):
        n = len((d / "SKILL.md").read_text().splitlines())
        if n > MAX_SKILL_LINES:
            over.append(f"{d.name}: {n} lines")
    assert not over, (
        f"SKILL.md over the {MAX_SKILL_LINES}-line budget (move detail to references/):\n"
        + "\n".join(over)
    )


def test_description_is_a_trigger_contract(repo_root):
    bad = []
    for d in _skill_dirs(repo_root):
        fm = _frontmatter((d / "SKILL.md").read_text())
        m = re.search(r"^description:\s*(.+?)(?=^\w+:|\Z)", fm, re.MULTILINE | re.DOTALL)
        desc = " ".join((m.group(1) if m else "").split())
        if not desc:
            bad.append(f"{d.name}: empty description")
        elif len(desc) > 1024:
            bad.append(f"{d.name}: description {len(desc)} chars (> 1024)")
        elif re.search(r"\bI can\b|\bI will\b|^['\"]?I\b", desc):
            bad.append(f"{d.name}: first-person description")
    assert not bad, "frontmatter description violations:\n" + "\n".join(bad)


def test_references_are_one_level_deep(repo_root):
    offenders = []
    for d in _skill_dirs(repo_root):
        refdir = d / "references"
        if not refdir.is_dir():
            continue
        for ref in refdir.glob("*.md"):
            text = ref.read_text()
            # A reference pointing at any references/*.md (its own dir or another
            # skill's) creates a >1-level chain — Claude previews long files, so
            # nested pointers cause partial reads.
            for hit in re.finditer(r"[\w./-]*references/[\w-]+\.md", text):
                offenders.append(f"{ref.relative_to(repo_root)}: points at {hit.group(0)}")
    assert not offenders, (
        "references must be one level deep (reachable from SKILL.md only):\n"
        + "\n".join(offenders)
    )


def test_no_shipped_md_instructs_reading_script_source(repo_root):
    offenders = []
    pattern = re.compile(
        r"(Read|read|open|inspect|study)\s+(tool:?\s*)?[`\"']?[\w./-]*scripts/[\w-]+\.py",
    )
    for md in (repo_root / "skills").rglob("*.md"):
        for lineno, line in enumerate(md.read_text().splitlines(), 1):
            if pattern.search(line) and "black box" not in line and "--help" not in line:
                offenders.append(f"{md.relative_to(repo_root)}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        "shipped skills must use scripts as black boxes (run them; never read source):\n"
        + "\n".join(offenders)
    )


STDLIB_OK = {
    "__future__", "argparse", "base64", "collections", "dataclasses", "datetime",
    "functools", "hashlib", "itertools", "json", "math", "os", "pathlib", "re",
    "shutil", "socket", "ssl", "statistics", "string", "subprocess", "sys",
    "tempfile", "textwrap", "time", "typing", "urllib", "uuid",
}
# Sibling script modules import each other by design (api, pipeline, ...).
SIBLING_OK_PATTERN = re.compile(r"^[a-z_]+$")


def _top_level_imports(pyfile):
    for line in pyfile.read_text().splitlines():
        m = re.match(r"^(?:import|from)\s+([\w.]+)", line)
        if m:
            yield m.group(1).split(".")[0]


def test_shipped_scripts_are_zero_dependency(repo_root):
    offenders = []
    script_names = {p.stem for p in (repo_root / "skills").rglob("scripts/*.py")}
    for py in (repo_root / "skills").rglob("scripts/*.py"):
        for mod in _top_level_imports(py):
            if mod in STDLIB_OK or mod in script_names:
                continue
            offenders.append(f"{py.relative_to(repo_root)}: imports {mod}")
    assert not offenders, (
        "shipped scripts must be stdlib-only (plus sibling scripts):\n" + "\n".join(offenders)
    )


def test_shipped_scripts_expose_help(repo_root):
    offenders = []
    for py in (repo_root / "skills").rglob("scripts/*.py"):
        if py.stem.endswith("_smoke"):
            continue  # smoke probes are dev-run, not agent-run
        text = py.read_text()
        if "argparse" not in text and "--help" not in text:
            offenders.append(str(py.relative_to(repo_root)))
    assert not offenders, (
        "shipped scripts must expose --help (argparse or explicit):\n" + "\n".join(offenders)
    )
