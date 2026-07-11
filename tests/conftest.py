"""Shared fixtures: load the skill scripts as modules (their dirs aren't packages)."""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def plan_batch():
    return _load("skills/squad-batch-run/scripts/plan_batch.py", "plan_batch")


@pytest.fixture(scope="session")
def render_mod():
    return _load("skills/squad/scripts/render_agent_prompt.py", "render_agent_prompt")


@pytest.fixture(scope="session")
def api_mod():
    return _load("skills/squad/scripts/api.py", "api")


@pytest.fixture(scope="session")
def observe_mod():
    return _load("skills/squad/scripts/observe.py", "observe")


@pytest.fixture(scope="session")
def refine_ledger():
    return _load("skills/squad/scripts/refine_ledger.py", "refine_ledger")


@pytest.fixture(scope="session")
def pipeline_mod():
    return _load("skills/squad/scripts/pipeline.py", "pipeline")


@pytest.fixture(scope="session")
def create_tasks_mod():
    return _load("skills/squad/scripts/create_tasks.py", "create_tasks")


@pytest.fixture(scope="session")
def stats_mod():
    return _load("skills/squad/scripts/stats.py", "stats")


@pytest.fixture(scope="session")
def repo_root():
    return ROOT
