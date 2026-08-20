import time
import pytest
from media_service.security.webhooks import WebhookSecurity
from shared.errors.errors import WebhookVerificationError


def test_webhook_signing_and_verification():
    sec = WebhookSecurity(secret="secret_key_12345678", timestamp_tolerance_seconds=300)
    body = '{"event":"clip.completed","job_id":"job_1"}'

    sig, ts = sec.sign_payload(body)
    assert sig is not None
    assert isinstance(ts, int)

    # Valid verification
    is_valid = sec.verify_inbound_signature(
        raw_body=body,
        signature_header=sig,
        timestamp_header=ts,
    )
    assert is_valid is True

    # With sha256= prefix
    is_valid_prefix = sec.verify_inbound_signature(
        raw_body=body,
        signature_header=f"sha256={sig}",
        timestamp_header=str(ts),
    )
    assert is_valid_prefix is True


def test_webhook_tampered_body_rejected():
    sec = WebhookSecurity(secret="secret_key_12345678")
    body = '{"event":"clip.completed","job_id":"job_1"}'
    sig, ts = sec.sign_payload(body)

    tampered_body = '{"event":"clip.completed","job_id":"job_TAMPERED"}'
    with pytest.raises(WebhookVerificationError) as exc:
        sec.verify_inbound_signature(
            raw_body=tampered_body,
            signature_header=sig,
            timestamp_header=ts,
        )
    assert "Invalid webhook signature" in str(exc.value)


def test_webhook_replay_tolerance():
    sec = WebhookSecurity(secret="secret_key_12345678", timestamp_tolerance_seconds=100)
    body = '{"event":"test"}'
    old_ts = int(time.time()) - 500
    sig, _ = sec.sign_payload(body, timestamp=old_ts)

    with pytest.raises(WebhookVerificationError) as exc:
        sec.verify_inbound_signature(
            raw_body=body,
            signature_header=sig,
            timestamp_header=old_ts,
        )
    assert "timestamp expired" in str(exc.value)


def test_webhook_missing_headers():
    sec = WebhookSecurity(secret="secret_key_12345678")
    with pytest.raises(WebhookVerificationError):
        sec.verify_inbound_signature(raw_body="test", signature_header=None, timestamp_header=12345)

    with pytest.raises(WebhookVerificationError):
        sec.verify_inbound_signature(raw_body="test", signature_header="sig", timestamp_header=None)
