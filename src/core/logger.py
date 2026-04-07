"""Structured JSON-line logger for MCP tool invocations."""

import datetime
import json
import logging
import sys


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Structured fields are passed via ``extra={"fields": {...}}`` and merged
    into the top-level JSON object alongside ``timestamp`` and ``level``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
        }
        if hasattr(record, "fields"):
            payload.update(record.fields)
        return json.dumps(payload, default=str)


def get_logger(name: str = "mcp_db_agent") -> logging.Logger:
    """Return a module-level logger that writes JSON lines to stderr.

    Safe to call multiple times — the handler is only attached once.
    Logs go to stderr so they do not interfere with the MCP stdio transport.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger
