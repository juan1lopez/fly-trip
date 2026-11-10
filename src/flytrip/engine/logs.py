"""JSON-lines logging to `logs/flytrip.jsonl`."""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
_HANDLER_FLAG = "_flytrip_jsonl"


class JsonLinesFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(logs_dir: Path) -> None:
    """Send `flytrip.*` logs to a rotating JSONL file; calling it twice adds no second handler."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("flytrip")
    for existing in logger.handlers:
        if getattr(existing, _HANDLER_FLAG, False):
            logger.removeHandler(existing)
            existing.close()
    handler = RotatingFileHandler(
        logs_dir / "flytrip.jsonl", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(JsonLinesFormatter())
    setattr(handler, _HANDLER_FLAG, True)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
