"""Tests for the Google Sheets export service: authorization checks, export
success/failure, duplicate export/update behavior, and rendering-remains-
successful-when-Sheets-fails isolation.

The Google Sheets REST API is mocked at the ``requests`` level so the tests
run without network access or real Google credentials. The export service
interface itself is exercised for real — only the HTTP transport is faked.
"""

import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from media_service.api.app import app, settings, job_store, google_sheets_service, idempotency_store
from media_service.integrations.google_sheets import GoogleSheetsExportService, ExportResult
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob

client = TestClient(app)

TEST_API_KEY = "test_gs_key_001"
TEST_TENANT = "tenant_gs_test"
settings.api_keys[TEST_API_KEY] = TEST_TENANT
HEADERS = {"X-API-Key": TEST_API_KEY}


def _make_completed_job(job_id: str, tenant_id: str = TEST_TENANT) -> RenderJob:
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
        status=JobStatus.COMPLETED,
        output_path=f"/tmp/out_{job_id}.mp4",
    )


@pytest.fixture(autouse=True)
def _clean_store():
    job_store.clear()
    idempotency_store.clear()
    yield
    job_store.clear()
    idempotency_store.clear()


# -- Service-level tests (direct, mocked HTTP) --------------------------------

def _mock_response(status_code=200, json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    mock.text = json.dumps(json_data or {})
    return mock


def test_export_service_not_configured():
    svc = GoogleSheetsExportService(client_id="", client_secret="", spreadsheet_id="")
    result = svc.export_jobs([_make_completed_job("j1")])
    assert result.status == "failed"
    assert "not configured" in result.errors[0].lower()


def test_export_service_not_authorized():
    svc = GoogleSheetsExportService(
        client_id="id", client_secret="secret", spreadsheet_id="sheet1",
        token_store_path="/tmp/nonexistent_token.json",
    )
    result = svc.export_jobs([_make_completed_job("j1")])
    assert result.status == "failed"
    assert "authorization" in result.errors[0].lower()


def test_export_service_success_with_mocked_http(tmp_path):
    token_path = str(tmp_path / "token.json")
    svc = GoogleSheetsExportService(
        client_id="id", client_secret="secret", redirect_uri="http://localhost/cb",
        spreadsheet_id="sheet1", token_store_path=token_path,
    )
    # Pre-populate a valid token.
    with open(token_path, "w") as f:
        json.dump({"access_token": "fake_token", "expires_at": time.time() + 3600, "refresh_token": "rt"}, f)

    job = _make_completed_job("export_ok_1")
    job_store.save_job(job)

    call_log = []

    def fake_request(method, url, **kwargs):
        call_log.append((method, url))
        if "batchUpdate" in url:
            return _mock_response(200, {})
        if url.endswith("/values") or "values" in url:
            if method == "GET":
                return _mock_response(200, {"values": []})  # no existing rows
            return _mock_response(200, {})
        if "append" in url:
            return _mock_response(200, {"updates": {}})
        return _mock_response(200, {})

    with patch("media_service.integrations.google_sheets.requests.request", side_effect=fake_request):
        result = svc.export_jobs([job])

    assert result.status == "success"
    assert result.exported == 1
    assert result.failed == 0


def test_export_service_updates_existing_row(tmp_path):
    """Re-exporting the same job should update the existing row, not append a duplicate."""
    token_path = str(tmp_path / "token.json")
    svc = GoogleSheetsExportService(
        client_id="id", client_secret="secret", redirect_uri="http://localhost/cb",
        spreadsheet_id="sheet1", token_store_path=token_path,
    )
    with open(token_path, "w") as f:
        json.dump({"access_token": "fake_token", "expires_at": time.time() + 3600, "refresh_token": "rt"}, f)

    job = _make_completed_job("dup_1")

    def fake_request(method, url, **kwargs):
        if "batchUpdate" in url:
            return _mock_response(200, {})
        if method == "GET" and "values" in url:
            # Simulate the job already existing in row 2.
            return _mock_response(200, {"values": [["Job ID"], ["dup_1"]]})
        if method == "PUT":
            return _mock_response(200, {})
        return _mock_response(200, {})

    with patch("media_service.integrations.google_sheets.requests.request", side_effect=fake_request):
        result = svc.export_jobs([job])

    assert result.status == "success"
    assert result.updated == 1
    assert result.exported == 0  # no new row — it was an update


def test_export_service_partial_failure(tmp_path):
    token_path = str(tmp_path / "token.json")
    svc = GoogleSheetsExportService(
        client_id="id", client_secret="secret", redirect_uri="http://localhost/cb",
        spreadsheet_id="sheet1", token_store_path=token_path,
    )
    with open(token_path, "w") as f:
        json.dump({"access_token": "fake_token", "expires_at": time.time() + 3600, "refresh_token": "rt"}, f)

    job_ok = _make_completed_job("partial_ok")
    job_fail = _make_completed_job("partial_fail")

    def fake_request(method, url, **kwargs):
        if "batchUpdate" in url:
            return _mock_response(200, {})
        if method == "GET" and "values" in url:
            return _mock_response(200, {"values": []})
        if "append" in url:
            # Simulate one success, one failure.
            body = kwargs.get("json", {})
            vals = body.get("values", [[]])
            if vals and vals[0] and vals[0][0] == "partial_fail":
                return _mock_response(500, {"error": "quota exceeded"})
            return _mock_response(200, {})
        return _mock_response(200, {})

    with patch("media_service.integrations.google_sheets.requests.request", side_effect=fake_request):
        result = svc.export_jobs([job_ok, job_fail])

    assert result.status == "partial"
    assert result.exported == 1
    assert result.failed == 1


# -- API-level tests ----------------------------------------------------------

def test_export_endpoint_not_configured():
    """When Google Sheets is not configured, the API returns a 503."""
    # Temporarily unconfigure the service.
    original = (google_sheets_service.client_id, google_sheets_service.client_secret,
                google_sheets_service.spreadsheet_id)
    google_sheets_service.client_id = ""
    google_sheets_service.client_secret = ""
    google_sheets_service.spreadsheet_id = ""
    try:
        res = client.post("/v1/export/google-sheets", json={"job_ids": None}, headers=HEADERS)
        assert res.status_code == 503
    finally:
        google_sheets_service.client_id, google_sheets_service.client_secret, \
            google_sheets_service.spreadsheet_id = original


def test_export_endpoint_requires_auth():
    res = client.post("/v1/export/google-sheets", json={"job_ids": None})
    assert res.status_code == 401


def test_export_endpoint_tenant_isolation():
    """Cannot export another tenant's jobs."""
    other_job = _make_completed_job("other_export", "tenant_other")
    job_store.save_job(other_job)

    # Configure the service so it passes the configured check.
    google_sheets_service.client_id = "id"
    google_sheets_service.client_secret = "secret"
    google_sheets_service.spreadsheet_id = "sheet1"
    google_sheets_service.redirect_uri = "http://localhost/cb"

    res = client.post("/v1/export/google-sheets", json={"job_ids": ["other_export"]}, headers=HEADERS)
    assert res.status_code == 403


def test_rendering_remains_successful_when_sheets_fails():
    """The core invariant: a render job completes successfully even if the
    Google Sheets export fails. This test verifies the export is decoupled
    from rendering by submitting a render job and confirming it completes,
    then confirming a failed export does not affect the job state.
    """
    # Submit a render job via the API — it should complete regardless of
    # Google Sheets configuration.
    res = client.post(
        "/v1/render-jobs",
        json={
            "job_id": "isolation_test_1",
            "tenant_id": TEST_TENANT,
            "spec": {
                "spec_id": "spec_iso",
                "source_media_id": "src_iso",
                "segments": [{"start_ms": 0, "end_ms": 3000}],
            },
        },
        headers=HEADERS,
    )
    assert res.status_code == 200
    assert res.json()["job"]["status"] == "completed"

    # Verify the job is in the store as completed.
    job = job_store.get_job("isolation_test_1")
    assert job is not None
    assert job.status == JobStatus.COMPLETED

    # Attempt an export with Sheets unconfigured — should fail, but the job
    # remains completed.
    google_sheets_service.client_id = ""
    google_sheets_service.spreadsheet_id = ""
    export_res = client.post(
        "/v1/export/google-sheets",
        json={"job_ids": ["isolation_test_1"]},
        headers=HEADERS,
    )
    assert export_res.status_code == 503

    # The job is still completed — export failure did not affect it.
    job_after = job_store.get_job("isolation_test_1")
    assert job_after.status == JobStatus.COMPLETED


def test_google_sheets_status_endpoint():
    res = client.get("/v1/integrations/google/status", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert "configured" in data
    assert "authorized" in data
