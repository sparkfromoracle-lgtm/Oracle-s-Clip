import os
import json
import sqlite3
import time
import threading
from typing import Any, Dict, Optional, Tuple


class IdempotencyStore:
    """Thread-safe and process-restart resilient idempotency cache with TTL,
    execution locks, and SQLite persistence.
    """

    def __init__(self, default_ttl_seconds: int = 86400, db_path: Optional[str] = None):
        self.default_ttl_seconds = default_ttl_seconds
        self.db_path = db_path if db_path is not None else os.getenv("ORACLE_CLIP_IDEMPOTENCY_DB", "/tmp/oracle_clip_idempotency.db")
        self._lock = threading.Lock()
        self._memory_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
        elif self.db_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    key TEXT PRIMARY KEY,
                    payload_json TEXT,
                    expiry REAL NOT NULL,
                    is_in_progress INTEGER NOT NULL
                );
            """)
            if self._memory_conn is None:
                conn.commit()
                conn.close()
            else:
                conn.commit()

    def get(self, key: str) -> Optional[Any]:
        """Retrieves cached response if valid and not expired."""
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT payload_json, expiry, is_in_progress FROM idempotency_records WHERE key = ?;
            """, (key,))
            row = cursor.fetchone()

            result = None
            if row:
                payload_json, expiry, in_progress = row
                if now < expiry and not bool(in_progress) and payload_json is not None:
                    try:
                        result = json.loads(payload_json)
                    except Exception:
                        result = None
                elif now >= expiry:
                    conn.execute("DELETE FROM idempotency_records WHERE key = ?;", (key,))
                    conn.commit()

            if self._memory_conn is None:
                conn.close()
            return result

    def acquire_lock(self, key: str) -> bool:
        """Attempts to lock a key for an in-flight operation.
        
        Returns True if acquired (first time), False if already in-progress or cached.
        """
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT expiry, is_in_progress FROM idempotency_records WHERE key = ?;
            """, (key,))
            row = cursor.fetchone()

            if row:
                expiry, in_progress = row
                if now < expiry:
                    if self._memory_conn is None:
                        conn.close()
                    return False  # Already cached or in-progress

            # Insert or replace in-progress marker
            conn.execute("""
                INSERT INTO idempotency_records (key, payload_json, expiry, is_in_progress)
                VALUES (?, NULL, ?, 1)
                ON CONFLICT(key) DO UPDATE SET
                    payload_json = NULL,
                    expiry = excluded.expiry,
                    is_in_progress = 1;
            """, (key, now + self.default_ttl_seconds))
            conn.commit()
            if self._memory_conn is None:
                conn.close()
            return True

    @staticmethod
    def _json_serial(obj):
        """JSON serializer for objects not serializable by default json code."""
        if hasattr(obj, "value"):
            return obj.value
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items()}
        return str(obj)

    def put(self, key: str, payload: Any, ttl_seconds: Optional[int] = None) -> None:
        """Stores result payload for idempotency key."""
        ttl = ttl_seconds or self.default_ttl_seconds
        expiry = time.time() + ttl
        payload_json = json.dumps(payload, default=self._json_serial)
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                INSERT INTO idempotency_records (key, payload_json, expiry, is_in_progress)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    expiry = excluded.expiry,
                    is_in_progress = 0;
            """, (key, payload_json, expiry))
            conn.commit()
            if self._memory_conn is None:
                conn.close()

    def release_lock_on_failure(self, key: str) -> None:
        """Cleans up in-progress lock if operation failed."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM idempotency_records WHERE key = ? AND is_in_progress = 1;", (key,))
            conn.commit()
            if self._memory_conn is None:
                conn.close()

    def clear(self) -> None:
        """Clears all stored entries."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM idempotency_records;")
            conn.commit()
            if self._memory_conn is None:
                conn.close()
