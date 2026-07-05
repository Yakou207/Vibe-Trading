from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from fintech_quant.backtesting import EquityPoint, calculate_drawdown


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PerformanceSummary:
    name: str
    initial_equity: float
    ending_equity: float
    total_return: float
    annualized_return: float
    sharpe: float
    max_drawdown: float
    trade_count: int
    win_rate: float


@dataclass(frozen=True)
class StrategyComparison:
    baseline: PerformanceSummary
    candidate: PerformanceSummary
    excess_return: float
    walk_forward: list[dict[str, float | int | str]]


def compare_strategy_reports(
    baseline_report: Mapping[str, object],
    candidate_report: Mapping[str, object],
    *,
    walk_forward_segments: int = 4,
    align_to_candidate: bool = False,
) -> StrategyComparison:
    if align_to_candidate:
        baseline_report = _align_report_to_candidate_dates(baseline_report, candidate_report)
    baseline_curve = _equity_curve(baseline_report)
    candidate_curve = _equity_curve(candidate_report)
    _require_matching_dates(baseline_curve, candidate_curve)
    baseline = summarize_report(baseline_report)
    candidate = summarize_report(candidate_report)
    return StrategyComparison(
        baseline=baseline,
        candidate=candidate,
        excess_return=round(candidate.total_return - baseline.total_return, 6),
        walk_forward=_walk_forward(baseline_curve, candidate_curve, walk_forward_segments),
    )


def _align_report_to_candidate_dates(
    baseline_report: Mapping[str, object],
    candidate_report: Mapping[str, object],
) -> dict[str, object]:
    baseline_dates = {point["trade_date"] for point in _equity_curve(baseline_report)}
    candidate_dates = [point["trade_date"] for point in _equity_curve(candidate_report)]
    missing_dates = [trade_date for trade_date in candidate_dates if trade_date not in baseline_dates]
    if missing_dates:
        raise ValueError("baseline report is missing candidate equity dates")
    candidate_date_set = set(candidate_dates)
    aligned = dict(baseline_report)
    raw_curve = baseline_report.get("equity_curve")
    if not isinstance(raw_curve, list):
        raise ValueError("report must contain a non-empty equity_curve")
    aligned["equity_curve"] = [
        point for point in raw_curve if _parse_date(point["trade_date"]) in candidate_date_set
    ]
    aligned_trades = _align_trades_to_dates(baseline_report.get("trades"), candidate_date_set)
    aligned["trades"] = aligned_trades
    summary = dict(_summary(aligned))
    summary["trade_count"] = len(aligned_trades)
    summary["win_rate"] = _win_rate_from_realized_pnl(aligned_trades)
    aligned["summary"] = summary
    return aligned


def summarize_report(report: Mapping[str, object]) -> PerformanceSummary:
    curve = _equity_curve(report)
    summary = _summary(report)
    _require_summary_fields(summary, ("trade_count", "win_rate"))
    returns = _daily_returns(curve)
    drawdown = calculate_drawdown([EquityPoint(point["trade_date"], point["equity"]) for point in curve])
    initial = curve[0]["equity"]
    ending = curve[-1]["equity"]
    total_return = (ending - initial) / initial if initial else 0.0
    return PerformanceSummary(
        name=str(report.get("run_id", "unknown")),
        initial_equity=round(initial, 6),
        ending_equity=round(ending, 6),
        total_return=round(total_return, 6),
        annualized_return=_annualized_return(initial, ending, len(curve) - 1),
        sharpe=_sharpe(returns),
        max_drawdown=round(drawdown.max_drawdown, 6),
        trade_count=int(summary["trade_count"]),
        win_rate=round(float(summary["win_rate"]), 6),
    )


def write_comparison_report(path: Path, comparison: StrategyComparison) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_comparison_to_json(comparison), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _equity_curve(report: Mapping[str, object]) -> list[dict[str, object]]:
    raw_curve = report.get("equity_curve")
    if not isinstance(raw_curve, list) or not raw_curve:
        raise ValueError("report must contain a non-empty equity_curve")
    curve = [
        {
            "trade_date": _parse_date(point["trade_date"]),
            "equity": float(point["equity"]),
        }
        for point in raw_curve
    ]
    return sorted(curve, key=lambda point: point["trade_date"])


def _summary(report: Mapping[str, object]) -> Mapping[str, object]:
    raw_summary = report.get("summary", {})
    if not isinstance(raw_summary, Mapping):
        raise ValueError("report summary must be an object")
    return raw_summary


