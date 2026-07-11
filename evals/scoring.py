"""Git-versioned result store for behavioral evals.

Every run appends one JSON line to ``evals/history.jsonl`` (meant to be committed)
holding per-scenario, per-trial scores plus git metadata — so score changes trace to
commits and a trailing baseline can be computed locally without any SaaS.

Generated HTML reports live under ``evals/results/`` (gitignored); the *data* lives in
``history.jsonl`` (tracked). That split keeps the rolling baseline diffable in git while
the disposable dashboard stays out of version control.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

EVAL_DIR = pathlib.Path(__file__).parent
HISTORY = EVAL_DIR / "history.jsonl"          # committed — the rolling baseline
RESULTS_DIR = EVAL_DIR / "results"            # gitignored — generated reports


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str, default: str = "") -> str:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=EVAL_DIR, timeout=10
        )
        return out.stdout.strip() or default
    except Exception:
        return default


def git_meta() -> dict:
    return {
        "sha": _git("rev-parse", "--short", "HEAD", default="unknown"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", default="unknown"),
        "dirty": bool(_git("status", "--porcelain")),
    }


@dataclass
class ScenarioResult:
    """Outcome of one scenario across N trials."""
    id: str
    deterministic_pass: bool          # every trial reached the expected board state
    deterministic_passes: int         # how many of N trials passed the hard checks
    trials: int
    score: float | None               # mean GEval score across trials (None if no judge)
    score_trials: list[float] = field(default_factory=list)
    tool_calls: list[int] = field(default_factory=list)   # cost/efficiency signal
    durations_s: list[float] = field(default_factory=list)  # wall-clock per trial (speed signal)
    errors: int = 0                   # trials where the agent exited non-zero
    reasons: list[str] = field(default_factory=list)      # judge reasoning per trial
    note: str = ""


@dataclass
class RunRecord:
    timestamp: str
    git: dict
    agent: str
    judge: str | None
    trials: int
    scenarios: list[dict]             # serialized ScenarioResult list

    @classmethod
    def build(cls, *, agent: str, judge: str | None, trials: int,
              scenarios: list[ScenarioResult]) -> "RunRecord":
        return cls(
            timestamp=now_iso(),
            git=git_meta(),
            agent=agent,
            judge=judge,
            trials=trials,
            scenarios=[asdict(s) for s in scenarios],
        )


def append_run(record: RunRecord) -> pathlib.Path:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record)) + "\n")
    return HISTORY


def load_history() -> list[dict]:
    if not HISTORY.is_file():
        return []
    return [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines()
            if line.strip()]
