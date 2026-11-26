"""
Structured logging (tiêu chí 10): mỗi dòng log của app là 1 JSON object hợp lệ.

Dùng json.dumps cho cả dòng log, nên message hay field nào chứa dấu " hoặc xuống dòng
cũng được escape đúng (khác với kiểu ghép chuỗi '{"msg":"%(message)s"}').
"""
import json
import logging
import sys
from datetime import datetime, timezone

# Thuộc tính có sẵn của LogRecord — không đưa vào JSON như field tuỳ ý
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Field truyền qua extra={...}, vd logger.info("request", extra={"path": "/ask"})
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Logger "agent" ghi JSON ra stdout. Không đụng tới logger của uvicorn."""
    logger = logging.getLogger("agent")
    if not logger.handlers:  # tránh gắn handler 2 lần khi module bị import lại
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False  # không đi qua root logger (format mặc định, không phải JSON)
    return logger
