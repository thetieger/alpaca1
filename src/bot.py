"""
Main bot loop — long-running worker process.

State machine:
    IDLE    → waiting for market open
    ARMED   → market open, scanning for entry signal
    IN_TRADE → position open, monitoring for exit
    LOCKED  → daily trade limit hit or post-close; no new trades

The bot polls on a 1-minute cadence aligned to bar intervals.
"""

from __future__ import annotations

import logging
import signal
import time
from enum import Enum

from src.config import load_config
from src.data import (
    build_data_client,
    get_latest_price,
    get_prior_close,
    get_recent_bars,
    get_today_open,
)
from src.execution import (
    build_trading_client,
    close_all_positions,
    get_account_equity,
    submit_entry_order,
    submit_exit_order,
)
from src.logging_utils import setup_logging
from src.market_hours import (
    is_market_open,
    is_within_entry_window,
    now_et,
    seconds_until_market_open,
    time_until_close_seconds,
)
from src.risk import RiskManager
from src.strategy import Direction, evaluate_entry, evaluate_exit

log: logging.Logger = logging.getLogger("bot")

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class BotState(str, Enum):
    IDLE = "IDLE"
    ARMED = "ARMED"
    IN_TRADE = "IN_TRADE"
    LOCKED = "LOCKED"


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum: int, _frame) -> None:
    global _shutdown_requested
    log.info("Received signal %d — requesting shutdown", signum,
             extra={"event": "shutdown_signal"})
    _shutdown_requested = True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECONDS = 60  # 1-minute cadence
EOD_FLATTEN_BUFFER_SECONDS = 300  # flatten 5 min before close


# ---------------------------------------------------------------------------
# Mutable context for bot state
# ---------------------------------------------------------------------------
class _Ctx:
    """Mutable bot context passed through the tick loop."""
    def __init__(self) -> None:
        self.state: BotState = BotState.IDLE
        self.entry_price: float | None = None
        self.direction: Direction | None = None
        self.trade_qty: int = 0
        self.prior_close: float | None = None
        self.today_open: float | None = None
        self.last_trading_day: str | None = None


def _set_state(ctx: _Ctx, new_state: BotState) -> None:
    log.info(
        "State: %s → %s", ctx.state.value, new_state.value,
        extra={"event": "state_change", "state": new_state.value},
    )
    ctx.state = new_state


def run_loop() -> None:
    """Entry point for the worker process."""
    setup_logging()
    log.info("Bot starting", extra={"event": "bot_start"})

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    creds, cfg = load_config()
    log.info(
        "Config loaded: symbol=%s dry_run=%s paper=%s",
        cfg.symbol, cfg.dry_run, creds.paper,
        extra={"event": "config_loaded", "symbol": cfg.symbol},
    )

    data_client = build_data_client(creds)
    trading_client = build_trading_client(creds)
    risk_mgr = RiskManager(cfg)
    ctx = _Ctx()

    while not _shutdown_requested:
        try:
            tick(ctx, cfg, data_client, trading_client, risk_mgr)
        except Exception:
            log.exception("Unhandled error in tick — will retry next cycle",
                          extra={"event": "tick_error"})
        time.sleep(POLL_INTERVAL_SECONDS)

    log.info("Shutting down — flattening positions", extra={"event": "bot_shutdown"})
    close_all_positions(trading_client, dry_run=cfg.dry_run)
    log.info("Bot stopped", extra={"event": "bot_stopped"})


