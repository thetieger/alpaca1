"""
Configuration loaded from environment variables with sensible defaults.
All secrets come from env vars — never hardcode credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env file if present (local dev); on Railway env vars are injected directly.
load_dotenv()


def _env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(key, default)
    if required and val is None:
        raise EnvironmentError(f"Required environment variable {key!r} is not set")
    if required and val == "":
        raise EnvironmentError(f"Required environment variable {key!r} is set but empty")
    return val  # type: ignore[return-value]


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


def _env_int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(_env(key, str(default)))


@dataclass(frozen=True)
class AlpacaCreds:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    paper: bool = True

    @classmethod
    def from_env(cls) -> AlpacaCreds:
        # Accept both this project's names and Alpaca's standard SDK names.
        api_key = (
            os.environ.get("ALPACA_KEY")
            or os.environ.get("APCA_API_KEY_ID")
        )
        api_secret = (
            os.environ.get("ALPACA_SECRET")
            or os.environ.get("APCA_API_SECRET_KEY")
        )
        if not api_key:
            raise EnvironmentError(
                "API key not found. Set ALPACA_KEY (or APCA_API_KEY_ID) environment variable."
            )
        if not api_secret:
            raise EnvironmentError(
                "API secret not found. Set ALPACA_SECRET (or APCA_API_SECRET_KEY) environment variable."
            )
        return cls(
            api_key=api_key,
            api_secret=api_secret,
            paper=_env_bool("ALPACA_PAPER", default=True),
        )


@dataclass(frozen=True)
class StrategyConfig:
    symbol: str = "SPY"
    max_trades_per_day: int = 5
    risk_pct: float = 0.01
    gap_threshold: float = 0.005
    band_lookback: int = 20
    band_mult: float = 2.0
    entry_window_minutes: int = 30
    stop_pct: float = 0.01
    use_vwap_exit: bool = True
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> StrategyConfig:
        return cls(
            symbol=_env("SYMBOL", "SPY"),
            max_trades_per_day=_env_int("MAX_TRADES_PER_DAY", 5),
            risk_pct=_env_float("RISK_PCT", 0.01),
            gap_threshold=_env_float("GAP_THRESHOLD", 0.005),
            band_lookback=_env_int("BAND_LOOKBACK", 20),
            band_mult=_env_float("BAND_MULT", 2.0),
            entry_window_minutes=_env_int("ENTRY_WINDOW_MINUTES", 30),
            stop_pct=_env_float("STOP_PCT", 0.01),
            use_vwap_exit=_env_bool("USE_VWAP_EXIT", default=True),
            dry_run=_env_bool("DRY_RUN", default=False),
        )


def load_config() -> tuple[AlpacaCreds, StrategyConfig]:
    """Return (credentials, strategy_config) from environment."""
    creds = AlpacaCreds.from_env()
    if not creds.paper:
        raise RuntimeError(
            "Live trading is disabled in this version. "
            "Set ALPACA_PAPER=true to use paper trading."
        )
    strat = StrategyConfig.from_env()
    return creds, strat
