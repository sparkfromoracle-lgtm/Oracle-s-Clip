import os
import time
import pytest
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
from shared.errors.errors import RenderingError, StorageError, CircuitBreakerOpenError
from media_service.orchestration.orchestrator import CanonicalPipelineOrchestrator
from media_service.resilience.circuit_breaker import CircuitBreaker, CircuitState


class FailingRenderer:
    def __init__(self, failure_count: int = 1):
        self.attempts = 0
        self.failure_count = failure_count

    def render(self, job, source_media_path, output_path):
        self.attempts += 1
        if self.attempts <= self.failure_count:
            raise RenderingError(f"Simulated FFmpeg process crash on attempt {self.attempts}")
        
        # After failures, succeed
        from shared.contracts.jobs import RenderedAsset
        return RenderedAsset(
            asset_id=f"asset_{job.job_id}",
            job_id=job.job_id,
            storage_path=output_path,
            duration_ms=5000,
            file_size_bytes=1024,
            checksum_sha256="abc123success",
        )


def test_orchestrator_retry_on_transient_rendering_failure(tmp_path):
    renderer = FailingRenderer(failure_count=1)
    orchestrator = CanonicalPipelineOrchestrator(
        renderer=renderer,
        max_retries=2,
    )

    spec = ClipSpecification(
        spec_id="spec_fail_retry",
        source_media_id="media_fail",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000, source_media_id="media_fail")],
    )
    job = RenderJob(
        job_id="job_retry_success",
        tenant_id="tenant_retry",
        spec=spec,
        status=JobStatus.PENDING,
    )

    source_path = str(tmp_path / "in.mp4")
    out_path = str(tmp_path / "out.mp4")
    with open(source_path, "wb") as f:
        f.write(b"dummy_media_bytes")

    result = orchestrator.render_job(job, source_media_path=source_path, output_path=out_path)
    assert result.status == JobStatus.COMPLETED
    assert renderer.attempts == 2


def test_orchestrator_fails_closed_when_retries_exhausted(tmp_path):
    renderer = FailingRenderer(failure_count=5)
    orchestrator = CanonicalPipelineOrchestrator(
        renderer=renderer,
        max_retries=2,
    )

    spec = ClipSpecification(
        spec_id="spec_exhaust",
        source_media_id="media_exhaust",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000, source_media_id="media_exhaust")],
    )
    job = RenderJob(
        job_id="job_exhaust",
        tenant_id="tenant_exhaust",
        spec=spec,
        status=JobStatus.PENDING,
    )

    with pytest.raises(RenderingError):
        orchestrator.render_job(job, source_media_path=str(tmp_path / "in.mp4"), output_path=str(tmp_path / "out.mp4"))
    assert job.status == JobStatus.FAILED


def test_circuit_breaker_trips_and_recovers():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=0.3, half_open_success_threshold=1)

    def failing_action():
        raise RuntimeError("upstream failure")

    def successful_action():
        return "success"

    # Trip the breaker with 3 failures
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.call(failing_action)

    assert cb.state == CircuitState.OPEN

    # Immediate call is rejected by CircuitBreakerOpenError
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(successful_action)

    # Wait for recovery timeout -> enters HALF_OPEN -> transitions to CLOSED on success
    time.sleep(0.4)
    res = cb.call(successful_action)
    assert res == "success"
    assert cb.state == CircuitState.CLOSED
