"""Google Sheets export service for completed render jobs.

This module provides a clean, replaceable interface for exporting completed
RenderJob records to a Google Sheets spreadsheet. It uses Google's official
Sheets REST API via the ``requests`` library (already a project dependency),
so no heavyweight Google client SDK is required.

OAuth 2.0 is used for authorization. Credentials are NEVER hard-coded — they
are read from environment variables / application Settings. Access and refresh
tokens are persisted to a small JSON file so the user does not need to
re-authorize on every export.

Architecture rules:
- This service is completely decoupled from the orchestrator's rendering logic.
- If the export fails, the render job itself remains successful.
- Duplicate exports update an existing row (matched by Job ID) rather than
  appending a new row.
"""

import json
import logging
import os
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from shared.contracts.jobs import RenderJob

logger = logging.getLogger("oracle_clip.google_sheets")

# Google OAuth 2.0 endpoints.
GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

# The columns written to the spreadsheet, in order.
SHEET_COLUMNS = [
    "Job ID",
    "Tenant ID",
    "Source",
    "Output",
    "Render Type",
    "Status",
    "Started At",
    "Completed At",
    "Duration",
    "Error",
    "Created At",
]

# Scopes required for Sheets read/write access.
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


class ExportResult:
    """Outcome of a batch export operation."""

    def __init__(
        self,
        status: str,
        exported: int = 0,
        updated: int = 0,
        failed: int = 0,
        errors: Optional[List[str]] = None,
    ):
        self.status = status  # "success" | "partial" | "failed"
        self.exported = exported
        self.updated = updated
        self.failed = failed
        self.errors = errors or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "exported": self.exported,
            "updated": self.updated,
            "failed": self.failed,
            "errors": self.errors,
        }


