"""Regression detection vs a trailing baseline computed from history.jsonl.

Best practice (2026) for catching eval drift on a small golden set:
  * per-scenario **absolute floor** (hard gate — score must clear it), plus
  * a **delta gate** using **Welch's unequal-variance t-test** against the trailing-N
    baseline, so a statistically-significant drop fails even when it's still above the
    floor — while run-to-run noise does not.

Pure-Python statistics (Student-t survival function via the regularized incomplete beta);
no scipy/numpy dependency.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

# Verdict statuses (gate fails on BELOW_FLOOR or REGRESSION).
PASS = "pass"               # within noise of baseline (or first clearing run)
IMPROVE = "improve"         # significant improvement vs baseline
REGRESSION = "regression"   # significant drop vs baseline
BELOW_FLOOR = "below_floor"  # below the absolute per-scenario floor
NO_BASELINE = "no_baseline"  # nothing to compare against yet
NO_SCORE = "no_score"        # rubric skipped (no judge) — only board-state gated


# ── pure-Python Student-t two-sided p-value (Numerical Recipes incomplete beta) ──
def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_two_sided(t: float, df: float) -> float:
    """Two-sided p-value for a Student-t statistic via the incomplete beta function."""
    return betai(df / 2.0, 0.5, df / (df + t * t))


def welch_ttest(a: list[float], b: list[float]) -> tuple[float, float, float] | None:
    """Welch's t-test for two samples. Returns (t, df, two_sided_p) or None if undersized."""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    na, nb = len(a), len(b)
    se2 = va / na + vb / nb
    if se2 == 0.0:
        return (0.0, float(na + nb - 2), 1.0)
    t = (ma - mb) / math.sqrt(se2)
    df = se2 ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return (t, df, student_t_two_sided(t, df))


@dataclass
class Verdict:
    status: str
    current: float | None
    baseline: float | None
    delta: float | None
    p_value: float | None
    baseline_runs: int
    detail: str

    @property
    def gate_fails(self) -> bool:
        return self.status in (REGRESSION, BELOW_FLOOR)


def trailing_scores(history: list[dict], scenario_id: str, window: int,
                    exclude_last: bool = False) -> tuple[list[float], int]:
    """Pool per-trial scores for ``scenario_id`` from the most recent ``window`` runs.

    Returns (pooled_scores, n_runs). Only runs that produced a score count.
    """
    runs = list(history)
    if exclude_last and runs:
        runs = runs[:-1]
    pooled: list[float] = []
    n = 0
    for rec in reversed(runs):
        if n >= window:
            break
        sc = next((s for s in rec.get("scenarios", []) if s.get("id") == scenario_id), None)
        if not sc or sc.get("score") is None:
            continue
        trials = sc.get("score_trials") or [sc["score"]]
        pooled.extend(float(x) for x in trials)
        n += 1
    return pooled, n


def assess(*, current_trials: list[float], baseline: list[float], baseline_runs: int,
           floor: float, alpha: float = 0.05, min_effect: float = 0.05) -> Verdict:
    """Classify the current scenario score vs its trailing baseline."""
    if not current_trials:
        return Verdict(NO_SCORE, None, None, None, None, baseline_runs,
                       "rubric skipped (no judge) — board-state checks still gated")

    cur = statistics.mean(current_trials)
    if cur < floor:
        return Verdict(BELOW_FLOOR, cur, None, None, None, baseline_runs,
                       f"mean {cur:.2f} < floor {floor:.2f}")

    if baseline_runs == 0:
        return Verdict(NO_BASELINE, cur, None, None, None, 0,
                       "no prior runs — establishing baseline")

    base = statistics.mean(baseline)
    delta = cur - base
    test = welch_ttest(current_trials, baseline)
    p = test[2] if test else None
    significant = p is not None and p < alpha

    if delta <= -min_effect and significant:
        return Verdict(REGRESSION, cur, base, delta, p, baseline_runs,
                       f"drop {delta:+.2f} vs baseline {base:.2f} (p={p:.3f})")
    if delta >= min_effect and significant:
        return Verdict(IMPROVE, cur, base, delta, p, baseline_runs,
                       f"gain {delta:+.2f} vs baseline {base:.2f} (p={p:.3f})")
    return Verdict(PASS, cur, base, delta, p, baseline_runs,
                   f"within noise of baseline {base:.2f} (Δ{delta:+.2f})")
