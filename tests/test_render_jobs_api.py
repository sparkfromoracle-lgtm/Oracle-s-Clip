"""Tests for active job retrieval, render job history, tenant isolation,
completed-job filtering, failed-job handling, and the batch processing endpoint.

These tests exercise the real DurableJobStore and API endpoints — no frontend-
only state is fabricated.
"""

import os
import time
import pytest
from fastapi.testclient import TestClient
from media_service.api.app import app, settings, job_store, idempotency_store
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import (
    ClipSpecification,
    ClipSegmentSpec,
    RenderJob,
)

client = TestClient(app)

TEST_API_KEY = "test_jobs_key_001"
TEST_TENANT = "tenant_jobs_test"
OTHER_TENANT = "tenant_jobs_other"
settings.api_keys[TEST_API_KEY] = TEST_TENANT
HEADERS = {"X-API-Key": TEST_API_KEY}


def _make_job(job_id: str, tenant_id: str, status: JobStatus) -> RenderJob:
    spec = ClipSpecification(
        spec_id=f"spec_{job_id}",
        source_media_id=f"source_{job_id}",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000, source_media_id=f"source_{job_id}")],
        target_aspect_ratio="9:16",
    )
    return RenderJob(
        job_id=job_id,
        tenant_id=tenant_id,
        spec=spec,
        status=status,
        output_path=f"/tmp/out_{job_id}.mp4" if status == JobStatus.COMPLETED else None,
        error_message="render failed" if status == JobStatus.FAILED else None,
    )


@pytest.fixture(autouse=True)
def _clean_store():
    """Clear the job store and idempotency cache before each test so tests are isolated."""
    job_store.clear()
    idempotency_store.clear()
    yield
    job_store.clear()
    idempotency_store.clear()


