"""Publishing data models and enums for multi-platform social publishing.

These models are separate from the render-job pipeline. A social post references
a completed RenderJob/RenderedAsset but never modifies it. A failed social post
must never invalidate a successfully rendered asset.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PostStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    QUEUED = "queued"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AccountStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"


class PlatformName(str, Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    X = "x"
    LINKEDIN = "linkedin"
    SNAPCHAT = "snapchat"


class ComplianceVerdict(str, Enum):
    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


@dataclass
class PlatformCapabilities:
    """Declares what a platform's official API supports.
    Used to build a capability matrix so the UI only exposes supported options.
    """
    platform: str
    supports_video: bool = True
    supports_caption: bool = True
    supports_title: bool = False
    supports_hashtags: bool = True
    supports_privacy: bool = False
    supports_scheduling: bool = False
    supports_thumbnail: bool = False
    max_video_duration_seconds: Optional[int] = None
    max_video_size_bytes: Optional[int] = None
    supported_aspect_ratios: List[str] = field(default_factory=lambda: ["9:16", "16:9", "1:1"])
    oauth_scopes: List[str] = field(default_factory=list)
    implementation_status: str = "not_implemented"  # working | partially_implemented | not_implemented | blocked


@dataclass
class ConnectedAccount:
    account_id: str
    tenant_id: str
    platform: str
    display_name: str
    platform_user_id: str
    status: str = "connected"
    connected_at: str = ""
    scopes: List[str] = field(default_factory=list)
    # Token storage is server-side only — never exposed to the frontend.
    # Tokens are stored in the publishing store, not in this dataclass.


@dataclass
class SocialPost:
    post_id: str
    tenant_id: str
    render_job_id: str
    rendered_asset_id: str
    platform: str
    account_id: str
    platform_post_id: Optional[str] = None
    status: str = "draft"
    title: Optional[str] = None
    caption: Optional[str] = None
    hashtags: List[str] = field(default_factory=list)
    privacy: Optional[str] = None
    scheduled_at: Optional[str] = None
    published_at: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    post_url: Optional[str] = None
    auto_publish: bool = False
    compliance_verdict: Optional[str] = None
    compliance_reasons: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class PublishResult:
    success: bool
    platform_post_id: Optional[str] = None
    post_url: Optional[str] = None
    error: Optional[str] = None
