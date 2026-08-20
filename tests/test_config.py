import pytest
from media_service.config.settings import Settings, load_settings_from_env
from shared.errors.errors import ConfigurationError


def test_settings_development_defaults():
    s = Settings(environment="development")
    assert s.is_production is False
    # In dev, validate_production is a no-op
    s.validate_production()


def test_settings_production_validation_fail_closed():
    # Missing API keys & webhook secret in prod
    s = Settings(environment="production", api_keys={}, webhook_secret="")
    assert s.is_production is True
    with pytest.raises(ConfigurationError) as exc_info:
        s.validate_production()
    assert "at least one configured API key" in str(exc_info.value)
    assert "webhook_secret" in str(exc_info.value)


def test_settings_production_validation_success():
    s = Settings(
        environment="production",
        api_keys={"supersecretkey123": "tenant_prod"},
        webhook_secret="strongwebhooksecret12345678",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        storage_backend="local",
        asr_provider="local",
        clip_provider="open_clip",
    )
    s.validate_production()


def test_settings_safe_summary_masks_secrets():
    s = Settings(
        environment="production",
        api_keys={"secret_abc_12345": "tenant_1"},
        webhook_secret="webhook_secret_9999",
    )
    summary = s.safe_summary()
    assert "webhook_secret_9999" not in str(summary)
    assert "secret_abc_12345" not in str(summary)
    assert summary["webhook_secret_configured"] is True
    assert "tenant_1" in summary["configured_tenants"]
