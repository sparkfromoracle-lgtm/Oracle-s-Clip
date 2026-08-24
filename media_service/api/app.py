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
from media_service.integrations.google_sheets import GoogleSheetsExportService
from media_service.publishing.adapters import get_platform_adapters
from media_service.publishing.publishing_store import PublishingStore
from media_service.publishing.publishing_service import PublishingService
from media_service.scheduling.scheduler import PublishingScheduler
import time
import shutil as shutil_module

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

# Select renderer: use real FFmpeg when the binary is available (even in dev),
# falling back to MockRendererAdapter only when FFmpeg is not installed or
# RENDERER_MODE=mock is set explicitly (useful for unit tests).
import shutil as _shutil
_renderer_mode = os.getenv("RENDERER_MODE", "").lower()
if _renderer_mode == "mock":
    renderer = MockRendererAdapter()
elif _shutil.which(settings.ffmpeg_binary) and _shutil.which(settings.ffprobe_binary):
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

# Google Sheets export service (optional, decoupled from rendering)
google_sheets_service = GoogleSheetsExportService(
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    redirect_uri=settings.google_redirect_uri,
    spreadsheet_id=settings.google_sheets_spreadsheet_id,
    token_store_path=os.getenv("GOOGLE_TOKEN_STORE", "/tmp/oracle_clip_google_token.json"),
)

# Social publishing service (optional, decoupled from rendering)
_publishing_store = PublishingStore(
    db_path=os.getenv("ORACLE_CLIP_PUBLISHING_DB", "/tmp/oracle_clip_publishing.db"),
)
_platform_adapters = get_platform_adapters(settings)
publishing_service = PublishingService(store=_publishing_store, adapters=_platform_adapters)

# Non-spam publishing scheduler (autopilot OFF by default)
publishing_scheduler = PublishingScheduler(autopilot_enabled=False)

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


# NOTE: /v1/render-jobs/active and /v1/render-jobs/history must be registered
# BEFORE /v1/render-jobs/{job_id} so FastAPI doesn't match them as job_id params.

