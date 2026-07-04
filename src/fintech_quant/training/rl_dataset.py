from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from fintech_quant.research.dataset import FeatureRow, ResearchDataset, SupplementalRow
from fintech_quant.research.scoring import build_score_input, build_stock_scores


DEFAULT_RL_STATE_FIELDS = (
    "return_1d",
    "close_above_ma20",
    "close_above_ma60",
    "close_above_ma250",
    "rsi14",
    "macd_hist",
    "macd_positive",
    "volatility20",
    "pe",
    "pb",
    "roe",
    "growth",
    "main_net_inflow",
    "main_outflow_days",
    "margin_financing_positive",
    "dragon_tiger_positive",
    "negative_event_count",
    "score_total",
    "score_confidence",
    "fundamental_score",
    "technical_score",
    "capital_flow_score",
    "sentiment_score",
)


@dataclass(frozen=True)
class RlStateSample:
    symbol: str
    trade_date: date
    next_trade_date: date
    state_fields: tuple[str, ...]
    state_vector: tuple[float, ...]
    forward_return_1d: float
    terminal: bool = False


def build_rl_state_samples(
    dataset: ResearchDataset,
    *,
    state_fields: Sequence[str] = DEFAULT_RL_STATE_FIELDS,
) -> list[RlStateSample]:
    fields = tuple(state_fields)
    scores = build_stock_scores(dataset)
    samples: list[RlStateSample] = []
    for _symbol, rows in _features_by_symbol(dataset.features):
        for current, following in zip(rows, rows[1:], strict=False):
            state_values = _state_values(dataset, current, scores)
            close = float(current.values["close"])
            next_close = float(following.values["close"])
            samples.append(
                RlStateSample(
                    symbol=current.symbol,
                    trade_date=current.trade_date,
                    next_trade_date=following.trade_date,
                    state_fields=fields,
                    state_vector=tuple(_numeric(state_values.get(field)) for field in fields),
                    forward_return_1d=round((next_close - close) / close, 6),
                    terminal=False,
                )
            )
    return samples


def write_rl_state_jsonl(path: Path, samples: Sequence[RlStateSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(_sample_to_json(sample), ensure_ascii=False, sort_keys=True) + "\n")


def load_rl_state_jsonl(path: Path) -> list[RlStateSample]:
    samples: list[RlStateSample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            samples.append(_sample_from_json(json.loads(line), line_number))
    return samples


def group_rl_state_samples_by_symbol(samples: Sequence[RlStateSample]) -> dict[str, list[list[RlStateSample]]]:
    grouped: dict[str, list[RlStateSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.symbol, []).append(sample)
    episodes: dict[str, list[list[RlStateSample]]] = {}
    for symbol, symbol_samples in sorted(grouped.items()):
        ordered = sorted(symbol_samples, key=lambda item: item.trade_date)
        episodes[symbol] = _episodes_for_symbol(ordered)
    return episodes


def _features_by_symbol(rows: Sequence[FeatureRow]) -> list[tuple[str, list[FeatureRow]]]:
    grouped: dict[str, list[FeatureRow]] = {}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)
    return [
        (symbol, sorted(symbol_rows, key=lambda item: item.trade_date))
        for symbol, symbol_rows in sorted(grouped.items())
    ]


def _state_values(
    dataset: ResearchDataset,
    row: FeatureRow,
    scores: Mapping[tuple[date, str], object],
) -> dict[str, object]:
    fundamentals = _supplement_for(dataset.fundamentals, row.symbol, row.trade_date)
    capital_flow = _supplement_for(dataset.capital_flow, row.symbol, row.trade_date)
    score_input = build_score_input(row, fundamentals, capital_flow, dataset.information_records)
    score = scores[(row.trade_date, row.symbol)]
    values = dict(row.values)
    values.update(_values(fundamentals))
    values.update(_values(capital_flow))
    values["negative_event_count"] = score_input.negative_event_count
    values["dragon_tiger_positive"] = score_input.dragon_tiger_positive
    values["score_total"] = score.total
    values["score_confidence"] = score.confidence
    for name, component in score.components.items():
        values[f"{name}_score"] = component.score
    return values


def _supplement_for(
    rows: Mapping[tuple[str, date | None], SupplementalRow],
    symbol: str,
    trade_date: date,
) -> SupplementalRow | None:
    return rows.get((symbol, trade_date)) or rows.get((symbol, None))


def _values(row: SupplementalRow | None) -> Mapping[str, object]:
    return row.values if row else {}


def _numeric(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def _sample_to_json(sample: RlStateSample) -> dict[str, object]:
    return {
        "symbol": sample.symbol,
        "trade_date": sample.trade_date.isoformat(),
        "next_trade_date": sample.next_trade_date.isoformat(),
        "state_fields": list(sample.state_fields),
        "state_vector": list(sample.state_vector),
        "forward_return_1d": sample.forward_return_1d,
        "terminal": sample.terminal,
    }


def _sample_from_json(payload: Mapping[str, object], line_number: int) -> RlStateSample:
    state_fields = tuple(str(field) for field in _list(payload, "state_fields", line_number))
    state_vector = tuple(float(value) for value in _list(payload, "state_vector", line_number))
    if len(state_fields) != len(state_vector):
        raise ValueError(f"line {line_number}: state_vector length must match state_fields length")
    return RlStateSample(
        symbol=str(payload["symbol"]),
        trade_date=date.fromisoformat(str(payload["trade_date"])),
        next_trade_date=date.fromisoformat(str(payload["next_trade_date"])),
        state_fields=state_fields,
        state_vector=state_vector,
        forward_return_1d=float(payload["forward_return_1d"]),
        terminal=bool(payload.get("terminal", False)),
    )


def _list(payload: Mapping[str, object], field: str, line_number: int) -> list[object]:
    value = payload[field]
    if not isinstance(value, list):
        raise ValueError(f"line {line_number}: {field} must be a list")
    return value


def _replace_terminal(sample: RlStateSample, *, terminal: bool) -> RlStateSample:
    if sample.terminal == terminal:
        return sample
    return RlStateSample(
        symbol=sample.symbol,
        trade_date=sample.trade_date,
        next_trade_date=sample.next_trade_date,
        state_fields=sample.state_fields,
        state_vector=sample.state_vector,
        forward_return_1d=sample.forward_return_1d,
        terminal=terminal,
    )


def _episodes_for_symbol(samples: Sequence[RlStateSample]) -> list[list[RlStateSample]]:
    episodes: list[list[RlStateSample]] = []
    current: list[RlStateSample] = []
    expected_fields: tuple[str, ...] | None = None
    previous: RlStateSample | None = None
    for sample in samples:
        if previous is not None and not previous.terminal and previous.next_trade_date != sample.trade_date:
            _finish_episode(episodes, current)
            current = []
            expected_fields = None
        if expected_fields is None:
            expected_fields = sample.state_fields
        elif sample.state_fields != expected_fields:
            raise ValueError("state_fields must be stable within an RL episode")
        current.append(sample)
        previous = sample
        if sample.terminal:
            _finish_episode(episodes, current)
            current = []
            expected_fields = None
            previous = None
    if current:
        _finish_episode(episodes, current)
    return episodes


def _finish_episode(episodes: list[list[RlStateSample]], samples: list[RlStateSample]) -> None:
    if not samples:
        return
    episode = list(samples)
    episode[-1] = _replace_terminal(episode[-1], terminal=True)
    episodes.append(episode)
