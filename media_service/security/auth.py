import hmac
import logging
from dataclasses import dataclass
from typing import Dict, Optional
from fastapi import Header, HTTPException, Security, Request, Depends
from fastapi.security import APIKeyHeader
from shared.errors.errors import AuthenticationError, TenantIsolationError
from media_service.config.settings import Settings

logger = logging.getLogger("oracle_clip.auth")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class AuthenticatedTenant:
    tenant_id: str
    key_identifier: str  # Safe identifier e.g. masked suffix or tenant name


class Authenticator:
    """Authentication and Tenant Isolation manager."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def authenticate_api_key(self, provided_key: Optional[str]) -> AuthenticatedTenant:
        if not provided_key:
            raise AuthenticationError(
                "Missing required authentication header: X-API-Key",
                details={"header": "X-API-Key"},
            )

        # Iterate over configured keys with timing-safe comparison
        for valid_key, tenant_id in self.settings.api_keys.items():
            if hmac.compare_digest(provided_key.encode("utf-8"), valid_key.encode("utf-8")):
                safe_id = provided_key[-4:].rjust(len(provided_key), "*") if len(provided_key) >= 4 else "****"
                return AuthenticatedTenant(tenant_id=tenant_id, key_identifier=safe_id)

        # Log safe error without printing provided key
        safe_preview = provided_key[-4:] if len(provided_key) >= 4 else "len<4"
        logger.warning(f"Failed authentication attempt with key ending in: ...{safe_preview}")
        raise AuthenticationError("Invalid API key provided", details={"reason": "key_mismatch"})

    def authorize_tenant_access(self, authenticated_tenant: AuthenticatedTenant, target_tenant_id: str) -> None:
        """Enforces tenant isolation: caller cannot access another tenant's resources."""
        if not target_tenant_id:
            raise TenantIsolationError("Target tenant_id cannot be empty")

        if not hmac.compare_digest(authenticated_tenant.tenant_id.encode("utf-8"), target_tenant_id.encode("utf-8")):
            logger.warning(
                f"Tenant isolation violation: authenticated tenant '{authenticated_tenant.tenant_id}' "
                f"attempted to access tenant '{target_tenant_id}'"
            )
            raise TenantIsolationError(
                f"Cross-tenant access forbidden: tenant '{authenticated_tenant.tenant_id}' "
                f"cannot access resources for tenant '{target_tenant_id}'",
                details={
                    "authenticated_tenant": authenticated_tenant.tenant_id,
                    "target_tenant": target_tenant_id,
                },
            )
