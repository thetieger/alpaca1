"""
Data fetching from Alpaca using alpaca-py.
Provides historical bars and the prior-day close needed for gap calculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame

from src.config import AlpacaCreds

log = logging.getLogger("bot.data")

# Free-tier and paper-trading accounts only have access to the IEX feed.
_FEED = DataFeed.IEX


def build_data_client(creds: AlpacaCreds) -> StockHistoricalDataClient:
    """Create an Alpaca historical-data client."""
    return StockHistoricalDataClient(
        api_key=creds.api_key,
        secret_key=creds.api_secret,
    )


def get_recent_bars(
    client: StockHistoricalDataClient,
    symbol: str,
    lookback_minutes: int = 60,
) -> pd.DataFrame:
    """
    Fetch the most recent 1-minute bars for *symbol*.
    Returns a DataFrame with columns: open, high, low, close, volume, vwap.
    """
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=lookback_minutes + 5)  # small buffer

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            limit=lookback_minutes,
            feed=_FEED,
        )
        barset = client.get_stock_bars(request)

        # alpaca-py returns a BarSet; convert to DataFrame.
        bars = barset.df
        if bars.empty:
            log.warning("No bars returned for %s", symbol)
            return pd.DataFrame()

        # If multi-index (symbol, timestamp), drop the symbol level.
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.droplevel("symbol")

        return bars
    except Exception:
        log.exception("Failed to fetch recent bars for %s", symbol)
        return pd.DataFrame()


def get_prior_close(
    client: StockHistoricalDataClient,
    symbol: str,
) -> float | None:
    """
    Return the prior regular-session close price for *symbol*.
    Uses the previous trading day's daily bar.
    """
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=5)  # go back far enough to cover weekends

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            limit=5,
            feed=_FEED,
        )
        barset = client.get_stock_bars(request)
        bars = barset.df
        if bars.empty:
            log.warning("No daily bars returned for %s", symbol)
            return None

        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.droplevel("symbol")

        # The last completed daily bar is the prior session close.
        # Filter out today's (possibly partial) bar to reliably get yesterday's close.
        today = datetime.now(timezone.utc).date()
        completed = bars[bars.index.date < today]

        if completed.empty:
            # Fallback: use whatever bars we have.
            return float(bars.iloc[-1]["close"])

        return float(completed.iloc[-1]["close"])
    except Exception:
        log.exception("Failed to get prior close for %s", symbol)
        return None


def get_today_open(
    client: StockHistoricalDataClient,
    symbol: str,
) -> float | None:
    """
    Return today's regular-session open price.
    Fetches today's first 1-minute bar.
    """
    try:
        end = datetime.now(timezone.utc)
        # Start from midnight UTC — the first bar after 09:30 ET is the open.
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            limit=1,
            feed=_FEED,
        )
        barset = client.get_stock_bars(request)
        bars = barset.df
        if bars.empty:
            log.warning("No intraday bars yet for %s today", symbol)
            return None

        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.droplevel("symbol")

        return float(bars.iloc[0]["open"])
    except Exception:
        log.exception("Failed to get today's open for %s", symbol)
        return None


@dataclass
class GapData:
    """Prior close and today's open needed for gap calculation."""
    prior_close: float
    today_open: float


def get_gap_data(
    client: StockHistoricalDataClient,
    symbol: str,
) -> GapData | None:
    """
    Fetch prior close and today's open via the snapshot endpoint.

    The snapshot returns both `previous_daily_bar` (prior session) and
    `daily_bar` (current session) in a single call, which is more reliable
    than issuing two separate historical-bars requests.
    """
    try:
        request = StockSnapshotRequest(
            symbol_or_symbols=symbol,
            feed=_FEED,
        )
        snapshots = client.get_stock_snapshot(request)
        snap = snapshots.get(symbol) if isinstance(snapshots, dict) else snapshots
        if snap is None:
            log.warning("No snapshot returned for %s", symbol)
            return None

        prior_close: float | None = None
        today_open: float | None = None

        if snap.previous_daily_bar is not None:
            prior_close = float(snap.previous_daily_bar.close)
        if snap.daily_bar is not None:
            today_open = float(snap.daily_bar.open)

        if prior_close is None or today_open is None:
            log.warning(
                "Snapshot incomplete for %s: prior_close=%s today_open=%s",
                symbol, prior_close, today_open,
            )
            return None

        return GapData(prior_close=prior_close, today_open=today_open)
    except Exception:
        log.exception("Failed to get snapshot for %s", symbol)
        return None


def get_latest_price(
    client: StockHistoricalDataClient,
    symbol: str,
) -> float | None:
    """Return the latest quote mid-price for *symbol*."""
    try:
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=_FEED)
        quotes = client.get_stock_latest_quote(request)
        quote = quotes[symbol]
        mid = (quote.ask_price + quote.bid_price) / 2
        return float(mid)
    except Exception:
        log.exception("Failed to get latest price for %s", symbol)
        return None
