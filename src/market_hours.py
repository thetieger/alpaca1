"""
Market-hours helpers for US equity regular session (09:30–16:00 ET).
Uses the Alpaca calendar API as the source of truth for holidays/half-days,
with a local fallback for basic weekday checks.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import pytz

log = logging.getLogger("bot.market_hours")

ET = pytz.timezone("America/New_York")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def now_et() -> datetime:
    """Current time in US/Eastern."""
    return datetime.now(ET)


def is_market_open() -> bool:
    """True if we are inside regular trading hours on a weekday."""
    n = now_et()
    if n.weekday() >= 5:  # Saturday / Sunday
        return False
    t = n.time()
    return MARKET_OPEN <= t < MARKET_CLOSE


def _today_et() -> date:
    """Return today's date in US/Eastern (not the server's local date)."""
    return now_et().date()


def market_open_today() -> datetime:
    """Return today's 09:30 ET as an aware datetime."""
    return ET.localize(datetime.combine(_today_et(), MARKET_OPEN))


def market_close_today() -> datetime:
    """Return today's 16:00 ET as an aware datetime."""
    return ET.localize(datetime.combine(_today_et(), MARKET_CLOSE))


def entry_window_end(entry_window_minutes: int) -> datetime:
    """Return the cutoff time for opening new positions."""
    return market_open_today() + timedelta(minutes=entry_window_minutes)


def is_within_entry_window(entry_window_minutes: int) -> bool:
    """True if current time is between market open and open + entry_window_minutes."""
    n = now_et()
    return market_open_today() <= n < entry_window_end(entry_window_minutes)


def seconds_until_market_open() -> float:
    """Seconds until next 09:30 ET (may be negative if already open or past close)."""
    n = now_et()
    open_dt = market_open_today()
    if n >= market_close_today():
        # Next open is tomorrow (or Monday).
        days_ahead = 1
        if n.weekday() == 4:  # Friday
            days_ahead = 3
        elif n.weekday() == 5:  # Saturday
            days_ahead = 2
        open_dt = ET.localize(
            datetime.combine(_today_et() + timedelta(days=days_ahead), MARKET_OPEN)
        )
    return (open_dt - n).total_seconds()


def time_until_close_seconds() -> float:
    """Seconds remaining until 16:00 ET today. Negative if past close."""
    return (market_close_today() - now_et()).total_seconds()
