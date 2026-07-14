from __future__ import annotations

import csv
import json
import math
import mmap
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from fintech_quant.data.run_artifacts import sha256_file


INITIAL_EQUITY = 100000.0
SERIES_KEYS = ("risk_controlled", "baseline", "csi300")


def build_pnl_curve(
    *,
    baseline_report: Path,
    risk_controlled_report: Path,
    benchmark: Path,
    initial_equity: float = INITIAL_EQUITY,
) -> dict[str, object]:
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial equity must be finite and positive")
    baseline_curve = _load_equity_curve(baseline_report)
    risk_curve = _load_equity_curve(risk_controlled_report)
    baseline_dates = [point[0] for point in baseline_curve]
    risk_dates = [point[0] for point in risk_curve]
    if baseline_dates != risk_dates:
        raise ValueError("baseline and risk-controlled equity curves must use matching dates")

    benchmark_by_date = _load_benchmark(benchmark)
    missing = [trade_date for trade_date in baseline_dates if trade_date not in benchmark_by_date]
    if missing:
        raise ValueError("benchmark is missing strategy dates")
    benchmark_curve = [(trade_date, benchmark_by_date[trade_date]) for trade_date in baseline_dates]

    payload: dict[str, object] = {
        "schema_version": 1,
        "initial_equity": round(initial_equity, 6),
        "dates": [trade_date.isoformat() for trade_date in baseline_dates],
        "series": {
            "risk_controlled": _normalize_series(
                "Risk-Controlled", risk_curve, initial_equity
            ),
            "baseline": _normalize_series("Baseline", baseline_curve, initial_equity),
            "csi300": _normalize_series("CSI 300", benchmark_curve, initial_equity),
        },
        "inputs": {
            "baseline_report": _file_reference(baseline_report),
            "risk_controlled_report": _file_reference(risk_controlled_report),
            "benchmark": _file_reference(benchmark),
        },
    }
    validate_pnl_curve(payload)
    return payload


def validate_pnl_curve(payload: Mapping[str, object]) -> None:
    if payload.get("schema_version") != 1:
        raise ValueError("PnL curve schema_version must be 1")
    initial_equity = _finite_number(payload.get("initial_equity"), "initial_equity")
    if initial_equity != INITIAL_EQUITY:
        raise ValueError(f"PnL curve initial_equity must be {INITIAL_EQUITY}")

    raw_dates = payload.get("dates")
    if not isinstance(raw_dates, list) or not raw_dates:
        raise ValueError("PnL curve dates must be a non-empty list")
    dates = [_parse_date(value, "PnL curve") for value in raw_dates]
    _require_strictly_increasing(dates, "PnL curve dates")

    raw_series = payload.get("series")
    if not isinstance(raw_series, Mapping) or set(raw_series) != set(SERIES_KEYS):
        raise ValueError("PnL curve must contain risk_controlled, baseline, and csi300 series")
    for key in SERIES_KEYS:
        raw = raw_series[key]
        if not isinstance(raw, Mapping):
            raise ValueError(f"PnL curve series {key} must be an object")
        if not isinstance(raw.get("label"), str) or not str(raw["label"]).strip():
            raise ValueError(f"PnL curve series {key} label is required")
        arrays: dict[str, list[float]] = {}
        for field in ("equity", "pnl", "return"):
            values = raw.get(field)
            if not isinstance(values, list) or len(values) != len(dates):
                raise ValueError(f"PnL curve series {key} {field} length mismatch")
            arrays[field] = [
                _finite_number(value, f"PnL curve series {key} {field}") for value in values
            ]
        for equity, pnl, total_return in zip(
            arrays["equity"], arrays["pnl"], arrays["return"], strict=True
        ):
            if not math.isclose(equity - initial_equity, pnl, abs_tol=1e-5):
                raise ValueError(f"PnL curve series {key} equity and pnl are inconsistent")
            if not math.isclose(pnl / initial_equity, total_return, abs_tol=1e-9):
                raise ValueError(f"PnL curve series {key} pnl and return are inconsistent")

    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, Mapping):
        raise ValueError("PnL curve inputs must be an object")
    for name in ("baseline_report", "risk_controlled_report", "benchmark"):
        reference = raw_inputs.get(name)
        if not isinstance(reference, Mapping):
            raise ValueError(f"PnL curve input {name} is required")
        if not isinstance(reference.get("path"), str) or not reference["path"]:
            raise ValueError(f"PnL curve input {name} path is required")
        if not isinstance(reference.get("bytes"), int) or int(reference["bytes"]) < 0:
            raise ValueError(f"PnL curve input {name} bytes is invalid")
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"PnL curve input {name} sha256 is invalid")


