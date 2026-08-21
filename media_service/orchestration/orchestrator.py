import os
import time
import logging
from typing import Any, Dict, List, Optional
from shared.contracts.enums import JobStatus, QualityVerdict, ClipSpecStatus
from shared.contracts.jobs import (
    ContentOpportunity,
    ClipSegmentSpec,
    ClipSpecification,
    RenderJob,
    RenderedAsset,
    QualityReport,
    MediaJobStateMachine,
)
from shared.contracts.media import MediaMetadata, SceneBoundary
from shared.errors.errors import (
    OracleClipError,
    ValidationError,
    RenderingError,
    TenantIsolationError,
)
from media_service.opportunities.template_generator import TemplateOpportunityGenerator
from media_service.clip_spec.validator import ClipSpecificationValidator
from media_service.rendering.ffmpeg_renderer import FFmpegRendererAdapter, MockRendererAdapter
from media_service.quality.guardian_hooks import QualityChecker, PassThroughGuardianHook
from media_service.security.webhooks import WebhookDispatcher
from media_service.security.media_guard import MediaGuard
from media_service.storage.object_storage import ObjectStorageBackend
from media_service.orchestration.contracts import OrchestrationClipTask, WebhookPayload, Base44IntegrationHints

logger = logging.getLogger("oracle_clip.orchestrator")