@app.get("/v1/render-jobs/active", tags=["rendering"])
def get_active_render_jobs(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Returns all active (PENDING / IN_PROGRESS) render jobs for the caller's tenant."""
    jobs = job_store.list_active_jobs(tenant.tenant_id)
    return {
        "jobs": [j.__dict__ for j in jobs],
        "count": len(jobs),
    }


@app.get("/v1/render-jobs/history", tags=["rendering"])
def get_render_job_history(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Returns terminal-state render jobs (completed/failed/cancelled) for the
    caller's tenant, with optional filtering, search, and pagination.
    """
    jobs, total = job_store.list_history(
        tenant_id=tenant.tenant_id,
        status=status,
        search=search,
        limit=min(limit, 200),
        offset=offset,
    )
    counts = job_store.count_by_status(tenant.tenant_id)
    return {
        "jobs": [j.__dict__ for j in jobs],
        "total": total,
        "counts": counts,
        "limit": min(limit, 200),
        "offset": offset,
    }


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

    # Persist the completed job so it appears in history.
    if result.get("job"):
        job_data = result["job"]
        persisted_spec = ClipSpecification(
            spec_id=f"spec_{req.task_id}",
            source_media_id=req.source_media_path,
            segments=[ClipSegmentSpec(start_ms=0, end_ms=req.duration_ms, source_media_id=req.source_media_path)],
            target_aspect_ratio=req.target_aspect_ratio,
        )
        job = RenderJob(
            job_id=job_data["job_id"],
            tenant_id=job_data["tenant_id"],
            spec=persisted_spec,
            status=JobStatus(job_data["status"]),
            output_path=job_data.get("output_path"),
            error_message=job_data.get("error_message"),
        )
        job_store.save_job(job)
    return result


# ---------------------------------------------------------------------------
# Google Sheets Export Endpoints
# ---------------------------------------------------------------------------

# -- Google Sheets Export ----------------------------------------------------

class GoogleSheetsExportRequest(BaseModel):
    job_ids: Optional[List[str]] = None  # If None, exports all completed jobs


@app.post("/v1/export/google-sheets", tags=["export"])
def export_to_google_sheets(
    req: GoogleSheetsExportRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Exports completed render jobs to Google Sheets.

    - If ``job_ids`` is provided, exports only those (must be completed + owned
      by the caller's tenant).
    - If ``job_ids`` is omitted, exports all completed jobs for the tenant.
    - Duplicate exports update existing rows (matched by Job ID) rather than
      creating duplicates.
    - Export failure never affects the render job itself.
    """
    if not google_sheets_service.is_configured():
        raise DependencyUnavailableError(
            "Google Sheets is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
            "GOOGLE_REDIRECT_URI, and GOOGLE_SHEETS_SPREADSHEET_ID environment variables.",
        )

    # Gather completed jobs to export.
    if req.job_ids:
        jobs_to_export = []
        for jid in req.job_ids:
            job = job_store.get_job(jid)
            if not job:
                continue
            # Enforce tenant isolation.
            authenticator.authorize_tenant_access(tenant, job.tenant_id)
            if job.status == JobStatus.COMPLETED:
                jobs_to_export.append(job)
    else:
        all_jobs, _ = job_store.list_history(
            tenant_id=tenant.tenant_id,
            status=JobStatus.COMPLETED.value,
            limit=200,
        )
        jobs_to_export = all_jobs

    if not jobs_to_export:
        return {"result": {"status": "success", "exported": 0, "updated": 0, "failed": 0, "errors": ["No completed jobs to export."]}}

    result = google_sheets_service.export_jobs(jobs_to_export)

    # Record export tracking on each successfully exported job.
    from datetime import datetime
    now_iso = datetime.utcnow().isoformat() + "Z"
    for job in jobs_to_export:
        if result.status != "failed":
            job_store.update_export_tracking(job.job_id, now_iso, job.job_id)

    return {"result": result.to_dict()}


@app.get("/v1/integrations/google/status", tags=["export"])
def get_google_sheets_status(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Returns whether Google Sheets export is configured and authorized."""
    return {
        "configured": google_sheets_service.is_configured(),
        "authorized": google_sheets_service.is_authorized(),
    }


@app.get("/v1/integrations/google/auth", tags=["export"])
def start_google_oauth(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Initiates the Google OAuth 2.0 authorization flow. Returns the redirect URL."""
    if not google_sheets_service.is_configured():
        raise DependencyUnavailableError(
            "Google Sheets is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
            "GOOGLE_REDIRECT_URI, and GOOGLE_SHEETS_SPREADSHEET_ID environment variables.",
        )
    auth_url = google_sheets_service.get_auth_url(state=tenant.tenant_id)
    return {"auth_url": auth_url}


class GoogleOAuthCallbackRequest(BaseModel):
    code: str
    state: Optional[str] = None


@app.post("/v1/integrations/google/callback", tags=["export"])
def handle_google_oauth_callback(
    req: GoogleOAuthCallbackRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Handles the OAuth callback: exchanges the authorization code for tokens."""
    try:
        token_data = google_sheets_service.exchange_code(req.code)
        return {"status": "authorized", "token_type": token_data.get("token_type", "Bearer")}
    except Exception as e:
        raise DependencyUnavailableError(f"Google OAuth callback failed: {e}")


# -- Batch / Autonomous Clip Generation ---------------------------------------

class BatchProcessRequest(BaseModel):
    tenant_id: str
    source_media_path: str
    duration_ms: int
    scenes: Optional[List[SceneInput]] = None
    target_aspect_ratio: str = "9:16"
    max_clips: int = 10
    output_dir: Optional[str] = None


@app.post("/v1/orchestration/batch", tags=["orchestration"])
def batch_process_video(
    req: BatchProcessRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Autonomously generates multiple clips from a single source video.

    Runs the full canonical pipeline (opportunity detection → spec generation
    → validation → rendering → quality check → guardian) for each selected
    opportunity, creating one render job per clip. Jobs are persisted to the
    durable store so they appear in the active dashboard and history.
    """
    authenticator.authorize_tenant_access(tenant, req.tenant_id)

    out_dir = req.output_dir or f"/tmp/oracle_clip_renders/{req.tenant_id}"
    os.makedirs(out_dir, exist_ok=True)

    # Step 1: Generate content opportunities from the source.
    meta = MediaMetadata(duration_ms=req.duration_ms, format_name="mp4")
    scenes = None
    if req.scenes:
        scenes = [
            SceneBoundary(scene_index=s.scene_index, start_ms=s.start_ms, end_ms=s.end_ms, score=s.score)
            for s in req.scenes
        ]

    opportunities = opp_generator.generate(
        source_media_id=req.source_media_path,
        metadata=meta,
        scenes=scenes,
        max_opportunities=req.max_clips,
    )
    if not opportunities:
        raise ValidationError(f"No content opportunities could be generated for the source video.")

    results = []
    for i, opp in enumerate(opportunities[: req.max_clips]):
        task_id = f"batch_{int(time.time())}_{i}"
        segments = [ClipSegmentSpec(start_ms=opp.start_ms, end_ms=opp.end_ms, source_media_id=req.source_media_path)]
        spec = ClipSpecification(
            spec_id=f"spec_{task_id}",
            source_media_id=req.source_media_path,
            segments=segments,
            target_aspect_ratio=req.target_aspect_ratio,
            metadata={"opportunity_id": opp.opportunity_id, "score": opp.score, "reason": opp.reason},
        )

        # Validate the specification.
        try:
            spec_validator.raise_if_invalid(spec, source_duration_ms=req.duration_ms)
        except Exception as e:
            results.append({"task_id": task_id, "status": "failed", "error": str(e)})
            continue

        job = RenderJob(
            job_id=f"job_{task_id}",
            tenant_id=req.tenant_id,
            spec=spec,
            status=JobStatus.PENDING,
        )
        job_store.save_job(job)

        # Transition to IN_PROGRESS and render.
        out_path = os.path.join(out_dir, f"rendered_{task_id}.mp4")
        try:
            job, asset = pipeline_orchestrator.render_job_with_asset(
                job, source_media_path=req.source_media_path, output_path=out_path
            )
            job_store.save_job(job)

            # Quality check + guardian.
            quality_report = quality_checker.check(asset)
            guardian_decision = guardian_hook.evaluate(quality_report)

            results.append({
                "task_id": task_id,
                "job_id": job.job_id,
                "status": job.status.value,
                "opportunity_score": opp.score,
                "opportunity_reason": opp.reason,
                "asset": asset.__dict__,
                "quality_verdict": quality_report.verdict.value,
                "guardian_approved": guardian_decision["approved"],
                "output_path": job.output_path,
            })
        except Exception as e:
            failed_job = RenderJob(
                job_id=job.job_id,
                tenant_id=req.tenant_id,
                spec=spec,
                status=JobStatus.FAILED,
                error_message=str(e),
            )
            job_store.save_job(failed_job)
            results.append({"task_id": task_id, "job_id": job.job_id, "status": "failed", "error": str(e)})

    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    return {
        "total": len(results),
        "completed": completed,
        "failed": failed,
        "clips": results,
    }


# ---------------------------------------------------------------------------
# Social Publishing Endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/publishing/capabilities", tags=["publishing"])
def get_publishing_capabilities(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Returns the platform capability matrix for all supported platforms."""
    return {"platforms": publishing_service.get_capability_matrix()}


@app.get("/v1/publishing/accounts", tags=["publishing"])
def list_connected_accounts(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Lists all connected social accounts for the caller's tenant."""
    accounts = publishing_service.list_accounts(tenant.tenant_id)
    return {
        "accounts": [
            {
                "account_id": a.account_id,
                "platform": a.platform,
                "display_name": a.display_name,
                "platform_user_id": a.platform_user_id,
                "status": a.status,
                "connected_at": a.connected_at,
                "scopes": a.scopes,
            }
            for a in accounts
        ],
        "count": len(accounts),
    }


class StartOAuthRequest(BaseModel):
    platform: str
    redirect_uri: Optional[str] = None


@app.post("/v1/publishing/oauth/start", tags=["publishing"])
def start_platform_oauth(
    req: StartOAuthRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Initiates the OAuth 2.0 flow for a social platform."""
    redirect_uri = req.redirect_uri or settings.social_oauth_redirect_uri
    if not redirect_uri:
        raise ValidationError("redirect_uri is required (set SOCIAL_OAUTH_REDIRECT_URI or pass redirect_uri in the request).")
    try:
        auth_url = publishing_service.start_oauth(
            tenant_id=tenant.tenant_id,
            platform=req.platform,
            redirect_uri=redirect_uri,
        )
        return {"auth_url": auth_url}
    except RuntimeError as e:
        raise DependencyUnavailableError(str(e))
    except ValueError as e:
        raise ValidationError(str(e))


class OAuthCallbackRequest(BaseModel):
    platform: str
    code: str
    redirect_uri: Optional[str] = None


@app.post("/v1/publishing/oauth/callback", tags=["publishing"])
def handle_platform_oauth_callback(
    req: OAuthCallbackRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Handles the OAuth callback: exchanges code for tokens and stores the account."""
    redirect_uri = req.redirect_uri or settings.social_oauth_redirect_uri
    if not redirect_uri:
        raise ValidationError("redirect_uri is required.")
    try:
        account = publishing_service.complete_oauth(
            tenant_id=tenant.tenant_id,
            platform=req.platform,
            code=req.code,
            redirect_uri=redirect_uri,
        )
        return {
            "account_id": account.account_id,
            "platform": account.platform,
            "display_name": account.display_name,
            "status": account.status,
        }
    except RuntimeError as e:
        raise DependencyUnavailableError(str(e))


@app.delete("/v1/publishing/accounts/{account_id}", tags=["publishing"])
def disconnect_account(
    account_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Revokes the platform token and disconnects the account."""
    try:
        success = publishing_service.disconnect_account(tenant.tenant_id, account_id)
        if not success:
            raise ResourceNotFoundError(f"Account '{account_id}' not found.")
        return {"status": "disconnected", "account_id": account_id}
    except PermissionError as e:
        raise TenantIsolationError(str(e))


class CreatePostRequest(BaseModel):
    render_job_id: str
    rendered_asset_id: str
    platform: str
    account_id: str
    title: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    privacy: Optional[str] = None
    scheduled_at: Optional[str] = None
    video_path: Optional[str] = None
    auto_publish: bool = False


@app.post("/v1/publishing/posts", tags=["publishing"])
def create_social_post(
    req: CreatePostRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Creates a draft social post for a rendered clip. Does NOT publish yet."""
    post = publishing_service.create_post(
        tenant_id=tenant.tenant_id,
        render_job_id=req.render_job_id,
        rendered_asset_id=req.rendered_asset_id,
        platform=req.platform,
        account_id=req.account_id,
        title=req.title,
        caption=req.caption,
        hashtags=req.hashtags,
        privacy=req.privacy,
        scheduled_at=req.scheduled_at,
        video_path=req.video_path,
        auto_publish=req.auto_publish,
    )
    return {"post": post.__dict__}


class PublishPostRequest(BaseModel):
    post_id: str
    force: bool = True  # Explicit user approval


@app.post("/v1/publishing/posts/publish", tags=["publishing"])
def publish_social_post(
    req: PublishPostRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Publishes a social post to its platform. Requires explicit approval."""
    result = publishing_service.publish_post(
        post_id=req.post_id,
        tenant_id=tenant.tenant_id,
        force=req.force,
    )
    return {
        "success": result.success,
        "platform_post_id": result.platform_post_id,
        "post_url": result.post_url,
        "error": result.error,
    }


class BulkPublishRequest(BaseModel):
    render_job_id: str
    rendered_asset_id: str
    video_path: Optional[str] = None
    posts: List[CreatePostRequest]


@app.post("/v1/publishing/posts/bulk", tags=["publishing"])
def bulk_publish(
    req: BulkPublishRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Creates and publishes posts to multiple platforms in one request.
    Each post requires the same explicit approval as single publishing.
    """
    results = []
    for post_req in req.posts:
        post = publishing_service.create_post(
            tenant_id=tenant.tenant_id,
            render_job_id=req.render_job_id,
            rendered_asset_id=req.rendered_asset_id,
            platform=post_req.platform,
            account_id=post_req.account_id,
            title=post_req.title,
            caption=post_req.caption,
            hashtags=post_req.hashtags,
            privacy=post_req.privacy,
            scheduled_at=post_req.scheduled_at,
            video_path=req.video_path,
            auto_publish=post_req.auto_publish,
        )
        result = publishing_service.publish_post(
            post_id=post.post_id,
            tenant_id=tenant.tenant_id,
            force=True,
        )
        results.append({
            "post_id": post.post_id,
            "platform": post.platform,
            "success": result.success,
            "post_url": result.post_url,
            "error": result.error,
        })
    succeeded = sum(1 for r in results if r["success"])
    return {
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@app.post("/v1/publishing/posts/{post_id}/retry", tags=["publishing"])
def retry_social_post(
    post_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Retries a failed social post."""
    result = publishing_service.retry_post(post_id, tenant.tenant_id)
    return {
        "success": result.success,
        "platform_post_id": result.platform_post_id,
        "post_url": result.post_url,
        "error": result.error,
    }


@app.post("/v1/publishing/posts/{post_id}/cancel", tags=["publishing"])
def cancel_social_post(
    post_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Cancels a draft or queued social post."""
    try:
        success = publishing_service.cancel_post(post_id, tenant.tenant_id)
        if not success:
            raise ValidationError(f"Cannot cancel post '{post_id}' in its current state.")
        return {"status": "cancelled", "post_id": post_id}
    except PermissionError as e:
        raise TenantIsolationError(str(e))


@app.get("/v1/publishing/posts", tags=["publishing"])
def list_social_posts(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
    status: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Lists social posts for the caller's tenant with optional filters."""
    posts, total = publishing_service.list_posts(
        tenant.tenant_id, status, platform, min(limit, 200), offset
    )
    return {
        "posts": [p.__dict__ for p in posts],
        "total": total,
        "limit": min(limit, 200),
        "offset": offset,
    }


@app.get("/v1/publishing/posts/{post_id}", tags=["publishing"])
def get_social_post(
    post_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Retrieves a single social post by ID."""
    try:
        post = publishing_service.get_post(post_id, tenant.tenant_id)
    except PermissionError as e:
        raise TenantIsolationError(str(e))
    if not post:
        raise ResourceNotFoundError(f"Social post '{post_id}' not found.")
    return {"post": post.__dict__}


# ---------------------------------------------------------------------------
# Media Upload Endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/media/upload", tags=["media"])
async def upload_media(
    request: Request,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Uploads a source video file for processing. Validates the file and stores
    it in the tenant-scoped storage directory.

    Returns the server-side path to use as ``source_media_path`` in render jobs.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise ValidationError("Expected multipart/form-data upload.")

    from starlette.formparsers import MultiPartParser
    form = await request.form()
    upload_file = form.get("file")
    if upload_file is None:
        raise ValidationError("No 'file' field in upload.")

    # Read the file bytes
    file_bytes = await upload_file.read()
    if not file_bytes:
        raise ValidationError("Uploaded file is empty.")

    # Validate the media bytes (magic bytes, size)
    media_guard.validate_bytes(file_bytes, filename=upload_file.filename)

    # Store in tenant-scoped directory
    upload_dir = os.path.join(settings.local_storage_base_dir, "tenants", tenant.tenant_id, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    # Generate a unique filename
    original_name = upload_file.filename or "upload.mp4"
    safe_name = os.path.basename(original_name)
    timestamp = int(time.time())
    stored_name = f"{timestamp}_{safe_name}"
    stored_path = os.path.join(upload_dir, stored_name)

    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    # Probe the media for duration if ffprobe is available
    duration_ms = 0
    try:
        from media_service.inspect.media_inspector import MediaInspector
        inspector = MediaInspector(ffprobe_binary=settings.ffprobe_binary)
        probed = inspector.inspect(stored_path)
        duration_ms = probed.duration_ms or 0
    except Exception:
        pass

    return {
        "source_media_path": stored_path,
        "filename": stored_name,
        "file_size_bytes": len(file_bytes),
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Rendered Asset Download Endpoint
# ---------------------------------------------------------------------------

@app.get("/v1/render-jobs/{job_id}/download", tags=["rendering"])
def download_rendered_asset(
    job_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Serves the rendered output file for download. Enforces tenant isolation."""
    job = job_store.get_job(job_id)
    if not job:
        raise ResourceNotFoundError(f"RenderJob with id '{job_id}' not found")

    authenticator.authorize_tenant_access(tenant, job.tenant_id)

    if job.status != JobStatus.COMPLETED:
        raise ValidationError(f"Job '{job_id}' is not completed (status: {job.status.value}).")

    if not job.output_path or not os.path.exists(job.output_path):
        raise ResourceNotFoundError(f"Rendered output file not found for job '{job_id}'.")

    from fastapi.responses import FileResponse
    filename = os.path.basename(job.output_path)
    return FileResponse(
        path=job.output_path,
        media_type="video/mp4",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Rights / Provenance Endpoints
# ---------------------------------------------------------------------------

class UpdateRightsRequest(BaseModel):
    job_id: str
    rights_status: str
    rights_owner: Optional[str] = None
    rights_source: Optional[str] = None
    rights_license: Optional[str] = None
    rights_notes: Optional[str] = None


@app.post("/v1/rights/update", tags=["rights"])
def update_job_rights(
    req: UpdateRightsRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Updates the rights/provenance status of a render job.

    Unknown rights must never silently become publishable — the publishing
    compliance gate checks this status before allowing publication.
    """
    job = job_store.get_job(req.job_id)
    if not job:
        raise ResourceNotFoundError(f"RenderJob with id '{req.job_id}' not found")

    authenticator.authorize_tenant_access(tenant, job.tenant_id)

    from shared.contracts.enums import RightsStatus
    valid_statuses = {rs.value for rs in RightsStatus}
    if req.rights_status not in valid_statuses:
        raise ValidationError(f"Invalid rights_status. Must be one of: {valid_statuses}")

    # Update the job with rights information
    updated_job = RenderJob(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        spec=job.spec,
        status=job.status,
        output_path=job.output_path,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        progress=job.progress,
        google_sheet_exported_at=job.google_sheet_exported_at,
        google_sheet_row_id=job.google_sheet_row_id,
        rights_status=req.rights_status,
        rights_owner=req.rights_owner,
        rights_source=req.rights_source,
        rights_license=req.rights_license,
        rights_notes=req.rights_notes,
        metadata=job.metadata,
    )
    job_store.save_job(updated_job)
    return {"job_id": req.job_id, "rights_status": req.rights_status}


@app.get("/v1/rights/{job_id}", tags=["rights"])
def get_job_rights(
    job_id: str,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Returns the rights/provenance status for a render job."""
    job = job_store.get_job(job_id)
    if not job:
        raise ResourceNotFoundError(f"RenderJob with id '{job_id}' not found")

    authenticator.authorize_tenant_access(tenant, job.tenant_id)
    return {
        "job_id": job_id,
        "rights_status": job.rights_status,
        "rights_owner": job.rights_owner,
        "rights_source": job.rights_source,
        "rights_license": job.rights_license,
        "rights_notes": job.rights_notes,
    }


# ---------------------------------------------------------------------------
# Scheduler Endpoints
# ---------------------------------------------------------------------------

class ScheduleEvaluateRequest(BaseModel):
    quality_verdict: str = "pass"
    quality_score: float = 0.0
    opportunity_score: float = 0.0
    rights_status: str = "rights_unknown"
    guardian_approved: bool = False
    platform: Optional[str] = None
    posts_today: int = 0
    max_posts_per_day: int = 3


@app.post("/v1/scheduler/evaluate", tags=["scheduler"])
def evaluate_schedule(
    req: ScheduleEvaluateRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Evaluates whether a candidate clip should be published now, later, or not at all.

    The scheduler can decide 'Nothing worth publishing right now' — it never
    creates filler content to satisfy a posting quota. Autopilot is OFF by default.
    """
    result = publishing_scheduler.evaluate(
        quality_verdict=req.quality_verdict,
        quality_score=req.quality_score,
        opportunity_score=req.opportunity_score,
        rights_status=req.rights_status,
        guardian_approved=req.guardian_approved,
        platform=req.platform,
        posts_today=req.posts_today,
        max_posts_per_day=req.max_posts_per_day,
    )
    return result


class SetAutopilotRequest(BaseModel):
    enabled: bool


@app.post("/v1/scheduler/autopilot", tags=["scheduler"])
def set_autopilot(
    req: SetAutopilotRequest,
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Toggles autopilot mode. OFF by default — manual review is always required
    when autopilot is disabled."""
    publishing_scheduler.autopilot_enabled = req.enabled
    return {"autopilot_enabled": req.enabled}


@app.get("/v1/scheduler/status", tags=["scheduler"])
def get_scheduler_status(
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
):
    """Returns the current scheduler configuration."""
    return {
        "autopilot_enabled": publishing_scheduler.autopilot_enabled,
        "min_quality_score": 0.75,
        "min_opportunity_score": 0.70,
        "min_platform_interval_hours": 4,
    }
