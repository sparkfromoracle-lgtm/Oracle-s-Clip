"""SQLite-backed persistence for social publishing: connected accounts and
social posts. Tokens are stored server-side only and never exposed to the
frontend. Tenant isolation is enforced at the query level.
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from shared.contracts.publishing import (
    AccountStatus,
    ConnectedAccount,
    PostStatus,
    SocialPost,
)


class PublishingStore:
    """Durable SQLite store for social publishing state."""

    def __init__(self, db_path: str = "/tmp/oracle_clip_publishing.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS connected_accounts (
                    account_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    platform_user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    connected_at TEXT NOT NULL,
                    scopes TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expires_at REAL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS social_posts (
                    post_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    render_job_id TEXT NOT NULL,
                    rendered_asset_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    platform_post_id TEXT,
                    status TEXT NOT NULL,
                    title TEXT,
                    caption TEXT,
                    hashtags TEXT,
                    privacy TEXT,
                    scheduled_at TEXT,
                    published_at TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    post_url TEXT,
                    auto_publish INTEGER DEFAULT 0,
                    compliance_verdict TEXT,
                    compliance_reasons TEXT,
                    video_path TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pa_tenant ON connected_accounts(tenant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sp_tenant ON social_posts(tenant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sp_status ON social_posts(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sp_platform ON social_posts(platform);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sp_render_job ON social_posts(render_job_id);")

    # -- Connected Accounts --------------------------------------------------

    def save_account(self, account: ConnectedAccount, access_token: str = "",
                      refresh_token: str = "", token_expires_at: float = 0) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT INTO connected_accounts (
                    account_id, tenant_id, platform, display_name, platform_user_id,
                    status, connected_at, scopes, access_token, refresh_token, token_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    status=excluded.status,
                    display_name=excluded.display_name,
                    access_token=excluded.access_token,
                    refresh_token=excluded.refresh_token,
                    token_expires_at=excluded.token_expires_at;
            """, (
                account.account_id, account.tenant_id, account.platform,
                account.display_name, account.platform_user_id,
                account.status, account.connected_at,
                json.dumps(account.scopes),
                access_token, refresh_token, token_expires_at,
            ))

    def get_account(self, account_id: str) -> Optional[Tuple[ConnectedAccount, str, str, float]]:
        """Returns (account, access_token, refresh_token, expires_at) or None."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT account_id, tenant_id, platform, display_name, platform_user_id,
                       status, connected_at, scopes, access_token, refresh_token, token_expires_at
                FROM connected_accounts WHERE account_id = ?;
            """, (account_id,))
            row = cursor.fetchone()
        if not row:
            return None
        (acc_id, tenant_id, platform, display_name, platform_user_id,
         status, connected_at, scopes_json, access_token, refresh_token, expires_at) = row
        account = ConnectedAccount(
            account_id=acc_id, tenant_id=tenant_id, platform=platform,
            display_name=display_name, platform_user_id=platform_user_id,
            status=status, connected_at=connected_at,
            scopes=json.loads(scopes_json) if scopes_json else [],
        )
        return account, access_token or "", refresh_token or "", expires_at or 0

    def list_accounts(self, tenant_id: str) -> List[ConnectedAccount]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT account_id, tenant_id, platform, display_name, platform_user_id,
                       status, connected_at, scopes
                FROM connected_accounts WHERE tenant_id = ? ORDER BY connected_at DESC;
            """, (tenant_id,))
            rows = cursor.fetchall()
        return [
            ConnectedAccount(
                account_id=r[0], tenant_id=r[1], platform=r[2], display_name=r[3],
                platform_user_id=r[4], status=r[5], connected_at=r[6],
                scopes=json.loads(r[7]) if r[7] else [],
            )
            for r in rows
        ]

    def update_account_status(self, account_id: str, status: str) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "UPDATE connected_accounts SET status = ? WHERE account_id = ?;",
                (status, account_id),
            )

    def delete_account(self, account_id: str) -> bool:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM connected_accounts WHERE account_id = ?;", (account_id,))
            return cursor.rowcount > 0

    def get_account_token(self, account_id: str) -> Optional[str]:
        """Returns the access token for an account. Server-side only — never
        returned to the frontend."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT access_token FROM connected_accounts WHERE account_id = ?;",
                (account_id,),
            )
            row = cursor.fetchone()
        return row[0] if row else None

    # -- Social Posts --------------------------------------------------------

    def save_post(self, post: SocialPost, video_path: str = "") -> None:
        now = time.time()
        created_at = now
        with self._lock, self._get_connection() as conn:
            existing = conn.execute(
                "SELECT created_at FROM social_posts WHERE post_id = ?;", (post.post_id,)
            ).fetchone()
            if existing:
                created_at = existing[0]
            conn.execute("""
                INSERT INTO social_posts (
                    post_id, tenant_id, render_job_id, rendered_asset_id, platform,
                    account_id, platform_post_id, status, title, caption, hashtags,
                    privacy, scheduled_at, published_at, error_message, retry_count,
                    post_url, auto_publish, compliance_verdict, compliance_reasons,
                    video_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    status=excluded.status,
                    platform_post_id=excluded.platform_post_id,
                    title=excluded.title,
                    caption=excluded.caption,
                    hashtags=excluded.hashtags,
                    privacy=excluded.privacy,
                    scheduled_at=excluded.scheduled_at,
                    published_at=COALESCE(social_posts.published_at, excluded.published_at),
                    error_message=excluded.error_message,
                    retry_count=excluded.retry_count,
                    post_url=excluded.post_url,
                    auto_publish=excluded.auto_publish,
                    compliance_verdict=excluded.compliance_verdict,
                    compliance_reasons=excluded.compliance_reasons,
                    updated_at=excluded.updated_at;
            """, (
                post.post_id, post.tenant_id, post.render_job_id, post.rendered_asset_id,
                post.platform, post.account_id, post.platform_post_id, post.status,
                post.title, post.caption, json.dumps(post.hashtags), post.privacy,
                post.scheduled_at, post.published_at, post.error_message, post.retry_count,
                post.post_url, int(post.auto_publish), post.compliance_verdict,
                json.dumps(post.compliance_reasons), video_path, created_at, now,
            ))

    def get_post(self, post_id: str) -> Optional[SocialPost]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT post_id, tenant_id, render_job_id, rendered_asset_id, platform,
                       account_id, platform_post_id, status, title, caption, hashtags,
                       privacy, scheduled_at, published_at, error_message, retry_count,
                       post_url, auto_publish, compliance_verdict, compliance_reasons,
                       created_at, updated_at
                FROM social_posts WHERE post_id = ?;
            """, (post_id,))
            row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_post(row)

    def list_posts(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SocialPost], int]:
        conditions = ["tenant_id = ?"]
        params: list = [tenant_id]
        if status:
            conditions.append("status = ?")
            params.append(status)
        if platform:
            conditions.append("platform = ?")
            params.append(platform)
        where = " AND ".join(conditions)
        with self._lock, self._get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM social_posts WHERE {where};", params
            ).fetchone()[0]
            cursor = conn.execute(
                f"SELECT post_id, tenant_id, render_job_id, rendered_asset_id, platform,"
                f" account_id, platform_post_id, status, title, caption, hashtags,"
                f" privacy, scheduled_at, published_at, error_message, retry_count,"
                f" post_url, auto_publish, compliance_verdict, compliance_reasons,"
                f" created_at, updated_at"
                f" FROM social_posts WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?;",
                (*params, limit, offset),
            )
            rows = cursor.fetchall()
        return [self._row_to_post(r) for r in rows], total

    def list_posts_by_render_job(self, render_job_id: str, tenant_id: str) -> List[SocialPost]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT post_id, tenant_id, render_job_id, rendered_asset_id, platform,
                   account_id, platform_post_id, status, title, caption, hashtags,
                   privacy, scheduled_at, published_at, error_message, retry_count,
                   post_url, auto_publish, compliance_verdict, compliance_reasons,
                   created_at, updated_at
                   FROM social_posts WHERE render_job_id = ? AND tenant_id = ?
                   ORDER BY created_at DESC;""",
                (render_job_id, tenant_id),
            )
            rows = cursor.fetchall()
        return [self._row_to_post(r) for r in rows]

    def get_post_video_path(self, post_id: str) -> Optional[str]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT video_path FROM social_posts WHERE post_id = ?;", (post_id,)
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def _row_to_post(self, row) -> SocialPost:
        return SocialPost(
            post_id=row[0], tenant_id=row[1], render_job_id=row[2], rendered_asset_id=row[3],
            platform=row[4], account_id=row[5], platform_post_id=row[6], status=row[7],
            title=row[8], caption=row[9],
            hashtags=json.loads(row[10]) if row[10] else [],
            privacy=row[11], scheduled_at=row[12], published_at=row[13],
            error_message=row[14], retry_count=row[15], post_url=row[16],
            auto_publish=bool(row[17]), compliance_verdict=row[18],
            compliance_reasons=json.loads(row[19]) if row[19] else [],
            created_at=datetime.fromtimestamp(row[20]).isoformat() + "Z" if row[20] else None,
            updated_at=datetime.fromtimestamp(row[21]).isoformat() + "Z" if row[21] else None,
        )

    def clear(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM connected_accounts;")
            conn.execute("DELETE FROM social_posts;")
