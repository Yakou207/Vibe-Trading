from __future__ import annotations

import pandas as pd


PRICE_COLUMNS = ("open", "high", "low", "close")


def build_daily_feature_frame(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
    frame = frame.sort_values(["代码", "date"]).reset_index(drop=True)

    groups = frame.groupby("代码", group_keys=False)
    frame["return_1d"] = groups["close"].pct_change()
    frame["return_5d"] = groups["close"].pct_change(periods=5)
    frame["return_20d"] = groups["close"].pct_change(periods=20)
    frame["return_60d"] = groups["close"].pct_change(periods=60)
    frame["log_return_1d"] = groups["close"].transform(lambda value: _log_return(value))

    for window in (5, 10, 20, 60):
        frame[f"ma_{window}"] = groups["close"].transform(
            lambda value, size=window: value.rolling(size, min_periods=1).mean()
        )
        frame[f"close_to_ma_{window}"] = frame["close"] / frame[f"ma_{window}"] - 1

    frame["ma_20_slope"] = groups["ma_20"].pct_change(periods=5)
    frame["ma_60_slope"] = groups["ma_60"].pct_change(periods=5)

    frame["volume_ma_5"] = groups["volume"].transform(
        lambda value: value.rolling(5, min_periods=1).mean()
    )
    frame["volume_ma_20"] = groups["volume"].transform(
        lambda value: value.rolling(20, min_periods=1).mean()
    )
    frame["volume_ratio_20"] = frame["volume"] / frame["volume_ma_20"] - 1
    frame["volatility_20"] = groups["return_1d"].transform(
        lambda value: value.rolling(20, min_periods=2).std()
    )

    frame["high_low_range"] = (frame["high"] - frame["low"]) / frame["close"]
    price_range = frame["high"] - frame["low"]
    frame["close_position"] = (
        (frame["close"] - frame["low"]) / price_range.where(price_range != 0)
    ).fillna(0.5)

    frame["rsi_14"] = groups["close"].transform(_rsi_14)
    macd = groups["close"].apply(_macd_frame).reset_index(level=0, drop=True)
    frame[["macd", "macd_signal", "macd_hist"]] = macd[["macd", "macd_signal", "macd_hist"]]

    frame["target_next_return_1d"] = groups["close"].pct_change().groupby(frame["代码"]).shift(-1)
    frame["target_action"] = frame["target_next_return_1d"].map(_action_from_return).fillna("hold")

    numeric_columns = frame.select_dtypes(include=["number"]).columns
    frame[numeric_columns] = frame[numeric_columns].replace([float("inf"), float("-inf")], pd.NA)
    return frame


def feature_columns() -> list[str]:
    return [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "after_volume",
        "after_amount",
        "outstanding_share",
        "turnover",
        "return_1d",
        "return_5d",
        "return_20d",
        "return_60d",
        "log_return_1d",
        "ma_5",
        "close_to_ma_5",
        "ma_10",
        "close_to_ma_10",
        "ma_20",
        "close_to_ma_20",
        "ma_20_slope",
        "ma_60",
        "close_to_ma_60",
        "ma_60_slope",
        "volume_ma_5",
        "volume_ma_20",
        "volume_ratio_20",
        "volatility_20",
        "high_low_range",
        "close_position",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
    ]


def _log_return(close: pd.Series) -> pd.Series:
    import numpy as np

    return np.log(close / close.shift(1))


def _rsi_14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14, min_periods=1).mean()
    avg_loss = loss.rolling(14, min_periods=1).mean()
    rs = avg_gain / avg_loss.where(avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return rsi.fillna(50.0)


def _macd_frame(close: pd.Series) -> pd.DataFrame:
    ema_12 = close.ewm(span=12, adjust=False, min_periods=1).mean()
    ema_26 = close.ewm(span=26, adjust=False, min_periods=1).mean()
    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False, min_periods=1).mean()
    return pd.DataFrame(
        {
            "macd": macd,
            "macd_signal": signal,
            "macd_hist": macd - signal,
        }
    )


def _action_from_return(value: float | None) -> str | None:
    if pd.isna(value):
        return None
    if value > 0:
        return "buy"
    if value < 0:
        return "sell"
    return "hold"