class CanonicalPipelineOrchestrator:
    """End-to-end deterministic orchestrator executing the canonical media pipeline:
    
    ContentOpportunity -> ClipSpecification -> Validator -> Renderer -> RenderJob -> RenderedAsset -> QualityChecker -> GuardianHook -> Storage -> Webhook Delivery
    """

    def __init__(
        self,
        renderer: Optional[Any] = None,
        storage_backend: Optional[ObjectStorageBackend] = None,
        webhook_dispatcher: Optional[WebhookDispatcher] = None,
        webhook_target_url: Optional[str] = None,
        max_retries: int = 2,
    ):
        self.opportunity_generator = TemplateOpportunityGenerator()
        self.spec_validator = ClipSpecificationValidator()
        self.renderer = renderer or MockRendererAdapter()
        self.quality_checker = QualityChecker()
        self.guardian_hook = PassThroughGuardianHook()
        self.storage_backend = storage_backend
        self.webhook_dispatcher = webhook_dispatcher
        self.webhook_target_url = webhook_target_url
        self.media_guard = MediaGuard()
        self.max_retries = max_retries
        self.hints = Base44IntegrationHints()

    def _dispatch_event(self, tenant_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """Dispatches signed Base44 webhook event if dispatcher and target URL are configured."""
        if not self.webhook_dispatcher or not self.webhook_target_url:
            return

        body = WebhookPayload(
            event_type=event_type,
            tenant_id=tenant_id,
            payload=payload,
        )
        try:
            self.webhook_dispatcher.deliver(
                target_url=self.webhook_target_url,
                payload=body.__dict__,
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch Base44 webhook '{event_type}' to {self.webhook_target_url}: {e}")

    def _render_with_retries(self, job: RenderJob, source_media_path: str, output_path: str) -> RenderedAsset:
        """Single implementation of the render step: bounded retries, fail-closed.

        Raises RenderingError once `max_retries` retries are exhausted.
        """
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= self.max_retries:
            try:
                return self.renderer.render(
                    job,
                    source_media_path=source_media_path,
                    output_path=output_path,
                )
            except Exception as e:
                attempt += 1
                last_error = e
                logger.warning(f"Render attempt {attempt} failed for job {job.job_id}: {e}")

        raise RenderingError(f"Rendering failed after {attempt} attempts: {last_error}")

    def render_job(self, job: RenderJob, source_media_path: str, output_path: str) -> RenderJob:
        """Renders one RenderJob, updating its lifecycle state in place.

        Used by the /v1/render-jobs endpoint and by execute_pipeline so both
        share the same retry and failure semantics. The produced RenderedAsset
        is exposed via `self.last_rendered_asset` for callers that need it.
        """
        try:
            asset = self._render_with_retries(job, source_media_path, output_path)
        except RenderingError as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            raise

        self.last_rendered_asset = asset
        job.status = JobStatus.COMPLETED
        job.output_path = output_path
        return job

    def render_job_with_asset(self, job: RenderJob, source_media_path: str, output_path: str):
        """Same as `render_job` but returns the (job, RenderedAsset) pair."""
        job = self.render_job(job, source_media_path, output_path)
        return job, self.last_rendered_asset

    def execute_pipeline(
        self,
        task_id: str,
        tenant_id: str,
        source_media_path: str,
        duration_ms: int,
        scenes: Optional[List[SceneBoundary]] = None,
        target_aspect_ratio: str = "9:16",
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes full canonical pipeline for an input media item."""
        out_dir = output_dir or "/tmp"
        os.makedirs(out_dir, exist_ok=True)

        # 0. Input media validation & security boundary
        self.media_guard.validate_file_path(source_media_path)

        state_machine = MediaJobStateMachine()

        # Step 1: ContentOpportunity Generation
        meta = MediaMetadata(duration_ms=duration_ms, format_name="mp4")
        opps = self.opportunity_generator.generate(
            source_media_id=task_id,
            metadata=meta,
            scenes=scenes,
            max_opportunities=3,
        )
        if not opps:
            raise ValidationError(f"No valid ContentOpportunity could be generated for {task_id}")

        primary_opp = opps[0]
        self._dispatch_event(tenant_id, "clip.opportunity.detected", {
            "task_id": task_id,
            "opportunity": primary_opp.__dict__,
        })

        # Step 2: ClipSpecification Assembly
        segments = [
            ClipSegmentSpec(
                start_ms=primary_opp.start_ms,
                end_ms=primary_opp.end_ms,
                source_media_id=task_id,
            )
        ]
        spec = ClipSpecification(
            spec_id=f"spec_{task_id}",
            source_media_id=task_id,
            segments=segments,
            schema_version="1.0.0",
            version=1,
            target_aspect_ratio=target_aspect_ratio,
            status=ClipSpecStatus.DRAFT,
            metadata={"opportunity_id": primary_opp.opportunity_id},
        )

        # Step 3: Structural ClipSpecification Validation
        self.spec_validator.raise_if_invalid(spec, source_duration_ms=duration_ms)
        self._dispatch_event(tenant_id, "clip.spec.created", {
            "task_id": task_id,
            "spec_id": spec.spec_id,
        })

        # Step 4: Render Job & State Machine Transition
        job = RenderJob(
            job_id=f"job_{task_id}",
            tenant_id=tenant_id,
            spec=spec,
            status=JobStatus.PENDING,
        )

        # Transition to IN_PROGRESS
        state_machine.transition(JobStatus.PENDING, JobStatus.IN_PROGRESS)
        job.status = JobStatus.IN_PROGRESS

        # Step 5: Rendering (FFmpeg with retry handling)
        out_path = os.path.join(out_dir, f"rendered_{task_id}.mp4")
        try:
            rendered_asset = self._render_with_retries(job, source_media_path, out_path)
        except RenderingError as e:
            state_machine.transition(JobStatus.IN_PROGRESS, JobStatus.FAILED)
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            self._dispatch_event(tenant_id, "clip.failed", {
                "task_id": task_id,
                "job_id": job.job_id,
                "error": str(e),
            })
            raise

        state_machine.transition(JobStatus.IN_PROGRESS, JobStatus.COMPLETED)
        job.status = JobStatus.COMPLETED
        job.output_path = out_path
        self.last_rendered_asset = rendered_asset
        self._dispatch_event(tenant_id, "clip.rendered", {
            "task_id": task_id,
            "job_id": job.job_id,
            "asset_id": rendered_asset.asset_id,
        })

        # Step 6: Quality Assessment
        quality_report = self.quality_checker.check(rendered_asset)
        self._dispatch_event(tenant_id, "clip.quality.checked", {
            "task_id": task_id,
            "report_id": quality_report.report_id,
            "verdict": quality_report.verdict.value,
            "overall_score": quality_report.overall_score,
        })

        # Step 7: Guardian Policy Evaluation
        guardian_decision = self.guardian_hook.evaluate(quality_report)
        self._dispatch_event(tenant_id, "clip.guardian.decided", {
            "task_id": task_id,
            "decision": guardian_decision,
        })

        # Step 8: Optional Durable Storage Upload
        storage_url = None
        if self.storage_backend and os.path.exists(out_path):
            storage_key = f"tenants/{tenant_id}/clips/{task_id}.mp4"
            storage_url = self.storage_backend.put_object(storage_key, out_path, content_type="video/mp4")

        return {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "status": "COMPLETED",
            "opportunity": primary_opp.__dict__,
            "spec": spec.__dict__,
            "job": job.__dict__,
            "asset": rendered_asset.__dict__,
            "quality_report": quality_report.__dict__,
            "guardian_decision": guardian_decision,
            "storage_url": storage_url,
        }