def tick(ctx, cfg, data_client, trading_client, risk_mgr) -> None:
    """Single iteration of the bot loop."""

    today_str = now_et().strftime("%Y-%m-%d")

    # --- New trading day detection ---
    if ctx.last_trading_day != today_str:
        log.info("New trading day: %s", today_str, extra={"event": "new_day"})
        ctx.last_trading_day = today_str
        ctx.prior_close = None
        ctx.today_open = None
        ctx.entry_price = None
        ctx.direction = None
        ctx.trade_qty = 0
        risk_mgr.reset_daily()
        _set_state(ctx, BotState.IDLE)

    # --- Pre-market / after-hours → IDLE ---
    if not is_market_open():
        if ctx.state != BotState.IDLE:
            _set_state(ctx, BotState.IDLE)
        wait = seconds_until_market_open()
        if wait > 120:
            log.debug("Market closed. Next open in %.0f s", wait)
        return

    # --- Fetch gap data once per day ---
    if ctx.prior_close is None:
        ctx.prior_close = get_prior_close(data_client, cfg.symbol)
        log.info("Prior close: %s", ctx.prior_close,
                 extra={"event": "prior_close", "price": ctx.prior_close})
    if ctx.today_open is None:
        ctx.today_open = get_today_open(data_client, cfg.symbol)
        log.info("Today open: %s", ctx.today_open,
                 extra={"event": "today_open", "price": ctx.today_open})

    if ctx.prior_close is None or ctx.today_open is None:
        log.warning("Cannot compute gap — missing price data")
        return

    # --- End-of-day flatten ---
    if time_until_close_seconds() <= EOD_FLATTEN_BUFFER_SECONDS:
        if ctx.state == BotState.IN_TRADE and ctx.direction is not None:
            log.info("EOD flatten triggered", extra={"event": "eod_flatten"})
            submit_exit_order(
                trading_client, cfg.symbol, ctx.direction, ctx.trade_qty,
                dry_run=cfg.dry_run,
            )
            ctx.entry_price = None
            ctx.direction = None
            ctx.trade_qty = 0
        _set_state(ctx, BotState.LOCKED)
        return

    # --- State: IDLE → try to arm ---
    if ctx.state == BotState.IDLE:
        _set_state(ctx, BotState.ARMED)
        return

    # --- State: LOCKED → no action ---
    if ctx.state == BotState.LOCKED:
        return

    # --- Fetch latest market data ---
    bars = get_recent_bars(data_client, cfg.symbol, lookback_minutes=max(cfg.band_lookback + 10, 60))
    if bars.empty:
        log.warning("No bars available — skipping tick")
        return

    latest_price = get_latest_price(data_client, cfg.symbol)
    if latest_price is None:
        latest_price = float(bars.iloc[-1]["close"])

    # --- State: ARMED → look for entry ---
    if ctx.state == BotState.ARMED:
        if not risk_mgr.can_trade():
            _set_state(ctx, BotState.LOCKED)
            return

        if not is_within_entry_window(cfg.entry_window_minutes):
            log.debug("Outside entry window — waiting for exit or EOD")
            # Past entry window with no position → just wait for EOD.
            return

        signal_entry = evaluate_entry(
            cfg, bars, latest_price, ctx.prior_close, ctx.today_open,
        )
        if signal_entry is None:
            return

        # Size the position.
        equity = get_account_equity(trading_client)
        qty = risk_mgr.compute_shares(equity, latest_price)
        if qty <= 0:
            log.warning("Computed qty=0 — skipping entry")
            return

        fill = submit_entry_order(
            trading_client, cfg.symbol, signal_entry.direction, qty,
            dry_run=cfg.dry_run,
        )
        if fill is None:
            log.error("Entry order failed — staying ARMED")
            return

        ctx.entry_price = fill.filled_avg_price if fill.filled_avg_price is not None else latest_price
        ctx.direction = signal_entry.direction
        ctx.trade_qty = qty
        risk_mgr.record_trade()
        _set_state(ctx, BotState.IN_TRADE)
        return

    # --- State: IN_TRADE → look for exit ---
    if ctx.state == BotState.IN_TRADE:
        if ctx.entry_price is None or ctx.direction is None:
            log.error("IN_TRADE but missing entry_price/direction — forcing flat")
            close_all_positions(trading_client, dry_run=cfg.dry_run)
            _set_state(ctx, BotState.ARMED)
            return

        exit_signal = evaluate_exit(
            cfg, bars, latest_price, ctx.entry_price, ctx.direction,
        )
        if exit_signal is None:
            return

        fill = submit_exit_order(
            trading_client, cfg.symbol, ctx.direction, ctx.trade_qty,
            dry_run=cfg.dry_run,
        )
        if fill is None:
            log.error("Exit order failed — will retry next tick")
            return

        log.info(
            "Trade closed: %s | entry=%.2f exit=%.2f reason=%s",
            ctx.direction.value, ctx.entry_price, latest_price,
            exit_signal.reason.value,
            extra={"event": "trade_closed", "reason": exit_signal.reason.value,
                    "side": ctx.direction.value},
        )
        ctx.entry_price = None
        ctx.direction = None
        ctx.trade_qty = 0

        # Back to ARMED (can take more trades if under limit).
        if risk_mgr.can_trade():
            _set_state(ctx, BotState.ARMED)
        else:
            _set_state(ctx, BotState.LOCKED)
        return


# ---------------------------------------------------------------------------
# __main__ entry
# ---------------------------------------------------------------------------

def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
