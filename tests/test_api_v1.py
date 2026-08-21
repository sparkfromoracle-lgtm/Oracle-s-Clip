import time
from fastapi.testclient import TestClient
from media_service.api.app import app, settings, webhook_security

client = TestClient(app)

# Ensure a test API key is configured
TEST_API_KEY = "test_api_key_123"
TEST_TENANT = "tenant_test"
OTHER_TENANT = "tenant_other"
settings.api_keys[TEST_API_KEY] = TEST_TENANT
webhook_security.secret = "test_webhook_secret_12345"


def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_readiness_endpoint():
    res = client.get("/ready")
    assert res.status_code == 200
    assert "status" in res.json()
    assert "checks" in res.json()


def test_unauthenticated_request_rejected():
    res = client.post("/v1/opportunities/generate", json={"source_media_id": "m1", "duration_ms": 10000})
    assert res.status_code == 401
    assert "error" in res.json()
    assert "AuthenticationError" in res.json()["error"]


def test_invalid_api_key_rejected():
    res = client.post(
        "/v1/opportunities/generate",
        json={"source_media_id": "m1", "duration_ms": 10000},
        headers={"X-API-Key": "invalid_key_999"},
    )
    assert res.status_code == 401


def test_generate_opportunities_authenticated():
    res = client.post(
        "/v1/opportunities/generate",
        json={
            "source_media_id": "media_test_001",
            "duration_ms": 30000,
            "scenes": [
                {"scene_index": 0, "start_ms": 0, "end_ms": 10000, "score": 1.0},
                {"scene_index": 1, "start_ms": 10000, "end_ms": 30000, "score": 1.0},
            ],
            "max_opportunities": 5,
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res.status_code == 200
    data = res.json()
    assert "opportunities" in data
    assert len(data["opportunities"]) > 0


def test_validate_clip_spec_endpoint():
    res = client.post(
        "/v1/clip-specs/validate",
        json={
            "spec": {
                "spec_id": "spec_1",
                "source_media_id": "src_1",
                "segments": [{"start_ms": 0, "end_ms": 5000}],
                "schema_version": "1.0.0",
                "version": 1,
                "target_aspect_ratio": "9:16",
                "status": "draft",
            },
            "source_duration_ms": 10000,
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res.status_code == 200
    assert res.json()["is_valid"] is True


def test_render_job_lifecycle_and_tenant_isolation():
    # 1. Create RenderJob for own tenant
    res = client.post(
        "/v1/render-jobs",
        json={
            "job_id": "job_001",
            "tenant_id": TEST_TENANT,
            "spec": {
                "spec_id": "spec_job_1",
                "source_media_id": "src_1",
                "segments": [{"start_ms": 0, "end_ms": 5000}],
            },
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["job"]["job_id"] == "job_001"
    assert data["job"]["status"] == "completed"

    # 2. Get RenderJob
    res_get = client.get(
        "/v1/render-jobs/job_001",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res_get.status_code == 200
    assert res_get.json()["job"]["job_id"] == "job_001"

    # 3. Cross-Tenant RenderJob creation rejected (403)
    res_cross = client.post(
        "/v1/render-jobs",
        json={
            "job_id": "job_cross_002",
            "tenant_id": OTHER_TENANT,
            "spec": {
                "spec_id": "spec_job_cross",
                "source_media_id": "src_1",
                "segments": [{"start_ms": 0, "end_ms": 5000}],
            },
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res_cross.status_code == 403
    assert "TenantIsolationError" in res_cross.json()["error"]


def test_quality_and_guardian_endpoints():
    # Quality check
    res_q = client.post(
        "/v1/quality/check",
        json={
            "asset_id": "asset_q1",
            "job_id": "job_001",
            "tenant_id": TEST_TENANT,
            "storage_path": "/tmp/test.mp4",
            "duration_ms": 5000,
            "width": 1080,
            "height": 1920,
            "bitrate": 2000000,
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res_q.status_code == 200
    report = res_q.json()["quality_report"]
    assert report["verdict"] == "pass"

    # Guardian evaluation
    res_g = client.post(
        "/v1/guardian/evaluate",
        json={
            "report_id": report["report_id"],
            "asset_id": report["asset_id"],
            "verdict": report["verdict"],
            "overall_score": report["overall_score"],
            "summary": "High quality asset",
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res_g.status_code == 200
    assert res_g.json()["decision"]["approved"] is True


def test_checksum_verify_endpoint():
    res = client.post(
        "/v1/checksums/verify",
        json={
            "artifact_identity": "test_artifact_01",
            "content": "TEST_CONTENT_STRING",
            "expected_checksum": "99ea78f89b917ffb459bb652b04fec9b8a8b1a80c98f80cb4b71be0d5bbec191",
        },
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert res.status_code == 200
    data = res.json()["verification"]
    assert data["artifact_identity"] == "test_artifact_01"
    assert data["verification_result"] in {"VERIFIED", "MISMATCH"}


def test_inbound_webhook_endpoint():
    body = '{"event_type":"media.ingested","media_id":"m_99"}'
    sig, ts = webhook_security.sign_payload(body)

    # Valid webhook
    res = client.post(
        "/v1/webhooks/inbound",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": sig,
            "X-Webhook-Timestamp": str(ts),
        },
    )
    assert res.status_code == 200
    assert res.json()["verified"] is True
    assert res.json()["event_type"] == "media.ingested"

    # Tampered webhook rejected (400)
    res_bad = client.post(
        "/v1/webhooks/inbound",
        content='{"event_type":"media.TAMPERED"}',
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": sig,
            "X-Webhook-Timestamp": str(ts),
        },
    )
    assert res_bad.status_code == 400
    assert "WebhookVerificationError" in res_bad.json()["error"]
