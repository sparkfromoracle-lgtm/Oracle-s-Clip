import os
import sqlite3
import shutil
import pytest
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
from media_service.storage.job_store import DurableJobStore


def test_backup_and_disaster_recovery_restore(tmp_path):
    primary_db = str(tmp_path / "primary_jobs.db")
    backup_db = str(tmp_path / "backup_jobs.db")

    # 1. Initialize primary store and insert data
    store = DurableJobStore(db_path=primary_db)
    spec = ClipSpecification(
        spec_id="spec_dr_1",
        source_media_id="media_dr_1",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=3000, source_media_id="media_dr_1")],
    )
    job = RenderJob(
        job_id="job_dr_1",
        tenant_id="tenant_dr",
        spec=spec,
        status=JobStatus.COMPLETED,
        output_path="/tmp/dr_out.mp4",
    )
    store.save_job(job)

    # 2. Perform online SQLite hot backup
    with sqlite3.connect(primary_db) as src, sqlite3.connect(backup_db) as dst:
        src.backup(dst)

    # 3. Simulate disaster: delete or corrupt primary database
    os.remove(primary_db)
    assert not os.path.exists(primary_db)

    # 4. Restore from backup
    shutil.copy2(backup_db, primary_db)
    assert os.path.exists(primary_db)

    # 5. Verify restored state
    restored_store = DurableJobStore(db_path=primary_db)
    restored_job = restored_store.get_job("job_dr_1")
    assert restored_job is not None
    assert restored_job.job_id == "job_dr_1"
    assert restored_job.tenant_id == "tenant_dr"
    assert restored_job.status == JobStatus.COMPLETED
