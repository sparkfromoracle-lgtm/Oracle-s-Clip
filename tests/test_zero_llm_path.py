from shared.contracts.enums import JobStatus, QualityVerdict, ClipSpecStatus
from shared.contracts.media import MediaMetadata, SceneBoundary
from shared.contracts.jobs import (
    ClipSpecification,
    ClipSegmentSpec,
    RenderJob,
    MediaJobStateMachine,
)
from media_service.opportunities.template_generator import TemplateOpportunityGenerator
from media_service.clip_spec.validator import ClipSpecificationValidator
from media_service.rendering.ffmpeg_renderer import MockRendererAdapter
from media_service.quality.guardian_hooks import QualityChecker, PassThroughGuardianHook


def test_complete_zero_llm_pipeline(tmp_path):
    """Verifies end-to-end Zero-LLM pipeline without commercial LLMs or AI Gateways:
    
    ContentOpportunity
    -> ClipSpecification
    -> ClipSpecificationValidator
    -> Renderer
    -> RenderJob
    -> RenderedAsset
    -> QualityChecker
    -> QualityReport
    -> GuardianHook
    -> Decision / Webhook
    """
    # 1. Opportunity Generation (Phase 13.1)
    meta = MediaMetadata(duration_ms=60000, format_name="mp4")
    scenes = [
        SceneBoundary(scene_index=0, start_ms=0, end_ms=15000),
        SceneBoundary(scene_index=1, start_ms=15000, end_ms=45000),
        SceneBoundary(scene_index=2, start_ms=45000, end_ms=60000),
    ]
    opp_gen = TemplateOpportunityGenerator()
    opportunities = opp_gen.generate(source_media_id="vid_source_001", metadata=meta, scenes=scenes)
    assert len(opportunities) >= 1
    selected_opp = opportunities[0]

    # 2. ClipSpecification Construction & Validation (Phase 13.2)
    spec = ClipSpecification(
        spec_id=f"spec_{selected_opp.opportunity_id}",
        source_media_id=selected_opp.source_media_id,
        segments=[ClipSegmentSpec(start_ms=selected_opp.start_ms, end_ms=selected_opp.end_ms)],
        schema_version="1.0.0",
        version=1,
        status=ClipSpecStatus.DRAFT,
    )
    validator = ClipSpecificationValidator()
    val_res = validator.validate(spec, source_duration_ms=meta.duration_ms)
    assert val_res.is_valid is True
    validator.raise_if_invalid(spec, source_duration_ms=meta.duration_ms)

    # 3. Job State Machine & Rendering
    job = RenderJob(
        job_id="job_render_001",
        tenant_id="tenant_alpha",
        spec=spec,
        status=JobStatus.PENDING,
    )
    new_status = MediaJobStateMachine.transition(job.status, JobStatus.IN_PROGRESS)
    assert new_status == JobStatus.IN_PROGRESS

    renderer = MockRendererAdapter()
    out_file = str(tmp_path / "clip_001.mp4")
    asset = renderer.render(job, source_media_path="dummy_in.mp4", output_path=out_file)

    assert asset.asset_id == "asset_job_render_001"
    assert asset.duration_ms == (selected_opp.end_ms - selected_opp.start_ms)
    assert asset.content_hash is not None

    # Complete Job
    final_status = MediaJobStateMachine.transition(new_status, JobStatus.COMPLETED)
    assert final_status == JobStatus.COMPLETED

    # 4. Quality Checking & Guardian Hook (Phase 13.4)
    checker = QualityChecker()
    report = checker.check(asset)
    assert report.verdict in {QualityVerdict.PASS, QualityVerdict.WARN}

    guardian = PassThroughGuardianHook()
    decision = guardian.evaluate(report)
    assert decision["approved"] is True
    assert decision["action"] == "publish"
