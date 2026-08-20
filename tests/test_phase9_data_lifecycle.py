import os
import time
import pytest
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
from media_service.storage.job_store import DurableJobStore
from media_service.storage.lifecycle import DataLifecycleManager


def test_lifecycle_manager_temp_and_failed_cleanup(tmp_path):
    jobs_db = str(tmp_path / "lifecycle_jobs.db")
    storage_dir = str(tmp_path / "storage")
    temp_dir = str(tmp_path / "tmp_processing")
    os.makedirs(storage_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    job_store = DurableJobStore(db_path=jobs_db)
    manager = DataLifecycleManager(
        job_store=job_store,
        storage_base_dir=storage_dir,
        temp_dir=temp_dir,
        max_tenant_quota_bytes=1000000,
    )

    # 1. Create a dummy temp file
    old_temp = os.path.join(temp_dir, "clip_old.tmp")
    with open(old_temp, "w") as f:
        f.write("old temp data")
    # Backdate mtime
    past_time = time.time() - 7200
    os.utime(old_temp, (past_time, past_time))

    cleaned = manager.cleanup_temp_files(max_age_seconds=3600)
    assert cleaned >= 1
    assert not os.path.exists(old_temp)

    # 2. Test failed render cleanup
    failed_out = os.path.join(storage_dir, "failed_out.mp4")
    with open(failed_out, "w") as f:
        f.write("failed output")

    spec = ClipSpecification(
        spec_id="spec_fail_lc",
        source_media_id="src_fail",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=1000, source_media_id="src_fail")],
    )
    failed_job = RenderJob(
        job_id="job_fail_lc",
        tenant_id="tenant_lc",
        spec=spec,
        status=JobStatus.FAILED,
        output_path=failed_out,
    )
    job_store.save_job(failed_job)

    assert os.path.exists(failed_out)
    cleaned_failed = manager.cleanup_failed_renders()
    assert cleaned_failed >= 1
    assert not os.path.exists(failed_out)

    # 3. Test quota calculation and tenant purging
    active_out = os.path.join(storage_dir, "active_out.mp4")
    with open(active_out, "w") as f:
        f.write("active output data")

    active_job = RenderJob(
        job_id="job_active_lc",
        tenant_id="tenant_lc",
        spec=spec,
        status=JobStatus.COMPLETED,
        output_path=active_out,
    )
    job_store.save_job(active_job)

    usage = manager.get_tenant_storage_usage("tenant_lc")
    assert usage["file_count"] == 1
    assert usage["total_bytes_used"] > 0

    # Purge tenant
    purge_report = manager.purge_tenant_data("tenant_lc")
    assert purge_report["purged_jobs"] >= 1
    assert purge_report["deleted_files"] >= 1
    assert not os.path.exists(active_out)
    assert len(job_store.list_jobs(tenant_id="tenant_lc")) == 0
