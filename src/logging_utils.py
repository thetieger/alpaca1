"""
Structured JSON logging for the trading bot.
All log output goes to stdout so Railway captures it automatically.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach extra structured fields if present.
        for key in ("event", "symbol", "side", "qty", "price", "state",
                     "gap_pct", "signal", "order_id", "reason"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger with JSON output to stdout and return 'bot' logger."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers to avoid duplicate output.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    return logging.getLogger("bot")