def write_pnl_curve(path: Path, payload: Mapping[str, object]) -> None:
    validate_pnl_curve(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_equity_curve(path: Path) -> list[tuple[date, float]]:
    raw_curve = _load_json_array(path, "equity_curve")
    if not raw_curve:
        raise ValueError(f"{path} must contain a non-empty equity_curve")
    curve: list[tuple[date, float]] = []
    for raw in raw_curve:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path} equity_curve must contain objects")
        trade_date = _parse_date(raw.get("trade_date"), str(path))
        try:
            equity = float(raw["equity"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path} equity_curve contains an invalid equity") from error
        curve.append((trade_date, equity))
    _require_strictly_increasing([point[0] for point in curve], f"{path} equity_curve")
    return curve


def _load_json_array(path: Path, key: str) -> list[object]:
    marker = json.dumps(key).encode("utf-8")
    with path.open("rb") as handle:
        if path.stat().st_size == 0:
            raise ValueError(f"{path} is empty")
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            offset = 0
            while True:
                key_start = data.find(marker, offset)
                if key_start < 0:
                    raise ValueError(f"{path} must contain {key}")
                cursor = key_start + len(marker)
                cursor = _skip_whitespace(data, cursor)
                if cursor < len(data) and data[cursor] == ord(":"):
                    cursor = _skip_whitespace(data, cursor + 1)
                    if cursor < len(data) and data[cursor] == ord("["):
                        end = _array_end(data, cursor)
                        payload = json.loads(data[cursor : end + 1].decode("utf-8"))
                        if not isinstance(payload, list):
                            raise ValueError(f"{path} {key} must be an array")
                        return payload
                offset = key_start + len(marker)


def _skip_whitespace(data: mmap.mmap, cursor: int) -> int:
    while cursor < len(data) and data[cursor] in b" \t\r\n":
        cursor += 1
    return cursor


def _array_end(data: mmap.mmap, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for cursor in range(start, len(data)):
        value = data[cursor]
        if in_string:
            if escaped:
                escaped = False
            elif value == ord("\\"):
                escaped = True
            elif value == ord('"'):
                in_string = False
            continue
        if value == ord('"'):
            in_string = True
        elif value == ord("["):
            depth += 1
        elif value == ord("]"):
            depth -= 1
            if depth == 0:
                return cursor
    raise ValueError("equity_curve array is not terminated")


def _load_benchmark(path: Path) -> dict[date, float]:
    rows: list[tuple[date, float]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            trade_date = _parse_date(raw.get("trade_date"), str(path))
            value = _benchmark_value(raw)
            if not math.isfinite(value):
                raise ValueError(f"{path} benchmark values must be finite")
            rows.append((trade_date, value))
    if not rows:
        raise ValueError(f"{path} benchmark must contain at least one row")
    _require_strictly_increasing([row[0] for row in rows], f"{path} benchmark dates")
    return dict(rows)


def _benchmark_value(row: Mapping[str, object]) -> float:
    for key in ("index_close", "close", "equity"):
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(str(value).replace(",", "").strip())
            except ValueError as error:
                raise ValueError("benchmark contains an invalid value") from error
    raise ValueError("benchmark row must contain index_close, close, or equity")


def _normalize_series(
    label: str,
    curve: Sequence[tuple[date, float]],
    initial_equity: float,
) -> dict[str, object]:
    source_initial = curve[0][1]
    if not math.isfinite(source_initial) or source_initial <= 0:
        raise ValueError(f"{label} initial equity must be finite and positive")
    equity_values: list[float] = []
    pnl_values: list[float] = []
    return_values: list[float] = []
    for _, raw_value in curve:
        if not math.isfinite(raw_value):
            raise ValueError(f"{label} equity values must be finite")
        equity = round(initial_equity * raw_value / source_initial, 6)
        pnl = round(equity - initial_equity, 6)
        total_return = round(pnl / initial_equity, 10)
        equity_values.append(equity)
        pnl_values.append(pnl)
        return_values.append(total_return)
    return {
        "label": label,
        "equity": equity_values,
        "pnl": pnl_values,
        "return": return_values,
    }


def _file_reference(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _parse_date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} trade_date must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} trade_date must be an ISO date") from error


def _require_strictly_increasing(values: Sequence[date], label: str) -> None:
    if any(current <= previous for previous, current in zip(values, values[1:], strict=False)):
        raise ValueError(f"{label} must be strictly increasing and unique")


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number
