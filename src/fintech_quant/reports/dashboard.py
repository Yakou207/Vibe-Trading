from __future__ import annotations

from pathlib import Path
from typing import Any

from fintech_quant.reports.research_results import DashboardDataSource


def main() -> None:
    try:
        import pandas as pd
        import plotly.express as px
        import streamlit as st
    except ModuleNotFoundError as exc:
        missing = exc.name or "dashboard dependency"
        raise SystemExit(
            f"Missing {missing}. Install dashboard dependencies with: "
            "python -m pip install -e '.[dashboard]'"
        ) from exc

    st.set_page_config(
        page_title="Vibe Trading Research Dashboard",
        layout="wide",
    )
    _apply_theme(st)

    project_root = Path.cwd()
    if st.sidebar.button("Reload research files", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    load_dashboard_model = st.cache_data(show_spinner=False)(_load_dashboard_model)
    model = load_dashboard_model(str(project_root))
    config = model["config"]

    st.title("Vibe Trading Research Dashboard")
    st.caption(
        f"{config['market']} | {config['frequency']} | {config['execution_mode']} | "
        "research performance cockpit"
    )

    _render_source_status(st, model["source_status"])

    strategy_rows = model["strategy_rows"]
    if not strategy_rows:
        st.warning("No strategy comparison rows found. Generate backtest outputs first.")
        _render_data_ops(st, model)
        return

    strategy_frame = pd.DataFrame(strategy_rows)
    selected_mode, selected_window = _render_sidebar_controls(st, strategy_frame)
    visible = _visible_strategy_frame(strategy_frame, selected_mode, selected_window)
    recommendation = strategy_recommendation(visible.to_dict("records"))

    _render_decision_header(st, visible, recommendation, selected_mode, selected_window)

    overview_tab, pnl_tab, strategy_tab, factors_tab, data_tab = st.tabs(
        ["Overview", "PnL", "Strategy Lab", "Factors", "Data Ops"]
    )
    with overview_tab:
        _render_overview(st, px, visible)
    with pnl_tab:
        _render_equity_curve(st, px, model["equity_curve"], model["equity_metrics"])
    with strategy_tab:
        _render_strategy_lab(st, px, visible, strategy_frame)
    with factors_tab:
        _render_factor_diagnostics(st, pd, model["factor_diagnostics"])
    with data_tab:
        _render_data_ops(st, model)


def format_percent(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def select_latest_window(rows: list[dict[str, Any]], validation_mode: str) -> str:
    candidates = [row for row in rows if row.get("validation_mode") == validation_mode]
    if not candidates:
        return ""
    latest = max(
        candidates,
        key=lambda row: (str(row.get("test_end", "")), str(row.get("window_name", ""))),
    )
    return str(latest.get("window_name", ""))


def strategy_recommendation(rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {
            "strategy": "n/a",
            "risk_status": "No data",
            "reason": "No strategy rows selected.",
        }

    ranked = sorted(
        rows,
        key=lambda row: (
            float(row.get("sharpe_ratio", 0.0)),
            float(row.get("total_return", 0.0)),
            float(row.get("max_drawdown", 0.0)),
        ),
        reverse=True,
    )
    leader = ranked[0]
    drawdown = float(leader.get("max_drawdown", 0.0))
    risk_status = "Researchable"
    if drawdown <= -0.2:
        risk_status = "Needs risk work"
    elif drawdown <= -0.1:
        risk_status = "Watch drawdown"

    return {
        "strategy": str(leader.get("strategy", "")),
        "risk_status": risk_status,
        "reason": "Top risk-adjusted candidate by Sharpe, then return, then drawdown.",
    }


def _window_index(rows: list[dict[str, Any]], validation_mode: str) -> int:
    latest = select_latest_window(rows, validation_mode)
    windows = sorted(
        {row["window_name"] for row in rows if row["validation_mode"] == validation_mode}
    )
    if latest in windows:
        return windows.index(latest)
    return 0


def _render_sidebar_controls(st: Any, strategy_frame: Any) -> tuple[str, str]:
    st.sidebar.header("Research Slice")
    validation_modes = sorted(strategy_frame["validation_mode"].dropna().unique().tolist())
    selected_mode = st.sidebar.radio("Validation mode", validation_modes, horizontal=True)
    windows = sorted(
        strategy_frame[strategy_frame["validation_mode"] == selected_mode]["window_name"].unique()
    )
    selected_window = st.sidebar.selectbox(
        "Window",
        windows,
        index=_window_index(strategy_frame.to_dict("records"), selected_mode),
    )
    selected = strategy_frame[
        (strategy_frame["validation_mode"] == selected_mode)
        & (strategy_frame["window_name"] == selected_window)
    ]
    test_start = selected["test_start"].iloc[0]
    test_end = selected["test_end"].iloc[0]
    st.sidebar.caption(f"Showing out-of-sample period {test_start} to {test_end}.")
    return selected_mode, selected_window


def _visible_strategy_frame(strategy_frame: Any, selected_mode: str, selected_window: str) -> Any:
    visible = strategy_frame[
        (strategy_frame["validation_mode"] == selected_mode)
        & (strategy_frame["window_name"] == selected_window)
    ].copy()
    return visible.sort_values(["sharpe_ratio", "total_return"], ascending=False)


def _render_decision_header(
    st: Any,
    frame: Any,
    recommendation: dict[str, str],
    selected_mode: str,
    selected_window: str,
) -> None:
    best_return = frame.sort_values("total_return", ascending=False).iloc[0]
    safest = frame.sort_values("max_drawdown", ascending=False).iloc[0]
    total_trades = int(frame["trade_count"].sum())

    col1, col2, col3, col4 = st.columns([1.4, 1, 1, 1])
    col1.metric("Research candidate", recommendation["strategy"], recommendation["risk_status"])
    col2.metric("Best return", best_return["strategy"], format_percent(best_return["total_return"]))
    col3.metric("Lowest MDD", safest["strategy"], format_percent(safest["max_drawdown"]))
    col4.metric("Trades in slice", f"{total_trades:,}")
    st.info(
        f"{selected_mode} / {selected_window}: {recommendation['reason']} "
        "Use this as a research shortlist, not a live-trading approval."
    )


def _render_overview(st: Any, px: Any, frame: Any) -> None:
    st.subheader("Strategy scoreboard")
    col1, col2 = st.columns(2)

    return_chart = px.bar(
        frame,
        x="strategy",
        y="total_return",
        color="strategy",
        title="Total return",
        labels={"total_return": "Total return", "strategy": "Strategy"},
        text=frame["total_return"].map(lambda value: format_percent(value)),
    )
    return_chart.update_layout(showlegend=False, yaxis_tickformat=".0%")
    col1.plotly_chart(return_chart, width="stretch")

    risk_chart = px.scatter(
        frame,
        x="max_drawdown",
        y="sharpe_ratio",
        size="trade_count",
        color="strategy",
        hover_data=["total_return", "annualized_return", "final_equity"],
        title="Risk-adjusted map",
        labels={"max_drawdown": "Max drawdown", "sharpe_ratio": "Sharpe"},
    )
    risk_chart.update_layout(xaxis_tickformat=".0%")
    col2.plotly_chart(risk_chart, width="stretch")

    display = frame[
        [
            "strategy",
            "total_return",
            "annualized_return",
            "sharpe_ratio",
            "max_drawdown",
            "trade_count",
            "buy_count",
            "sell_count",
            "final_equity",
        ]
    ].copy()
    display["total_return"] = display["total_return"].map(format_percent)
    display["annualized_return"] = display["annualized_return"].map(format_percent)
    display["max_drawdown"] = display["max_drawdown"].map(format_percent)
    st.dataframe(display, width="stretch", hide_index=True)


def _render_equity_curve(
    st: Any,
    px: Any,
    equity_curve: list[dict[str, Any]],
    equity_metrics: dict[str, Any] | None,
) -> None:
    st.subheader("PnL and drawdown")
    if not equity_curve:
        st.info("No baseline equity curve found in outputs/baseline_backtest.json.")
        return

    chart = px.line(
        equity_curve,
        x="date",
        y="equity",
        title="Baseline equity curve",
        labels={"date": "Date", "equity": "Equity"},
    )
    st.plotly_chart(chart, width="stretch")

    if any("drawdown" in row for row in equity_curve):
        drawdown_chart = px.area(
            equity_curve,
            x="date",
            y="drawdown",
            title="Baseline drawdown",
            labels={"date": "Date", "drawdown": "Drawdown"},
        )
        drawdown_chart.update_layout(yaxis_tickformat=".0%")
        st.plotly_chart(drawdown_chart, width="stretch")

    if equity_metrics:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Baseline return", format_percent(equity_metrics["total_return"]))
        col2.metric("Baseline Sharpe", f"{equity_metrics['sharpe_ratio']:.3f}")
        col3.metric("Baseline MDD", format_percent(equity_metrics["max_drawdown"]))
        col4.metric("Observations", f"{equity_metrics['observations']:,}")


def _render_strategy_lab(st: Any, px: Any, visible: Any, strategy_frame: Any) -> None:
    st.subheader("Strategy lab")
    selected_strategy = st.selectbox("Inspect strategy", visible["strategy"].tolist())
    strategy_history = strategy_frame[strategy_frame["strategy"] == selected_strategy].sort_values(
        "test_end"
    )
    history_chart = px.line(
        strategy_history,
        x="test_end",
        y="total_return",
        color="validation_mode",
        markers=True,
        title=f"{selected_strategy} walk-forward returns",
        labels={"test_end": "Test end", "total_return": "Total return"},
    )
    history_chart.update_layout(yaxis_tickformat=".0%")
    st.plotly_chart(history_chart, width="stretch")

    latest = visible[visible["strategy"] == selected_strategy].iloc[0].to_dict()
    st.json(
        {
            "strategy": latest.get("strategy"),
            "sharpe_ratio": latest.get("sharpe_ratio"),
            "total_return": latest.get("total_return"),
            "max_drawdown": latest.get("max_drawdown"),
            "trade_count": latest.get("trade_count"),
            "train_window": f"{latest.get('train_start')} to {latest.get('train_end')}",
            "test_window": f"{latest.get('test_start')} to {latest.get('test_end')}",
        }
    )


def _render_data_ops(st: Any, model: dict[str, Any]) -> None:
    st.subheader("Data operations")
    data_quality = model["data_quality"]
    feature_summary = model["feature_summary"]

    col1, col2, col3, col4 = st.columns(4)
    row_count = int(data_quality.get("rows", feature_summary.get("rows", 0)))
    symbol_count = int(data_quality.get("symbols", feature_summary.get("symbols", 0)))
    col1.metric("Rows", f"{row_count:,}")
    col2.metric("Symbols", f"{symbol_count:,}")
    col3.metric("Date min", data_quality.get("date_min", feature_summary.get("date_min", "n/a")))
    col4.metric("Date max", data_quality.get("date_max", feature_summary.get("date_max", "n/a")))

    status_rows = [
        {"source": source, "status": status, "path": model["source_paths"].get(source, "")}
        for source, status in model["source_status"].items()
    ]
    st.dataframe(status_rows, width="stretch", hide_index=True)

    st.json(
        {
            "passes_core_checks": data_quality.get("passes_core_checks"),
            "duplicate_symbol_dates": data_quality.get("duplicate_symbol_dates"),
            "missing_required_values": data_quality.get("missing_required_values"),
            "ohlc_violations": data_quality.get("ohlc_violations"),
            "negative_volume_rows": data_quality.get("negative_volume_rows"),
        }
    )


def _render_factor_diagnostics(st: Any, pd: Any, factor_diagnostics: dict[str, Any]) -> None:
    st.subheader("Factor diagnostics")
    top_abs_ic = factor_diagnostics.get("top_abs_ic", [])
    if top_abs_ic:
        st.dataframe(pd.DataFrame(top_abs_ic), width="stretch", hide_index=True)
    else:
        st.info("No factor diagnostics found in outputs/factor_diagnostics_report.json.")

    warnings = factor_diagnostics.get("warnings", [])
    if warnings:
        st.warning("\n".join(str(item) for item in warnings))


def _render_source_status(st: Any, source_status: dict[str, str]) -> None:
    missing = [name for name, status in source_status.items() if status != "ready"]
    if missing:
        st.warning(f"Missing optional dashboard sources: {', '.join(missing)}")
    else:
        st.success("All local research result sources are available.")


def _apply_theme(st: Any) -> None:
    st.markdown(
        """
        <style>
        .block-container {
          padding-top: 1.5rem;
          padding-bottom: 2rem;
          max-width: 1360px;
        }
        [data-testid="stMetric"] {
          border: 1px solid #dde3ea;
          border-radius: 8px;
          padding: 0.7rem 0.85rem;
          background: #ffffff;
        }
        [data-testid="stMetricLabel"] {
          color: #566371;
        }
        div[data-testid="stInfo"] {
          border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _load_dashboard_model(project_root: str) -> dict[str, Any]:
    return DashboardDataSource(Path(project_root)).load()


if __name__ == "__main__":
    main()
