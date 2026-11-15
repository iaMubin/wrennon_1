"""
Standard logging setup for the application.
Provides a configured logger that writes to stdout and a file.
"""

import logging
import sys
from pathlib import Path

from app.security.pii import redact_for_log


class RedactingFilter(logging.Filter):
    """Scrub credentials (JWTs, ?token=, bearer, API keys) and personal data
    (emails, phones, cards, addresses...) from every record before any handler
    sees it. Attached to the app logger AND uvicorn's access/error loggers, so
    WebSocket URLs such as ``/ws/customer/<id>?token=<jwt>`` never reach disk."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            record.msg, record.args = redact_for_log(msg), ()
        except Exception:  # noqa: BLE001,S110 - logging must never raise  # nosec B110
            pass
        return True

# Ensure data directory exists for the log file
log_dir = Path("./data")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "app.log"

logger = logging.getLogger("wrennon")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File handler
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

_redactor = RedactingFilter()
for _h in (console_handler, file_handler):
    _h.addFilter(_redactor)

# uvicorn creates its own handlers; attach the filter to its loggers so access
# lines (which contain full request URLs) are scrubbed as well.
for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    logging.getLogger(_name).addFilter(_redactor)
    for _h in logging.getLogger(_name).handlers:
        _h.addFilter(_redactor)
