#!/usr/bin/env bash
#
# validate-skills.sh — verify every skill conforms to the Agent Skills open standard
# (https://agentskills.io). Uses a REAL YAML parser (like the installers do), so it
# catches malformed frontmatter a naive grep would miss — e.g. an unquoted ": " or
# embedded quotes in `description` that make tools like `npx skills` silently skip
# the skill.
#
# Checks each skills/<name>/SKILL.md: parseable YAML frontmatter that is a mapping
# with non-empty `name` + `description`, and `name` == directory.
#
# Requires PyYAML (CI installs it). Exit non-zero on any violation.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$REPO_ROOT" <<'PY'
import sys, os, glob, yaml

root = sys.argv[1]
skills = sorted(glob.glob(os.path.join(root, "skills", "*", "SKILL.md")))
if not skills:
    print("❌ no skills found under skills/*"); sys.exit(1)

fail = 0
for path in skills:
    name = os.path.basename(os.path.dirname(path))
    txt = open(path, encoding="utf-8").read()
    if not txt.startswith("---"):
        print(f"❌ {name}: SKILL.md must start with YAML frontmatter ('---')"); fail += 1; continue
    parts = txt.split("---", 2)
    if len(parts) < 3:
        print(f"❌ {name}: frontmatter not closed with '---'"); fail += 1; continue
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        print(f"❌ {name}: invalid YAML frontmatter — {str(e).splitlines()[0]}"); fail += 1; continue
    if not isinstance(fm, dict):
        print(f"❌ {name}: frontmatter is not a mapping"); fail += 1; continue
    if not fm.get("name"):        print(f"❌ {name}: missing 'name'"); fail += 1
    if not fm.get("description"): print(f"❌ {name}: missing 'description'"); fail += 1
    if fm.get("name") and fm["name"] != name:
        print(f"❌ {name}: frontmatter name '{fm['name']}' must match directory '{name}'"); fail += 1

if fail:
    print(f"validation FAILED ({fail} issue(s))"); sys.exit(1)
print(f"✓ {len(skills)} skills valid")
PY
