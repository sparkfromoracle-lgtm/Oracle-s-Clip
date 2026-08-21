import os
import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
    ClipSpecificationValidationError,
    SecurityError,
    AuthenticationError,
    TenantIsolationError,
    WebhookVerificationError,
    ResourceNotFoundError,
    DependencyUnavailableError,
    RenderingError,
    StorageError,
)
from media_service.config.settings import Settings, load_settings_from_env
from media_service.security.auth import Authenticator, AuthenticatedTenant, API_KEY_HEADER
from media_service.security.webhooks import WebhookSecurity, WebhookDispatcher
from media_service.security.rate_limiter import TokenBucketRateLimiter, RateLimitExceededError
from media_service.security.idempotency import IdempotencyStore
from media_service.security.media_guard import MediaGuard
from media_service.storage.object_storage import get_storage_backend
from media_service.opportunities.template_generator import TemplateOpportunityGenerator
from media_service.clip_spec.validator import ClipSpecificationValidator
from media_service.rendering.ffmpeg_renderer import MockRendererAdapter, FFmpegRendererAdapter
from media_service.quality.guardian_hooks import QualityChecker, PassThroughGuardianHook
from media_service.orchestration.orchestrator import CanonicalPipelineOrchestrator
from media_service.api.readiness import ReadinessProbe
from media_service.observability.logging import redact_sensitive_data
from media_service.observability.metrics import metrics_collector
from media_service.storage.job_store import DurableJobStore
from media_service.storage.lifecycle import DataLifecycleManager
import time

logger = logging.getLogger("oracle_clip.api")

settings = load_settings_from_env()
authenticator = Authenticator(settings)
webhook_security = WebhookSecurity(
    secret=settings.webhook_secret,
    timestamp_tolerance_seconds=settings.webhook_timestamp_tolerance_seconds,
)
webhook_dispatcher = WebhookDispatcher(security=webhook_security) if settings.webhook_secret else None
storage_backend = get_storage_backend(settings) if not settings.is_production or settings.storage_backend == "local" else None
rate_limiter = TokenBucketRateLimiter(requests_per_minute=settings.rate_limit_requests_per_minute)
idempotency_store = IdempotencyStore(default_ttl_seconds=settings.idempotency_ttl_seconds)
media_guard = MediaGuard(max_file_size_bytes=settings.max_upload_size_bytes)
readiness_probe = ReadinessProbe(settings)

# Select renderer
if settings.is_production:
    renderer = FFmpegRendererAdapter(
        ffmpeg_binary=settings.ffmpeg_binary,
        timeout_seconds=settings.rendering_timeout_seconds,
        ffprobe_binary=settings.ffprobe_binary,
    )
else:
    renderer = MockRendererAdapter()

opp_generator = TemplateOpportunityGenerator()
spec_validator = ClipSpecificationValidator()
quality_checker = QualityChecker()
guardian_hook = PassThroughGuardianHook()
pipeline_orchestrator = CanonicalPipelineOrchestrator(
    renderer=renderer,
    storage_backend=storage_backend,
    webhook_dispatcher=webhook_dispatcher,
    max_retries=settings.max_render_retries,
)

# Durable storage for jobs in this service process
job_store = DurableJobStore(db_path=os.getenv("ORACLE_CLIP_JOBS_DB", "/tmp/oracle_clip_jobs.db"))
lifecycle_manager = DataLifecycleManager(job_store=job_store)

app = FastAPI(
    title="Oracle Clip Production Hub API",
    version="1.0.0",
    description="Deterministic media processing, opportunity generation, clip validation, and rendering service.",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_and_telemetry_middleware(request: Request, call_next):
    start_time = time.time()
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000.0
        metrics_collector.record_request(response.status_code, duration_ms)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        metrics_collector.record_request(500, duration_ms)
        raise e


@app.exception_handler(OracleClipError)
async def oracle_clip_error_handler(request: Request, exc: OracleClipError):
    status_code = 500
    if isinstance(exc, RateLimitExceededError):
        status_code = 429
        metrics_collector.record_rate_limit()
    elif isinstance(exc, TenantIsolationError):
        status_code = 403
        metrics_collector.record_tenant_isolation_violation()
    elif isinstance(exc, WebhookVerificationError):
        status_code = 400
        metrics_collector.record_webhook_failure()
    elif isinstance(exc, (AuthenticationError, SecurityError)):
        status_code = 401
        metrics_collector.record_auth_failure()
    elif isinstance(exc, (ValidationError, ClipSpecificationValidationError)):
        status_code = 422
    elif isinstance(exc, ResourceNotFoundError):
        status_code = 404
    elif isinstance(exc, DependencyUnavailableError):
        status_code = 503
    elif isinstance(exc, RenderingError):
        metrics_collector.record_ffmpeg_failure()
    elif isinstance(exc, StorageError):
        metrics_collector.record_storage_failure()

    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.error(f"[{correlation_id}] Handled {exc.__class__.__name__}: {exc.message}")

    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": redact_sensitive_data(exc.details),
            "correlation_id": correlation_id,
        },
    )