def test_active_jobs_returns_pending_and_in_progress():
    job_store.save_job(_make_job("active_1", TEST_TENANT, JobStatus.PENDING))
    job_store.save_job(_make_job("active_2", TEST_TENANT, JobStatus.IN_PROGRESS))
    job_store.save_job(_make_job("done_1", TEST_TENANT, JobStatus.COMPLETED))

    res = client.get("/v1/render-jobs/active", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 2
    job_ids = {j["job_id"] for j in data["jobs"]}
    assert job_ids == {"active_1", "active_2"}


def test_active_jobs_enforces_tenant_isolation():
    job_store.save_job(_make_job("other_active", OTHER_TENANT, JobStatus.IN_PROGRESS))
    job_store.save_job(_make_job("my_active", TEST_TENANT, JobStatus.IN_PROGRESS))

    res = client.get("/v1/render-jobs/active", headers=HEADERS)
    assert res.status_code == 200
    job_ids = {j["job_id"] for j in res.json()["jobs"]}
    assert "other_active" not in job_ids
    assert "my_active" in job_ids


def test_active_jobs_requires_authentication():
    res = client.get("/v1/render-jobs/active")
    assert res.status_code == 401


def test_history_returns_terminal_jobs_only():
    job_store.save_job(_make_job("h_pending", TEST_TENANT, JobStatus.PENDING))
    job_store.save_job(_make_job("h_completed", TEST_TENANT, JobStatus.COMPLETED))
    job_store.save_job(_make_job("h_failed", TEST_TENANT, JobStatus.FAILED))

    res = client.get("/v1/render-jobs/history", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    job_ids = {j["job_id"] for j in data["jobs"]}
    assert "h_completed" in job_ids
    assert "h_failed" in job_ids
    assert "h_pending" not in job_ids
    assert data["total"] == 2


def test_history_filter_by_status():
    job_store.save_job(_make_job("f_completed", TEST_TENANT, JobStatus.COMPLETED))
    job_store.save_job(_make_job("f_failed", TEST_TENANT, JobStatus.FAILED))

    res = client.get("/v1/render-jobs/history?status=completed", headers=HEADERS)
    assert res.status_code == 200
    job_ids = {j["job_id"] for j in res.json()["jobs"]}
    assert job_ids == {"f_completed"}


def test_history_search_by_job_id():
    job_store.save_job(_make_job("searchable_001", TEST_TENANT, JobStatus.COMPLETED))
    job_store.save_job(_make_job("other_002", TEST_TENANT, JobStatus.COMPLETED))

    res = client.get("/v1/render-jobs/history?search=searchable", headers=HEADERS)
    assert res.status_code == 200
    job_ids = {j["job_id"] for j in res.json()["jobs"]}
    assert job_ids == {"searchable_001"}


def test_history_tenant_isolation():
    job_store.save_job(_make_job("other_done", OTHER_TENANT, JobStatus.COMPLETED))
    job_store.save_job(_make_job("my_done", TEST_TENANT, JobStatus.COMPLETED))

    res = client.get("/v1/render-jobs/history", headers=HEADERS)
    assert res.status_code == 200
    job_ids = {j["job_id"] for j in res.json()["jobs"]}
    assert "other_done" not in job_ids
    assert "my_done" in job_ids


def test_history_pagination():
    for i in range(25):
        job_store.save_job(_make_job(f"page_{i:02d}", TEST_TENANT, JobStatus.COMPLETED))

    res = client.get("/v1/render-jobs/history?limit=10&offset=0", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert len(data["jobs"]) == 10
    assert data["total"] == 25

    res2 = client.get("/v1/render-jobs/history?limit=10&offset=10", headers=HEADERS)
    assert len(res2.json()["jobs"]) == 10


def test_history_counts_by_status():
    job_store.save_job(_make_job("c1", TEST_TENANT, JobStatus.COMPLETED))
    job_store.save_job(_make_job("c2", TEST_TENANT, JobStatus.COMPLETED))
    job_store.save_job(_make_job("f1", TEST_TENANT, JobStatus.FAILED))

    res = client.get("/v1/render-jobs/history", headers=HEADERS)
    counts = res.json()["counts"]
    assert counts.get("completed") == 2
    assert counts.get("failed") == 1


def test_batch_process_creates_multiple_completed_jobs(tmp_path):
    """The batch endpoint should create multiple render jobs from a single source."""
    source = tmp_path / "batch_input.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 200)

    res = client.post(
        "/v1/orchestration/batch",
        json={
            "tenant_id": TEST_TENANT,
            "source_media_path": str(source),
            "duration_ms": 30000,
            "max_clips": 3,
            "target_aspect_ratio": "9:16",
            "scenes": [
                {"scene_index": 0, "start_ms": 0, "end_ms": 10000, "score": 1.0},
                {"scene_index": 1, "start_ms": 10000, "end_ms": 20000, "score": 1.0},
                {"scene_index": 2, "start_ms": 20000, "end_ms": 30000, "score": 1.0},
            ],
        },
        headers=HEADERS,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["completed"] == 3
    assert data["failed"] == 0

    # Verify jobs are persisted in the store.
    for clip in data["clips"]:
        job = job_store.get_job(clip["job_id"])
        assert job is not None
        assert job.status == JobStatus.COMPLETED


def test_batch_process_tenant_isolation():
    res = client.post(
        "/v1/orchestration/batch",
        json={
            "tenant_id": OTHER_TENANT,
            "source_media_path": "/tmp/dummy.mp4",
            "duration_ms": 10000,
            "max_clips": 1,
        },
        headers=HEADERS,
    )
    assert res.status_code == 403


def test_get_render_job_detail():
    job_store.save_job(_make_job("detail_1", TEST_TENANT, JobStatus.COMPLETED))

    res = client.get("/v1/render-jobs/detail_1", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["job"]["job_id"] == "detail_1"
    assert res.json()["job"]["status"] == "completed"


def test_get_render_job_cross_tenant_denied():
    job_store.save_job(_make_job("other_detail", OTHER_TENANT, JobStatus.COMPLETED))

    res = client.get("/v1/render-jobs/other_detail", headers=HEADERS)
    assert res.status_code == 403
