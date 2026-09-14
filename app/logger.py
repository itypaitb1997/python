"""Logging setup with secure filtering and rotation."""
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from typing import Optional


class SensitiveFilter(logging.Filter):
    """Filter out tokens, passwords, and sensitive keys from log output."""
    SENSITIVE_PATTERNS = [
        re.compile(r'(token["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE),
        re.compile(r'(password["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])', re.IGNORECASE),
        re.compile(r'(authorization:\s*bearer\s+)([^\s]+)', re.IGNORECASE),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern in self.SENSITIVE_PATTERNS:
                msg = pattern.sub(r"\1***REDACTED***\3" if pattern.groups == 3 else r"\1***REDACTED***", msg)
            record.msg = msg
        return True


def setup_logger(name: str = "farlink", log_file: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(SensitiveFilter())
        logger.addHandler(stream_handler)

        if log_file:
            try:
                log_dir = os.path.dirname(log_file)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
                file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
                file_handler.setFormatter(formatter)
                file_handler.addFilter(SensitiveFilter())
                logger.addHandler(file_handler)
            except Exception as e:
                logger.warning(f"Could not initialize file log handler at {log_file}: {e}")


    return logger
