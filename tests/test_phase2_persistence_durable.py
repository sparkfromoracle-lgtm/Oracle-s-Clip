import os
import time
import pytest
from shared.contracts.enums import JobStatus, ClipSpecStatus
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
from media_service.storage.job_store import DurableJobStore
from media_service.security.idempotency import IdempotencyStore


def test_durable_job_store_crud_and_restart(tmp_path):
    db_path = str(tmp_path / "test_jobs.db")
    store = DurableJobStore(db_path=db_path)

    spec = ClipSpecification(
        spec_id="spec_101",
        source_media_id="media_101",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000, source_media_id="media_101")],
        status=ClipSpecStatus.APPROVED,
    )
    job = RenderJob(
        job_id="job_101",
        tenant_id="tenant_x",
        spec=spec,
        status=JobStatus.PENDING,
    )

    # 1. Save
    store.save_job(job)
    assert len(store) == 1
    assert "job_101" in store

    # 2. Update status and output path (now allowed since RenderJob is mutable)
    job.status = JobStatus.COMPLETED
    job.output_path = "/tmp/out_101.mp4"
    store.save_job(job)

    # 3. Simulate process restart by creating a new store instance with same db
    store_restarted = DurableJobStore(db_path=db_path)
    loaded = store_restarted.get_job("job_101")
    assert loaded is not None
    assert loaded.job_id == "job_101"
    assert loaded.tenant_id == "tenant_x"
    assert loaded.status == JobStatus.COMPLETED
    assert loaded.output_path == "/tmp/out_101.mp4"
    assert loaded.spec.spec_id == "spec_101"

    # 4. List and filter by tenant and status
    jobs_x = store_restarted.list_jobs(tenant_id="tenant_x")
    assert len(jobs_x) == 1

    jobs_y = store_restarted.list_jobs(tenant_id="tenant_y")
    assert len(jobs_y) == 0

    # 5. Delete job
    assert store_restarted.delete_job("job_101") is True
    assert store_restarted.get_job("job_101") is None
    assert len(store_restarted) == 0


def test_idempotency_store_persistence_and_expiry(tmp_path):
    db_path = str(tmp_path / "test_idempotency.db")
    store = IdempotencyStore(default_ttl_seconds=2, db_path=db_path)

    # Lock acquisition
    assert store.acquire_lock("req_1") is True
    assert store.acquire_lock("req_1") is False

    # Store payload
    store.put("req_1", {"status": "ok", "count": 42})

    # Read from restarted instance
    restarted = IdempotencyStore(default_ttl_seconds=2, db_path=db_path)
    cached = restarted.get("req_1")
    assert cached == {"status": "ok", "count": 42}

    # Test TTL expiration
    time.sleep(2.1)
    assert restarted.get("req_1") is None
