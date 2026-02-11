"""
Technical indicators for the gap mean-reversion strategy.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger("bot.indicators")


def compute_gap_pct(prior_close: float, today_open: float) -> float:
    """
    Overnight gap as a signed percentage.
    Positive = gap up, negative = gap down.
    """
    if prior_close <= 0:
        return 0.0
    return (today_open - prior_close) / prior_close


def compute_bands(
    bars: pd.DataFrame,
    lookback: int,
    mult: float,
) -> dict[str, float] | None:
    """
    Compute rolling volatility bands on the close column.

    Returns {"mean": ..., "upper": ..., "lower": ..., "std": ...}
    or None if there aren't enough bars.
    """
    if len(bars) < lookback:
        log.debug("Not enough bars (%d) for lookback=%d", len(bars), lookback)
        return None

    closes = bars["close"].astype(float)
    rolling_mean = closes.rolling(window=lookback).mean().iloc[-1]
    rolling_std = closes.rolling(window=lookback).std().iloc[-1]

    if np.isnan(rolling_mean) or np.isnan(rolling_std):
        return None

    return {
        "mean": float(rolling_mean),
        "std": float(rolling_std),
        "upper": float(rolling_mean + mult * rolling_std),
        "lower": float(rolling_mean - mult * rolling_std),
    }


def compute_vwap(bars: pd.DataFrame) -> float | None:
    """
    Compute the cumulative VWAP from the bars DataFrame.
    Expects columns: close (or typical price), volume.
    If a 'vwap' column is already present from Alpaca, use the latest value.
    """
    if "vwap" in bars.columns:
        val = bars["vwap"].iloc[-1]
        if not np.isnan(val):
            return float(val)

    # Manual VWAP fallback using typical price.
    if not {"high", "low", "close", "volume"}.issubset(bars.columns):
        return None

    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    cum_vol = bars["volume"].cumsum()
    cum_tp_vol = (typical * bars["volume"]).cumsum()

    if cum_vol.iloc[-1] == 0:
        return None

    return float(cum_tp_vol.iloc[-1] / cum_vol.iloc[-1])
