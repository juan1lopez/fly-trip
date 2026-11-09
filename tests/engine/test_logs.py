import json
import logging
from pathlib import Path

from flytrip.engine.logs import configure_logging


def test_configure_logging_writes_jsonl_once(tmp_path: Path):
    logger = logging.getLogger("flytrip")
    before = list(logger.handlers)
    try:
        configure_logging(tmp_path / "logs")
        configure_logging(tmp_path / "logs")
        jsonl = [h for h in logger.handlers if getattr(h, "_flytrip_jsonl", False)]
        assert len(jsonl) == 1
        extra = {"source": "kiwi", "count": 3}
        logging.getLogger("flytrip.search").info("source_done", extra=extra)
        for handler in logger.handlers:
            handler.flush()
        lines = (tmp_path / "logs" / "flytrip.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["message"] == "source_done" and entry["source"] == "kiwi"
        assert entry["count"] == 3 and entry["level"] == "INFO"
    finally:
        for handler in list(logger.handlers):
            if handler not in before:
                logger.removeHandler(handler)
                handler.close()
