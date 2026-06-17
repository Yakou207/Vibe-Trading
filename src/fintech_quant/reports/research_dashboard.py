from __future__ import annotations

from html import escape
from typing import Any


def render_research_dashboard(
    strategy_report: dict[str, Any],
    factor_report: dict[str, Any],
    data_quality_report: dict[str, Any] | None = None,
) -> str:
    data_quality_report = data_quality_report or {}
    latest_window = _latest_window(strategy_report)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>Quant Research Dashboard</title>",
            "<style>",
            _styles(),
            "</style>",
            "</head>",
            "<body>",
            "<main>",
            "<h1>Quant Research Dashboard</h1>",
            '<p class="subtitle">A-share daily research view combining factor diagnostics and RL strategy outcomes.</p>',
            _coverage_section(data_quality_report, factor_report, strategy_report),
            _validation_section(strategy_report),
            _strategy_section(latest_window),
            _dqn_section(strategy_report, latest_window),
            _factor_section(factor_report),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _coverage_section(
    data_quality_report: dict[str, Any],
    factor_report: dict[str, Any],
    strategy_report: dict[str, Any],
) -> str:
    cards = [
        ("Symbols", data_quality_report.get("symbols", "n/a")),
        ("Rows", data_quality_report.get("rows", "n/a")),
        ("Date Range", f"{data_quality_report.get('date_min', 'n/a')} to {data_quality_report.get('date_max', 'n/a')}"),
        ("Factors", factor_report.get("factor_count", 0)),
        ("Walk-forward Windows", len(strategy_report.get("windows", []))),
    ]
    return f"""
<section>
  <h2>Data Coverage</h2>
  <div class="cards">{''.join(_card(label, value) for label, value in cards)}</div>
</section>
"""


def _strategy_section(window: dict[str, Any]) -> str:
    strategies = window.get("strategies", {})
    rows = []
    for name, metrics in strategies.items():
        rows.append(
            "<tr>"
            f"<td>{escape(str(name))}</td>"
            f"<td>{_pct(metrics.get('total_return'))}</td>"
            f"<td>{_number(metrics.get('sharpe_ratio'))}</td>"
            f"<td>{_pct(metrics.get('max_drawdown'))}</td>"
            f"<td>{escape(str(metrics.get('trade_count', 'n/a')))}</td>"
            "</tr>"
        )
    return f"""
<section>
  <h2>Strategy Comparison</h2>
  <p class="context">Latest window: {escape(str(window.get('window_name', 'n/a')))}</p>
  <table>
    <thead><tr><th>Strategy</th><th>Total Return</th><th>Sharpe</th><th>Max Drawdown</th><th>Trades</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
"""


def _validation_section(strategy_report: dict[str, Any]) -> str:
    validation_modes = strategy_report.get("validation_modes", {})
    mode_cards = [
        (mode, f"{len(windows)} windows")
        for mode, windows in validation_modes.items()
    ]
    controls = strategy_report.get("validation", {}).get("look_ahead_bias_controls", [])
    controls_html = "".join(f"<li>{escape(str(control))}</li>" for control in controls)
    if not controls_html:
        controls_html = "<li>No explicit look-ahead controls recorded.</li>"
    return f"""
<section>
  <h2>Validation Modes</h2>
  <div class="cards">{''.join(_card(str(mode), value) for mode, value in mode_cards)}</div>
  <h3>Look-ahead Controls</h3>
  <ul>{controls_html}</ul>
</section>
"""


def _dqn_section(strategy_report: dict[str, Any], window: dict[str, Any]) -> str:
    config = strategy_report.get("dqn", {})
    diagnostics = window.get("dqn_diagnostics", {})
    action_counts = diagnostics.get("decision_action_counts", {})
    feature_columns = diagnostics.get("feature_columns", [])
    cards = [
        ("Episodes", config.get("episodes", "n/a")),
        ("Epsilon", config.get("epsilon", "n/a")),
        ("Min Epsilon", config.get("min_epsilon", "n/a")),
        ("Decay", config.get("epsilon_decay", "n/a")),
        ("Training Steps", diagnostics.get("training_steps", "n/a")),
    ]
    return f"""
<section>
  <h2>DQN Training</h2>
  <div class="cards">{''.join(_card(label, value) for label, value in cards)}</div>
  <p class="context">Decision mix: buy {escape(str(action_counts.get('buy', 0)))}, hold {escape(str(action_counts.get('hold', 0)))}, sell {escape(str(action_counts.get('sell', 0)))}.</p>
  <p class="context">Feature count: {len(feature_columns)}</p>
</section>
"""


def _factor_section(factor_report: dict[str, Any]) -> str:
    top_rows = []
    for row in factor_report.get("top_abs_ic", []):
        top_rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('factor', '')))}</td>"
            f"<td>{escape(str(row.get('group', '')))}</td>"
            f"<td>{_number(row.get('ic'))}</td>"
            f"<td>{_number(row.get('rank_ic'))}</td>"
            f"<td>{_pct(row.get('coverage'))}</td>"
            "</tr>"
        )
    warnings = factor_report.get("warnings", [])
    warning_html = "".join(f"<li>{escape(str(warning))}</li>" for warning in warnings)
    if not warning_html:
        warning_html = "<li>No factor coverage warnings.</li>"
    return f"""
<section>
  <h2>Factor Diagnostics</h2>
  <table>
    <thead><tr><th>Factor</th><th>Group</th><th>IC</th><th>Rank IC</th><th>Coverage</th></tr></thead>
    <tbody>{''.join(top_rows)}</tbody>
  </table>
  <h3>Warnings</h3>
  <ul>{warning_html}</ul>
</section>
"""


def _latest_window(strategy_report: dict[str, Any]) -> dict[str, Any]:
    windows = strategy_report.get("windows", [])
    if not windows:
        return {}
    return windows[-1]


def _card(label: str, value: object) -> str:
    return (
        '<div class="card">'
        f'<div class="label">{escape(str(label))}</div>'
        f'<div class="value">{escape(str(value))}</div>'
        "</div>"
    )


def _number(value: object) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return escape(str(value))


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return escape(str(value))


def _styles() -> str:
    return """
:root { color-scheme: light; font-family: Arial, Helvetica, sans-serif; }
body { margin: 0; background: #f6f7f9; color: #1f2933; }
main { max-width: 1120px; margin: 0 auto; padding: 32px 20px 48px; }
h1 { margin: 0 0 6px; font-size: 32px; letter-spacing: 0; }
h2 { margin: 0 0 14px; font-size: 20px; letter-spacing: 0; }
h3 { margin: 16px 0 8px; font-size: 15px; letter-spacing: 0; }
.subtitle, .context { color: #52616f; }
section { margin-top: 24px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.card { background: white; border: 1px solid #d8dee6; border-radius: 8px; padding: 12px; }
.label { color: #687585; font-size: 12px; text-transform: uppercase; }
.value { margin-top: 6px; font-size: 20px; font-weight: 700; }
table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #d8dee6; }
th, td { padding: 10px 12px; border-bottom: 1px solid #e5e9ef; text-align: left; font-size: 14px; }
th { background: #eef2f6; color: #344150; }
ul { background: white; border: 1px solid #d8dee6; border-radius: 8px; padding: 12px 12px 12px 28px; }
"""
