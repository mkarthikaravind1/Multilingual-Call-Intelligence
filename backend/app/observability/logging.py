"""Process-wide logging: every record carries the current request id, and
logs can be written as JSON lines for a log collector."""

import contextvars
import json
import logging
import sys
import time

# The id of the HTTP request being handled, "-" outside a request.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in ("method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


_TEXT_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if fmt.strip().lower() == "json" else logging.Formatter(_TEXT_FORMAT)
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.strip().upper() or "INFO")
    # Our middleware logs each request; uvicorn's access log would repeat it.
    logging.getLogger("uvicorn.access").disabled = True
