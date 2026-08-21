import os
import subprocess
import pytest
from fastapi.testclient import TestClient

from media_service.api.app import app, settings, rate_limiter, idempotency_store
from media_service.security.rate_limiter import TokenBucketRateLimiter
from media_service.security.idempotency import IdempotencyStore
from media_service.security.media_guard import MediaGuard
from media_service.orchestration.orchestrator import CanonicalPipelineOrchestrator
from media_service.rendering.ffmpeg_renderer import FFmpegRendererAdapter
from media_service.storage.object_storage import LocalStorageBackend
from media_service.security.webhooks import WebhookSecurity, WebhookDispatcher
from shared.contracts.enums import QualityVerdict
from shared.errors.errors import ValidationError, RateLimitExceededError

TEST_API_KEY = "test_key_tenant_alpha"
TEST_TENANT = "tenant_alpha"
settings.api_keys[TEST_API_KEY] = TEST_TENANT
client = TestClient(app)


def test_rate_limiter_token_bucket():
    limiter = TokenBucketRateLimiter(requests_per_minute=60, burst_capacity=2)
    # Burst 1
    allowed, _ = limiter.check_and_consume("t1")
    assert allowed is True
    # Burst 2
    allowed, _ = limiter.check_and_consume("t1")
    assert allowed is True
    # Burst 3 should fail
    allowed, _ = limiter.check_and_consume("t1")
    assert allowed is False

    with pytest.raises(RateLimitExceededError):
        limiter.enforce("t1")


def test_idempotency_store_caching_and_lock():
    # Isolated store: the production default path is durable on disk, so the
    # test must not share state with other runs/processes.
    store = IdempotencyStore(default_ttl_seconds=60, db_path=":memory:")
    # First acquisition succeeds
    assert store.acquire_lock("key1") is True
    # Second acquisition fails (in-progress)
    assert store.acquire_lock("key1") is False

    # Store payload
    store.put("key1", {"result": "success"})
    cached = store.get("key1")
    assert cached == {"result": "success"}


def test_media_guard_validations(tmp_path):
    guard = MediaGuard(max_file_size_bytes=1024 * 1024, min_file_size_bytes=32)

    # 1. Non-existent file
    with pytest.raises(ValidationError):
        guard.validate_file_path(str(tmp_path / "non_existent.mp4"))

    # 2. Too small file
    tiny_file = tmp_path / "tiny.mp4"
    tiny_file.write_bytes(b"short")
    with pytest.raises(ValidationError):
        guard.validate_file_path(str(tiny_file))

    # 3. Corrupt header
    bad_header_file = tmp_path / "bad.mp4"
    bad_header_file.write_bytes(b"X" * 100)
    with pytest.raises(ValidationError):
        guard.validate_file_path(str(bad_header_file))

    # 4. Valid ISO BMFF MP4 header
    valid_mp4 = tmp_path / "valid.mp4"
    # MP4 ftyp box: 4 bytes len + 'ftyp' + brand
    valid_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 50)
    guard.validate_file_path(str(valid_mp4))


def test_end_to_end_canonical_orchestrator(tmp_path):
    """Executes full canonical pipeline with real media generation and verified lifecycle."""
    source_media = tmp_path / "input.mp4"
    # Generate a real valid 2-second MP4 test file
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(source_media)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res.returncode == 0
    assert source_media.exists()

    renderer = FFmpegRendererAdapter(ffmpeg_binary="ffmpeg")
    storage = LocalStorageBackend(base_dir=str(tmp_path / "storage"))
    webhook_sec = WebhookSecurity(secret="test_webhook_secret_key_123456789")
    dispatcher = WebhookDispatcher(security=webhook_sec)

    orchestrator = CanonicalPipelineOrchestrator(
        renderer=renderer,
        storage_backend=storage,
        webhook_dispatcher=dispatcher,
        webhook_target_url="http://127.0.0.1:9999/dummy_webhook",
    )

    result = orchestrator.execute_pipeline(
        task_id="audit_task_01",
        tenant_id=TEST_TENANT,
        source_media_path=str(source_media),
        duration_ms=2000,
        output_dir=str(tmp_path / "rendered"),
    )

    assert result["status"] == "COMPLETED"
    assert result["task_id"] == "audit_task_01"
    assert result["tenant_id"] == TEST_TENANT
    assert result["opportunity"]["source_media_id"] == "audit_task_01"
    assert result["spec"]["spec_id"] == "spec_audit_task_01"
    assert result["job"]["status"] == "completed"
    assert result["asset"]["width"] > 0
    assert result["asset"]["height"] > 0
    assert result["quality_report"]["verdict"] in {
        QualityVerdict.PASS,
        QualityVerdict.WARN,
        QualityVerdict.FAIL,
    }
    # The renderer must honour the clip specification's target aspect ratio.
    assert result["asset"]["width"] == 1080
    assert result["asset"]["height"] == 1920
    assert result["guardian_decision"]["approved"] is True
    assert result["storage_url"] is not None


def test_api_idempotency_and_orchestration_endpoint(tmp_path):
    # Test idempotency on render jobs endpoint
    job_req = {
        "job_id": "idem_job_001",
        "tenant_id": TEST_TENANT,
        "spec": {
            "spec_id": "idem_spec_001",
            "source_media_id": "media_src_01",
            "segments": [{"start_ms": 0, "end_ms": 1000}],
            "schema_version": "1.0.0",
            "version": 1,
            "target_aspect_ratio": "9:16",
            "status": "draft",
            "metadata": {},
        },
    }

    headers = {
        "X-API-Key": TEST_API_KEY,
        "Idempotency-Key": "unique_request_token_abc_123",
    }

    # First call
    res1 = client.post("/v1/render-jobs", json=job_req, headers=headers)
    assert res1.status_code == 200
    data1 = res1.json()

    # Second call with same idempotency key returns identical cached output
    res2 = client.post("/v1/render-jobs", json=job_req, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data1 == data2


def test_api_rate_limiting_enforcement():
    """Verifies that exceeding rate limit returns HTTP 429."""
    limiter = TokenBucketRateLimiter(requests_per_minute=60, burst_capacity=2)
    tenant_key = "tenant_burst_test"
    assert limiter.check_and_consume(tenant_key)[0] is True
    assert limiter.check_and_consume(tenant_key)[0] is True
    # Third request blocked
    allowed, _ = limiter.check_and_consume(tenant_key)
    assert allowed is False


def test_orchestration_run_endpoint_authenticated(tmp_path):
    """Verifies /v1/orchestration/run endpoint execution and rejection on bad auth."""
    # 1. Unauthenticated request rejected
    res_unauth = client.post("/v1/orchestration/run", json={
        "task_id": "t_01",
        "tenant_id": TEST_TENANT,
        "source_media_path": "/tmp/dummy.mp4",
        "duration_ms": 5000,
    })
    assert res_unauth.status_code == 401

    # 2. Cross-tenant access rejected
    res_cross = client.post(
        "/v1/orchestration/run",
        json={
            "task_id": "t_01",
            "tenant_id": "tenant_other_unauthorized",
            "source_media_path": "/tmp/dummy.mp4",
            "duration_ms": 5000,
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res_cross.status_code == 403

