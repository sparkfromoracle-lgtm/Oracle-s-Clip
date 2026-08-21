"""Regression tests for the orchestration render step, event dispatch and
renderer artifact metadata (checksum + target aspect ratio geometry)."""

import pytest

from shared.contracts.enums import JobStatus
from shared.contracts.jobs import ClipSegmentSpec, ClipSpecification, RenderJob
from shared.errors.errors import RenderingError
from media_service.orchestration.orchestrator import CanonicalPipelineOrchestrator
from media_service.rendering.ffmpeg_renderer import (
    MockRendererAdapter,
    resolve_target_frame_size,
)
from shared.hashing.checksum_verifier import calculate_sha256


def _job(job_id: str = "job_evt_1", aspect: str = "9:16") -> RenderJob:
    spec = ClipSpecification(
        spec_id=f"spec_{job_id}",
        source_media_id="media_evt",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=4000, source_media_id="media_evt")],
        target_aspect_ratio=aspect,
    )
    return RenderJob(job_id=job_id, tenant_id="tenant_evt", spec=spec, status=JobStatus.PENDING)


class RecordingDispatcher:
    """Stands in for WebhookDispatcher, recording the real delivery interface."""

    def __init__(self):
        self.delivered = []

    def deliver(self, target_url, payload, extra_headers=None):
        self.delivered.append((target_url, payload))
        return True, 200, "ok"


def test_render_job_returns_asset_with_artifact_checksum(tmp_path):
    orchestrator = CanonicalPipelineOrchestrator(renderer=MockRendererAdapter())
    out_path = str(tmp_path / "out.mp4")

    job, asset = orchestrator.render_job_with_asset(
        _job(), source_media_path=str(tmp_path / "in.mp4"), output_path=out_path
    )

    assert job.status == JobStatus.COMPLETED
    assert job.output_path == out_path
    # checksum_sha256 is the digest of the artifact actually written to disk.
    expected_checksum, size = calculate_sha256(out_path)
    assert asset.checksum_sha256 == expected_checksum
    assert asset.file_size_bytes == size
    assert asset.tenant_id == "tenant_evt"


def test_render_job_records_failure_state_and_raises(tmp_path):
    class AlwaysFails:
        def __init__(self):
            self.attempts = 0

        def render(self, job, source_media_path, output_path):
            self.attempts += 1
            raise RenderingError("boom")

    renderer = AlwaysFails()
    orchestrator = CanonicalPipelineOrchestrator(renderer=renderer, max_retries=1)
    job = _job("job_evt_fail")

    with pytest.raises(RenderingError):
        orchestrator.render_job(job, str(tmp_path / "in.mp4"), str(tmp_path / "out.mp4"))

    assert renderer.attempts == 2  # initial attempt + 1 retry
    assert job.status == JobStatus.FAILED
    assert job.error_message


def test_pipeline_dispatches_lifecycle_events_through_dispatcher(tmp_path):
    dispatcher = RecordingDispatcher()
    orchestrator = CanonicalPipelineOrchestrator(
        renderer=MockRendererAdapter(),
        webhook_dispatcher=dispatcher,
        webhook_target_url="https://example.invalid/hook",
    )
    source = tmp_path / "input.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 200)

    result = orchestrator.execute_pipeline(
        task_id="evt_task",
        tenant_id="tenant_evt",
        source_media_path=str(source),
        duration_ms=30000,
        output_dir=str(tmp_path / "rendered"),
    )

    assert result["status"] == "COMPLETED"
    event_types = [payload["event_type"] for _, payload in dispatcher.delivered]
    assert event_types == [
        "clip.opportunity.detected",
        "clip.spec.created",
        "clip.rendered",
        "clip.quality.checked",
        "clip.guardian.decided",
    ]
    assert result["asset"]["checksum_sha256"] is not None


@pytest.mark.parametrize(
    "ratio,expected",
    [
        ("9:16", (1080, 1920)),
        ("16:9", (1920, 1080)),
        ("1:1", (1080, 1080)),
        ("2:1", (1920, 960)),
    ],
)
def test_resolve_target_frame_size(ratio, expected):
    assert resolve_target_frame_size(ratio) == expected


def test_resolve_target_frame_size_rejects_invalid_ratio():
    with pytest.raises(RenderingError):
        resolve_target_frame_size("not-a-ratio")
