"""Self-contained HTML trend dashboard for the behavioral evals.

Renders score-over-runs sparklines + the latest run's verdict per scenario from
``history.jsonl`` — no server, no external assets (works offline, opens from disk).
"""
from __future__ import annotations

import html
import pathlib
import statistics

from baseline import (BELOW_FLOOR, IMPROVE, NO_BASELINE, NO_SCORE, PASS,
                      REGRESSION, Verdict)

_COLORS = {
    REGRESSION: "#c0392b", BELOW_FLOOR: "#c0392b", IMPROVE: "#1e8e3e",
    PASS: "#555", NO_BASELINE: "#2563eb", NO_SCORE: "#888",
}
_ICON = {
    REGRESSION: "🔴", BELOW_FLOOR: "🔴", IMPROVE: "🟢",
    PASS: "⚪", NO_BASELINE: "🔵", NO_SCORE: "⚪",
}


def _scenario_series(history: list[dict], scenario_id: str) -> list[float | None]:
    series: list[float | None] = []
    for rec in history:
        sc = next((s for s in rec.get("scenarios", []) if s.get("id") == scenario_id), None)
        series.append(None if not sc or sc.get("score") is None else float(sc["score"]))
    return series


def _sparkline(scores: list[float | None], floor: float) -> str:
    pts = [(i, v) for i, v in enumerate(scores) if v is not None]
    if not pts:
        return '<span class="muted">no scores yet</span>'
    W, H, pad = 240, 48, 5
    n = max(len(scores) - 1, 1)

    def x(i: int) -> float:
        return round(i / n * (W - 2 * pad) + pad, 1)

    def y(v: float) -> float:
        return round((1 - v) * (H - 2 * pad) + pad, 1)

    poly = " ".join(f"{x(i)},{y(v)}" for i, v in pts)
    dots = "".join(f'<circle cx="{x(i)}" cy="{y(v)}" r="2.3" fill="#2563eb"/>' for i, v in pts)
    fy = y(floor)
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="score trend">'
        f'<line x1="{pad}" y1="{fy}" x2="{W - pad}" y2="{fy}" stroke="#c0392b" '
        f'stroke-dasharray="3 3" stroke-width="1"/>'
        f'<polyline points="{poly}" fill="none" stroke="#2563eb" stroke-width="1.6"/>'
        f'{dots}</svg>'
    )


def _card(rec_sc: dict, verdict: Verdict, series: list[float | None], floor: float) -> str:
    sid = html.escape(rec_sc["id"])
    color = _COLORS.get(verdict.status, "#555")
    icon = _ICON.get(verdict.status, "⚪")
    cur = "—" if verdict.current is None else f"{verdict.current:.2f}"
    base = "—" if verdict.baseline is None else f"{verdict.baseline:.2f}"
    delta = "—" if verdict.delta is None else f"{verdict.delta:+.2f}"
    p = "—" if verdict.p_value is None else f"{verdict.p_value:.3f}"
    det = f'{rec_sc.get("deterministic_passes", 0)}/{rec_sc.get("trials", 0)}'
    tools = rec_sc.get("tool_calls") or []
    avg_tools = f"{statistics.mean(tools):.1f}" if tools else "—"
    reason = html.escape((rec_sc.get("reasons") or [""])[0])[:600]
    status_label = html.escape(verdict.status.replace("_", " "))
    detail = html.escape(verdict.detail)
    return f"""
    <section class="card">
      <header><h2>{sid}</h2>
        <span class="badge" style="background:{color}">{icon} {status_label}</span></header>
      <div class="row">
        <div class="spark">{_sparkline(series, floor)}<div class="muted">score / run · dashed = floor {floor:.2f}</div></div>
        <table class="kv">
          <tr><th>current</th><td><b>{cur}</b></td><th>baseline</th><td>{base}</td></tr>
          <tr><th>Δ</th><td>{delta}</td><th>p-value</th><td>{p}</td></tr>
          <tr><th>board pass</th><td>{det}</td><th>avg tool calls</th><td>{avg_tools}</td></tr>
        </table>
      </div>
      <p class="detail">{detail}</p>
      {f'<details><summary>judge reasoning</summary><p class="reason">{reason}</p></details>' if reason else ''}
    </section>"""


def render(history: list[dict], verdicts: dict[str, Verdict], *, floor: float,
           out_path: pathlib.Path) -> pathlib.Path:
    latest = history[-1] if history else {"scenarios": [], "git": {}, "timestamp": "—",
                                          "judge": None, "trials": 0}
    gate_fail = any(v.gate_fails for v in verdicts.values()) or any(
        not s.get("deterministic_pass") for s in latest.get("scenarios", []))
    g = latest.get("git", {})
    sha = html.escape(str(g.get("sha", "—")))
    branch = html.escape(str(g.get("branch", "—")))
    dirty = " (dirty)" if g.get("dirty") else ""
    judge = html.escape(str(latest.get("judge") or "none — board-state only"))
    banner_color = "#c0392b" if gate_fail else "#1e8e3e"
    banner_text = "REGRESSION / FAILURE" if gate_fail else "ALL GATES PASSED"

    cards = "".join(
        _card(sc, verdicts.get(sc["id"], Verdict(NO_SCORE, None, None, None, None, 0, "")),
              _scenario_series(history, sc["id"]), floor)
        for sc in latest.get("scenarios", [])
    )

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Squad skills — behavioral eval trends</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 0; padding: 24px;
          max-width: 980px; margin-inline: auto; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: #888; margin-bottom: 16px; }}
  .banner {{ color: #fff; padding: 10px 16px; border-radius: 8px; font-weight: 600;
             margin-bottom: 20px; }}
  .card {{ border: 1px solid #8883; border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; }}
  .card header {{ display: flex; align-items: center; justify-content: space-between; }}
  .card h2 {{ font-size: 16px; margin: 0; font-family: ui-monospace, monospace; }}
  .badge {{ color: #fff; padding: 2px 10px; border-radius: 999px; font-size: 12px; }}
  .row {{ display: flex; gap: 24px; align-items: center; flex-wrap: wrap; margin-top: 10px; }}
  .kv {{ border-collapse: collapse; }}
  .kv th {{ text-align: right; color: #888; font-weight: 500; padding: 2px 8px; }}
  .kv td {{ padding: 2px 16px 2px 0; font-variant-numeric: tabular-nums; }}
  .muted {{ color: #999; font-size: 11px; }}
  .detail {{ color: #777; font-size: 13px; margin: 8px 0 4px; }}
  .reason {{ color: #666; font-size: 12px; white-space: pre-wrap; }}
  details summary {{ cursor: pointer; color: #2563eb; font-size: 12px; }}
</style></head><body>
<h1>Squad skills — behavioral eval trends</h1>
<div class="sub">{html.escape(latest.get("timestamp", "—"))} · {sha} on {branch}{dirty} ·
  {len(history)} run(s) · judge: {judge}</div>
<div class="banner" style="background:{banner_color}">{banner_text}</div>
{cards or '<p class="muted">No runs recorded yet.</p>'}
</body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
