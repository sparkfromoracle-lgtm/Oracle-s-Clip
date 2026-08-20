import pytest
from shared.contracts.enums import QualityVerdict
from shared.contracts.jobs import RenderedAsset
from shared.errors.errors import DependencyUnavailableError
from media_service.quality.guardian_hooks import QualityChecker, PassThroughGuardianHook
from ai_gateway_client.contracts.gateway import UnavailableAIGatewayClient


def test_quality_checker_and_guardian_flow():
    checker = QualityChecker(min_duration_ms=1000, min_width=720, min_height=1280)
    hook = PassThroughGuardianHook()

    # Passing asset
    pass_asset = RenderedAsset(
        asset_id="asset_pass",
        job_id="job_pass",
        tenant_id="tenant_1",
        storage_path="/tmp/pass.mp4",
        duration_ms=5000,
        width=1080,
        height=1920,
        bitrate=2_000_000,
    )
    report_pass = checker.check(pass_asset)
    assert report_pass.verdict == QualityVerdict.PASS
    assert report_pass.overall_score == 1.0

    decision = hook.evaluate(report_pass)
    assert decision["approved"] is True
    assert decision["verdict"] == "pass"

    # Failing asset (duration too short)
    fail_asset = RenderedAsset(
        asset_id="asset_fail",
        job_id="job_fail",
        tenant_id="tenant_1",
        storage_path="/tmp/fail.mp4",
        duration_ms=200,
        width=1080,
        height=1920,
    )
    report_fail = checker.check(fail_asset)
    assert report_fail.verdict == QualityVerdict.FAIL
    assert report_fail.overall_score < 1.0

    decision_fail = hook.evaluate(report_fail)
    assert decision_fail["approved"] is False
    assert decision_fail["verdict"] == "fail"


def test_unavailable_ai_gateway_client():
    client = UnavailableAIGatewayClient()
    assert client.is_available() is False

    with pytest.raises(DependencyUnavailableError):
        client.generate("Summarize this video")
