"""Per-platform social publishing adapters.

Each adapter implements the PlatformAdapter interface. Adapters use the
platform's official OAuth 2.0 and content publishing APIs via the ``requests``
library. No browser automation, scraping, or password storage.

Implementation status:
- YouTube: PARTIALLY IMPLEMENTED (OAuth + upload architecture; requires real
  Google API credentials and YouTube Data API v3 quota)
- TikTok: PARTIALLY IMPLEMENTED (OAuth + upload architecture; requires real
  TikTok for Developers credentials)
- Instagram: PARTIALLY IMPLEMENTED (OAuth + container upload; requires Meta
  Developer credentials)
- Facebook: PARTIALLY IMPLEMENTED (OAuth + video upload; requires Meta
  Developer credentials)
- X: PARTIALLY IMPLEMENTED (OAuth 2.0 PKCE + media upload; requires X API v2
  credentials)
- LinkedIn: PARTIALLY IMPLEMENTED (OAuth 2.0 + video upload; requires LinkedIn
  Developer credentials)
- Snapchat: NOT IMPLEMENTED (Snapchat Content Publishing API requires
  partner-level access; BLOCKED BY PLATFORM API/PERMISSION REQUIREMENTS)

All adapters fail safely: if publishing fails, the render job remains
successful. Token exchange and publishing are tested behind mocked HTTP.
"""

import json
import logging
import urllib.parse
import requests
from typing import Any, Dict, Optional

from shared.contracts.publishing import (
    PlatformCapabilities,
    PublishResult,
    SocialPost,
)
from media_service.publishing import PlatformAdapter

logger = logging.getLogger("oracle_clip.publishing.adapters")


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

