import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient
from media_service.api.app import app
from media_service.config.settings import Settings
from media_service.security.auth import Authenticator, AuthenticatedTenant
from media_service.security.webhooks import WebhookSecurity, WebhookDispatcher
from media_service.storage.object_storage import LocalStorageBackend
from media_service.rendering.ffmpeg_exec import FFmpegCommandExecutor
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import ClipSegmentSpec, ClipSpecification, RenderJob
from shared.errors.errors import (
    AuthenticationError,
    TenantIsolationError,
    StorageError,
    RenderingError,
    WebhookVerificationError,
    ConfigurationError,
)
from shared.hashing.checksum_verifier import (
    verify_artifact_checksum,
    verify_artifacts_manifest,
    calculate_sha256,
)
from media_service.observability.logging import redact_sensitive_data, StructuredJsonFormatter
import logging


def test_command_injection_defense_in_ffmpeg_executor():
    """Verifies that shell metacharacters cannot execute arbitrary commands through FFmpeg executor."""
    executor = FFmpegCommandExecutor()
    malicious_inputs = [
        "; touch /tmp/pwned_001.txt ;",
        "| cat /etc/passwd",
        "$(whoami)",
        "`id`",
        "& echo injected &",
    ]
    
    for payload in malicious_inputs:
        with pytest.raises(RenderingError):
            # Because shell=False, malicious strings are passed literally as arguments to ffmpeg binary
            # FFmpeg will reject them as invalid inputs and fail safely with RenderingError
            executor.execute_ffmpeg(
                args=["-i", payload, "-f", "null", "-"],
                timeout_seconds=5,
            )
        assert not os.path.exists("/tmp/pwned_001.txt")


def test_path_traversal_defense_in_storage_backend():
    """Verifies that local storage backend rejects directory traversal attacks."""
    temp_dir = tempfile.mkdtemp()
    storage = LocalStorageBackend(base_dir=temp_dir)

    traversal_keys = [
        "../etc/passwd",
        "../../root/.ssh/id_rsa",
        "/absolute/path/escape",
        "nested/../../secret.key",
        "....//....//escape.txt",
    ]

    for key in traversal_keys:
        with pytest.raises(StorageError):
            storage.store(b"malicious_data", key)

        with pytest.raises(StorageError):
            storage.get_bytes(key)


def test_outbound_webhook_dispatcher_signing_and_retries(monkeypatch):
    """Tests WebhookDispatcher payload signing, timestamp attachment, and retry behavior."""
    sec = WebhookSecurity(secret="test_webhook_secret_key_123")
    dispatcher = WebhookDispatcher(security=sec, max_retries=2, timeout_seconds=2.0, backoff_factor=0.01)

    calls = []

    class MockResponse:
        def __init__(self, status_code: int, text: str = "ok"):
            self.status_code = status_code
            self.text = text

    def mock_post_success(url, data, headers, timeout):
        calls.append({"url": url, "data": data, "headers": headers})
        assert "X-Webhook-Signature" in headers
        assert "X-Webhook-Timestamp" in headers
        # Verify the signature matches
        sig = headers["X-Webhook-Signature"]
        ts = headers["X-Webhook-Timestamp"]
        assert sec.verify_inbound_signature(data, sig, ts)
        return MockResponse(200, '{"received": true}')

    import requests
    monkeypatch.setattr(requests, "post", mock_post_success)

    payload = {"event": "TEST_EVENT", "value": 42}
    success, status, resp_text = dispatcher.deliver("http://webhook-target.internal/endpoint", payload)
    assert success is True
    assert status == 200
    assert len(calls) == 1


def test_outbound_webhook_dispatcher_server_error_retry(monkeypatch):
    """Tests that WebhookDispatcher retries on 500 server error up to max_retries."""
    sec = WebhookSecurity(secret="test_webhook_secret_key_123")
    dispatcher = WebhookDispatcher(security=sec, max_retries=3, timeout_seconds=2.0, backoff_factor=0.01)

    call_count = [0]

    def mock_post_server_error(url, data, headers, timeout):
        call_count[0] += 1
        return type("Resp", (), {"status_code": 503, "text": "Service Unavailable"})()

    import requests
    monkeypatch.setattr(requests, "post", mock_post_server_error)

    success, status, resp_text = dispatcher.deliver("http://webhook-target.internal/endpoint", {"test": "data"})
    assert success is False
    assert status == 503
    assert call_count[0] == 3


def test_cryptographic_checksum_verification_and_manifest():
    """Tests the cryptographic checksum verification module."""
    data = b"ORACLE_CLIP_CANONICAL_TEST_PAYLOAD_V1"
    calculated_hash, size = calculate_sha256(data)
    assert len(calculated_hash) == 64
    assert size == len(data)

    # 1. Matching expected checksum
    rep_match = verify_artifact_checksum(
        artifact_identity="artifact_alpha",
        data_or_path=data,
        expected_checksum=calculated_hash,
    )
    assert rep_match.verification_result == "VERIFIED"
    assert rep_match.checksum_algorithm == "SHA-256"
    assert rep_match.file_size_bytes == len(data)

    # 2. Mismatched expected checksum
    rep_mismatch = verify_artifact_checksum(
        artifact_identity="artifact_alpha",
        data_or_path=data,
        expected_checksum="0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert rep_mismatch.verification_result == "MISMATCH"

    # 3. Manifest batch verification
    manifest = {
        "artifact_1": b"hello",
        "artifact_2": b"world",
    }
    reports = verify_artifacts_manifest(manifest)
    assert len(reports) == 2
    assert reports[0].verification_result == "COMPUTED"
    assert reports[1].verification_result == "COMPUTED"


def test_logging_redaction_across_all_secret_keys():
    """Verifies that all secret-shaped keys are recursively redacted from logs."""
    sensitive_dict = {
        "user": "operator_1",
        "api_key": "sec_live_abcdef123456",
        "nested": {
            "password": "super_secret_password",
            "webhook_secret": "my_webhook_hmac_secret",
            "authorization": "Bearer ya29.secret_token",
            "safe_field": "visible_metadata",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----",
        },
        "items": [
            {"token": "access_token_value_here", "label": "auth_token"},
            {"secret_access_key": "aws_secret_key_value"},
        ],
    }

    redacted = redact_sensitive_data(sensitive_dict)
    assert redacted["api_key"] == "***3456"
    assert redacted["nested"]["password"] == "***word"
    assert redacted["nested"]["webhook_secret"] == "***cret"
    assert redacted["nested"]["authorization"] == "***oken"
    assert redacted["nested"]["private_key"] == "***----"
    assert redacted["nested"]["safe_field"] == "visible_metadata"
    assert redacted["items"][0]["token"] == "***here"
    assert redacted["items"][1]["secret_access_key"] == "***alue"


def test_production_mode_fails_closed_when_mock_asr_or_clip_configured():
    """Verifies that Settings.validate_production() fails closed if mock ASR or CLIP is set."""
    settings = Settings(
        environment="production",
        api_keys={"valid_key_123": "tenant_1"},
        webhook_secret="strong_webhook_secret_minimum_16_chars",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        asr_provider="mock",
        clip_provider="open_clip",
    )
    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_production()
    assert "mock is forbidden" in str(exc_info.value).lower()

    settings_clip = Settings(
        environment="production",
        api_keys={"valid_key_123": "tenant_1"},
        webhook_secret="strong_webhook_secret_minimum_16_chars",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        asr_provider="local",
        clip_provider="mock",
    )
    with pytest.raises(ConfigurationError) as exc_info2:
        settings_clip.validate_production()
    assert "mock is forbidden" in str(exc_info2.value).lower()
