from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fintech_quant.backtesting.metrics import calculate_equity_metrics


def build_dashboard_model(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root)
    outputs_dir = root / "outputs"
    processed_dir = root / "data" / "processed"

    strategy_path = outputs_dir / "strategy_comparison_report.json"
    baseline_path = outputs_dir / "baseline_backtest.json"
    data_quality_path = outputs_dir / "data_quality_report.json"
    factor_path = outputs_dir / "factor_diagnostics_report.json"
    features_path = processed_dir / "akshare_research_features.csv"

    strategy_rows = load_strategy_comparison(strategy_path) if strategy_path.exists() else []
    baseline = _load_json(baseline_path) if baseline_path.exists() else {}
    equity_curve = list(baseline.get("equity_curve", []))
    data_quality = _load_json(data_quality_path) if data_quality_path.exists() else {}
    factor_diagnostics = _load_json(factor_path) if factor_path.exists() else {}
    feature_summary = load_feature_summary(features_path) if features_path.exists() else {}

    equity_metrics = None
    if equity_curve:
        equity_metrics = calculate_equity_metrics(equity_curve).__dict__

    return {
        "source_status": {
            "strategy_comparison": _status(strategy_path),
            "baseline_backtest": _status(baseline_path),
            "data_quality": _status(data_quality_path),
            "factor_diagnostics": _status(factor_path),
            "features": _status(features_path),
        },
        "strategy_rows": strategy_rows,
        "equity_curve": equity_curve,
        "baseline_metrics": baseline.get("metrics", {}),
        "equity_metrics": equity_metrics,
        "data_quality": data_quality,
        "factor_diagnostics": factor_diagnostics,
        "feature_summary": feature_summary,
    }


def load_strategy_comparison(path: Path | str) -> list[dict[str, Any]]:
    payload = _load_json(Path(path))
    windows_by_mode = payload.get("validation_modes")
    if windows_by_mode is None:
        windows = payload.get("windows", [])
        windows_by_mode = {"default": windows}

    rows: list[dict[str, Any]] = []
    for mode, windows in windows_by_mode.items():
        for window in windows:
            validation_mode = window.get("validation_mode", mode)
            for strategy, metrics in window.get("strategies", {}).items():
                rows.append(
                    {
                        "validation_mode": validation_mode,
                        "window_name": window.get("window_name", ""),
                        "strategy": strategy,
                        "train_start": window.get("train_start", ""),
                        "train_end": window.get("train_end", ""),
                        "test_start": window.get("test_start", ""),
                        "test_end": window.get("test_end", ""),
                        "train_rows": window.get("train_rows", 0),
                        "test_rows": window.get("test_rows", 0),
                        "total_return": float(metrics.get("total_return", 0.0)),
                        "annualized_return": float(metrics.get("annualized_return", 0.0)),
                        "sharpe_ratio": float(metrics.get("sharpe_ratio", 0.0)),
                        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
                        "trade_count": int(metrics.get("trade_count", 0)),
                        "buy_count": int(metrics.get("buy_count", 0)),
                        "sell_count": int(metrics.get("sell_count", 0)),
                        "final_equity": float(metrics.get("final_equity", 0.0)),
                    }
                )
    return rows


def load_feature_summary(path: Path | str) -> dict[str, Any]:
    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    if not rows:
        return {"rows": 0, "symbols": 0, "date_min": "", "date_max": "", "columns": []}

    dates = [row["date"] for row in rows if row.get("date")]
    symbols = {row.get("代码", "") for row in rows if row.get("代码")}
    return {
        "rows": len(rows),
        "symbols": len(symbols),
        "date_min": min(dates) if dates else "",
        "date_max": max(dates) if dates else "",
        "columns": reader.fieldnames or [],
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _status(path: Path) -> str:
    return "ready" if path.exists() else "missing"
