"""Structured logging setup for gateway and CLI."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for attr in (
            "request_id",
            "provider",
            "key_id",
            "model",
            "error_class",
            "route_alias",
        ):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        return json.dumps(payload, ensure_ascii=True)


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