class GoogleSheetsExportService:
    """Clean, replaceable Google Sheets export service.

    All Google-specific logic lives behind this class so it can be swapped for
    another spreadsheet provider without touching the orchestrator or API.
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        redirect_uri: str = "",
        spreadsheet_id: str = "",
        token_store_path: str = "/tmp/oracle_clip_google_token.json",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.spreadsheet_id = spreadsheet_id
        self.token_store_path = token_store_path

    # -- Configuration checks ------------------------------------------------

    def is_configured(self) -> bool:
        """Returns True if all required Google env vars are present."""
        return bool(self.client_id and self.client_secret and self.spreadsheet_id)

    def is_authorized(self) -> bool:
        """Returns True if a valid (non-expired) access token is available."""
        token = self._load_token()
        if not token:
            return False
        expires_at = token.get("expires_at", 0)
        return time.time() < expires_at - 60  # 60s safety margin

    # -- OAuth flow ----------------------------------------------------------

    def get_auth_url(self, state: Optional[str] = None) -> str:
        """Builds the Google OAuth 2.0 authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SHEETS_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{GOOGLE_AUTH_BASE}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchanges an OAuth authorization code for access/refresh tokens.

        Persists the token to disk for future use. Raises ``RuntimeError`` on
        failure.
        """
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Google OAuth token exchange failed: {resp.text}")

        token_data = resp.json()
        token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600)
        self._save_token(token_data)
        return token_data

    def _refresh_access_token(self) -> Optional[Dict[str, Any]]:
        """Refreshes an expired access token using the stored refresh token."""
        token = self._load_token()
        if not token or not token.get("refresh_token"):
            return None

        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"Google token refresh failed: {resp.text}")
            return None

        new_data = resp.json()
        token["access_token"] = new_data["access_token"]
        token["expires_at"] = time.time() + new_data.get("expires_in", 3600)
        self._save_token(token)
        return token

    def _get_access_token(self) -> str:
        """Returns a valid access token, refreshing if necessary."""
        if self.is_authorized():
            return self._load_token()["access_token"]
        refreshed = self._refresh_access_token()
        if refreshed:
            return refreshed["access_token"]
        raise RuntimeError(
            "Google Sheets authorization has expired. Re-authorize via the OAuth flow."
        )

    # -- Token persistence ---------------------------------------------------

    def _load_token(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.token_store_path):
            return None
        try:
            with open(self.token_store_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _save_token(self, token: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.token_store_path)), exist_ok=True)
        with open(self.token_store_path, "w") as f:
            json.dump(token, f)

    # -- Sheets operations ---------------------------------------------------

    def _sheets_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Makes an authenticated request to the Google Sheets REST API."""
        token = self._get_access_token()
        url = f"{GOOGLE_SHEETS_API}/{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        return requests.request(method, url, headers=headers, timeout=60, **kwargs)

    def _ensure_header_row(self) -> str:
        """Ensures the sheet has a header row. Returns the sheet name."""
        # Use the first sheet (SpreadsheetId's default sheet).
        sheet_name = "Render Jobs"

        # Try to create the sheet; ignore error if it already exists.
        self._sheets_request(
            "POST",
            f"{self.spreadsheet_id}:batchUpdate",
            json={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {"title": sheet_name}
                        }
                    }
                ]
            },
        )

        # Write the header row.
        self._sheets_request(
            "PUT",
            f"{self.spreadsheet_id}/values/{urllib.parse.quote(sheet_name + '!A1:K1')}",
            json={"values": [SHEET_COLUMNS]},
            params={"valueInputOption": "RAW"},
        )
        return sheet_name

    def _find_existing_row(self, sheet_name: str, job_id: str) -> Optional[int]:
        """Finds the row number for an already-exported job by Job ID (column A).

        Returns the 1-based row number, or None if not found.
        """
        resp = self._sheets_request(
            "GET",
            f"{self.spreadsheet_id}/values/{urllib.parse.quote(sheet_name + '!A:A')}",
        )
        if resp.status_code != 200:
            return None
        values = resp.json().get("values", [])
        for i, row in enumerate(values):
            if row and row[0] == job_id:
                return i + 1  # 1-based row number
        return None

    @staticmethod
    def _job_to_row(job: RenderJob) -> List[str]:
        """Maps a RenderJob to the spreadsheet row format."""
        render_type = job.spec.target_aspect_ratio or "9:16"
        source = job.spec.source_media_id or ""
        output = job.output_path or ""
        duration = ""
        if job.created_at and job.completed_at:
            try:
                start = datetime.fromisoformat(job.created_at.replace("Z", ""))
                end = datetime.fromisoformat(job.completed_at.replace("Z", ""))
                duration = f"{(end - start).total_seconds():.1f}s"
            except (ValueError, TypeError):
                pass
        return [
            job.job_id,
            job.tenant_id,
            source,
            output,
            render_type,
            job.status.value if hasattr(job.status, "value") else str(job.status),
            job.created_at or "",
            job.completed_at or "",
            duration,
            job.error_message or "",
            job.created_at or "",
        ]

    def export_jobs(self, jobs: List[RenderJob]) -> ExportResult:
        """Exports a list of completed RenderJobs to Google Sheets.

        - Creates the sheet and header row if needed.
        - For each job, updates the existing row if the Job ID is already
          present; otherwise appends a new row.
        - Returns an ExportResult summarising the outcome.
        """
        if not self.is_configured():
            return ExportResult(
                status="failed",
                errors=["Google Sheets is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_SHEETS_SPREADSHEET_ID."],
            )
        if not self.is_authorized():
            return ExportResult(
                status="failed",
                errors=["Google Sheets authorization has expired. Re-authorize via the OAuth flow."],
            )

        if not jobs:
            return ExportResult(status="success")

        try:
            sheet_name = self._ensure_header_row()
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheet: {e}")
            return ExportResult(status="failed", errors=[str(e)])

        exported = 0
        updated = 0
        failed = 0
        errors: List[str] = []
        now_iso = datetime.utcnow().isoformat() + "Z"

        for job in jobs:
            row_data = self._job_to_row(job)
            try:
                existing_row = self._find_existing_row(sheet_name, job.job_id)
                if existing_row is not None:
                    # Update existing row.
                    cell_range = f"{sheet_name}!A{existing_row}:K{existing_row}"
                    resp = self._sheets_request(
                        "PUT",
                        f"{self.spreadsheet_id}/values/{urllib.parse.quote(cell_range)}",
                        json={"values": [row_data]},
                        params={"valueInputOption": "RAW"},
                    )
                    if resp.status_code == 200:
                        updated += 1
                    else:
                        failed += 1
                        errors.append(f"Job {job.job_id}: update failed ({resp.status_code})")
                else:
                    # Append new row.
                    resp = self._sheets_request(
                        "POST",
                        f"{self.spreadsheet_id}/values/{urllib.parse.quote(sheet_name + '!A:K')}:append",
                        json={"values": [row_data]},
                        params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                    )
                    if resp.status_code == 200:
                        exported += 1
                    else:
                        failed += 1
                        errors.append(f"Job {job.job_id}: append failed ({resp.status_code})")
            except Exception as e:
                failed += 1
                errors.append(f"Job {job.job_id}: {e}")

        if failed == 0:
            status = "success"
        elif exported > 0 or updated > 0:
            status = "partial"
        else:
            status = "failed"

        return ExportResult(status=status, exported=exported, updated=updated, failed=failed, errors=errors)
