import os
import json
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Iterator, Tuple
from shared.contracts.enums import JobStatus, ClipSpecStatus
from shared.contracts.jobs import RenderJob, ClipSpecification, ClipSegmentSpec, MediaJobStateMachine
from shared.errors.errors import OracleClipError, ValidationError, TenantIsolationError


class DurableJobStore:
    """Production-grade durable SQLite-backed Job Store with WAL mode, atomic transitions,
    and process-restart resilience.
    """

    def __init__(self, db_path: str = "/tmp/oracle_clip_jobs.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._state_machine = MediaJobStateMachine()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS render_jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    spec_id TEXT NOT NULL,
                    source_media_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    output_path TEXT,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    google_sheet_exported_at TEXT,
                    google_sheet_row_id TEXT
                );
            """)
            # Migration: add columns if upgrading from an older schema.
            self._migrate_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_id ON render_jobs(tenant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON render_jobs(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_status ON render_jobs(tenant_id, status);")

    @staticmethod
    def _migrate_columns(conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(render_jobs);")}
        for col, col_type in [
            ("completed_at", "REAL"),
            ("google_sheet_exported_at", "TEXT"),
            ("google_sheet_row_id", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE render_jobs ADD COLUMN {col} {col_type};")

    def save_job(self, job: RenderJob) -> None:
        """Atomically saves or updates a RenderJob."""
        now = time.time()
        spec_dict = {
            "spec_id": job.spec.spec_id,
            "source_media_id": job.spec.source_media_id,
            "segments": [s.__dict__ for s in job.spec.segments],
            "schema_version": job.spec.schema_version,
            "version": job.spec.version,
            "target_aspect_ratio": job.spec.target_aspect_ratio,
            "status": job.spec.status.value if hasattr(job.spec.status, "value") else str(job.spec.status),
            "metadata": job.spec.metadata,
        }
        spec_json = json.dumps(spec_dict)
        status_val = job.status.value if hasattr(job.status, "value") else str(job.status)

        # Preserve original created_at on updates; set completed_at when terminal.
        created_at = now
        completed_at = None
        with self._lock, self._get_connection() as conn:
            existing = conn.execute(
                "SELECT created_at FROM render_jobs WHERE job_id = ?;", (job.job_id,)
            ).fetchone()
            if existing:
                created_at = existing[0]
            if status_val in (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value):
                completed_at = now

            conn.execute("""
                INSERT INTO render_jobs (
                    job_id, tenant_id, spec_id, source_media_id, status, spec_json,
                    output_path, error_message, created_at, updated_at, completed_at,
                    google_sheet_exported_at, google_sheet_row_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    spec_json=excluded.spec_json,
                    output_path=excluded.output_path,
                    error_message=excluded.error_message,
                    updated_at=excluded.updated_at,
                    completed_at=COALESCE(render_jobs.completed_at, excluded.completed_at),
                    google_sheet_exported_at=excluded.google_sheet_exported_at,
                    google_sheet_row_id=excluded.google_sheet_row_id;
            """, (
                job.job_id,
                job.tenant_id,
                job.spec.spec_id,
                job.spec.source_media_id,
                status_val,
                spec_json,
                job.output_path,
                job.error_message,
                created_at,
                now,
                completed_at,
                job.google_sheet_exported_at,
                job.google_sheet_row_id,
            ))

    def get_job(self, job_id: str) -> Optional[RenderJob]:
        """Retrieves a job by ID."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT job_id, tenant_id, spec_json, status, output_path, error_message,
                       created_at, completed_at, google_sheet_exported_at, google_sheet_row_id
                FROM render_jobs WHERE job_id = ?;
            """, (job_id,))
            row = cursor.fetchone()

        if not row:
            return None

        (j_id, tenant_id, spec_json, status_str, output_path, error_message,
         created_at_ts, completed_at_ts, gs_exported_at, gs_row_id) = row
        s_data = json.loads(spec_json)
        segments = [
            ClipSegmentSpec(
                start_ms=s["start_ms"],
                end_ms=s["end_ms"],
                source_media_id=s.get("source_media_id", s_data["source_media_id"]),
            )
            for s in s_data.get("segments", [])
        ]
        spec = ClipSpecification(
            spec_id=s_data["spec_id"],
            source_media_id=s_data["source_media_id"],
            segments=segments,
            schema_version=s_data.get("schema_version", "1.0.0"),
            version=s_data.get("version", 1),
            target_aspect_ratio=s_data.get("target_aspect_ratio", "9:16"),
            status=ClipSpecStatus(s_data.get("status", "draft")),
            metadata=s_data.get("metadata", {}),
        )

        return RenderJob(
            job_id=j_id,
            tenant_id=tenant_id,
            spec=spec,
            status=JobStatus(status_str),
            output_path=output_path,
            error_message=error_message,
            created_at=datetime.fromtimestamp(created_at_ts).isoformat() + "Z" if created_at_ts else None,
            completed_at=datetime.fromtimestamp(completed_at_ts).isoformat() + "Z" if completed_at_ts else None,
            google_sheet_exported_at=gs_exported_at,
            google_sheet_row_id=gs_row_id,
        )

    def transition_job_status(self, job_id: str, new_status: JobStatus, output_path: Optional[str] = None, error_message: Optional[str] = None) -> RenderJob:
        """Atomically transitions job state validating state machine rules."""
        job = self.get_job(job_id)
        if not job:
            raise ValidationError(f"RenderJob with id '{job_id}' not found.")

        # Validate transition
        self._state_machine.transition(job.status, new_status)

        updated_job = RenderJob(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            spec=job.spec,
            status=new_status,
            output_path=output_path or job.output_path,
            error_message=error_message or job.error_message,
        )
        self.save_job(updated_job)
        return updated_job

    def list_jobs(self, tenant_id: Optional[str] = None, limit: int = 100) -> List[RenderJob]:
        """Lists jobs with optional tenant filtering."""
        with self._lock, self._get_connection() as conn:
            if tenant_id:
                cursor = conn.execute("""
                    SELECT job_id FROM render_jobs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?;
                """, (tenant_id, limit))
            else:
                cursor = conn.execute("""
                    SELECT job_id FROM render_jobs ORDER BY created_at DESC LIMIT ?;
                """, (limit,))
            job_ids = [r[0] for r in cursor.fetchall()]

        results = []
        for j_id in job_ids:
            job = self.get_job(j_id)
            if job:
                results.append(job)
        return results

    def delete_job(self, job_id: str) -> bool:
        """Deletes a job by ID. Returns True if deleted, False if not found."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM render_jobs WHERE job_id = ?;", (job_id,))
            return cursor.rowcount > 0

    def __len__(self) -> int:
        """Returns the total count of jobs in the store."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM render_jobs;")
            count = cursor.fetchone()[0]
        return count

    def __getitem__(self, job_id: str) -> RenderJob:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        return job

    def __setitem__(self, job_id: str, job: RenderJob) -> None:
        self.save_job(job)

    def __contains__(self, job_id: str) -> bool:
        return self.get_job(job_id) is not None

    def get(self, job_id: str, default: Optional[RenderJob] = None) -> Optional[RenderJob]:
        return self.get_job(job_id) or default

    def list_active_jobs(self, tenant_id: str) -> List[RenderJob]:
        """Returns jobs in PENDING or IN_PROGRESS state for a tenant."""
        active_statuses = (JobStatus.PENDING.value, JobStatus.IN_PROGRESS.value)
        placeholders = ",".join("?" * len(active_statuses))
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                f"SELECT job_id FROM render_jobs WHERE tenant_id = ? AND status IN ({placeholders}) ORDER BY created_at ASC;",
                (tenant_id, *active_statuses),
            )
            job_ids = [r[0] for r in cursor.fetchall()]
        return [job for jid in job_ids if (job := self.get_job(jid)) is not None]

    def list_history(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[RenderJob], int]:
        """Returns terminal-state jobs (completed/failed/cancelled) for a tenant.

        Supports optional status filter, job-id search, pagination, and returns
        the total matching count for the UI.
        """
        terminal_statuses = (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        )
        placeholders = ",".join("?" * len(terminal_statuses))
        conditions = ["tenant_id = ?", f"status IN ({placeholders})"]
        params: list = [tenant_id, *terminal_statuses]

        if status and status in terminal_statuses:
            conditions.append("status = ?")
            params.append(status)

        if search:
            conditions.append("job_id LIKE ?")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)
        with self._lock, self._get_connection() as conn:
            count_cursor = conn.execute(
                f"SELECT COUNT(*) FROM render_jobs WHERE {where};", params
            )
            total = count_cursor.fetchone()[0]

            cursor = conn.execute(
                f"SELECT job_id FROM render_jobs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (*params, limit, offset),
            )
            job_ids = [r[0] for r in cursor.fetchall()]

        jobs = [job for jid in job_ids if (job := self.get_job(jid)) is not None]
        return jobs, total

    def count_by_status(self, tenant_id: str) -> Dict[str, int]:
        """Returns a count of jobs per status for a tenant."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) FROM render_jobs WHERE tenant_id = ? GROUP BY status;",
                (tenant_id,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def update_export_tracking(
        self, job_id: str, exported_at: str, row_id: str
    ) -> None:
        """Records Google Sheets export metadata on a job."""
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """UPDATE render_jobs
                   SET google_sheet_exported_at = ?, google_sheet_row_id = ?, updated_at = ?
                   WHERE job_id = ?;""",
                (exported_at, row_id, time.time(), job_id),
            )

    def clear(self) -> None:
        """Clears all job records."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM render_jobs;")
