import pytest
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
from shared.contracts.enums import JobStatus
from shared.errors.errors import CircuitBreakerOpenError, BulkheadFullError
from media_service.resilience.circuit_breaker import CircuitBreaker, CircuitState
from media_service.resilience.bulkhead import Bulkhead
from media_service.rendering.ffmpeg_renderer import MockRendererAdapter


def test_circuit_breaker_flow():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.1, half_open_success_threshold=1)
    assert cb.state == CircuitState.CLOSED

    # Failure 1
    def failing():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        cb.call(failing)
    assert cb.state == CircuitState.CLOSED

    # Failure 2 -> opens
    with pytest.raises(RuntimeError):
        cb.call(failing)
    assert cb.state == CircuitState.OPEN

    # Call blocked
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "ok")

    # Wait for recovery
    import time
    time.sleep(0.12)
    assert cb.state == CircuitState.HALF_OPEN

    # Success in half open -> closes
    res = cb.call(lambda: "recovered")
    assert res == "recovered"
    assert cb.state == CircuitState.CLOSED


def test_bulkhead_limit():
    bh = Bulkhead(max_concurrent=1)
    
    # Nested call should fail because max_concurrent is 1
    def outer():
        return bh.call(lambda: "nested")

    with pytest.raises(BulkheadFullError):
        bh.call(outer)


def test_mock_renderer_adapter(tmp_path):
    renderer = MockRendererAdapter()
    spec = ClipSpecification(
        spec_id="spec_1",
        source_media_id="media_1",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000)],
    )
    job = RenderJob(job_id="job_1", tenant_id="tenant_1", spec=spec)
    out_file = str(tmp_path / "out.mp4")

    asset = renderer.render(job, source_media_path="dummy.mp4", output_path=out_file)
    assert asset.asset_id == "asset_job_1"
    assert asset.duration_ms == 5000
    assert asset.content_hash is not None
