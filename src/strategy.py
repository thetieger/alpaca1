"""
Gap mean-reversion strategy logic.

Signal generation is pure — it reads market state and returns a Signal,
without placing orders or managing state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from src.config import StrategyConfig
from src.indicators import compute_bands, compute_gap_pct, compute_vwap

log = logging.getLogger("bot.strategy")


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    MEAN_REVERSION = "mean_reversion"
    VWAP_REVERSION = "vwap_reversion"
    STOP_LOSS = "stop_loss"
    END_OF_DAY = "end_of_day"


@dataclass
class EntrySignal:
    direction: Direction
    price: float
    gap_pct: float
    band_value: float  # the band level that was touched


@dataclass
class ExitSignal:
    reason: ExitReason
    price: float


def evaluate_entry(
    cfg: StrategyConfig,
    bars: pd.DataFrame,
    latest_price: float,
    prior_close: float,
    today_open: float,
) -> EntrySignal | None:
    """
    Check if entry conditions are met.

    Rules:
    - Gap must exceed GAP_THRESHOLD.
    - Down gap → wait for price to touch lower band → go long.
    - Up gap → wait for price to touch upper band → go short.
    """
    gap_pct = compute_gap_pct(prior_close, today_open)

    if abs(gap_pct) < cfg.gap_threshold:
        log.debug("Gap %.4f below threshold %.4f", gap_pct, cfg.gap_threshold)
        return None

    bands = compute_bands(bars, cfg.band_lookback, cfg.band_mult)
    if bands is None:
        log.debug("Bands not available yet")
        return None

    # Down gap → expect reversion upward → buy at lower band.
    if gap_pct < 0 and latest_price <= bands["lower"]:
        signal = EntrySignal(
            direction=Direction.LONG,
            price=latest_price,
            gap_pct=gap_pct,
            band_value=bands["lower"],
        )
        log.info(
            "ENTRY signal: LONG | gap=%.4f | price=%.2f <= lower=%.2f",
            gap_pct, latest_price, bands["lower"],
            extra={"event": "entry_signal", "signal": "long",
                    "gap_pct": round(gap_pct, 5), "price": latest_price},
        )
        return signal

    # Up gap → expect reversion downward → sell at upper band.
    if gap_pct > 0 and latest_price >= bands["upper"]:
        signal = EntrySignal(
            direction=Direction.SHORT,
            price=latest_price,
            gap_pct=gap_pct,
            band_value=bands["upper"],
        )
        log.info(
            "ENTRY signal: SHORT | gap=%.4f | price=%.2f >= upper=%.2f",
            gap_pct, latest_price, bands["upper"],
            extra={"event": "entry_signal", "signal": "short",
                    "gap_pct": round(gap_pct, 5), "price": latest_price},
        )
        return signal

    return None


def evaluate_exit(
    cfg: StrategyConfig,
    bars: pd.DataFrame,
    latest_price: float,
    entry_price: float,
    direction: Direction,
    force_eod: bool = False,
) -> ExitSignal | None:
    """
    Check if exit conditions are met for an open position.

    Exits:
    1. Mean reversion — price crosses back to rolling mean.
    2. VWAP reversion (if enabled) — price crosses VWAP in favorable direction.
    3. Stop loss — price moves against us by STOP_PCT.
    4. End-of-day forced flatten.
    """
    if force_eod:
        return ExitSignal(reason=ExitReason.END_OF_DAY, price=latest_price)

    # --- Stop loss ---
    if direction == Direction.LONG:
        stop_price = entry_price * (1 - cfg.stop_pct)
        if latest_price <= stop_price:
            log.info(
                "EXIT signal: STOP_LOSS (long) | price=%.2f <= stop=%.2f",
                latest_price, stop_price,
                extra={"event": "exit_signal", "reason": "stop_loss"},
            )
            return ExitSignal(reason=ExitReason.STOP_LOSS, price=latest_price)
    else:
        stop_price = entry_price * (1 + cfg.stop_pct)
        if latest_price >= stop_price:
            log.info(
                "EXIT signal: STOP_LOSS (short) | price=%.2f >= stop=%.2f",
                latest_price, stop_price,
                extra={"event": "exit_signal", "reason": "stop_loss"},
            )
            return ExitSignal(reason=ExitReason.STOP_LOSS, price=latest_price)

    # --- Mean reversion ---
    bands = compute_bands(bars, cfg.band_lookback, cfg.band_mult)
    if bands is not None:
        mean = bands["mean"]
        if direction == Direction.LONG and latest_price >= mean:
            log.info(
                "EXIT signal: MEAN_REVERSION (long) | price=%.2f >= mean=%.2f",
                latest_price, mean,
                extra={"event": "exit_signal", "reason": "mean_reversion"},
            )
            return ExitSignal(reason=ExitReason.MEAN_REVERSION, price=latest_price)
        if direction == Direction.SHORT and latest_price <= mean:
            log.info(
                "EXIT signal: MEAN_REVERSION (short) | price=%.2f <= mean=%.2f",
                latest_price, mean,
                extra={"event": "exit_signal", "reason": "mean_reversion"},
            )
            return ExitSignal(reason=ExitReason.MEAN_REVERSION, price=latest_price)

    # --- VWAP reversion ---
    if cfg.use_vwap_exit:
        vwap = compute_vwap(bars)
        if vwap is not None:
            if direction == Direction.LONG and latest_price >= vwap:
                log.info(
                    "EXIT signal: VWAP_REVERSION (long) | price=%.2f >= vwap=%.2f",
                    latest_price, vwap,
                    extra={"event": "exit_signal", "reason": "vwap_reversion"},
                )
                return ExitSignal(reason=ExitReason.VWAP_REVERSION, price=latest_price)
            if direction == Direction.SHORT and latest_price <= vwap:
                log.info(
                    "EXIT signal: VWAP_REVERSION (short) | price=%.2f <= vwap=%.2f",
                    latest_price, vwap,
                    extra={"event": "exit_signal", "reason": "vwap_reversion"},
                )
                return ExitSignal(reason=ExitReason.VWAP_REVERSION, price=latest_price)

    return None
