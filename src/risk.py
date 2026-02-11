"""
Risk management: position sizing and daily trade-count enforcement.
"""

from __future__ import annotations

import logging
import math

from src.config import StrategyConfig

log = logging.getLogger("bot.risk")


class RiskManager:
    """
    Tracks daily trade count and computes risk-based position sizes.
    Reset at the start of each trading day.
    """

    def __init__(self, cfg: StrategyConfig) -> None:
        self.cfg = cfg
        self.trades_today: int = 0

    def reset_daily(self) -> None:
        """Call at the start of each trading day."""
        log.info("Resetting daily trade count (was %d)", self.trades_today,
                 extra={"event": "risk_reset"})
        self.trades_today = 0

    def can_trade(self) -> bool:
        """True if we haven't hit the daily trade limit."""
        allowed = self.trades_today < self.cfg.max_trades_per_day
        if not allowed:
            log.warning(
                "Daily trade limit reached (%d/%d)",
                self.trades_today, self.cfg.max_trades_per_day,
                extra={"event": "trade_limit_reached"},
            )
        return allowed

    def record_trade(self) -> None:
        """Increment the daily trade counter."""
        self.trades_today += 1
        log.info(
            "Trade recorded: %d/%d today",
            self.trades_today, self.cfg.max_trades_per_day,
            extra={"event": "trade_recorded"},
        )

    def compute_shares(
        self,
        equity: float,
        entry_price: float,
    ) -> int:
        """
        Compute position size based on risk percentage of account equity.

        risk_amount = equity * RISK_PCT
        shares = floor(risk_amount / (entry_price * STOP_PCT))

        This sizes the position so that a full stop-loss hit loses
        approximately RISK_PCT of total equity.
        """
        if entry_price <= 0 or equity <= 0:
            log.warning("Invalid inputs: equity=%.2f, price=%.2f", equity, entry_price)
            return 0

        risk_amount = equity * self.cfg.risk_pct
        loss_per_share = entry_price * self.cfg.stop_pct

        if loss_per_share <= 0:
            return 0

        shares = math.floor(risk_amount / loss_per_share)

        # Sanity: never exceed 10% of equity in a single position.
        max_shares_by_equity = math.floor((equity * 0.10) / entry_price)
        shares = min(shares, max_shares_by_equity)

        # Must buy at least 1 share.
        shares = max(shares, 0)

        log.info(
            "Position size: %d shares (equity=%.0f, price=%.2f, risk=%.4f)",
            shares, equity, entry_price, self.cfg.risk_pct,
            extra={"event": "position_size", "qty": shares},
        )
        return shares
