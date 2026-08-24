"""Durable SQLite store for the execution engine.

Three tables:

* ``engine_jobs`` — one row per production job, holding its current state, the
  stage cursor, measurable progress, output metadata, and the request that
  created it. This is the source of truth the UI reconstructs on refresh.
* ``engine_events`` — an append-only event log (event sourcing / audit). One
  structured event per state transition / stage action.
* ``engine_workers`` — one row per real worker thread, with its live state and
  the job it is currently executing (if any).

All writes are atomic and guarded by a single lock; reads are concurrent.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from media_service.engine.states import (
    EngineJobState,
    EngineStateMachine,
    WorkerState,
    ACTIVE_JOB_STATES,
    TERMINAL_JOB_STATES,
)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


class EngineStore:
    """SQLite-backed durable store for engine jobs, events, and workers."""

    def __init__(self, db_path: str = "/tmp/oracle_clip_engine.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # -- connection ---------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS engine_jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    stage_index INTEGER NOT NULL DEFAULT 0,
                    source_media_path TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    target_aspect_ratio TEXT NOT NULL DEFAULT '9:16',
                    publish INTEGER NOT NULL DEFAULT 0,
                    platform TEXT,
                    account_id TEXT,
                    worker_id TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    progress REAL NOT NULL DEFAULT 0.0,
                    progress_measurable INTEGER NOT NULL DEFAULT 0,
                    output_path TEXT,
                    asset_id TEXT,
                    quality_verdict TEXT,
                    quality_score REAL,
                    guardian_approved INTEGER,
                    rights_status TEXT NOT NULL DEFAULT 'rights_unknown',
                    schedule_decision TEXT,
                    publish_status TEXT,
                    post_id TEXT,
                    post_url TEXT,
                    analytics_status TEXT,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS engine_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    job_id TEXT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    worker_id TEXT,
                    previous_state TEXT,
                    new_state TEXT,
                    metadata TEXT,
                    error TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS engine_workers (
                    worker_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    current_job_id TEXT,
                    last_job_id TEXT,
                    jobs_completed INTEGER NOT NULL DEFAULT 0,
                    jobs_failed INTEGER NOT NULL DEFAULT 0,
                    started_at REAL,
                    last_heartbeat REAL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON engine_jobs(state);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON engine_jobs(tenant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_job ON engine_events(job_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON engine_events(timestamp);")

    # -- jobs ---------------------------------------------------------------

    def create_job(
        self,
        job_id: str,
        tenant_id: str,
        source_media_path: str,
        duration_ms: int,
        target_aspect_ratio: str = "9:16",
        publish: bool = False,
        platform: Optional[str] = None,
        account_id: Optional[str] = None,
        rights_status: str = "rights_unknown",
    ) -> Dict[str, Any]:
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO engine_jobs
                   (job_id, tenant_id, state, stage_index, source_media_path, duration_ms,
                    target_aspect_ratio, publish, platform, account_id, rights_status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    job_id, tenant_id, EngineJobState.CREATED.value,
                    source_media_path, duration_ms, target_aspect_ratio,
                    1 if publish else 0, platform, account_id, rights_status,
                    now, now,
                ),
            )
        self.append_event(
            event_type="job.created",
            job_id=job_id,
            source="api",
            new_state=EngineJobState.CREATED.value,
            metadata={
                "source_media_path": source_media_path,
                "duration_ms": duration_ms,
                "publish": publish,
                "platform": platform,
            },
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM engine_jobs WHERE job_id = ?;", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if tenant_id:
                rows = conn.execute(
                    "SELECT * FROM engine_jobs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?;",
                    (tenant_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM engine_jobs ORDER BY created_at DESC LIMIT ?;", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def list_active_jobs(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        states = [s.value for s in ACTIVE_JOB_STATES]
        placeholders = ",".join("?" * len(states))
        with self._lock, self._conn() as conn:
            if tenant_id:
                rows = conn.execute(
                    f"SELECT * FROM engine_jobs WHERE tenant_id = ? AND state IN ({placeholders}) ORDER BY created_at ASC;",
                    (tenant_id, *states),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM engine_jobs WHERE state IN ({placeholders}) ORDER BY created_at ASC;",
                    (*states,),
                ).fetchall()
        return [dict(r) for r in rows]

    def count_by_state(self, tenant_id: Optional[str] = None) -> Dict[str, int]:
        with self._lock, self._conn() as conn:
            if tenant_id:
                rows = conn.execute(
                    "SELECT state, COUNT(*) FROM engine_jobs WHERE tenant_id = ? GROUP BY state;",
                    (tenant_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT state, COUNT(*) FROM engine_jobs GROUP BY state;"
                ).fetchall()
        return {r[0]: r[1] for r in rows}

    def transition(
        self,
        job_id: str,
        new_state: EngineJobState,
        *,
        worker_id: Optional[str] = None,
        event_type: Optional[str] = None,
        event_source: str = "worker",
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        **field_updates,
    ) -> Dict[str, Any]:
        """Validate + persist a state transition, append an event, return the row."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Engine job '{job_id}' not found")

        current = EngineJobState(job["state"])
        EngineStateMachine.transition(current, new_state)

        now = time.time()
        completed_at = now if new_state in TERMINAL_JOB_STATES else None

        columns = ["state = ?", "updated_at = ?"]
        values: List[Any] = [new_state.value, now]
        if worker_id is not None:
            columns.append("worker_id = ?")
            values.append(worker_id)
        if completed_at is not None:
            columns.append("completed_at = ?")
            values.append(completed_at)
        for k, v in field_updates.items():
            columns.append(f"{k} = ?")
            values.append(v)
        values.append(job_id)

        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE engine_jobs SET {', '.join(columns)} WHERE job_id = ?;", values
            )

        self.append_event(
            event_type=event_type or f"job.{new_state.value}",
            job_id=job_id,
            source=event_source,
            worker_id=worker_id,
            previous_state=current.value,
            new_state=new_state.value,
            metadata=metadata,
            error=error,
        )
        return self.get_job(job_id)

    def claim_next_queued_job(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest QUEUED job for a worker.

        Holds the write lock + an immediate transaction so two workers can never
        claim the same job. Validates the QUEUED -> ASSIGNED transition.
        """
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                row = conn.execute(
                    "SELECT * FROM engine_jobs WHERE state = ? ORDER BY created_at ASC LIMIT 1;",
                    (EngineJobState.QUEUED.value,),
                ).fetchone()
                if not row:
                    conn.execute("ROLLBACK;")
                    return None
                job = dict(row)
                EngineStateMachine.transition(EngineJobState.QUEUED, EngineJobState.ASSIGNED)
                now = time.time()
                conn.execute(
                    "UPDATE engine_jobs SET state = ?, worker_id = ?, updated_at = ? WHERE job_id = ?;",
                    (EngineJobState.ASSIGNED.value, worker_id, now, job["job_id"]),
                )
                conn.execute(
                    """INSERT INTO engine_events
                       (event_id, event_type, job_id, timestamp, source, worker_id,
                        previous_state, new_state, metadata, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                    (
                        f"evt_{uuid.uuid4().hex[:16]}", "job.assigned", job["job_id"], _now_iso(),
                        "worker", worker_id, EngineJobState.QUEUED.value,
                        EngineJobState.ASSIGNED.value, None, None,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
            finally:
                conn.close()
        return self.get_job(job["job_id"])

    def update_fields(self, job_id: str, **fields) -> None:
        """Update non-state fields (progress, output metadata) without a transition."""
        if not fields:
            return
        cols = [f"{k} = ?" for k in fields]
        vals = list(fields.values()) + [time.time(), job_id]
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE engine_jobs SET {', '.join(cols)}, updated_at = ? WHERE job_id = ?;", vals
            )

    # -- events -------------------------------------------------------------

    def append_event(
        self,
        event_type: str,
        job_id: Optional[str],
        source: str,
        worker_id: Optional[str] = None,
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        meta_json = json.dumps(metadata) if metadata else None
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO engine_events
                   (event_id, event_type, job_id, timestamp, source, worker_id,
                    previous_state, new_state, metadata, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    event_id, event_type, job_id, _now_iso(), source, worker_id,
                    previous_state, new_state, meta_json, error,
                ),
            )
        return {
            "event_id": event_id,
            "event_type": event_type,
            "job_id": job_id,
            "timestamp": _now_iso(),
            "source": source,
            "worker_id": worker_id,
            "previous_state": previous_state,
            "new_state": new_state,
            "metadata": metadata,
            "error": error,
        }

    def list_events(self, job_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            if job_id:
                rows = conn.execute(
                    "SELECT * FROM engine_events WHERE job_id = ? ORDER BY rowid DESC LIMIT ?;",
                    (job_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM engine_events ORDER BY rowid DESC LIMIT ?;", (limit,)
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else None
            out.append(d)
        return out

    # -- workers ------------------------------------------------------------

    def register_worker(self, worker_id: str, state: WorkerState) -> None:
        now = time.time()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO engine_workers (worker_id, state, current_job_id, jobs_completed,
                   jobs_failed, started_at, last_heartbeat)
                   VALUES (?, ?, NULL, 0, 0, ?, ?)
                   ON CONFLICT(worker_id) DO UPDATE SET state=excluded.state, started_at=excluded.started_at;""",
                (worker_id, state.value, now, now),
            )

    def set_worker_state(
        self,
        worker_id: str,
        state: WorkerState,
        current_job_id: Optional[str] = None,
        increment_completed: bool = False,
        increment_failed: bool = False,
    ) -> None:
        now = time.time()
        cols = ["state = ?", "last_heartbeat = ?"]
        vals: List[Any] = [state.value, now]
        if current_job_id is not None:
            cols.append("current_job_id = ?")
            vals.append(current_job_id)
        if increment_completed:
            cols.append("jobs_completed = jobs_completed + 1")
        if increment_failed:
            cols.append("jobs_failed = jobs_failed + 1")
        vals.append(worker_id)
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE engine_workers SET {', '.join(cols)} WHERE worker_id = ?;", vals
            )

    def set_worker_last_job(self, worker_id: str, job_id: Optional[str]) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE engine_workers SET last_job_id = ?, last_heartbeat = ? WHERE worker_id = ?;",
                (job_id, time.time(), worker_id),
            )

    def heartbeat(self, worker_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE engine_workers SET last_heartbeat = ? WHERE worker_id = ?;",
                (time.time(), worker_id),
            )

    def list_workers(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT * FROM engine_workers ORDER BY worker_id;").fetchall()
        return [dict(r) for r in rows]

    def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM engine_workers WHERE worker_id = ?;", (worker_id,)).fetchone()
        return dict(row) if row else None

    # -- maintenance --------------------------------------------------------

    def clear(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM engine_jobs;")
            conn.execute("DELETE FROM engine_events;")
            conn.execute("DELETE FROM engine_workers;")
