from media_service.config.settings import Settings
from media_service.api.readiness import ReadinessProbe


def test_readiness_probe_development():
    s = Settings(environment="development")
    probe = ReadinessProbe(s)
    res = probe.check_readiness()
    assert res["status"] == "ready"
    assert "ffmpeg" in res["checks"]
    assert "auth" in res["checks"]
    assert "storage" in res["checks"]


def test_readiness_probe_production_missing_dependencies():
    s = Settings(
        environment="production",
        api_keys={}, # Missing auth
        webhook_secret="", # Missing webhook secret
        ffmpeg_binary="non_existent_ffmpeg_binary_xyz",
    )
    probe = ReadinessProbe(s)
    res = probe.check_readiness()
    assert res["status"] == "degraded"
    assert res["checks"]["ffmpeg"]["available"] is False
    assert res["checks"]["auth"]["ready"] is False
