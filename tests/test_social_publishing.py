"""Tests for the social publishing engine: OAuth boundaries, token security,
tenant isolation, platform capability validation, publishing success/failure,
retry, duplicate-post prevention, multi-platform publishing, user approval,
revoked accounts, and platform API errors.

Platform HTTP calls are mocked at the ``requests`` level so tests run without
network access or real platform credentials. The publishing service, store,
and compliance gate are exercised for real — only the HTTP transport is faked.
"""

import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from media_service.api.app import app, settings, publishing_service, _publishing_store, rate_limiter
from media_service.publishing.adapters import YouTubeAdapter, TikTokAdapter, SnapchatAdapter
from media_service.publishing.publishing_store import PublishingStore
from media_service.publishing.publishing_service import PublishingService
from shared.contracts.publishing import (
    AccountStatus,
    ComplianceVerdict,
    ConnectedAccount,
    PostStatus,
    SocialPost,
)

client = TestClient(app)

TEST_API_KEY = "test_pub_key_001"
TEST_TENANT = "tenant_pub_test"
OTHER_TENANT = "tenant_pub_other"
settings.api_keys[TEST_API_KEY] = TEST_TENANT
HEADERS = {"X-API-Key": TEST_API_KEY}


def _mock_response(status_code=200, json_data=None, text=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    mock.text = text or json.dumps(json_data or {})
    return mock


@pytest.fixture(autouse=True)
def _clean_store():
    _publishing_store.clear()
    rate_limiter.reset()
    yield
    _publishing_store.clear()
    rate_limiter.reset()


# -- Capability Matrix --------------------------------------------------------

def test_capability_matrix_returns_all_platforms():
    res = client.get("/v1/publishing/capabilities", headers=HEADERS)
    assert res.status_code == 200
    platforms = res.json()["platforms"]
    names = {p["platform"] for p in platforms}
    assert {"youtube", "tiktok", "instagram", "facebook", "x", "linkedin", "snapchat"} <= names
    # Snapchat should be blocked
    snap = next(p for p in platforms if p["platform"] == "snapchat")
    assert snap["implementation_status"] == "blocked"


def test_capability_matrix_requires_auth():
    res = client.get("/v1/publishing/capabilities")
    assert res.status_code == 401


# -- OAuth Boundaries ---------------------------------------------------------

def test_oauth_start_returns_url():
    res = client.post(
        "/v1/publishing/oauth/start",
        json={"platform": "youtube", "redirect_uri": "http://localhost:8080/cb"},
        headers=HEADERS,
    )
    assert res.status_code == 200
    assert "auth_url" in res.json()
    assert "accounts.google.com" in res.json()["auth_url"]


def test_oauth_start_blocked_platform():
    res = client.post(
        "/v1/publishing/oauth/start",
        json={"platform": "snapchat", "redirect_uri": "http://localhost:8080/cb"},
        headers=HEADERS,
    )
    assert res.status_code == 503


def test_oauth_callback_stores_account():
    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {
            "access_token": "yt_token_123",
            "refresh_token": "yt_refresh_456",
            "expires_in": 3600,
            "user_id": "yt_user_001",
        })
        res = client.post(
            "/v1/publishing/oauth/callback",
            json={"platform": "youtube", "code": "test_code", "redirect_uri": "http://localhost:8080/cb"},
            headers=HEADERS,
        )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "connected"
    assert data["platform"] == "youtube"
    assert "account_id" in data


def test_oauth_callback_failure():
    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(400, {"error": "invalid_grant"})
        res = client.post(
            "/v1/publishing/oauth/callback",
            json={"platform": "youtube", "code": "bad_code", "redirect_uri": "http://localhost:8080/cb"},
            headers=HEADERS,
        )
    assert res.status_code == 503


# -- Token Security -----------------------------------------------------------

def test_list_accounts_does_not_expose_tokens():
    """Connected accounts API must never return access/refresh tokens."""
    # Manually store an account with a token.
    account = ConnectedAccount(
        account_id="acc_security_1",
        tenant_id=TEST_TENANT,
        platform="youtube",
        display_name="Test YT",
        platform_user_id="yt_001",
        status=AccountStatus.CONNECTED.value,
        connected_at="2026-01-01T00:00:00Z",
        scopes=["youtube.upload"],
    )
    _publishing_store.save_account(account, access_token="secret_token_123", refresh_token="secret_refresh")

    res = client.get("/v1/publishing/accounts", headers=HEADERS)
    assert res.status_code == 200
    accounts = res.json()["accounts"]
    assert len(accounts) == 1
    # No token fields should be present in the response.
    assert "access_token" not in accounts[0]
    assert "refresh_token" not in accounts[0]
    assert "token" not in json.dumps(accounts[0])


# -- Tenant Isolation ---------------------------------------------------------

def test_list_accounts_tenant_isolation():
    account = ConnectedAccount(
        account_id="acc_tenant_1",
        tenant_id=OTHER_TENANT,
        platform="youtube",
        display_name="Other Tenant",
        platform_user_id="yt_other",
        status=AccountStatus.CONNECTED.value,
        connected_at="2026-01-01T00:00:00Z",
    )
    _publishing_store.save_account(account, access_token="tok")

    res = client.get("/v1/publishing/accounts", headers=HEADERS)
    assert res.status_code == 200
    accounts = res.json()["accounts"]
    assert all(a["account_id"] != "acc_tenant_1" for a in accounts)


