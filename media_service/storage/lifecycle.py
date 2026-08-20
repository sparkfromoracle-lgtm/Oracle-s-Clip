import os
import time
import shutil
import logging
from typing import Dict, List, Optional, Any
from media_service.storage.job_store import DurableJobStore
from shared.contracts.enums import JobStatus

logger = logging.getLogger("oracle_clip.lifecycle")


class DataLifecycleManager:
    """Manages storage quotas, retention policies, orphaned artifact reclamation,
    and temporary processing file cleanup.
    """

    def __init__(
        self,
        job_store: DurableJobStore,
        storage_base_dir: str = "/tmp/oracle_clip_storage",
        temp_dir: str = "/tmp",
        default_retention_days: int = 30,
        max_tenant_quota_bytes: int = 10 * 1024 * 1024 * 1024, # 10 GB
    ):
        self.job_store = job_store
        self.storage_base_dir = storage_base_dir
        self.temp_dir = temp_dir
        self.default_retention_days = default_retention_days
        self.max_tenant_quota_bytes = max_tenant_quota_bytes

    def cleanup_temp_files(self, max_age_seconds: int = 3600) -> int:
        """Removes temporary clip/ffmpeg processing files older than max_age_seconds."""
        now = time.time()
        cleaned_count = 0

        if not os.path.exists(self.temp_dir):
            return 0

        for root, _, files in os.walk(self.temp_dir):
            for fname in files:
                if fname.startswith("clip_") or fname.startswith("tmp_") or fname.endswith(".tmp"):
                    fpath = os.path.join(root, fname)
                    try:
                        stat = os.stat(fpath)
                        if (now - stat.st_mtime) > max_age_seconds:
                            os.remove(fpath)
                            cleaned_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {fpath}: {e}")
        return cleaned_count

    def cleanup_failed_renders(self) -> int:
        """Cleans up leftover output artifacts for jobs marked as FAILED."""
        jobs = self.job_store.list_jobs(limit=1000)
        cleaned_count = 0
        for job in jobs:
            if job.status == JobStatus.FAILED and job.output_path:
                if os.path.exists(job.output_path):
                    try:
                        if os.path.isfile(job.output_path):
                            os.remove(job.output_path)
                            cleaned_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to remove failed render artifact {job.output_path}: {e}")
        return cleaned_count

    def get_tenant_storage_usage(self, tenant_id: str) -> Dict[str, Any]:
        """Calculates total disk bytes consumed by a tenant across all rendered assets."""
        jobs = self.job_store.list_jobs(tenant_id=tenant_id, limit=5000)
        total_bytes = 0
        active_files = []

        for job in jobs:
            if job.output_path and os.path.exists(job.output_path):
                try:
                    fsize = os.path.getsize(job.output_path)
                    total_bytes += fsize
                    active_files.append({"job_id": job.job_id, "path": job.output_path, "size_bytes": fsize})
                except Exception:
                    pass

        quota_percent = (total_bytes / self.max_tenant_quota_bytes) * 100.0 if self.max_tenant_quota_bytes > 0 else 0.0
        return {
            "tenant_id": tenant_id,
            "total_bytes_used": total_bytes,
            "quota_bytes": self.max_tenant_quota_bytes,
            "quota_usage_percent": round(quota_percent, 2),
            "file_count": len(active_files),
        }

    def enforce_retention_policy(self, max_age_days: Optional[int] = None) -> int:
        """Deletes artifacts and purges records older than max_age_days."""
        retention_days = max_age_days or self.default_retention_days
        cutoff_timestamp = time.time() - (retention_days * 86400)
        jobs = self.job_store.list_jobs(limit=5000)
        purged_count = 0

        for job in jobs:
            if job.created_at < cutoff_timestamp if hasattr(job, "created_at") else False:
                if job.output_path and os.path.exists(job.output_path):
                    try:
                        os.remove(job.output_path)
                    except Exception:
                        pass
                purged_count += 1
        return purged_count

    def purge_tenant_data(self, tenant_id: str) -> Dict[str, Any]:
        """Completely purges all data, jobs, and rendered artifacts for a deleted tenant."""
        jobs = self.job_store.list_jobs(tenant_id=tenant_id, limit=5000)
        deleted_files = 0
        total_freed_bytes = 0

        for job in jobs:
            if job.output_path and os.path.exists(job.output_path):
                try:
                    size = os.path.getsize(job.output_path)
                    os.remove(job.output_path)
                    deleted_files += 1
                    total_freed_bytes += size
                except Exception as e:
                    logger.warning(f"Error removing file {job.output_path}: {e}")

        # Remove from durable job store
        with self.job_store._lock, self.job_store._get_connection() as conn:
            conn.execute("DELETE FROM render_jobs WHERE tenant_id = ?;", (tenant_id,))

        return {
            "tenant_id": tenant_id,
            "purged_jobs": len(jobs),
            "deleted_files": deleted_files,
            "freed_bytes": total_freed_bytes,
        }
