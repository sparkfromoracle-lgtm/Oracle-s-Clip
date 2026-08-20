import json
import logging
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Union

SENSITIVE_KEY_PATTERNS = re.compile(r"(key|secret|token|password|auth|credential|signature|cookie)", re.IGNORECASE)


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively redacts sensitive or secret-shaped keys in dictionaries and lists."""
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            if isinstance(k, str) and SENSITIVE_KEY_PATTERNS.search(k):
                if isinstance(v, str) and len(v) > 4:
                    redacted[k] = f"***{v[-4:]}"
                else:
                    redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_sensitive_data(v)
        return redacted
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(redact_sensitive_data(item) for item in obj)
    return obj


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured JSON with correlation context and secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
            "job_id": getattr(record, "job_id", None),
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Merge any extra attributes
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_entry["details"] = redact_sensitive_data(record.extra_fields)

        # Redact entire log entry
        clean_entry = redact_sensitive_data(log_entry)
        # Remove null values
        clean_entry = {k: v for k, v in clean_entry.items() if v is not None}
        return json.dumps(clean_entry)


def setup_structured_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures structured JSON logging for the root logger."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(stream_handler)

    return root_logger
