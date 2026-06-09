"""Structural guards for the centralized Coach dispatch (#280).

#280 extracted the Coach dispatch (model resolution + render coach.md + Task launch + the
#276 silent-output rule) out of the 5 per-skill SKILL.md blocks into ONE canonical
`## Coach Dispatch` section in skills/squad/shared.md, leaving each skill a short reference.

These are deterministic guards for the centralization invariants the #280 done_when asks for
as grep proofs — they keep the DRY refactor from silently regressing (e.g. someone re-inlining a
dispatch block, the silent line creeping back into a skill, or a skill losing its reference,
which would silently stop the Coach firing for that skill). Docs-only structure, no runtime code.
"""

SILENT_RULE = "friction report(s) filed for triage"
INLINE_MODEL_RESOLUTION = "MODEL_PROVIDER=${SQUAD_MODEL_PROVIDER:-}"

# The 5 agent-run skills that dispatch the Coach at their close.
DISPATCHING_SKILLS = [
    "squad-run", "squad-explore", "squad-batch-run", "squad-refine", "squad-gen-wiki",
]
# The 3 dispatching skills that previously inlined Model Resolution in their Coach block.
INLINE_PROVIDER_SKILLS = ["squad-explore", "squad-batch-run", "squad-gen-wiki"]
# CRUD/setup skills that load shared.md but never invoke the Coach.
TRIVIAL_SKILLS = ["squad", "squad-init", "squad-kickstart", "squad-heartbeat"]


def _skill_text(repo_root, name):
    return (repo_root / "skills" / name / "SKILL.md").read_text()


def test_silent_rule_lives_only_in_shared(repo_root):
    """The #276 silent-output rule appears exactly once across all skills — in shared.md."""
    skills_dir = repo_root / "skills"
    hits = [p for p in skills_dir.rglob("*.md") if SILENT_RULE in p.read_text()]
    assert len(hits) == 1, f"silent rule should appear in exactly 1 file, found: {hits}"
    assert hits[0] == skills_dir / "squad" / "shared.md"


def test_shared_has_scoped_coach_dispatch_section(repo_root):
    """shared.md owns the canonical `## Coach Dispatch` section, scoped to the 5 invoking skills."""
    text = (repo_root / "skills" / "squad" / "shared.md").read_text()
    assert "## Coach Dispatch" in text
    assert SILENT_RULE in text
    for name in DISPATCHING_SKILLS:
        assert f"`{name}`" in text, f"{name} not named in Coach Dispatch scope"


def test_all_five_skills_reference_coach_dispatch(repo_root):
    """Each of the 5 agent-run skills references shared.md → Coach Dispatch and passes its inputs."""
    for name in DISPATCHING_SKILLS:
        text = _skill_text(repo_root, name)
        assert "Coach Dispatch" in text, f"{name} lost its Coach Dispatch reference"
        for token in ("`skill_name`", "`trajectory`", "`friction_signals`"):
            assert token in text, f"{name} reference missing {token}"


def test_inline_provider_skills_no_longer_inline_model_resolution(repo_root):
    """explore/batch-run/gen-wiki no longer inline Model Resolution in their Coach block."""
    for name in INLINE_PROVIDER_SKILLS:
        text = _skill_text(repo_root, name)
        assert INLINE_MODEL_RESOLUTION not in text, f"{name} still inlines Model Resolution"


def test_trivial_skills_do_not_dispatch_coach(repo_root):
    """CRUD/setup skills load shared.md but never invoke the Coach — no dispatch artifacts."""
    for name in TRIVIAL_SKILLS:
        text = _skill_text(repo_root, name)
        assert "Coach Dispatch" not in text, f"{name} should not reference Coach Dispatch"
        assert "read_model coach" not in text, f"{name} should not resolve the coach model"
