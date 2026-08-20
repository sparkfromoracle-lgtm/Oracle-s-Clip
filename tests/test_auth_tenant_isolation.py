import pytest
from media_service.config.settings import Settings
from media_service.security.auth import Authenticator, AuthenticatedTenant
from shared.errors.errors import AuthenticationError, TenantIsolationError


def test_authenticator_valid_key():
    settings = Settings(api_keys={"key_alpha": "tenant_alpha", "key_beta": "tenant_beta"})
    auth = Authenticator(settings)

    tenant = auth.authenticate_api_key("key_alpha")
    assert tenant.tenant_id == "tenant_alpha"
    assert "key_alpha" not in tenant.key_identifier  # Masked


def test_authenticator_missing_and_invalid_key():
    settings = Settings(api_keys={"valid_key": "tenant_1"})
    auth = Authenticator(settings)

    # Missing key
    with pytest.raises(AuthenticationError) as exc:
        auth.authenticate_api_key(None)
    assert "Missing required authentication header" in str(exc.value)

    # Invalid key
    with pytest.raises(AuthenticationError) as exc:
        auth.authenticate_api_key("invalid_key_123")
    assert "Invalid API key" in str(exc.value)


def test_tenant_isolation():
    settings = Settings(api_keys={"key_alpha": "tenant_alpha", "key_beta": "tenant_beta"})
    auth = Authenticator(settings)

    tenant_alpha = auth.authenticate_api_key("key_alpha")
    
    # Authorized access to own tenant
    auth.authorize_tenant_access(tenant_alpha, "tenant_alpha")

    # Cross-tenant access rejected
    with pytest.raises(TenantIsolationError) as exc:
        auth.authorize_tenant_access(tenant_alpha, "tenant_beta")
    assert "Cross-tenant access forbidden" in str(exc.value)