# Dependency for Tenant Authentication
def get_current_tenant(api_key: Optional[str] = Depends(API_KEY_HEADER)) -> AuthenticatedTenant:
    tenant = authenticator.authenticate_api_key(api_key)
    rate_limiter.enforce(tenant.tenant_id)
    return tenant


# System Health & Readiness Endpoints
@app.get("/health", tags=["system"])
def health_check():
    """Liveness probe: returns 200 if API process is running."""
    return {"status": "ok", "service": "oracle-clip-media-service"}


@app.get("/ready", tags=["system"])
def readiness_check():
    """Readiness probe: verifies external dependencies and configuration."""
    return readiness_probe.check_readiness()


@app.get("/metrics", tags=["observability"])
def get_prometheus_metrics():
    """Prometheus exposition format metrics."""
    return Response(content=metrics_collector.to_prometheus_format(), media_type="text/plain")


@app.get("/v1/metrics", tags=["observability"])
def get_json_metrics(tenant: AuthenticatedTenant = Depends(get_current_tenant)):
    """Structured JSON telemetry and performance percentiles."""
    return metrics_collector.get_summary()


@app.get("/v1/lifecycle/usage/{target_tenant_id}", tags=["lifecycle"])
def get_tenant_lifecycle_usage(
    target_tenant_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Returns disk and quota telemetry for the tenant."""
    authenticator.authorize_tenant_access(tenant, target_tenant_id)
    return lifecycle_manager.get_tenant_storage_usage(target_tenant_id)


@app.post("/v1/lifecycle/cleanup", tags=["lifecycle"])
def trigger_lifecycle_cleanup(tenant: AuthenticatedTenant = Depends(get_current_tenant)):
    """Runs automated temporary file and failed render cleanup."""
    temp_cleaned = lifecycle_manager.cleanup_temp_files(max_age_seconds=1800)
    failed_cleaned = lifecycle_manager.cleanup_failed_renders()
    return {
        "status": "success",
        "temp_files_cleaned": temp_cleaned,
        "failed_renders_cleaned": failed_cleaned,
    }


@app.get("/v1/config/summary", tags=["system"])
def get_config_summary(tenant: AuthenticatedTenant = Depends(get_current_tenant)):
    """Returns safe, sanitized configuration summary without credentials."""
    return settings.safe_summary()


# Opportunity Generation Schemas & Endpoints
class SceneInput(BaseModel):
    scene_index: int
    start_ms: int
    end_ms: int
    score: float = 1.0


class GenerateOpportunitiesRequest(BaseModel):
    source_media_id: str
    duration_ms: int
    scenes: Optional[List[SceneInput]] = None
    max_opportunities: int = 10


@app.post("/v1/opportunities/generate", tags=["opportunities"])
def generate_opportunities(
    req: GenerateOpportunitiesRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Phase 13.1: Deterministic Zero-LLM ContentOpportunity generation."""
    meta = MediaMetadata(duration_ms=req.duration_ms, format_name="mp4")
    scenes = None
    if req.scenes:
        scenes = [
            SceneBoundary(
                scene_index=s.scene_index,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                score=s.score,
            )
            for s in req.scenes
        ]

    opps = opp_generator.generate(
        source_media_id=req.source_media_id,
        metadata=meta,
        scenes=scenes,
        max_opportunities=req.max_opportunities,
    )
    return {"opportunities": [o.__dict__ for o in opps]}


# Clip Specification Validation Schemas & Endpoints
class SegmentSpecInput(BaseModel):
    start_ms: int
    end_ms: int
    source_media_id: Optional[str] = None
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None


class ClipSpecInput(BaseModel):
    spec_id: str
    source_media_id: str
    segments: List[SegmentSpecInput]
    schema_version: str = "1.0.0"
    version: int = 1
    target_aspect_ratio: str = "9:16"
    status: str = "draft"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ValidateClipSpecRequest(BaseModel):
    spec: ClipSpecInput
    source_duration_ms: Optional[int] = None


@app.post("/v1/clip-specs/validate", tags=["clip_spec"])
def validate_clip_specification(
    req: ValidateClipSpecRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Phase 13.2: Structural ClipSpecification validation."""
    segments = [
        ClipSegmentSpec(
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            source_media_id=s.source_media_id,
            transition_in=s.transition_in,
            transition_out=s.transition_out,
        )
        for s in req.spec.segments
    ]
    spec = ClipSpecification(
        spec_id=req.spec.spec_id,
        source_media_id=req.spec.source_media_id,
        segments=segments,
        schema_version=req.spec.schema_version,
        version=req.spec.version,
        target_aspect_ratio=req.spec.target_aspect_ratio,
        status=ClipSpecStatus(req.spec.status) if req.spec.status in ClipSpecStatus._value2member_map_ else ClipSpecStatus.DRAFT,
        metadata=req.spec.metadata,
    )

    res = spec_validator.validate(spec, source_duration_ms=req.source_duration_ms)
    return {"is_valid": res.is_valid, "errors": res.errors}


# Rendering Schemas & Endpoints
class CreateRenderJobRequest(BaseModel):
    job_id: str
    tenant_id: str
    spec: ClipSpecInput
    source_media_path: Optional[str] = None
    output_path: Optional[str] = None


@app.post("/v1/render-jobs", tags=["rendering"])
def create_render_job(
    req: CreateRenderJobRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Submits and renders a ClipSpecification with strict tenant isolation and idempotency."""
    # Tenant isolation enforcement
    authenticator.authorize_tenant_access(tenant, req.tenant_id)

    # Check idempotency cache
    cache_key = f"{req.tenant_id}:{idempotency_key}" if idempotency_key else f"{req.tenant_id}:job:{req.job_id}"
    cached = idempotency_store.get(cache_key)
    if cached:
        return cached

    segments = [
        ClipSegmentSpec(
            start_ms=s.start_ms,
            end_ms=s.end_ms,
            source_media_id=s.source_media_id,
        )
        for s in req.spec.segments
    ]
    spec = ClipSpecification(
        spec_id=req.spec.spec_id,
        source_media_id=req.spec.source_media_id,
        segments=segments,
        schema_version=req.spec.schema_version,
        version=req.spec.version,
        target_aspect_ratio=req.spec.target_aspect_ratio,
        metadata=req.spec.metadata,
    )

    # Validate specification first
    spec_validator.raise_if_invalid(spec)

    metrics_collector.record_job_submitted()
    job_start_time = time.time()

    job = RenderJob(
        job_id=req.job_id,
        tenant_id=req.tenant_id,
        spec=spec,
        status=JobStatus.PENDING,
    )
    job_store[job.job_id] = job

    # Execute render
    source_path = req.source_media_path or "/tmp/dummy_input.mp4"
    out_path = req.output_path or f"/tmp/render_{job.job_id}.mp4"

    # Transition to IN_PROGRESS
    job = RenderJob(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        spec=job.spec,
        status=JobStatus.IN_PROGRESS,
    )
    job_store[job.job_id] = job

    try:
        # Delegated to the orchestrator so the endpoint shares the pipeline's
        # bounded-retry / fail-closed semantics and honours max_render_retries.
        job, asset = pipeline_orchestrator.render_job_with_asset(
            job, source_media_path=source_path, output_path=out_path
        )
        job_store[job.job_id] = job
        render_duration_ms = (time.time() - job_start_time) * 1000.0
        metrics_collector.record_job_completed(render_duration_ms)
        response_data = {"job": job.__dict__, "asset": asset.__dict__}
        idempotency_store.put(cache_key, response_data)
        return response_data
    except Exception as e:
        metrics_collector.record_job_failed()
        job = RenderJob(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            spec=job.spec,
            status=JobStatus.FAILED,
            error_message=str(e),
        )
        job_store[job.job_id] = job
        raise e


@app.get("/v1/render-jobs/{job_id}", tags=["rendering"])
def get_render_job(
    job_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Retrieves RenderJob state with tenant scoping."""
    job = job_store.get(job_id)
    if not job:
        raise ResourceNotFoundError(f"RenderJob with id '{job_id}' not found")

    authenticator.authorize_tenant_access(tenant, job.tenant_id)
    return {"job": job.__dict__}


# Quality & Guardian Schemas & Endpoints
class RenderedAssetInput(BaseModel):
    asset_id: str
    job_id: str
    tenant_id: str
    storage_path: str
    duration_ms: int
    width: int
    height: int
    bitrate: Optional[int] = None
    file_size_bytes: Optional[int] = None
    content_hash: Optional[str] = None
    checksum_sha256: Optional[str] = None


@app.post("/v1/quality/check", tags=["quality"])
def check_asset_quality(
    req: RenderedAssetInput,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Phase 13.4: Evaluates quality metrics on a rendered asset."""
    authenticator.authorize_tenant_access(tenant, req.tenant_id)

    asset = RenderedAsset(
        asset_id=req.asset_id,
        job_id=req.job_id,
        tenant_id=req.tenant_id,
        storage_path=req.storage_path,
        duration_ms=req.duration_ms,
        width=req.width,
        height=req.height,
        bitrate=req.bitrate,
        file_size_bytes=req.file_size_bytes,
        content_hash=req.content_hash,
        checksum_sha256=req.checksum_sha256,
    )
    report = quality_checker.check(asset)
    guardian_decision = guardian_hook.evaluate(report)
    return {
        "quality_report": report.__dict__,
        "guardian_decision": guardian_decision,
    }


class GuardianEvaluateRequest(BaseModel):
    report_id: str
    asset_id: str
    verdict: str
    overall_score: float
    summary: str


@app.post("/v1/guardian/evaluate", tags=["quality"])
def evaluate_guardian_policy(
    req: GuardianEvaluateRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Phase 13.4: Evaluates Guardian policy for publication approval."""
    verdict_enum = QualityVerdict(req.verdict) if req.verdict in QualityVerdict._value2member_map_ else QualityVerdict.FAIL
    report = QualityReport(
        report_id=req.report_id,
        asset_id=req.asset_id,
        verdict=verdict_enum,
        overall_score=req.overall_score,
        metrics=[],
        created_at="",
        summary=req.summary,
    )
    decision = guardian_hook.evaluate(report)
    return {"decision": decision}


# Webhook Inbound Verification Endpoint
@app.post("/v1/webhooks/inbound", tags=["webhooks"])
async def receive_inbound_webhook(
    request: Request,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
    x_webhook_timestamp: Optional[str] = Header(None, alias="X-Webhook-Timestamp"),
):
    """Phase 13.7: Secure webhook receiver with HMAC-SHA256 signature verification and replay prevention."""
    raw_body = await request.body()
    webhook_security.verify_inbound_signature(
        raw_body=raw_body,
        signature_header=x_webhook_signature,
        timestamp_header=x_webhook_timestamp,
    )

    try:
        import json
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        payload = {}

    return {
        "status": "received",
        "verified": True,
        "event_type": payload.get("event_type", "unknown"),
    }


class ChecksumVerifyRequest(BaseModel):
    artifact_identity: str
    content: str
    expected_checksum: Optional[str] = None


@app.post("/v1/checksums/verify", tags=["checksums"])
def verify_checksum_endpoint(
    req: ChecksumVerifyRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Cryptographic SHA-256 Checksum Verification endpoint."""
    from shared.hashing.checksum_verifier import verify_artifact_checksum

    report = verify_artifact_checksum(
        artifact_identity=req.artifact_identity,
        data_or_path=req.content.encode("utf-8"),
        expected_checksum=req.expected_checksum,
    )
    return {"verification": report.to_dict()}


class RunOrchestrationRequest(BaseModel):
    task_id: str
    tenant_id: str
    source_media_path: str
    duration_ms: int
    scenes: Optional[List[SceneInput]] = None
    target_aspect_ratio: str = "9:16"
    output_dir: Optional[str] = None


@app.post("/v1/orchestration/run", tags=["orchestration"])
def run_orchestration_pipeline(
    req: RunOrchestrationRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Executes full canonical media pipeline end-to-end with tenant authorization."""
    authenticator.authorize_tenant_access(tenant, req.tenant_id)

    scenes = None
    if req.scenes:
        scenes = [
            SceneBoundary(
                scene_index=s.scene_index,
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                score=s.score,
            )
            for s in req.scenes
        ]

    result = pipeline_orchestrator.execute_pipeline(
        task_id=req.task_id,
        tenant_id=req.tenant_id,
        source_media_path=req.source_media_path,
        duration_ms=req.duration_ms,
        scenes=scenes,
        target_aspect_ratio=req.target_aspect_ratio,
        output_dir=req.output_dir,
    )
    return result
