import os
import subprocess
import tempfile
import pytest
from media_service.opportunities.template_generator import TemplateOpportunityGenerator
from media_service.clip_spec.validator import ClipSpecificationValidator
from media_service.rendering.ffmpeg_renderer import FFmpegRendererAdapter
from media_service.quality.guardian_hooks import QualityChecker, PassThroughGuardianHook
from media_service.security.webhooks import WebhookSecurity, WebhookDispatcher
from shared.contracts.enums import JobStatus, QualityVerdict, ClipSpecStatus
from shared.contracts.jobs import ClipSegmentSpec, ClipSpecification, RenderJob
from shared.contracts.media import MediaMetadata
from shared.hashing.checksum_verifier import verify_artifact_checksum


@pytest.fixture(scope="module")
def synthetic_mp4_video():
    """Generates a real, valid 4-second test MP4 video using FFmpeg testsrc and sine audio."""
    temp_dir = tempfile.mkdtemp()
    video_path = os.path.join(temp_dir, "test_input.mp4")
    
    # Generate 4 seconds of color test pattern with 440Hz test audio tone
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=640x360:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        video_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg synthetic media generation failed: {res.stderr}"
    assert os.path.exists(video_path)
    assert os.path.getsize(video_path) > 0

    yield video_path

    # Cleanup
    if os.path.exists(video_path):
        os.remove(video_path)
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)


def test_complete_real_media_pipeline(synthetic_mp4_video):
    """Executes the complete canonical pipeline end-to-end against a real media file:
    ContentOpportunity -> ClipSpecification -> Validator -> Renderer (real FFmpeg) -> 
    RenderedAsset -> QualityChecker -> GuardianHook -> Webhook Signing
    """
    source_media_id = "media_prod_canon_001"
    
    # 1. ContentOpportunity Stage
    opp_gen = TemplateOpportunityGenerator()
    metadata = MediaMetadata(duration_ms=4000, format_name="mp4", width=640, height=360)
    opportunities = opp_gen.generate(source_media_id=source_media_id, metadata=metadata, max_opportunities=3)
    assert len(opportunities) > 0
    top_opp = opportunities[0]
    assert top_opp.start_ms >= 0
    assert top_opp.end_ms <= 4000

    # 2. ClipSpecification Stage
    segment = ClipSegmentSpec(
        start_ms=top_opp.start_ms,
        end_ms=top_opp.end_ms,
        source_media_id=source_media_id,
    )
    spec = ClipSpecification(
        spec_id="spec_test_001",
        source_media_id=source_media_id,
        segments=[segment],
        target_aspect_ratio="9:16",
        version=1,
    )

    # 3. ClipSpecificationValidator Stage
    validator = ClipSpecificationValidator()
    val_report = validator.validate(spec, source_duration_ms=4000)
    assert val_report.is_valid is True
    assert len(val_report.errors) == 0

    # 4. Renderer Stage (Real FFmpeg Subprocess)
    out_dir = tempfile.mkdtemp()
    rendered_output_path = os.path.join(out_dir, "rendered_clip.mp4")

    render_job = RenderJob(
        job_id="job_real_render_001",
        tenant_id="tenant_prod_alpha",
        spec=spec,
        status=JobStatus.PENDING,
    )

    renderer = FFmpegRendererAdapter(ffmpeg_binary="ffmpeg", timeout_seconds=60)
    rendered_asset = renderer.render(
        job=render_job,
        source_media_path=synthetic_mp4_video,
        output_path=rendered_output_path,
    )

    # 5. RenderedAsset Verification
    assert os.path.exists(rendered_output_path)
    assert os.path.getsize(rendered_output_path) > 0
    assert rendered_asset.file_size_bytes > 0
    assert rendered_asset.content_hash is not None
    assert len(rendered_asset.content_hash) == 64  # SHA-256 hex string

    # Verify cryptographic checksum of output artifact
    checksum_report = verify_artifact_checksum(
        artifact_identity=rendered_asset.asset_id,
        data_or_path=rendered_output_path,
        expected_checksum=rendered_asset.content_hash,
    )
    assert checksum_report.verification_result == "VERIFIED"
    assert checksum_report.calculated_checksum == rendered_asset.content_hash

    # 6. QualityChecker Stage
    checker = QualityChecker(min_duration_ms=500, min_width=320, min_height=240, min_bitrate=100_000)
    quality_report = checker.check(rendered_asset)
    assert quality_report.verdict in {QualityVerdict.PASS, QualityVerdict.WARN}
    assert quality_report.overall_score >= 0.75

    # 7. GuardianHook Stage
    guardian = PassThroughGuardianHook()
    decision = guardian.evaluate(quality_report)
    assert decision["approved"] is True
    assert decision["action"] == "publish"

    # 8. Publishing & Webhook Signing Stage
    webhook_sec = WebhookSecurity(secret="production_safe_webhook_secret_key_123")
    signed_event = {
        "event_type": "CLIP_RENDER_COMPLETED",
        "job_id": render_job.job_id,
        "tenant_id": render_job.tenant_id,
        "asset_id": rendered_asset.asset_id,
        "content_hash": rendered_asset.content_hash,
        "verdict": decision["verdict"],
        "guardian_approved": decision["approved"],
    }
    sig, ts = webhook_sec.sign_payload(str(signed_event))
    assert len(sig) == 64
    assert ts > 0

    # Verify inbound signature on receiver side
    verified = webhook_sec.verify_inbound_signature(
        raw_body=str(signed_event),
        signature_header=sig,
        timestamp_header=ts,
    )
    assert verified is True

    # Cleanup rendered test file
    if os.path.exists(rendered_output_path):
        os.remove(rendered_output_path)
    if os.path.exists(out_dir):
        os.rmdir(out_dir)
