#!/usr/bin/env bash
#
# validate-skills.sh — verify every skill conforms to the Agent Skills open standard
# (https://agentskills.io): a directory with SKILL.md whose YAML frontmatter has
# required `name` and `description` fields, and whose `name` matches its directory.
#
# Exit non-zero on any violation. Used by CI (.github/workflows/validate-skills.yml).
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

found=0
fail=0

for skill_md in "$REPO_ROOT"/plugins/*/skills/*/SKILL.md; do
  [ -f "$skill_md" ] || continue
  found=$((found + 1))
  name="$(basename "$(dirname "$skill_md")")"

  # Must open with a YAML frontmatter fence.
  if [ "$(head -n 1 "$skill_md")" != "---" ]; then
    echo "❌ $name: SKILL.md must start with '---' (YAML frontmatter)"; fail=1; continue
  fi

  # Extract the frontmatter block (between the first two '---' lines).
  fm="$(awk 'NR==1{next} /^---[[:space:]]*$/{exit} {print}' "$skill_md")"

  grep -qE '^name:[[:space:]]*[^[:space:]]'        <<<"$fm" || { echo "❌ $name: frontmatter missing 'name:'"; fail=1; }
  grep -qE '^description:[[:space:]]*[^[:space:]]' <<<"$fm" || { echo "❌ $name: frontmatter missing 'description:'"; fail=1; }

  fm_name="$(sed -nE 's/^name:[[:space:]]*//p' <<<"$fm" | head -n1 | tr -d '"'\' )"
  if [ -n "$fm_name" ] && [ "$fm_name" != "$name" ]; then
    echo "❌ $name: frontmatter name '$fm_name' must match directory '$name'"; fail=1
  fi
done

if [ "$found" -eq 0 ]; then
  echo "❌ no skills found under plugins/*/skills/*"; exit 1
fi

if [ "$fail" -ne 0 ]; then
  echo "validation FAILED"; exit 1
fi

echo "✓ $found skills valid"
