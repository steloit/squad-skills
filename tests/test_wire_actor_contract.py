"""Wire-actor contract: the 2-agent pipeline writes only server-valid `actor` labels.

The board validates the `actor` field (generic task PATCH + activity append) against a
fixed enum that predates the 2-agent pipeline; `actor:"Worker"` would 400. v2 therefore
maps each column to a wire label. These tests pin that mapping to the vendored OpenAPI
contract so a drifting enum (or a doc typo) fails deterministically.
"""
import json
import re

SKILL = "skills/squad-run/SKILL.md"
SCHEMA = "skills/squad/schema.md"

# The column → wire-label mapping v2 documents (schema.md → Wire Actor Labels).
WIRE_MAP = {
    "plan": "Planner",
    "plan_review": "Critic",
    "impl": "Builder",
    "impl_review": "Inspector",
    "test": "Ranger",
}


def _actor_enum(repo_root):
    """The `actor` enum from the vendored OpenAPI contract (the wire truth)."""
    spec = json.loads((repo_root / "tests" / "fixtures" / "openapi.json").read_text())
    enums = set()

    def walk(node):
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                actor = props.get("actor")
                if isinstance(actor, dict) and isinstance(actor.get("enum"), list):
                    enums.add(tuple(actor["enum"]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)
    assert enums, "openapi.json must define an `actor` enum"
    # All actor enums in the spec must agree; use the union defensively.
    members = set()
    for e in enums:
        members |= set(e)
    return members


def test_every_documented_wire_label_is_in_the_openapi_enum(repo_root):
    enum = _actor_enum(repo_root)
    for column, label in WIRE_MAP.items():
        assert label in enum, (
            f"wire label {label!r} (column {column}) is not in the server actor enum {enum}"
        )


def test_nicknames_are_not_in_the_enum_so_mapping_is_required(repo_root):
    """The reason the mapping exists: the real nicknames are NOT valid wire actors.
    If the backend ever adds them, this fails as a prompt to drop the mapping."""
    enum = _actor_enum(repo_root)
    assert "Worker" not in enum and "Reviewer" not in enum, (
        "Worker/Reviewer are now valid wire actors — the wire-label mapping can be retired"
    )


def test_schema_documents_the_full_mapping(repo_root):
    text = (repo_root / SCHEMA).read_text()
    assert "## Wire Actor Labels" in text, "schema.md must document the wire-actor contract"
    for column, label in WIRE_MAP.items():
        assert re.search(rf"\|\s*`{column}`\s*\|.*\|\s*`{label}`\s*\|", text), (
            f"schema.md Wire Actor Labels table missing row: {column} → {label}"
        )


def test_squad_run_documents_the_full_mapping(repo_root):
    text = (repo_root / SKILL).read_text()
    for column, label in WIRE_MAP.items():
        assert re.search(rf"\|\s*`{column}`\s*\|.*\|\s*`{label}`\s*\|", text), (
            f"squad-run Wire Actor Labels table missing row: {column} → {label}"
        )


def test_orchestrator_moves_stay_orchestrator_attributed(repo_root):
    """Status-move PATCHes are the orchestrator's own machine events — never swept
    into agent attribution."""
    text = (repo_root / SKILL).read_text()
    assert '"status": "done", "current_agent": null, "actor": "Orchestrator"' in text
    assert '"status": "impl_review", "current_agent": null, "actor": "Orchestrator"' in text


def test_templates_use_wire_labels_on_enum_bound_writes(repo_root):
    """worker.md's record PATCHes carry the column's wire label; the free-string
    verdict fields carry the real nicknames."""
    tpl_dir = repo_root / "skills" / "squad" / "templates"
    worker = (tpl_dir / "worker.md").read_text()
    assert '\\"actor\\": \\"Planner\\"' in worker, "plan focus PATCH must send actor Planner"
    assert '\\"actor\\": \\"Builder\\"' in worker, "impl focus PATCH must send actor Builder"
    assert '"tester": "Worker"' in worker, "test focus must record tester as the real nickname"
    reviewer = (tpl_dir / "reviewer.md").read_text()
    assert '"reviewer": "Reviewer"' in reviewer, (
        "verdict POSTs use the free-string reviewer nickname"
    )
    assert '"actor"' not in reviewer, (
        "reviewer.md records verdicts via /plan-review and /review only — no actor-bearing write"
    )