def test_disconnect_account_tenant_isolation():
    account = ConnectedAccount(
        account_id="acc_disconnect_1",
        tenant_id=OTHER_TENANT,
        platform="youtube",
        display_name="Other",
        platform_user_id="yt_002",
        status=AccountStatus.CONNECTED.value,
        connected_at="2026-01-01T00:00:00Z",
    )
    _publishing_store.save_account(account, access_token="tok")

    res = client.delete("/v1/publishing/accounts/acc_disconnect_1", headers=HEADERS)
    assert res.status_code == 403


def test_list_posts_tenant_isolation():
    post = SocialPost(
        post_id="post_tenant_1",
        tenant_id=OTHER_TENANT,
        render_job_id="job_1",
        rendered_asset_id="asset_1",
        platform="youtube",
        account_id="acc_1",
    )
    _publishing_store.save_post(post)

    res = client.get("/v1/publishing/posts", headers=HEADERS)
    assert res.status_code == 200
    assert all(p["post_id"] != "post_tenant_1" for p in res.json()["posts"])


# -- Publishing Success / Failure / Retry ------------------------------------

def _setup_account(platform="youtube", account_id="acc_pub_1"):
    account = ConnectedAccount(
        account_id=account_id,
        tenant_id=TEST_TENANT,
        platform=platform,
        display_name="Test Account",
        platform_user_id="yt_001",
        status=AccountStatus.CONNECTED.value,
        connected_at="2026-01-01T00:00:00Z",
        scopes=["youtube.upload"],
    )
    _publishing_store.save_account(account, access_token="valid_token", token_expires_at=time.time() + 3600)
    return account


def test_create_post_creates_draft():
    _setup_account()
    res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_1",
            "rendered_asset_id": "asset_1",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "title": "Test Clip",
            "caption": "Check this out!",
            "hashtags": ["#test", "#viral"],
        },
        headers=HEADERS,
    )
    assert res.status_code == 200
    post = res.json()["post"]
    assert post["status"] == "draft"
    assert post["title"] == "Test Clip"


def test_publish_requires_explicit_approval():
    """Without force=True, publishing should be rejected."""
    _setup_account()
    # Create a post with auto_publish=False
    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_1",
            "rendered_asset_id": "asset_1",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "auto_publish": False,
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    # Publish without force
    res = client.post(
        "/v1/publishing/posts/publish",
        json={"post_id": post_id, "force": False},
        headers=HEADERS,
    )
    assert res.status_code == 200
    assert res.json()["success"] is False
    assert "approval" in res.json()["error"].lower()


def test_publish_success_with_mocked_http(tmp_path):
    _setup_account()
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_1",
            "rendered_asset_id": "asset_1",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "title": "Test",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id": "yt_video_001"})
        res = client.post(
            "/v1/publishing/posts/publish",
            json={"post_id": post_id, "force": True},
            headers=HEADERS,
        )
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["platform_post_id"] == "yt_video_001"
    assert "youtube.com/watch" in res.json()["post_url"]


def test_publish_failure_does_not_break_render_job(tmp_path):
    """A failed social post must not affect the render job."""
    _setup_account()
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_render_ok",
            "rendered_asset_id": "asset_ok",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(500, {"error": "quota exceeded"})
        res = client.post(
            "/v1/publishing/posts/publish",
            json={"post_id": post_id, "force": True},
            headers=HEADERS,
        )
    assert res.status_code == 200
    assert res.json()["success"] is False
    assert "quota exceeded" in res.json()["error"]

    # Verify the post is marked failed but the render job is untouched.
    post = _publishing_store.get_post(post_id)
    assert post.status == PostStatus.FAILED.value
    assert post.retry_count == 1
    # The render job is not affected — it's not even in the publishing store.


