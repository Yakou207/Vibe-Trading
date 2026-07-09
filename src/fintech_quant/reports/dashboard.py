from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping


def build_research_dashboard(
    *,
    comparison: Mapping[str, object],
    walk_forward: Mapping[str, object] | None = None,
    paper_report: Mapping[str, object] | None = None,
) -> str:
    candidate = _mapping(comparison.get("candidate"))
    baseline = _mapping(comparison.get("baseline"))
    benchmark_rows = _benchmark_rows(_mapping(comparison.get("candidate_vs_benchmark")))
    walk_summary = _mapping((walk_forward or {}).get("summary")) if walk_forward else {}
    paper_nav = _mapping((paper_report or {}).get("nav")) if paper_report else {}
    paper_trades = paper_report.get("trades", []) if paper_report else []
    paper_blocked = paper_report.get("blocked_orders", []) if paper_report else []
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Daily Quant Monitor</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #17202a; background: #f6f8fb; }}
    header {{ padding: 24px 32px 12px; background: #ffffff; border-bottom: 1px solid #d9e2ec; }}
    main {{ padding: 24px 32px 40px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .meta {{ color: #5d6d7e; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .card {{ background: #ffffff; border: 1px solid #d9e2ec; border-radius: 8px; padding: 16px; }}
    .label {{ color: #5d6d7e; font-size: 13px; }}
    .value {{ margin-top: 8px; font-size: 24px; font-weight: 650; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d9e2ec; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #e7edf3; font-size: 14px; }}
    th {{ color: #334e68; background: #eef3f8; }}
  </style>
</head>
<body>
  <header>
    <h1>Daily Quant Monitor</h1>
    <div class="meta">Generated {html.escape(datetime.now().isoformat(timespec="seconds"))}</div>
  </header>
  <main>
    <section class="grid">
      {_card("Candidate Return", _fmt(candidate.get("total_return")))}
      {_card("Baseline Return", _fmt(baseline.get("total_return")))}
      {_card("Walk-Forward Windows", _fmt(walk_summary.get("window_count"), precision=0))}
      {_card("Paper NAV", _fmt(paper_nav.get("equity")))}
      {_card("Paper Trades", str(len(paper_trades) if isinstance(paper_trades, list) else 0))}
      {_card("Blocked Orders", str(len(paper_blocked) if isinstance(paper_blocked, list) else 0))}
    </section>
    <section class="card">
      <h2>Benchmark Relative Performance</h2>
      <table>
        <thead><tr><th>Benchmark</th><th>Excess Return</th><th>Tracking Max Drawdown</th></tr></thead>
        <tbody>{benchmark_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def write_dashboard(path: Path, html_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


def load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _card(label: str, value: str) -> str:
    return f'<div class="card"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div></div>'


def _benchmark_rows(metrics: Mapping[str, object]) -> str:
    rows = []
    for name, raw in sorted(metrics.items()):
        row = _mapping(raw)
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{html.escape(_fmt(row.get('excess_return')))}</td>"
            f"<td>{html.escape(_fmt(row.get('tracking_max_drawdown')))}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="3">No benchmark metrics available</td></tr>'


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _fmt(value: object, *, precision: int = 6) -> str:
    if value in (None, ""):
        return "n/a"
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return str(value)
