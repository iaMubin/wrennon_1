"""
Standard logging setup for the application.
Provides a configured logger that writes to stdout and a file.
"""

import logging
import sys
from pathlib import Path

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
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
