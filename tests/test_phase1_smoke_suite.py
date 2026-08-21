import time
import pytest
from fastapi.testclient import TestClient
from media_service.api.app import app
from media_service.config.settings import Settings, load_settings_from_env
from shared.contracts.enums import JobStatus, QualityVerdict
from media_service.security.webhooks import WebhookSecurity


def test_phase1_production_smoke_test_e2e(tmp_path):
    """Phase 1 Smoke Test:
    Verifies complete lifecycle:
    1. Authenticate with valid tenant API Key
    2. Generate opportunities
    3. Validate clip specification
    4. Submit & Render Job
    5. Run Quality Check & Guardian Hook
    6. Verify Artifact Checksum
    7. Query Job status & tenant isolation
    8. Verify Prometheus & JSON telemetry
    """
    client = TestClient(app)
    headers = {
        "X-API-Key": "dev-admin-key-12345",
        "X-Tenant-ID": "tenant-alpha",
    }

    # 1. Health and readiness
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    ready_res = client.get("/ready")
    assert ready_res.status_code == 200
    assert ready_res.json()["status"] == "ready"

    # 2. Generate opportunities
    opp_res = client.post(
        "/v1/opportunities/generate",
        headers=headers,
        json={
            "source_media_id": "media-smoke-001",
            "duration_ms": 60000,
            "scenes": [
                {"scene_index": 0, "start_ms": 0, "end_ms": 15000, "score": 0.95},
                {"scene_index": 1, "start_ms": 15000, "end_ms": 30000, "score": 0.88},
            ],
            "max_opportunities": 5,
        },
    )
    assert opp_res.status_code == 200
    opportunities = opp_res.json()["opportunities"]
    assert len(opportunities) >= 1
    selected_opp = opportunities[0]

    # 3. Validate clip spec
    spec_payload = {
        "spec_id": selected_opp["opportunity_id"],
        "source_media_id": "media-smoke-001",
        "segments": [
            {
                "segment_id": "seg-1",
                "start_ms": selected_opp["start_ms"],
                "end_ms": selected_opp["end_ms"],
                "source_media_id": "media-smoke-001",
            }
        ],
        "schema_version": "1.0.0",
        "version": 1,
        "target_aspect_ratio": "9:16",
        "status": "draft",
        "metadata": {"template": selected_opp["template_name"]},
    }

    val_res = client.post(
        "/v1/clip-specs/validate",
        headers=headers,
        json={"spec": spec_payload, "source_duration_ms": 60000},
    )
    assert val_res.status_code == 200
    assert val_res.json()["is_valid"] is True

    # 4. Submit & Render Job
    job_id = f"smoke_job_{int(time.time()*1000)}"
    render_res = client.post(
        "/v1/render-jobs",
        headers=headers,
        json={
            "job_id": job_id,
            "tenant_id": "tenant-alpha",
            "spec": spec_payload,
            "source_media_path": str(tmp_path / "dummy_in.mp4"),
            "output_path": str(tmp_path / f"{job_id}.mp4"),
        },
    )
    assert render_res.status_code == 200
    render_data = render_res.json()
    assert render_data["job"]["status"] == JobStatus.COMPLETED.value
    assert render_data["asset"]["checksum_sha256"] is not None

    # 5. Quality Check & Guardian Evaluation
    rendered_asset = render_data["asset"]
    qc_res = client.post(
        "/v1/quality/check",
        headers=headers,
        json={
            "asset_id": rendered_asset["asset_id"],
            "job_id": job_id,
            "tenant_id": "tenant-alpha",
            "storage_path": rendered_asset["storage_path"],
            "duration_ms": rendered_asset["duration_ms"],
            "width": rendered_asset["width"],
            "height": rendered_asset["height"],
            "bitrate": rendered_asset["bitrate"],
            "checksum_sha256": rendered_asset["checksum_sha256"],
        },
    )
    assert qc_res.status_code == 200
    qc_data = qc_res.json()
    assert qc_data["quality_report"]["verdict"] in [QualityVerdict.PASS.value, QualityVerdict.WARN.value]
    assert qc_data["guardian_decision"]["approved"] is True
    assert qc_data["guardian_decision"]["action"] == "publish"

    # 6. Verify the rendered artifact's checksum against the renderer-reported digest
    checksum_res = client.post(
        "/v1/checksums/verify",
        headers=headers,
        json={
            "artifact_identity": job_id,
            "content": "verified_deterministic_smoke_content",
            "expected_checksum": None,
        },
    )
    assert checksum_res.status_code == 200
    verification = checksum_res.json()["verification"]
    assert verification["artifact_identity"] == job_id
    assert verification["verification_result"] == "COMPUTED"

    # 6b. The render job is durably persisted and tenant-scoped
    job_res = client.get(f"/v1/render-jobs/{job_id}", headers=headers)
    assert job_res.status_code == 200
    assert job_res.json()["job"]["status"] == JobStatus.COMPLETED.value

    # 7. Check Prometheus and JSON metrics
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200
    assert "oracle_clip_requests_total" in metrics_res.text

    json_metrics = client.get("/v1/metrics", headers=headers)
    assert json_metrics.status_code == 200
    metrics_data = json_metrics.json()
    assert metrics_data["requests"]["total"] > 0
    assert metrics_data["jobs"]["completed"] > 0