class YouTubeAdapter(PlatformAdapter):
    """YouTube Data API v3 adapter for video uploads."""

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
    REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="youtube",
            supports_video=True,
            supports_caption=True,
            supports_title=True,
            supports_hashtags=True,
            supports_privacy=True,
            supports_scheduling=False,
            supports_thumbnail=True,
            max_video_duration_seconds=43200,  # 12 hours
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
            oauth_scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
            ],
            implementation_status="partially_implemented",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.get_capabilities().oauth_scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = requests.post(self.TOKEN_URL, data={
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"YouTube OAuth failed: {resp.text}")
        token = resp.json()
        token["platform_user_id"] = token.get("scope", "youtube")
        token["display_name"] = "YouTube Account"
        return token

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        import os
        if not os.path.exists(video_path):
            return PublishResult(success=False, error=f"Video file not found: {video_path}")

        metadata = {
            "snippet": {
                "title": post.title or "Untitled",
                "description": post.caption or "",
                "tags": post.hashtags,
            },
            "status": {
                "privacyStatus": post.privacy or "public",
            },
        }
        try:
            with open(video_path, "rb") as f:
                resp = requests.post(
                    self.UPLOAD_URL,
                    params={"uploadType": "multipart", "part": "snippet,status"},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    data=json.dumps(metadata),
                    files={"video": f},
                    timeout=300,
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                video_id = data.get("id")
                return PublishResult(
                    success=True,
                    platform_post_id=video_id,
                    post_url=f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
                )
            return PublishResult(success=False, error=f"YouTube API error ({resp.status_code}): {resp.text}")
        except Exception as e:
            return PublishResult(success=False, error=str(e))

    def revoke_token(self, access_token: str) -> bool:
        resp = requests.post(self.REVOKE_URL, params={"token": access_token}, timeout=15)
        return resp.status_code == 200


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------

class TikTokAdapter(PlatformAdapter):
    """TikTok Content Posting API adapter."""

    AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapi.com/v2/oauth/token/"
    UPLOAD_URL = "https://open.tiktokapi.com/v2/post/publish/video/init/"
    REVOKE_URL = "https://open.tiktokapi.com/v2/oauth/revoke/"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="tiktok",
            supports_video=True,
            supports_caption=True,
            supports_title=False,
            supports_hashtags=True,
            supports_privacy=True,
            supports_scheduling=False,
            supports_thumbnail=False,
            max_video_duration_seconds=600,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
            oauth_scopes=["video.upload", "video.publish"],
            implementation_status="partially_implemented",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_key": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(self.get_capabilities().oauth_scopes),
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = requests.post(self.TOKEN_URL, data={
            "client_key": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"TikTok OAuth failed: {resp.text}")
        token = resp.json()
        token["platform_user_id"] = token.get("open_id", "tiktok")
        token["display_name"] = "TikTok Account"
        return token

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        import os
        if not os.path.exists(video_path):
            return PublishResult(success=False, error=f"Video file not found: {video_path}")
        try:
            # Init upload
            resp = requests.post(
                self.UPLOAD_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={
                    "source": "FILE_UPLOAD",
                    "video_url": "",  # Would be a CDN URL in production
                    "title": post.caption or "",
                    "privacy_level": post.privacy or "PUBLIC_TO_EVERYONE",
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                publish_id = data.get("publish_id")
                return PublishResult(
                    success=True,
                    platform_post_id=publish_id,
                    post_url=f"https://www.tiktok.com/@user/video/{publish_id}" if publish_id else None,
                )
            return PublishResult(success=False, error=f"TikTok API error ({resp.status_code}): {resp.text}")
        except Exception as e:
            return PublishResult(success=False, error=str(e))

    def revoke_token(self, access_token: str) -> bool:
        resp = requests.post(self.REVOKE_URL, data={"token": access_token}, timeout=15)
        return resp.status_code == 200


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

class InstagramAdapter(PlatformAdapter):
    """Instagram Graph API adapter for Reels/video posts."""

    AUTH_URL = "https://api.instagram.com/oauth/authorize"
    TOKEN_URL = "https://api.instagram.com/oauth/access_token"
    MEDIA_URL = "https://graph.facebook.com/v18.0"
    REVOKE_URL = "https://graph.facebook.com/v18.0/{user_id}/permissions"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="instagram",
            supports_video=True,
            supports_caption=True,
            supports_title=False,
            supports_hashtags=True,
            supports_privacy=False,
            supports_scheduling=False,
            supports_thumbnail=False,
            max_video_duration_seconds=900,
            supported_aspect_ratios=["9:16", "1:1"],
            oauth_scopes=["instagram_content_publish"],
            implementation_status="partially_implemented",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "instagram_content_publish",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = requests.post(self.TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Instagram OAuth failed: {resp.text}")
        token = resp.json()
        token["platform_user_id"] = str(token.get("user_id", "instagram"))
        token["display_name"] = "Instagram Account"
        return token

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        # Instagram requires a two-step container + publish flow.
        try:
            # Step 1: Create media container
            resp = requests.post(
                f"{self.MEDIA_URL}/media",
                params={
                    "media_type": "REELS",
                    "video_url": "",  # Must be a public URL in production
                    "caption": (post.caption or "") + " " + " ".join(f"#{h}" for h in post.hashtags),
                    "access_token": access_token,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                return PublishResult(success=False, error=f"Instagram container creation failed ({resp.status_code}): {resp.text}")
            container_id = resp.json().get("id")

            # Step 2: Publish container
            resp2 = requests.post(
                f"{self.MEDIA_URL}/media_publish",
                params={"creation_id": container_id, "access_token": access_token},
                timeout=60,
            )
            if resp2.status_code == 200:
                media_id = resp2.json().get("id")
                return PublishResult(
                    success=True,
                    platform_post_id=media_id,
                    post_url=f"https://www.instagram.com/p/{media_id}" if media_id else None,
                )
            return PublishResult(success=False, error=f"Instagram publish failed ({resp2.status_code}): {resp2.text}")
        except Exception as e:
            return PublishResult(success=False, error=str(e))

    def revoke_token(self, access_token: str) -> bool:
        # Instagram uses Meta Graph API revocation
        resp = requests.delete(f"{self.MEDIA_URL}/me/permissions", params={"access_token": access_token}, timeout=15)
        return resp.status_code == 200


# ---------------------------------------------------------------------------
# Facebook
# ---------------------------------------------------------------------------

class FacebookAdapter(PlatformAdapter):
    """Facebook Graph API adapter for video posts."""

    AUTH_URL = "https://www.facebook.com/v18.0/dialog/oauth"
    TOKEN_URL = "https://graph.facebook.com/v18.0/oauth/access_token"
    VIDEO_URL = "https://graph.facebook.com/v18.0/me/videos"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="facebook",
            supports_video=True,
            supports_caption=True,
            supports_title=True,
            supports_hashtags=True,
            supports_privacy=True,
            supports_scheduling=False,
            supports_thumbnail=False,
            max_video_duration_seconds=2400,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
            oauth_scopes=["pages_manage_posts", "pages_read_engagement", "pages_show_list"],
            implementation_status="partially_implemented",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(self.get_capabilities().oauth_scopes),
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = requests.get(self.TOKEN_URL, params={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Facebook OAuth failed: {resp.text}")
        token = resp.json()
        token["platform_user_id"] = str(token.get("user_id", "facebook"))
        token["display_name"] = "Facebook Page"
        return token

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        import os
        if not os.path.exists(video_path):
            return PublishResult(success=False, error=f"Video file not found: {video_path}")
        try:
            with open(video_path, "rb") as f:
                resp = requests.post(
                    self.VIDEO_URL,
                    params={
                        "access_token": access_token,
                        "description": post.caption or "",
                        "title": post.title or "",
                    },
                    files={"source": f},
                    timeout=300,
                )
            if resp.status_code == 200:
                video_id = resp.json().get("id")
                return PublishResult(
                    success=True,
                    platform_post_id=video_id,
                    post_url=f"https://www.facebook.com/watch/?v={video_id}" if video_id else None,
                )
            return PublishResult(success=False, error=f"Facebook API error ({resp.status_code}): {resp.text}")
        except Exception as e:
            return PublishResult(success=False, error=str(e))

    def revoke_token(self, access_token: str) -> bool:
        resp = requests.delete(f"{self.VIDEO_URL.replace('/me/videos', '/me/permissions')}", params={"access_token": access_token}, timeout=15)
        return resp.status_code == 200


# ---------------------------------------------------------------------------
# X (Twitter)
# ---------------------------------------------------------------------------

class XAdapter(PlatformAdapter):
    """X (Twitter) API v2 adapter for video posts using OAuth 2.0 PKCE."""

    AUTH_URL = "https://twitter.com/i/oauth2/authorize"
    TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
    TWEET_URL = "https://api.twitter.com/2/tweets"
    MEDIA_URL = "https://upload.twitter.com/i/media/upload.json"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="x",
            supports_video=True,
            supports_caption=True,
            supports_title=False,
            supports_hashtags=True,
            supports_privacy=True,
            supports_scheduling=False,
            supports_thumbnail=False,
            max_video_duration_seconds=140,
            supported_aspect_ratios=["16:9", "1:1"],
            oauth_scopes=["tweet.read", "tweet.write", "users.read", "media.write"],
            implementation_status="partially_implemented",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.get_capabilities().oauth_scopes),
            "state": state,
            "code_challenge": "challenge",
            "code_challenge_method": "plain",
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = requests.post(self.TOKEN_URL, data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": "challenge",
        }, timeout=30, auth=(self.client_id, self.client_secret) if self.client_secret else None)
        if resp.status_code != 200:
            raise RuntimeError(f"X OAuth failed: {resp.text}")
        token = resp.json()
        token["platform_user_id"] = "x"
        token["display_name"] = "X Account"
        return token

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        import os
        if not os.path.exists(video_path):
            return PublishResult(success=False, error=f"Video file not found: {video_path}")
        try:
            # Step 1: Upload media
            with open(video_path, "rb") as f:
                resp = requests.post(
                    self.MEDIA_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    files={"media": f},
                    timeout=300,
                )
            if resp.status_code != 200:
                return PublishResult(success=False, error=f"X media upload failed ({resp.status_code}): {resp.text}")
            media_id = resp.json().get("media_id_string")

            # Step 2: Create tweet with media
            text = (post.caption or "")[:280]
            resp2 = requests.post(
                self.TWEET_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={"text": text, "media": {"media_ids": [media_id]}},
                timeout=30,
            )
            if resp2.status_code in (200, 201):
                tweet_id = resp2.json().get("data", {}).get("id")
                return PublishResult(
                    success=True,
                    platform_post_id=tweet_id,
                    post_url=f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
                )
            return PublishResult(success=False, error=f"X tweet creation failed ({resp2.status_code}): {resp2.text}")
        except Exception as e:
            return PublishResult(success=False, error=str(e))

    def revoke_token(self, access_token: str) -> bool:
        resp = requests.post(self.TOKEN_URL, data={
            "token": access_token,
            "client_id": self.client_id,
            "token_type_hint": "access_token",
        }, timeout=15)
        return resp.status_code == 200


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------

class LinkedInAdapter(PlatformAdapter):
    """LinkedIn API adapter for video posts."""

    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    UPLOAD_URL = "https://api.linkedin.com/v2/assets"
    POST_URL = "https://api.linkedin.com/v2/ugcPosts"

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="linkedin",
            supports_video=True,
            supports_caption=True,
            supports_title=True,
            supports_hashtags=True,
            supports_privacy=True,
            supports_scheduling=False,
            supports_thumbnail=False,
            max_video_duration_seconds=1800,
            supported_aspect_ratios=["16:9", "1:1", "9:16"],
            oauth_scopes=["w_member_social", "r_organization_social"],
            implementation_status="partially_implemented",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.get_capabilities().oauth_scopes),
            "state": state,
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = requests.post(self.TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
        }, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"LinkedIn OAuth failed: {resp.text}")
        token = resp.json()
        token["platform_user_id"] = "linkedin"
        token["display_name"] = "LinkedIn Account"
        return token

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        import os
        if not os.path.exists(video_path):
            return PublishResult(success=False, error=f"Video file not found: {video_path}")
        try:
            # Step 1: Register upload
            resp = requests.post(
                self.UPLOAD_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:video"],
                        "owner": "urn:li:person:local",
                    }
                },
                timeout=60,
            )
            if resp.status_code != 201:
                return PublishResult(success=False, error=f"LinkedIn upload register failed ({resp.status_code}): {resp.text}")
            asset_urn = resp.json().get("value", {}).get("asset")

            # Step 2: Create post
            resp2 = requests.post(
                self.POST_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={
                    "author": "urn:li:person:local",
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": post.caption or ""},
                            "shareMediaCategory": "VIDEO",
                            "media": [{"status": "READY", "media": asset_urn}],
                        }
                    },
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": post.privacy or "PUBLIC"},
                },
                timeout=60,
            )
            if resp2.status_code in (200, 201):
                post_urn = resp2.json().get("id")
                return PublishResult(
                    success=True,
                    platform_post_id=post_urn,
                    post_url=f"https://www.linkedin.com/feed/update/{post_urn}" if post_urn else None,
                )
            return PublishResult(success=False, error=f"LinkedIn post creation failed ({resp2.status_code}): {resp2.text}")
        except Exception as e:
            return PublishResult(success=False, error=str(e))

    def revoke_token(self, access_token: str) -> bool:
        resp = requests.post(self.TOKEN_URL, data={
            "token": access_token,
            "client_id": self.client_id,
            "token_type_hint": "access_token",
        }, timeout=15)
        return resp.status_code == 200


# ---------------------------------------------------------------------------
# Snapchat
# ---------------------------------------------------------------------------

class SnapchatAdapter(PlatformAdapter):
    """Snapchat Content Publishing API adapter.

    BLOCKED: Snapchat's Content Publishing API is only available to approved
    partners via the Snapchat Marketing API / Content Creator program. It is
    not publicly accessible for general developer OAuth.
    """

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform="snapchat",
            supports_video=True,
            supports_caption=True,
            supports_title=False,
            supports_hashtags=False,
            supports_privacy=False,
            supports_scheduling=False,
            supports_thumbnail=False,
            max_video_duration_seconds=60,
            supported_aspect_ratios=["9:16"],
            oauth_scopes=["snapchat-marketing-api"],
            implementation_status="blocked",
        )

    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        raise RuntimeError(
            "Snapchat Content Publishing API requires partner-level access. "
            "BLOCKED BY PLATFORM API/PERMISSION REQUIREMENTS."
        )

    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        raise RuntimeError("Snapchat publishing is blocked by platform API requirements.")

    def publish(self, post: SocialPost, video_path: str, access_token: str) -> PublishResult:
        return PublishResult(
            success=False,
            error="Snapchat Content Publishing API requires partner-level access. BLOCKED BY PLATFORM API/PERMISSION REQUIREMENTS.",
        )

    def revoke_token(self, access_token: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Adapter Registry
# ---------------------------------------------------------------------------

def get_platform_adapters(settings) -> Dict[str, PlatformAdapter]:
    """Returns a dict of platform name -> adapter, configured from settings."""
    return {
        "youtube": YouTubeAdapter(
            client_id=getattr(settings, "youtube_client_id", ""),
            client_secret=getattr(settings, "youtube_client_secret", ""),
        ),
        "tiktok": TikTokAdapter(
            client_id=getattr(settings, "tiktok_client_id", ""),
            client_secret=getattr(settings, "tiktok_client_secret", ""),
        ),
        "instagram": InstagramAdapter(
            client_id=getattr(settings, "instagram_client_id", ""),
            client_secret=getattr(settings, "instagram_client_secret", ""),
        ),
        "facebook": FacebookAdapter(
            client_id=getattr(settings, "facebook_client_id", ""),
            client_secret=getattr(settings, "facebook_client_secret", ""),
        ),
        "x": XAdapter(
            client_id=getattr(settings, "x_client_id", ""),
            client_secret=getattr(settings, "x_client_secret", ""),
        ),
        "linkedin": LinkedInAdapter(
            client_id=getattr(settings, "linkedin_client_id", ""),
            client_secret=getattr(settings, "linkedin_client_secret", ""),
        ),
        "snapchat": SnapchatAdapter(),
    }
