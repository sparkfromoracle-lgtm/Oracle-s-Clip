"""Tests for the new endpoints: media upload, asset download, rights/provenance
tracking, and the non-spam publishing scheduler."""

import os
import time
import pytest
from fastapi.testclient import TestClient

from media_service.api.app import app, settings, job_store, publishing_scheduler
from shared.contracts.enums import JobStatus, RightsStatus

client = TestClient(app)

TEST_API_KEY = "test_new_endpoints_key"
TEST_TENANT = "tenant_new_ep"
settings.api_keys[TEST_API_KEY] = TEST_TENANT
HEADERS = {"X-API-Key": TEST_API_KEY}


@pytest.fixture(autouse=True)
def _clean():
    job_store.clear()
    publishing_scheduler.autopilot_enabled = False
    yield
    job_store.clear()
    publishing_scheduler.autopilot_enabled = False


def _create_synthetic_video(tmp_path, name="test_input.mp4", duration=2):
    """Creates a real 2-second MP4 using FFmpeg."""
    import subprocess
    video_path = str(tmp_path / name)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=24",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        video_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg failed: {res.stderr}"
    return video_path


# -- Media Upload -----------------------------------------------------------

def test_upload_media_endpoint(tmp_path):
    """Upload a real video file through the API."""
    video_path = _create_synthetic_video(tmp_path)
    with open(video_path, "rb") as f:
        res = client.post(
            "/v1/media/upload",
            files={"file": ("test.mp4", f, "video/mp4")},
            headers=HEADERS,
        )
    assert res.status_code == 200
    data = res.json()
    assert "source_media_path" in data
    assert os.path.exists(data["source_media_path"])
    assert data["file_size_bytes"] > 0
    assert data["duration_ms"] > 0


def test_upload_media_requires_auth():
    res = client.post("/v1/media/upload", files={"file": ("test.mp4", b"data", "video/mp4")})
    assert res.status_code == 401


def test_upload_media_rejects_non_media(tmp_path):
    """Non-media files should be rejected by the media guard."""
    res = client.post(
        "/v1/media/upload",
        files={"file": ("test.txt", b"This is not a media file, just text data here.", "text/plain")},
        headers=HEADERS,
    )
    assert res.status_code == 422


# -- Asset Download ---------------------------------------------------------

def test_download_rendered_asset(tmp_path):
    """Create a completed job with a real output file, then download it."""
    output_path = str(tmp_path / "rendered_output.mp4")

    # Create a real output file with FFmpeg
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path],
        capture_output=True,
    )
    assert os.path.exists(output_path)

    from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
    spec = ClipSpecification(
        spec_id="spec_dl_1",
        source_media_id="test_video.mp4",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=2000, source_media_id="test_video.mp4")],
    )
    job = RenderJob(
        job_id="job_dl_1",
        tenant_id=TEST_TENANT,
        spec=spec,
        status=JobStatus.COMPLETED,
        output_path=output_path,
    )
    job_store.save_job(job)

    res = client.get("/v1/render-jobs/job_dl_1/download", headers=HEADERS)
    assert res.status_code == 200
    assert "video/mp4" in res.headers.get("content-type", "")
    assert len(res.content) > 0


def test_download_nonexistent_job():
    res = client.get("/v1/render-jobs/nonexistent/download", headers=HEADERS)
    assert res.status_code == 404


def test_download_cross_tenant_denied(tmp_path):
    from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
    spec = ClipSpecification(
        spec_id="spec_x",
        source_media_id="test",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=1000)],
    )
    job = RenderJob(
        job_id="job_cross_dl",
        tenant_id="other_tenant",
        spec=spec,
        status=JobStatus.COMPLETED,
        output_path="/tmp/fake.mp4",
    )
    job_store.save_job(job)
    res = client.get("/v1/render-jobs/job_cross_dl/download", headers=HEADERS)
    assert res.status_code == 403


# -- Rights / Provenance ----------------------------------------------------

def test_update_and_get_job_rights():
    from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
    spec = ClipSpecification(
        spec_id="spec_rights",
        source_media_id="test",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=1000)],
    )
    job = RenderJob(
        job_id="job_rights_1",
        tenant_id=TEST_TENANT,
        spec=spec,
        status=JobStatus.COMPLETED,
    )
    job_store.save_job(job)

    # Update rights
    res = client.post("/v1/rights/update", json={
        "job_id": "job_rights_1",
        "rights_status": "rights_verified",
        "rights_owner": "Creator Name",
        "rights_source": "Original creation",
        "rights_license": "All rights reserved",
    }, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["rights_status"] == "rights_verified"

    # Get rights
    res = client.get("/v1/rights/job_rights_1", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["rights_status"] == "rights_verified"
    assert data["rights_owner"] == "Creator Name"
    assert data["rights_source"] == "Original creation"

    # Verify the job store persisted it
    job = job_store.get_job("job_rights_1")
    assert job.rights_status == "rights_verified"
    assert job.rights_owner == "Creator Name"


def test_rights_default_is_unknown():
    """New jobs must default to rights_unknown."""
    from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
    spec = ClipSpecification(
        spec_id="spec_default",
        source_media_id="test",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=1000)],
    )
    job = RenderJob(
        job_id="job_default_rights",
        tenant_id=TEST_TENANT,
        spec=spec,
    )
    job_store.save_job(job)
    retrieved = job_store.get_job("job_default_rights")
    assert retrieved.rights_status == RightsStatus.RIGHTS_UNKNOWN.value