def _align_trades_to_dates(
    raw_trades: object,
    trade_dates: set[date],
) -> list[Mapping[str, object]]:
    if not isinstance(raw_trades, list):
        raise ValueError("baseline report trades are required when aligning to candidate dates")
    aligned: list[Mapping[str, object]] = []
    for trade in raw_trades:
        if not isinstance(trade, Mapping):
            raise ValueError("report trades must contain objects")
        if "trade_date" not in trade:
            raise ValueError("report trades must contain trade_date")
        if _parse_date(trade["trade_date"]) in trade_dates:
            aligned.append(trade)
    return aligned


def _win_rate_from_realized_pnl(trades: Sequence[Mapping[str, object]]) -> float:
    pnl_values: list[float] = []
    for trade in trades:
        for field in ("realized_pnl", "pnl", "profit"):
            if field in trade:
                pnl_values.append(float(trade[field]))
                break
    if not pnl_values:
        return 0.0
    return round(sum(1 for value in pnl_values if value > 0) / len(pnl_values), 6)


def _require_summary_fields(summary: Mapping[str, object], fields: Sequence[str]) -> None:
    missing = [field for field in fields if field not in summary]
    if missing:
        raise ValueError(f"report summary is missing required fields: {', '.join(missing)}")


def _require_matching_dates(
    baseline_curve: Sequence[Mapping[str, object]],
    candidate_curve: Sequence[Mapping[str, object]],
) -> None:
    baseline_dates = [point["trade_date"] for point in baseline_curve]
    candidate_dates = [point["trade_date"] for point in candidate_curve]
    if baseline_dates != candidate_dates:
        raise ValueError("baseline and candidate equity curves must use matching dates")


def _daily_returns(curve: Sequence[Mapping[str, object]]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(curve, curve[1:], strict=False):
        previous_equity = float(previous["equity"])
        current_equity = float(current["equity"])
        returns.append((current_equity - previous_equity) / previous_equity if previous_equity else 0.0)
    return returns


def _annualized_return(initial: float, ending: float, periods: int) -> float:
    if initial <= 0 or ending <= 0 or periods <= 0:
        return 0.0
    return round((ending / initial) ** (TRADING_DAYS_PER_YEAR / periods) - 1.0, 6)


def _sharpe(returns: Sequence[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return 0.0
    return round((mean / std_dev) * math.sqrt(TRADING_DAYS_PER_YEAR), 6)


def _walk_forward(
    baseline_curve: Sequence[Mapping[str, object]],
    candidate_curve: Sequence[Mapping[str, object]],
    segments: int,
) -> list[dict[str, float | int | str]]:
    if segments <= 0:
        raise ValueError("walk_forward_segments must be positive")
    interval_count = len(baseline_curve) - 1
    if interval_count <= 0:
        return []
    actual_segments = min(segments, interval_count)
    rows: list[dict[str, float | int | str]] = []
    for index in range(actual_segments):
        start = round(index * interval_count / actual_segments)
        end = round((index + 1) * interval_count / actual_segments)
        baseline_return = _segment_return(baseline_curve, start, end)
        candidate_return = _segment_return(candidate_curve, start, end)
        rows.append(
            {
                "segment": index + 1,
                "start_date": baseline_curve[start]["trade_date"].isoformat(),
                "end_date": baseline_curve[end]["trade_date"].isoformat(),
                "baseline_return": baseline_return,
                "candidate_return": candidate_return,
                "excess_return": round(candidate_return - baseline_return, 6),
            }
        )
    return rows


def _segment_return(curve: Sequence[Mapping[str, object]], start: int, end: int) -> float:
    start_equity = float(curve[start]["equity"])
    end_equity = float(curve[end]["equity"])
    return round((end_equity - start_equity) / start_equity, 6) if start_equity else 0.0


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _comparison_to_json(comparison: StrategyComparison) -> dict[str, object]:
    return {
        "baseline": _summary_to_json(comparison.baseline),
        "candidate": _summary_to_json(comparison.candidate),
        "excess_return": comparison.excess_return,
        "walk_forward": comparison.walk_forward,
    }


def _summary_to_json(summary: PerformanceSummary) -> dict[str, object]:
    return {
        "name": summary.name,
        "initial_equity": summary.initial_equity,
        "ending_equity": summary.ending_equity,
        "total_return": summary.total_return,
        "annualized_return": summary.annualized_return,
        "sharpe": summary.sharpe,
        "max_drawdown": summary.max_drawdown,
        "trade_count": summary.trade_count,
        "win_rate": summary.win_rate,
    }
