"""Deterministic unit tests for the eval regression statistics (evals/baseline.py).

The regression gate's correctness hinges on the pure-Python Student-t / incomplete-beta
math, so it's pinned here against known values — runs on every PR, no LLM, no keys.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "evals"))
import baseline as bl  # noqa: E402


def approx(a: float, b: float, tol: float = 2e-3) -> bool:
    return abs(a - b) <= tol


# ── incomplete beta ──
def test_betai_symmetry():
    assert approx(bl.betai(0.5, 0.5, 0.5), 0.5)


def test_betai_endpoints():
    assert bl.betai(2, 3, 0.0) == 0.0
    assert bl.betai(2, 3, 1.0) == 1.0


# ── Student-t two-sided p-value (vs standard t-tables) ──
def test_student_t_critical_values():
    assert approx(bl.student_t_two_sided(2.228, 10), 0.05)   # t_{0.025,10}
    assert approx(bl.student_t_two_sided(0.0, 10), 1.0)
    assert approx(bl.student_t_two_sided(-2.228, 10), 0.05)  # symmetric in sign
    assert approx(bl.student_t_two_sided(3.169, 10), 0.01)   # t_{0.005,10}


# ── Welch's t-test ──
def test_welch_identical_samples_high_p():
    t, df, p = bl.welch_ttest([0.90, 0.90, 0.91], [0.90, 0.91, 0.90])
    assert p > 0.5


def test_welch_clear_difference_low_p():
    res = bl.welch_ttest([0.30, 0.32, 0.31], [0.90, 0.92, 0.91])
    assert res is not None and res[2] < 0.01


def test_welch_undersized_returns_none():
    assert bl.welch_ttest([0.5], [0.5, 0.6]) is None


# ── regression verdicts ──
def test_assess_below_floor_fails_gate():
    v = bl.assess(current_trials=[0.4, 0.5], baseline=[], baseline_runs=0, floor=0.7)
    assert v.status == bl.BELOW_FLOOR and v.gate_fails


def test_assess_no_baseline_is_neutral():
    v = bl.assess(current_trials=[0.85, 0.9], baseline=[], baseline_runs=0, floor=0.7)
    assert v.status == bl.NO_BASELINE and not v.gate_fails


def test_assess_regression_fails_gate():
    v = bl.assess(current_trials=[0.72, 0.73, 0.71],
                  baseline=[0.90, 0.91, 0.92, 0.90], baseline_runs=4, floor=0.7)
    assert v.status == bl.REGRESSION and v.gate_fails


def test_assess_within_noise_passes():
    v = bl.assess(current_trials=[0.90, 0.89, 0.91],
                  baseline=[0.90, 0.91, 0.90, 0.89], baseline_runs=4, floor=0.7)
    assert v.status == bl.PASS and not v.gate_fails


def test_assess_improvement_is_neutral():
    v = bl.assess(current_trials=[0.95, 0.96, 0.97],
                  baseline=[0.80, 0.81, 0.79, 0.80], baseline_runs=4, floor=0.7)
    assert v.status == bl.IMPROVE and not v.gate_fails


def test_assess_no_score_when_rubric_skipped():
    v = bl.assess(current_trials=[], baseline=[], baseline_runs=0, floor=0.7)
    assert v.status == bl.NO_SCORE and not v.gate_fails


# ── trailing-baseline pooling ──
def test_trailing_scores_pools_recent_runs():
    history = [
        {"scenarios": [{"id": "a", "score": 0.8, "score_trials": [0.8, 0.82]}]},
        {"scenarios": [{"id": "a", "score": 0.9, "score_trials": [0.9, 0.91]}]},
        {"scenarios": [{"id": "b", "score": 0.5, "score_trials": [0.5]}]},
    ]
    pooled, n = bl.trailing_scores(history, "a", window=5)
    assert n == 2 and sorted(pooled) == [0.8, 0.82, 0.9, 0.91]
    assert bl.trailing_scores(history, "missing", window=5) == ([], 0)
