"""Publishing service: orchestrates platform adapters and the publishing store.

This service is completely decoupled from the render pipeline. It consumes
completed RenderJob/RenderedAsset records and publishes them to social platforms
via per-platform adapters. A failed social post never invalidates a render job.

Compliance gate: before publishing, the service evaluates rights, policy risk,
and content quality. A post must be READY to publish. BLOCKED posts are never
published.
"""

import logging
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from shared.contracts.publishing import (
    AccountStatus,
    ComplianceVerdict,
    ConnectedAccount,
    PostStatus,
    PublishResult,
    SocialPost,
)
from media_service.publishing import PlatformAdapter
from media_service.publishing.publishing_store import PublishingStore

logger = logging.getLogger("oracle_clip.publishing.service")


class PublishingService:
    """Coordinates social publishing across multiple platforms."""

    def __init__(self, store: PublishingStore, adapters: Dict[str, PlatformAdapter]):
        self.store = store
        self.adapters = adapters

    # -- Capability Matrix ---------------------------------------------------

    def get_capability_matrix(self) -> List[Dict[str, Any]]:
        """Returns the capability matrix for all registered platforms."""
        matrix = []
        for name, adapter in self.adapters.items():
            caps = adapter.get_capabilities()
            matrix.append({
                "platform": caps.platform,
                "supports_video": caps.supports_video,
                "supports_caption": caps.supports_caption,
                "supports_title": caps.supports_title,
                "supports_hashtags": caps.supports_hashtags,
                "supports_privacy": caps.supports_privacy,
                "supports_scheduling": caps.supports_scheduling,
                "supports_thumbnail": caps.supports_thumbnail,
                "max_video_duration_seconds": caps.max_video_duration_seconds,
                "supported_aspect_ratios": caps.supported_aspect_ratios,
                "oauth_scopes": caps.oauth_scopes,
                "implementation_status": caps.implementation_status,
            })
        return matrix

    # -- OAuth / Account Management ------------------------------------------

    def start_oauth(self, tenant_id: str, platform: str, redirect_uri: str) -> str:
        """Returns the OAuth authorization URL for a platform."""
        adapter = self.adapters.get(platform)
        if not adapter:
            raise ValueError(f"Unknown platform: {platform}")
        if adapter.get_capabilities().implementation_status == "blocked":
            raise RuntimeError(f"Platform '{platform}' is blocked by API requirements.")
        state = f"{tenant_id}:{platform}"
        return adapter.get_oauth_url(redirect_uri=redirect_uri, state=state)

    def complete_oauth(self, tenant_id: str, platform: str, code: str, redirect_uri: str) -> ConnectedAccount:
        """Exchanges OAuth code and stores the connected account + token."""
        adapter = self.adapters.get(platform)
        if not adapter:
            raise ValueError(f"Unknown platform: {platform}")

        token_data = adapter.exchange_oauth_code(code=code, redirect_uri=redirect_uri)

        account_id = f"acc_{platform}_{uuid.uuid4().hex[:8]}"
        account = ConnectedAccount(
            account_id=account_id,
            tenant_id=tenant_id,
            platform=platform,
            display_name=token_data.get("display_name", f"{platform} Account"),
            platform_user_id=token_data.get("platform_user_id", ""),
            status=AccountStatus.CONNECTED.value,
            connected_at=datetime.utcnow().isoformat() + "Z",
            scopes=adapter.get_capabilities().oauth_scopes,
        )
        self.store.save_account(
            account,
            access_token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token", ""),
            token_expires_at=time.time() + token_data.get("expires_in", 3600),
        )
        return account

    def disconnect_account(self, tenant_id: str, account_id: str) -> bool:
        """Revokes the platform token and removes the account."""
        result = self.store.get_account(account_id)
        if not result:
            return False
        account, access_token, _, _ = result
        if account.tenant_id != tenant_id:
            raise PermissionError("Tenant isolation violation: account belongs to another tenant.")

        adapter = self.adapters.get(account.platform)
        if adapter and access_token:
            try:
                adapter.revoke_token(access_token)
            except Exception as e:
                logger.warning(f"Token revocation failed for {account.platform}: {e}")

        self.store.delete_account(account_id)
        return True

    def list_accounts(self, tenant_id: str) -> List[ConnectedAccount]:
        return self.store.list_accounts(tenant_id)

    # -- Compliance Gate ------------------------------------------------------

    def evaluate_compliance(
        self,
        post: SocialPost,
        rights_status: str = "rights_unknown",
        quality_verdict: str = "pass",
    ) -> Tuple[str, List[str]]:
        """Evaluates compliance before publishing.

        Returns (verdict, reasons). BLOCKED posts are never published.
        """
        reasons: List[str] = []

        # 1. Rights check
        if rights_status in ("restricted", "claimed", "not_monetizable"):
            reasons.append(f"Rights status is '{rights_status}' — publishing blocked.")
            return ComplianceVerdict.BLOCKED.value, reasons

        # 2. Quality check
        if quality_verdict == "fail":
            reasons.append("Quality verdict is 'fail' — publishing blocked.")
            return ComplianceVerdict.BLOCKED.value, reasons

        # 3. Platform blocked check
        adapter = self.adapters.get(post.platform)
        if not adapter:
            reasons.append(f"Unknown platform: {post.platform}")
            return ComplianceVerdict.BLOCKED.value, reasons

        caps = adapter.get_capabilities()
        if caps.implementation_status == "blocked":
            reasons.append(f"Platform '{post.platform}' is blocked by API requirements.")
            return ComplianceVerdict.BLOCKED.value, reasons

        # 4. Account authorization check
        account_data = self.store.get_account(post.account_id)
        if not account_data:
            reasons.append("Connected account not found.")
            return ComplianceVerdict.BLOCKED.value, reasons

        account, _, _, expires_at = account_data
        if account.tenant_id != post.tenant_id:
            reasons.append("Account belongs to another tenant.")
            return ComplianceVerdict.BLOCKED.value, reasons

        if account.status != AccountStatus.CONNECTED.value:
            reasons.append(f"Account status is '{account.status}' — not connected.")
            return ComplianceVerdict.BLOCKED.value, reasons

        if expires_at and time.time() > expires_at:
            reasons.append("Access token has expired — re-authorize the account.")
            return ComplianceVerdict.BLOCKED.value, reasons

        # 5. Duplicate post prevention
        existing_posts = self.store.list_posts_by_render_job(post.render_job_id, post.tenant_id)
        for ep in existing_posts:
            if ep.platform == post.platform and ep.account_id == post.account_id and ep.status == PostStatus.PUBLISHED.value:
                reasons.append(f"Already published to {post.platform} on this account (post {ep.post_id}).")
                return ComplianceVerdict.BLOCKED.value, reasons

        # All checks passed
        return ComplianceVerdict.READY.value, reasons

    # -- Publishing -----------------------------------------------------------

    def create_post(
        self,
        tenant_id: str,
        render_job_id: str,
        rendered_asset_id: str,
        platform: str,
        account_id: str,
        title: Optional[str] = None,
        caption: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        privacy: Optional[str] = None,
        scheduled_at: Optional[str] = None,
        video_path: Optional[str] = None,
        auto_publish: bool = False,
    ) -> SocialPost:
        """Creates a draft social post. Does NOT publish yet — requires explicit
        approval unless auto_publish is True."""
        post_id = f"post_{uuid.uuid4().hex[:12]}"
        post = SocialPost(
            post_id=post_id,
            tenant_id=tenant_id,
            render_job_id=render_job_id,
            rendered_asset_id=rendered_asset_id,
            platform=platform,
            account_id=account_id,
            status=PostStatus.DRAFT.value,
            title=title,
            caption=caption,
            hashtags=hashtags or [],
            privacy=privacy,
            scheduled_at=scheduled_at,
            auto_publish=auto_publish,
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        self.store.save_post(post, video_path=video_path or "")
        return post

    def publish_post(self, post_id: str, tenant_id: str, force: bool = False) -> PublishResult:
        """Publishes a social post to its platform.

        - Enforces tenant isolation.
        - Runs the compliance gate.
        - Requires explicit approval (force=True) unless auto_publish is set.
        - A failed publish does NOT affect the render job.
        """
        post = self.store.get_post(post_id)
        if not post:
            return PublishResult(success=False, error="Social post not found.")

        if post.tenant_id != tenant_id:
            return PublishResult(success=False, error="Tenant isolation violation.")

        # Require explicit approval unless auto_publish is enabled.
        if not post.auto_publish and not force:
            return PublishResult(
                success=False,
                error="Publishing requires explicit user approval. Pass force=True or enable auto_publish.",
            )

        # Compliance gate
        verdict, reasons = self.evaluate_compliance(post)
        post.compliance_verdict = verdict
        post.compliance_reasons = reasons
        if verdict == ComplianceVerdict.BLOCKED.value:
            post.status = PostStatus.FAILED.value
            post.error_message = "; ".join(reasons)
            self.store.save_post(post)
            return PublishResult(success=False, error="; ".join(reasons))

        # Get the access token (server-side only)
        account_data = self.store.get_account(post.account_id)
        if not account_data:
            post.status = PostStatus.FAILED.value
            post.error_message = "Connected account not found."
            self.store.save_post(post)
            return PublishResult(success=False, error=post.error_message)

        account, access_token, _, _ = account_data
        if not access_token:
            post.status = PostStatus.FAILED.value
            post.error_message = "No access token for this account."
            self.store.save_post(post)
            return PublishResult(success=False, error=post.error_message)

        adapter = self.adapters.get(post.platform)
        if not adapter:
            post.status = PostStatus.FAILED.value
            post.error_message = f"No adapter for platform '{post.platform}'."
            self.store.save_post(post)
            return PublishResult(success=False, error=post.error_message)

        # Transition to PUBLISHING
        post.status = PostStatus.PUBLISHING.value
        self.store.save_post(post)

        # Get video path
        video_path = self.store.get_post_video_path(post_id) or ""

        try:
            result = adapter.publish(post, video_path, access_token)
            if result.success:
                post.status = PostStatus.PUBLISHED.value
                post.platform_post_id = result.platform_post_id
                post.post_url = result.post_url
                post.published_at = datetime.utcnow().isoformat() + "Z"
                post.error_message = None
            else:
                post.status = PostStatus.FAILED.value
                post.error_message = result.error
                post.retry_count += 1
            self.store.save_post(post)
            return result
        except Exception as e:
            post.status = PostStatus.FAILED.value
            post.error_message = str(e)
            post.retry_count += 1
            self.store.save_post(post)
            return PublishResult(success=False, error=str(e))

    def retry_post(self, post_id: str, tenant_id: str) -> PublishResult:
        """Retries a failed social post."""
        post = self.store.get_post(post_id)
        if not post:
            return PublishResult(success=False, error="Social post not found.")
        if post.tenant_id != tenant_id:
            return PublishResult(success=False, error="Tenant isolation violation.")
        if post.status != PostStatus.FAILED.value:
            return PublishResult(success=False, error=f"Cannot retry post in '{post.status}' state.")
        return self.publish_post(post_id, tenant_id, force=True)

    def cancel_post(self, post_id: str, tenant_id: str) -> bool:
        """Cancels a draft or queued social post."""
        post = self.store.get_post(post_id)
        if not post:
            return False
        if post.tenant_id != tenant_id:
            raise PermissionError("Tenant isolation violation.")
        if post.status not in (PostStatus.DRAFT.value, PostStatus.READY.value, PostStatus.QUEUED.value):
            return False
        post.status = PostStatus.CANCELLED.value
        self.store.save_post(post)
        return True

    def list_posts(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SocialPost], int]:
        return self.store.list_posts(tenant_id, status, platform, limit, offset)

    def get_post(self, post_id: str, tenant_id: str) -> Optional[SocialPost]:
        post = self.store.get_post(post_id)
        if not post:
            return None
        if post.tenant_id != tenant_id:
            raise PermissionError("Tenant isolation violation.")
        return post