def test_rights_update_invalid_status():
    from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
    spec = ClipSpecification(
        spec_id="spec_invalid",
        source_media_id="test",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=1000)],
    )
    job = RenderJob(
        job_id="job_invalid_status",
        tenant_id=TEST_TENANT,
        spec=spec,
    )
    job_store.save_job(job)

    res = client.post("/v1/rights/update", json={
        "job_id": "job_invalid_status",
        "rights_status": "invalid_status",
    }, headers=HEADERS)
    assert res.status_code == 422


def test_rights_cross_tenant_denied():
    from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
    spec = ClipSpecification(
        spec_id="spec_x",
        source_media_id="test",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=1000)],
    )
    job = RenderJob(
        job_id="job_rights_other",
        tenant_id="other_tenant",
        spec=spec,
    )
    job_store.save_job(job)
    res = client.post("/v1/rights/update", json={
        "job_id": "job_rights_other",
        "rights_status": "rights_verified",
    }, headers=HEADERS)
    assert res.status_code == 403


# -- Scheduler --------------------------------------------------------------

def test_scheduler_rejects_unknown_rights():
    """Unknown rights must never be publishable."""
    res = client.post("/v1/scheduler/evaluate", json={
        "quality_verdict": "pass",
        "quality_score": 0.95,
        "opportunity_score": 0.90,
        "rights_status": "rights_unknown",
        "guardian_approved": True,
    }, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["decision"] == "reject"
    assert any("rights" in r.lower() for r in res.json()["reasons"])


def test_scheduler_rejects_restricted_rights():
    res = client.post("/v1/scheduler/evaluate", json={
        "quality_verdict": "pass",
        "quality_score": 0.95,
        "opportunity_score": 0.90,
        "rights_status": "restricted",
        "guardian_approved": True,
    }, headers=HEADERS)
    assert res.json()["decision"] == "reject"


def test_scheduler_reviews_when_autopilot_off():
    """With autopilot OFF, even good clips require manual review."""
    res = client.post("/v1/scheduler/evaluate", json={
        "quality_verdict": "pass",
        "quality_score": 0.95,
        "opportunity_score": 0.90,
        "rights_status": "rights_verified",
        "guardian_approved": True,
    }, headers=HEADERS)
    assert res.json()["decision"] == "review"
    assert any("autopilot" in r.lower() for r in res.json()["reasons"])


def test_scheduler_publishes_when_autopilot_on():
    """With autopilot ON and all checks passed, decision is publish."""
    client.post("/v1/scheduler/autopilot", json={"enabled": True}, headers=HEADERS)
    res = client.post("/v1/scheduler/evaluate", json={
        "quality_verdict": "pass",
        "quality_score": 0.95,
        "opportunity_score": 0.90,
        "rights_status": "rights_verified",
        "guardian_approved": True,
        "posts_today": 0,
    }, headers=HEADERS)
    assert res.json()["decision"] == "publish"


def test_scheduler_waits_when_quota_exceeded():
    client.post("/v1/scheduler/autopilot", json={"enabled": True}, headers=HEADERS)
    res = client.post("/v1/scheduler/evaluate", json={
        "quality_verdict": "pass",
        "quality_score": 0.95,
        "opportunity_score": 0.90,
        "rights_status": "rights_verified",
        "guardian_approved": True,
        "posts_today": 3,
        "max_posts_per_day": 3,
    }, headers=HEADERS)
    assert res.json()["decision"] == "wait"
    assert any("limit" in r.lower() for r in res.json()["reasons"])


def test_scheduler_rejects_failed_quality():
    res = client.post("/v1/scheduler/evaluate", json={
        "quality_verdict": "fail",
        "quality_score": 0.3,
        "opportunity_score": 0.90,
        "rights_status": "rights_verified",
        "guardian_approved": True,
    }, headers=HEADERS)
    assert res.json()["decision"] == "reject"


def test_scheduler_status():
    res = client.get("/v1/scheduler/status", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["autopilot_enabled"] is False
    assert "min_quality_score" in data
    assert "min_opportunity_score" in data


def test_scheduler_autopilot_toggle():
    res = client.post("/v1/scheduler/autopilot", json={"enabled": True}, headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["autopilot_enabled"] is True

    res = client.post("/v1/scheduler/autopilot", json={"enabled": False}, headers=HEADERS)
    assert res.json()["autopilot_enabled"] is False
