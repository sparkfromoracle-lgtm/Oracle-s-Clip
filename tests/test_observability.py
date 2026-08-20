import json
import logging
from media_service.observability.logging import (
    redact_sensitive_data,
    StructuredJsonFormatter,
)


def test_redact_sensitive_data():
    raw = {
        "api_key": "secret_key_12345",
        "nested": {
            "webhook_secret": "mysecret9999",
            "password": "pass",
            "auth_token": "token1234",
            "safe_metric": 42.5,
        },
        "items": [{"token": "secret_token_111"}, "safe_string"],
    }
    redacted = redact_sensitive_data(raw)
    assert redacted["api_key"] == "***2345"
    assert redacted["nested"]["webhook_secret"] == "***9999"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["safe_metric"] == 42.5
    assert redacted["items"][0]["token"] == "***_111"
    assert redacted["items"][1] == "safe_string"


def test_structured_json_formatter():
    formatter = StructuredJsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Processing job",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "corr_123"
    record.tenant_id = "tenant_xyz"
    record.job_id = "job_999"
    record.extra_fields = {"api_key": "supersecretkey123", "status": "ok"}

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["logger"] == "test_logger"
    assert parsed["level"] == "INFO"
    assert parsed["correlation_id"] == "corr_123"
    assert parsed["tenant_id"] == "tenant_xyz"
    assert parsed["job_id"] == "job_999"
    assert "supersecretkey123" not in formatted
    assert parsed["details"]["api_key"] == "***y123"
