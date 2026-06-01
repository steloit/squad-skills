#!/usr/bin/env bash
#
# install.sh — install Steloit Squad skills into open-standard agent tools.
#
# Symlinks every skill in this repo into a target tool's skills directory.
# Symlinks (not copies) mean `git pull` in this repo updates all linked tools
# instantly. Idempotent: safe to re-run.
#
# Claude Code does NOT need this — use the marketplace instead:
#   /plugin marketplace add steloit/squad-skills
#   /plugin install squad@steloit
#
# Usage:
#   scripts/install.sh                 # → ~/.agents/skills (Codex / open standard, default)
#   scripts/install.sh --claude        # → ~/.claude/skills (non-plugin Claude Code use)
#   scripts/install.sh --target <dir>  # → a custom skills directory
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

target="${HOME}/.agents/skills"
case "${1:-}" in
  --claude)         target="${HOME}/.claude/skills" ;;
  --codex|"")       target="${HOME}/.agents/skills" ;;
  --target)         target="${2:?--target requires a path}" ;;
  -h|--help)        echo "usage: install.sh [--codex | --claude | --target <dir>]"; exit 0 ;;
  *)                echo "unknown option: $1" >&2; exit 2 ;;
esac

mkdir -p "$target"

count=0
# Canonical skills: plugins/<plugin>/skills/<skill>/SKILL.md
for skill_md in "$REPO_ROOT"/plugins/*/skills/*/SKILL.md; do
  [ -f "$skill_md" ] || continue
  skill_dir="$(dirname "$skill_md")"
  name="$(basename "$skill_dir")"
  link="$target/$name"
  rm -rf "$link"
  ln -s "$skill_dir" "$link"
  printf '  linked %-22s → %s\n' "$name" "$link"
  count=$((count + 1))
done

echo "Installed $count Squad skills into $target"
echo "Update anytime with:  git -C \"$REPO_ROOT\" pull   (symlinks track the repo)"
