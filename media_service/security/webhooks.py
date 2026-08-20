import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple, Union
import requests
from shared.errors.errors import WebhookVerificationError

logger = logging.getLogger("oracle_clip.webhooks")


class WebhookSecurity:
    """HMAC-SHA256 Webhook Signing and Verification with Replay Protection.
    
    Signing Scheme:
    Payload to sign: f"{timestamp}.{raw_body}"
    Signature: hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    """

    def __init__(self, secret: str, timestamp_tolerance_seconds: int = 300):
        self.secret = secret
        self.timestamp_tolerance_seconds = timestamp_tolerance_seconds

    def sign_payload(self, body: Union[str, bytes], timestamp: Optional[int] = None) -> Tuple[str, int]:
        """Signs an outbound webhook payload."""
        if not self.secret:
            raise WebhookVerificationError("Cannot sign webhook: webhook_secret is not configured.")

        ts = int(time.time()) if timestamp is None else timestamp
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        signed_data = f"{ts}.".encode("utf-8") + body_bytes
        sig = hmac.new(self.secret.encode("utf-8"), signed_data, hashlib.sha256).hexdigest()
        return sig, ts

    def verify_inbound_signature(
        self,
        raw_body: Union[str, bytes],
        signature_header: Optional[str],
        timestamp_header: Optional[Union[str, int]],
        current_time: Optional[int] = None,
    ) -> bool:
        """Verifies inbound webhook signature and protects against replay/tampering attacks."""
        if not self.secret:
            raise WebhookVerificationError("Webhook verification failed: secret is not configured on server.")

        if not signature_header:
            raise WebhookVerificationError(
                "Missing required webhook signature header (e.g. X-Webhook-Signature).",
                details={"header": "signature"},
            )

        if timestamp_header is None or str(timestamp_header).strip() == "":
            raise WebhookVerificationError(
                "Missing required webhook timestamp header (e.g. X-Webhook-Timestamp).",
                details={"header": "timestamp"},
            )

        try:
            ts = int(timestamp_header)
        except ValueError:
            raise WebhookVerificationError(
                f"Invalid timestamp header value '{timestamp_header}'. Must be an integer UNIX timestamp."
            )

        now = int(time.time()) if current_time is None else current_time
        age = abs(now - ts)
        if age > self.timestamp_tolerance_seconds:
            raise WebhookVerificationError(
                f"Webhook timestamp expired or in future. Age: {age}s (tolerance: {self.timestamp_tolerance_seconds}s).",
                details={"timestamp": ts, "now": now, "age": age},
            )

        body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
        signed_data = f"{ts}.".encode("utf-8") + body_bytes
        expected_sig = hmac.new(self.secret.encode("utf-8"), signed_data, hashlib.sha256).hexdigest()

        # Clean signature if prefixed with sha256=
        clean_sig = signature_header.strip()
        if clean_sig.startswith("sha256="):
            clean_sig = clean_sig[7:]

        if not hmac.compare_digest(expected_sig.lower().encode("utf-8"), clean_sig.lower().encode("utf-8")):
            raise WebhookVerificationError(
                "Invalid webhook signature: body or timestamp has been tampered with or key is mismatched.",
                details={"reason": "signature_mismatch"},
            )

        return True


class WebhookDispatcher:
    """Outbound webhook dispatcher with HMAC signing and retry policy."""

    def __init__(
        self,
        security: WebhookSecurity,
        max_retries: int = 3,
        timeout_seconds: float = 10.0,
        backoff_factor: float = 0.2,
    ):
        self.security = security
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.backoff_factor = backoff_factor

    def deliver(
        self,
        target_url: str,
        payload: Union[Dict[str, Any], str, bytes],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[bool, int, str]:
        """Signs and delivers an outbound webhook to target_url with automatic retry."""
        if isinstance(payload, dict):
            body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        elif isinstance(payload, str):
            body_bytes = payload.encode("utf-8")
        else:
            body_bytes = payload

        sig, ts = self.security.sign_payload(body_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": sig,
            "X-Webhook-Timestamp": str(ts),
        }
        if extra_headers:
            headers.update(extra_headers)

        last_error = ""
        last_status = 0

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"Delivering webhook to {target_url} (attempt {attempt}/{self.max_retries})")
                resp = requests.post(
                    target_url,
                    data=body_bytes,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                last_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    return True, resp.status_code, resp.text
                elif 400 <= resp.status_code < 500:
                    # Client errors (e.g. 400, 401, 403, 404, 422) should not be retried blindly
                    logger.warning(f"Webhook delivery rejected by client with status {resp.status_code}: {resp.text[:200]}")
                    return False, resp.status_code, resp.text
                else:
                    # 5xx Server Error - retry
                    last_error = f"Server error {resp.status_code}: {resp.text[:200]}"
            except requests.RequestException as e:
                last_error = str(e)
                last_status = 0

            if attempt < self.max_retries:
                sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_time)

        logger.error(f"Webhook delivery to {target_url} failed after {self.max_retries} attempts: {last_error}")
        return False, last_status, last_error

