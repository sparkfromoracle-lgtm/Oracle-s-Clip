"""Abstract platform adapter interface.

Each social platform gets its own adapter. Platform-specific code lives in the
adapter, never in the renderer or orchestrator. Adapters can be replaced
without touching the publishing service or the render pipeline.
"""

import abc
from typing import Any, Dict, Optional

from shared.contracts.publishing import PlatformCapabilities, PublishResult, SocialPost


class PlatformAdapter(abc.ABC):
    """Abstract interface for a social platform publishing adapter."""

    @abc.abstractmethod
    def get_capabilities(self) -> PlatformCapabilities:
        """Returns the capability matrix for this platform."""
        ...

    @abc.abstractmethod
    def get_oauth_url(self, redirect_uri: str, state: str) -> str:
        """Builds the OAuth 2.0 authorization URL for this platform."""
        ...

    @abc.abstractmethod
    def exchange_oauth_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchanges an OAuth authorization code for access/refresh tokens.

        Returns a dict with at least ``access_token``, ``refresh_token`` (if
        applicable), and ``platform_user_id`` / ``display_name``.
        """
        ...

    @abc.abstractmethod
    def publish(
        self,
        post: SocialPost,
        video_path: str,
        access_token: str,
    ) -> PublishResult:
        """Publishes a video to the platform. Returns a PublishResult."""
        ...

    @abc.abstractmethod
    def revoke_token(self, access_token: str) -> bool:
        """Revokes/disconnects the platform connection."""
        ...
