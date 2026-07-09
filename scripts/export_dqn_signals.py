from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Mapping


FIELDS = ("symbol", "trade_date", "rl_action", "source_action", "source_position", "source_trade_date")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export daily RL overlay signals from a DQN policy report.")
    parser.add_argument("--report", required=True, help="DQN run_report.json from scripts/train_dqn_policy.py.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", default="outputs/paper_trading/rl_signals.csv")
    parser.add_argument("--default-action", choices=("buy", "hold", "sell"), default="hold")
    parser.add_argument("--flat-action", choices=("buy", "hold", "sell"), default="hold")
    args = parser.parse_args()

    report = _load_json(Path(args.report))
    signals = export_signals(
        report,
        as_of=args.as_of,
        default_action=args.default_action,
        flat_action=args.flat_action,
    )
    write_signals(Path(args.output), signals)
    print(f"signal_count={len(signals)}")
    print(f"output={args.output}")
    return 0


def export_signals(
    report: Mapping[str, object],
    *,
    as_of: str,
    default_action: str = "hold",
    flat_action: str = "hold",
) -> list[dict[str, object]]:
    symbols = _symbols(report)
    latest = _latest_trades_by_symbol(report, as_of)
    rows = []
    for symbol in symbols:
        trade = latest.get(symbol)
        rows.append(
            {
                "symbol": symbol,
                "trade_date": as_of,
                "rl_action": _rl_action(trade, default_action, flat_action),
                "source_action": str(trade.get("action", "")) if trade else "",
                "source_position": str(trade.get("position", "")) if trade else "",
                "source_trade_date": str(trade.get("trade_date", "")) if trade else "",
            }
        )
    return rows


def write_signals(path: Path, signals: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(signals)


def _symbols(report: Mapping[str, object]) -> list[str]:
    config = report.get("strategy_config", {})
    if isinstance(config, Mapping) and isinstance(config.get("symbols"), list):
        return sorted(str(symbol) for symbol in config["symbols"])
    trades = report.get("trades", [])
    if isinstance(trades, list):
        return sorted({str(trade["symbol"]) for trade in trades if isinstance(trade, Mapping) and trade.get("symbol")})
    return []


def _latest_trades_by_symbol(report: Mapping[str, object], as_of: str) -> dict[str, Mapping[str, object]]:
    latest: dict[str, Mapping[str, object]] = {}
    trades = report.get("trades", [])
    if not isinstance(trades, list):
        return latest
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        symbol = trade.get("symbol")
        trade_date = str(trade.get("trade_date", ""))
        if not symbol or not trade_date or trade_date > as_of:
            continue
        current = latest.get(str(symbol))
        if current is None or str(current.get("trade_date", "")) <= trade_date:
            latest[str(symbol)] = trade
    return latest


def _rl_action(trade: Mapping[str, object] | None, default_action: str, flat_action: str) -> str:
    if trade is None:
        return default_action
    try:
        return "buy" if int(float(trade.get("position", 0))) > 0 else flat_action
    except (TypeError, ValueError):
        action = str(trade.get("action", "")).strip().lower()
        if action in {"buy", "hold", "sell"}:
            return action
        return default_action


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
