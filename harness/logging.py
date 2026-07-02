"""Structured JSON logging formatter for LokiStack compatibility.

LokiStack automatically collects STDOUT/STDERR from pods, but structured
JSON format improves filtering and querying with LogQL.
"""

import json
import logging


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON for LokiStack ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "session_id": getattr(record, "session_id", ""),
                "iteration": getattr(record, "iteration", 0),
                "layer": getattr(record, "layer", ""),
                "operation": getattr(record, "operation", ""),
            },
            ensure_ascii=False,
        )


def configure_json_logging(level: int = logging.INFO):
    """Replace the root logger's handlers with a JSON-formatted handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
