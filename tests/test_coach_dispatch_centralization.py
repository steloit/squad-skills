"""Structural guards for the centralized Coach dispatch.

The Coach dispatch (render coach.md + Task launch + the silent-output rule) lives in ONE
canonical section — now `## Coach dispatch` in skills/squad/references/friction.md (moved
there from shared.md when the shared context was split into on-demand references). Each of
the 5 agent-run skills carries a short reference that names its per-run inputs and mandates
a background launch; the CRUD/setup skills never dispatch the Coach.

These guards keep the DRY centralization from silently regressing (a re-inlined dispatch
block, the silent rule creeping back into a skill, or a skill losing its reference — which
would silently stop the Coach firing for that skill). Docs-only structure, no runtime code.
"""

SILENT_RULE = "friction report(s) filed for triage"
INLINE_MODEL_RESOLUTION = "MODEL_PROVIDER=${SQUAD_MODEL_PROVIDER:-}"
CANONICAL = ("skills", "squad", "references", "friction.md")

# The 5 agent-run skills that dispatch the Coach at their close.
DISPATCHING_SKILLS = [
    "squad-run", "squad-explore", "squad-batch-run", "squad-refine", "squad-gen-wiki",
]
# CRUD/setup skills that load shared.md but never invoke the Coach.
TRIVIAL_SKILLS = ["squad", "squad-init", "squad-kickstart", "squad-heartbeat"]


def _skill_text(repo_root, name):
    return (repo_root / "skills" / name / "SKILL.md").read_text()


def test_silent_rule_lives_only_in_canonical_file(repo_root):
    """The silent-output rule appears exactly once across all skills — in references/friction.md."""
    skills_dir = repo_root / "skills"
    hits = [p for p in skills_dir.rglob("*.md") if SILENT_RULE in p.read_text()]
    assert len(hits) == 1, f"silent rule should appear in exactly 1 file, found: {hits}"
    assert hits[0] == repo_root.joinpath(*CANONICAL)


def test_canonical_file_has_scoped_coach_dispatch_section(repo_root):
    """friction.md owns the canonical Coach dispatch section, scoped to the 5 invoking skills,
    with the background-launch mandate."""
    text = repo_root.joinpath(*CANONICAL).read_text()
    assert "## Coach dispatch" in text
    assert SILENT_RULE in text
    assert "background" in text.lower(), "the dispatch must be mandated as a background launch"
    for name in DISPATCHING_SKILLS:
        assert f"`{name}`" in text, f"{name} not named in the Coach dispatch scope"


def test_all_five_skills_reference_coach_dispatch(repo_root):
    """Each of the 5 agent-run skills references friction.md's Coach dispatch and passes its inputs."""
    for name in DISPATCHING_SKILLS:
        text = _skill_text(repo_root, name)
        assert "Coach" in text, f"{name} lost its Coach dispatch reference"
        assert "references/friction.md" in text, f"{name} must point at the canonical dispatch"
        for token in ("skill_name", "trajectory", "friction_signals"):
            assert token in text, f"{name} reference missing {token}"


def test_dispatching_skills_do_not_inline_model_resolution(repo_root):
    """No skill re-inlines the provider/model resolution block in its Coach reference."""
    for name in DISPATCHING_SKILLS:
        text = _skill_text(repo_root, name)
        assert INLINE_MODEL_RESOLUTION not in text, f"{name} inlines Model Resolution"


def test_trivial_skills_do_not_dispatch_coach(repo_root):
    """CRUD/setup skills never invoke the Coach — no dispatch artifacts."""
    for name in TRIVIAL_SKILLS:
        text = _skill_text(repo_root, name)
        assert "coach.md" not in text, f"{name} should not render the coach template"
        assert "read_model coach" not in text, f"{name} should not resolve the coach model"
        assert "friction_signals" not in text, f"{name} should not pass Coach inputs"
