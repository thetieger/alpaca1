"""
Order execution via Alpaca Trading API.
Paper-trading only. Uses market orders for simplicity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from src.config import AlpacaCreds, StrategyConfig
from src.strategy import Direction

log = logging.getLogger("bot.execution")


@dataclass
class FillInfo:
    order_id: str
    symbol: str
    side: str
    qty: int
    filled_avg_price: float | None


def build_trading_client(creds: AlpacaCreds) -> TradingClient:
    """Create an Alpaca trading client (paper mode)."""
    return TradingClient(
        api_key=creds.api_key,
        secret_key=creds.api_secret,
        paper=creds.paper,
    )


def get_account_equity(client: TradingClient) -> float:
    """Return current account equity as a float."""
    account = client.get_account()
    return float(account.equity)


def get_position_qty(client: TradingClient, symbol: str) -> int:
    """Return current position quantity (positive=long, negative=short, 0=flat)."""
    try:
        pos = client.get_open_position(symbol)
        return int(pos.qty)
    except Exception:
        # No position for this symbol.
        return 0


def submit_entry_order(
    client: TradingClient,
    symbol: str,
    direction: Direction,
    qty: int,
    dry_run: bool = False,
) -> FillInfo | None:
    """
    Submit a market order to open a position.
    Returns FillInfo or None on failure.
    """
    side = OrderSide.BUY if direction == Direction.LONG else OrderSide.SELL

    if dry_run:
        log.info(
            "DRY_RUN: would submit %s %d %s",
            side.value, qty, symbol,
            extra={"event": "dry_run_entry", "symbol": symbol,
                    "side": side.value, "qty": qty},
        )
        return FillInfo(
            order_id="dry-run",
            symbol=symbol,
            side=side.value,
            qty=qty,
            filled_avg_price=None,
        )

    try:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        log.info(
            "Entry order submitted: %s %d %s (order_id=%s)",
            side.value, qty, symbol, order.id,
            extra={"event": "entry_order", "symbol": symbol,
                    "side": side.value, "qty": qty, "order_id": str(order.id)},
        )
        return FillInfo(
            order_id=str(order.id),
            symbol=symbol,
            side=side.value,
            qty=qty,
            filled_avg_price=(
                float(order.filled_avg_price) if order.filled_avg_price is not None else None
            ),
        )
    except Exception:
        log.exception("Failed to submit entry order")
        return None


def submit_exit_order(
    client: TradingClient,
    symbol: str,
    direction: Direction,
    qty: int,
    dry_run: bool = False,
) -> FillInfo | None:
    """
    Submit a market order to close / flatten a position.
    The exit side is opposite the position direction.
    """
    # To close a long, we sell; to close a short, we buy.
    side = OrderSide.SELL if direction == Direction.LONG else OrderSide.BUY

    if dry_run:
        log.info(
            "DRY_RUN: would submit exit %s %d %s",
            side.value, qty, symbol,
            extra={"event": "dry_run_exit", "symbol": symbol,
                    "side": side.value, "qty": qty},
        )
        return FillInfo(
            order_id="dry-run",
            symbol=symbol,
            side=side.value,
            qty=qty,
            filled_avg_price=None,
        )

    try:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        log.info(
            "Exit order submitted: %s %d %s (order_id=%s)",
            side.value, qty, symbol, order.id,
            extra={"event": "exit_order", "symbol": symbol,
                    "side": side.value, "qty": qty, "order_id": str(order.id)},
        )
        return FillInfo(
            order_id=str(order.id),
            symbol=symbol,
            side=side.value,
            qty=qty,
            filled_avg_price=(
                float(order.filled_avg_price) if order.filled_avg_price is not None else None
            ),
        )
    except Exception:
        log.exception("Failed to submit exit order")
        return None


def close_all_positions(client: TradingClient, dry_run: bool = False) -> None:
    """Emergency flatten — close every open position."""
    if dry_run:
        log.info("DRY_RUN: would close all positions",
                 extra={"event": "dry_run_close_all"})
        return
    try:
        client.close_all_positions(cancel_orders=True)
        log.info("Closed all positions", extra={"event": "close_all"})
    except Exception:
        log.exception("Failed to close all positions")
