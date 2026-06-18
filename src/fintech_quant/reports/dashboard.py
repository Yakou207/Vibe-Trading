from __future__ import annotations

from pathlib import Path
from typing import Any

from fintech_quant.reports.research_results import build_dashboard_model


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
        page_icon="chart",
        layout="wide",
    )

    project_root = Path.cwd()
    model = build_dashboard_model(project_root)

    st.title("Vibe Trading Research Dashboard")
    st.caption(
        "Daily A-share research dashboard for strategy comparison, risk review, "
        "PnL monitoring, and factor diagnostics."
    )

    _render_source_status(st, model["source_status"])

    strategy_rows = model["strategy_rows"]
    if not strategy_rows:
        st.warning("No strategy comparison rows found in outputs/strategy_comparison_report.json.")
        return

    strategy_frame = pd.DataFrame(strategy_rows)
    validation_modes = sorted(strategy_frame["validation_mode"].dropna().unique().tolist())
    selected_mode = st.sidebar.selectbox("Validation mode", validation_modes, index=0)
    selected_window = st.sidebar.selectbox(
        "Validation window",
        sorted(strategy_frame[strategy_frame["validation_mode"] == selected_mode]["window_name"].unique()),
        index=_window_index(strategy_rows, selected_mode),
    )

    visible = strategy_frame[
        (strategy_frame["validation_mode"] == selected_mode)
        & (strategy_frame["window_name"] == selected_window)
    ].copy()
    visible = visible.sort_values(["sharpe_ratio", "total_return"], ascending=False)

    _render_strategy_kpis(st, visible)
    _render_strategy_charts(st, px, visible, selected_mode, selected_window)
    _render_equity_curve(st, px, model["equity_curve"], model["equity_metrics"])
    _render_data_quality(st, model)
    _render_factor_diagnostics(st, pd, model["factor_diagnostics"])


def format_percent(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def select_latest_window(rows: list[dict[str, Any]], validation_mode: str) -> str:
    candidates = [row for row in rows if row.get("validation_mode") == validation_mode]
    if not candidates:
        return ""
    latest = max(candidates, key=lambda row: (str(row.get("test_end", "")), str(row.get("window_name", ""))))
    return str(latest.get("window_name", ""))


def _window_index(rows: list[dict[str, Any]], validation_mode: str) -> int:
    latest = select_latest_window(rows, validation_mode)
    windows = sorted({row["window_name"] for row in rows if row["validation_mode"] == validation_mode})
    if latest in windows:
        return windows.index(latest)
    return 0


def _render_source_status(st: Any, source_status: dict[str, str]) -> None:
    missing = [name for name, status in source_status.items() if status != "ready"]
    if missing:
        st.warning(f"Missing optional dashboard sources: {', '.join(missing)}")
    else:
        st.success("All local research result sources are available.")


def _render_strategy_kpis(st: Any, frame: Any) -> None:
    best_sharpe = frame.iloc[0]
    best_return = frame.sort_values("total_return", ascending=False).iloc[0]
    lowest_drawdown = frame.sort_values("max_drawdown", ascending=False).iloc[0]
    total_trades = int(frame["trade_count"].sum())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Best Sharpe", best_sharpe["strategy"], f"{best_sharpe['sharpe_ratio']:.3f}")
    col2.metric("Best Return", best_return["strategy"], format_percent(best_return["total_return"]))
    col3.metric(
        "Lowest MDD",
        lowest_drawdown["strategy"],
        format_percent(lowest_drawdown["max_drawdown"]),
    )
    col4.metric("Total Trades", f"{total_trades:,}")


def _render_strategy_charts(
    st: Any,
    px: Any,
    frame: Any,
    validation_mode: str,
    window_name: str,
) -> None:
    st.subheader(f"Strategy Comparison: {validation_mode} / {window_name}")

    col1, col2 = st.columns(2)
    return_chart = px.bar(
        frame,
        x="strategy",
        y="total_return",
        color="strategy",
        title="Total Return by Strategy",
        labels={"total_return": "Total return", "strategy": "Strategy"},
    )
    return_chart.update_layout(showlegend=False)
    col1.plotly_chart(return_chart, use_container_width=True)

    risk_chart = px.scatter(
        frame,
        x="max_drawdown",
        y="sharpe_ratio",
        size="trade_count",
        color="strategy",
        hover_data=["total_return", "annualized_return", "final_equity"],
        title="Risk/Return Map",
        labels={"max_drawdown": "Max drawdown", "sharpe_ratio": "Sharpe ratio"},
    )
    col2.plotly_chart(risk_chart, use_container_width=True)

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
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_equity_curve(
    st: Any,
    px: Any,
    equity_curve: list[dict[str, Any]],
    equity_metrics: dict[str, Any] | None,
) -> None:
    st.subheader("Baseline PnL / Equity Curve")
    if not equity_curve:
        st.info("No baseline equity curve found in outputs/baseline_backtest.json.")
        return

    chart = px.line(
        equity_curve,
        x="date",
        y="equity",
        title="Baseline Equity Curve",
        labels={"date": "Date", "equity": "Equity"},
    )
    st.plotly_chart(chart, use_container_width=True)

    if equity_metrics:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Baseline Return", format_percent(equity_metrics["total_return"]))
        col2.metric("Baseline Sharpe", f"{equity_metrics['sharpe_ratio']:.3f}")
        col3.metric("Baseline MDD", format_percent(equity_metrics["max_drawdown"]))
        col4.metric("Observations", f"{equity_metrics['observations']:,}")


def _render_data_quality(st: Any, model: dict[str, Any]) -> None:
    st.subheader("Data Quality and Coverage")
    data_quality = model["data_quality"]
    feature_summary = model["feature_summary"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Rows", f"{int(data_quality.get('rows', feature_summary.get('rows', 0))):,}")
    col2.metric("Symbols", f"{int(data_quality.get('symbols', feature_summary.get('symbols', 0))):,}")
    col3.metric("Date Min", data_quality.get("date_min", feature_summary.get("date_min", "n/a")))
    col4.metric("Date Max", data_quality.get("date_max", feature_summary.get("date_max", "n/a")))

    if data_quality:
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
    st.subheader("Factor Diagnostics")
    top_abs_ic = factor_diagnostics.get("top_abs_ic", [])
    if top_abs_ic:
        st.dataframe(pd.DataFrame(top_abs_ic), use_container_width=True, hide_index=True)
    else:
        st.info("No factor diagnostics found in outputs/factor_diagnostics_report.json.")

    warnings = factor_diagnostics.get("warnings", [])
    if warnings:
        st.warning("\n".join(str(item) for item in warnings))


if __name__ == "__main__":
    main()
