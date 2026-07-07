from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from fintech_quant.training.rl_dataset import RlStateSample
from fintech_quant.training.torch_dqn import (
    TORCH_DQN_POLICY_NAME,
    TorchDQNConfig,
    evaluate_torch_dqn_policy,
    train_torch_dqn_policy,
)


@dataclass(frozen=True)
class DqnWalkForwardWindow:
    name: str
    train_start: date
    train_end: date
    eval_start: date
    eval_end: date


def rolling_dqn_windows(
    samples: Sequence[RlStateSample],
    *,
    train_years: int = 2,
    eval_years: int = 1,
) -> list[DqnWalkForwardWindow]:
    if not samples:
        raise ValueError("samples must not be empty")
    _require_positive_int("train_years", train_years)
    _require_positive_int("eval_years", eval_years)

    ordered_dates = sorted({sample.trade_date for sample in samples})
    start = ordered_dates[0]
    max_date = ordered_dates[-1]
    windows: list[DqnWalkForwardWindow] = []
    index = 1
    while True:
        train_start = start
        train_end = _add_years(train_start, train_years) - timedelta(days=1)
        eval_start = train_end + timedelta(days=1)
        eval_end = _add_years(eval_start, eval_years) - timedelta(days=1)
        if eval_end > max_date:
            break
        windows.append(
            DqnWalkForwardWindow(
                name=f"rolling_{index}",
                train_start=train_start,
                train_end=train_end,
                eval_start=eval_start,
                eval_end=eval_end,
            )
        )
        start = _add_years(start, eval_years)
        index += 1
    return windows


def slice_dqn_window(
    samples: Sequence[RlStateSample],
    window: DqnWalkForwardWindow,
) -> tuple[list[RlStateSample], list[RlStateSample]]:
    train = [
        sample
        for sample in samples
        if window.train_start <= sample.trade_date <= window.train_end
        and window.train_start <= sample.next_trade_date <= window.train_end
    ]
    evaluation = [
        sample
        for sample in samples
        if window.eval_start <= sample.trade_date <= window.eval_end
        and window.eval_start <= sample.next_trade_date <= window.eval_end
    ]
    return train, evaluation


def run_torch_dqn_walk_forward_report(
    samples: Sequence[RlStateSample],
    *,
    config: TorchDQNConfig | None = None,
    run_id: str = "torch-dqn-walk-forward",
    symbol: str | None = None,
    train_years: int = 2,
    eval_years: int = 1,
) -> dict[str, object]:
    windows = rolling_dqn_windows(samples, train_years=train_years, eval_years=eval_years)
    if not windows:
        raise ValueError("samples do not span enough dates for a walk-forward window")

    dqn_config = config or TorchDQNConfig()
    window_reports: list[dict[str, object]] = []
    skipped_windows: list[dict[str, object]] = []
    for window in windows:
        train_samples, eval_samples = slice_dqn_window(samples, window)
        if not train_samples or not eval_samples:
            skipped_windows.append(_window_payload(window, train_samples, eval_samples))
            continue
        policy = train_torch_dqn_policy(train_samples, dqn_config)
        evaluation = evaluate_torch_dqn_policy(
            eval_samples,
            policy,
            run_id=f"{run_id}:{window.name}",
            symbol=symbol,
        )
        payload = _window_payload(window, train_samples, eval_samples)
        payload["evaluation"] = evaluation
        window_reports.append(payload)

    if not window_reports:
        raise ValueError("all walk-forward windows were empty")

    return {
        "run_id": run_id,
        "policy": TORCH_DQN_POLICY_NAME,
        "validation": {
            "mode": "rolling_walk_forward",
            "train_years": train_years,
            "eval_years": eval_years,
            "look_ahead_bias_control": "Each window trains only on train dates and evaluates on later held-out dates.",
        },
        "config": dqn_config.__dict__,
        "windows": window_reports,
        "skipped_windows": skipped_windows,
        "summary": _summary(window_reports),
    }


def write_dqn_walk_forward_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _window_payload(
    window: DqnWalkForwardWindow,
    train_samples: Sequence[RlStateSample],
    eval_samples: Sequence[RlStateSample],
) -> dict[str, object]:
    return {
        "name": window.name,
        "train_start": window.train_start.isoformat(),
        "train_end": window.train_end.isoformat(),
        "eval_start": window.eval_start.isoformat(),
        "eval_end": window.eval_end.isoformat(),
        "train_sample_count": len(train_samples),
        "eval_sample_count": len(eval_samples),
    }


def _summary(window_reports: Sequence[dict[str, object]]) -> dict[str, object]:
    returns = [
        float(report["evaluation"]["summary"]["total_return"])
        for report in window_reports
    ]
    drawdowns = [
        float(report["evaluation"]["summary"].get("max_drawdown", 0.0))
        for report in window_reports
    ]
    return {
        "window_count": len(window_reports),
        "mean_total_return": _mean(returns),
        "mean_max_drawdown": _mean(drawdowns),
        "positive_window_rate": _mean([1.0 if value > 0 else 0.0 for value in returns]),
    }


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