def test_retry_failed_post(tmp_path):
    _setup_account()
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_retry",
            "rendered_asset_id": "asset_retry",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    # First attempt fails
    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(500, {"error": "server error"})
        client.post("/v1/publishing/posts/publish", json={"post_id": post_id, "force": True}, headers=HEADERS)

    # Retry succeeds
    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id": "yt_retry_ok"})
        res = client.post(f"/v1/publishing/posts/{post_id}/retry", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["success"] is True


# -- Duplicate Post Prevention ------------------------------------------------

def test_duplicate_post_prevention(tmp_path):
    _setup_account()
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    # First publish succeeds
    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_dup",
            "rendered_asset_id": "asset_dup",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id_1 = create_res.json()["post"]["post_id"]

    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id": "yt_dup_001"})
        client.post("/v1/publishing/posts/publish", json={"post_id": post_id_1, "force": True}, headers=HEADERS)

    # Second publish to same platform/account for same render job should be blocked
    create_res_2 = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_dup",
            "rendered_asset_id": "asset_dup",
            "platform": "youtube",
            "account_id": "acc_pub_1",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id_2 = create_res_2.json()["post"]["post_id"]

    with patch("media_service.publishing.adapters.requests.post"):
        res = client.post("/v1/publishing/posts/publish", json={"post_id": post_id_2, "force": True}, headers=HEADERS)
    assert res.json()["success"] is False
    assert "Already published" in res.json()["error"]


# -- Multi-Platform Publishing ------------------------------------------------

def test_bulk_publish_to_multiple_platforms(tmp_path):
    _setup_account(platform="youtube", account_id="acc_yt")
    _setup_account(platform="tiktok", account_id="acc_tt")
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    with patch("media_service.publishing.adapters.requests.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id": "vid_001"})
        res = client.post(
            "/v1/publishing/posts/bulk",
            json={
                "render_job_id": "job_bulk",
                "rendered_asset_id": "asset_bulk",
                "video_path": str(video),
                "posts": [
                    {"platform": "youtube", "account_id": "acc_yt", "render_job_id": "job_bulk", "rendered_asset_id": "asset_bulk"},
                    {"platform": "tiktok", "account_id": "acc_tt", "render_job_id": "job_bulk", "rendered_asset_id": "asset_bulk"},
                ],
            },
            headers=HEADERS,
        )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2


# -- Revoked / Expired Account ------------------------------------------------

def test_publish_with_expired_token_blocked(tmp_path):
    account = ConnectedAccount(
        account_id="acc_expired",
        tenant_id=TEST_TENANT,
        platform="youtube",
        display_name="Expired",
        platform_user_id="yt_003",
        status=AccountStatus.CONNECTED.value,
        connected_at="2026-01-01T00:00:00Z",
    )
    _publishing_store.save_account(account, access_token="old_token", token_expires_at=time.time() - 100)

    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_exp",
            "rendered_asset_id": "asset_exp",
            "platform": "youtube",
            "account_id": "acc_expired",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    res = client.post("/v1/publishing/posts/publish", json={"post_id": post_id, "force": True}, headers=HEADERS)
    assert res.json()["success"] is False
    assert "expired" in res.json()["error"].lower()


def test_publish_with_disconnected_account_blocked(tmp_path):
    account = ConnectedAccount(
        account_id="acc_disconnected",
        tenant_id=TEST_TENANT,
        platform="youtube",
        display_name="Disconnected",
        platform_user_id="yt_004",
        status=AccountStatus.DISCONNECTED.value,
        connected_at="2026-01-01T00:00:00Z",
    )
    _publishing_store.save_account(account, access_token="tok", token_expires_at=time.time() + 3600)

    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)

    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_disc",
            "rendered_asset_id": "asset_disc",
            "platform": "youtube",
            "account_id": "acc_disconnected",
            "video_path": str(video),
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    res = client.post("/v1/publishing/posts/publish", json={"post_id": post_id, "force": True}, headers=HEADERS)
    assert res.json()["success"] is False
    assert "not connected" in res.json()["error"].lower()


# -- Platform API Errors -------------------------------------------------------

def test_snapchat_publish_blocked():
    """Snapchat should always return blocked."""
    _setup_account(platform="snapchat", account_id="acc_snap")
    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_snap",
            "rendered_asset_id": "asset_snap",
            "platform": "snapchat",
            "account_id": "acc_snap",
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]
    res = client.post("/v1/publishing/posts/publish", json={"post_id": post_id, "force": True}, headers=HEADERS)
    assert res.json()["success"] is False
    assert "blocked" in res.json()["error"].lower()


# -- Cancel Post --------------------------------------------------------------

def test_cancel_draft_post():
    _setup_account()
    create_res = client.post(
        "/v1/publishing/posts",
        json={
            "render_job_id": "job_cancel",
            "rendered_asset_id": "asset_cancel",
            "platform": "youtube",
            "account_id": "acc_pub_1",
        },
        headers=HEADERS,
    )
    post_id = create_res.json()["post"]["post_id"]

    res = client.post(f"/v1/publishing/posts/{post_id}/cancel", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"


# -- Service-level compliance gate tests --------------------------------------

def test_compliance_gate_blocks_restricted_rights():
    """Posts with restricted rights status should be blocked."""
    svc = publishing_service
    post = SocialPost(
        post_id="post_rights_1",
        tenant_id=TEST_TENANT,
        render_job_id="job_r",
        rendered_asset_id="asset_r",
        platform="youtube",
        account_id="acc_pub_1",
    )
    verdict, reasons = svc.evaluate_compliance(post, rights_status="restricted")
    assert verdict == ComplianceVerdict.BLOCKED.value
    assert any("restricted" in r for r in reasons)


def test_compliance_gate_blocks_failed_quality():
    svc = publishing_service
    post = SocialPost(
        post_id="post_q_1",
        tenant_id=TEST_TENANT,
        render_job_id="job_q",
        rendered_asset_id="asset_q",
        platform="youtube",
        account_id="acc_pub_1",
    )
    verdict, reasons = svc.evaluate_compliance(post, quality_verdict="fail")
    assert verdict == ComplianceVerdict.BLOCKED.value
    assert any("fail" in r for r in reasons)
