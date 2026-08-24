"""HTTP routes for the execution engine (Engine Room backend).

Every response is read from the durable ``EngineStore`` — there is no in-memory
mock. The UI polls these endpoints to reconstruct real state.
"""

import os
import time
import uuid
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from media_service.security.auth import Authenticator, AuthenticatedTenant, API_KEY_HEADER
from media_service.engine.engine import Engine
from media_service.engine.states import EngineJobState


def build_engine_router(
    engine: Engine,
    authenticator: Authenticator,
    local_storage_base_dir: str,
    ffprobe_binary: str = "ffprobe",
) -> APIRouter:
    router = APIRouter(prefix="/v1/engine", tags=["engine"])

    def _tenant(api_key: Optional[str] = Depends(API_KEY_HEADER)) -> AuthenticatedTenant:
        return authenticator.authenticate_api_key(api_key)

    # -- create job ---------------------------------------------------------

    class CreateEngineJobRequest(BaseModel):
        source_media_path: str
        duration_ms: int
        target_aspect_ratio: str = "9:16"
        publish: bool = False
        platform: Optional[str] = None
        account_id: Optional[str] = None
        rights_status: str = "rights_unknown"

    @router.post("/jobs")
    def create_engine_job(req: CreateEngineJobRequest, tenant: AuthenticatedTenant = Depends(_tenant)):
        job_id = f"eng_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = engine.store.create_job(
            job_id=job_id,
            tenant_id=tenant.tenant_id,
            source_media_path=req.source_media_path,
            duration_ms=req.duration_ms,
            target_aspect_ratio=req.target_aspect_ratio,
            publish=req.publish,
            platform=req.platform,
            account_id=req.account_id,
            rights_status=req.rights_status,
        )
        # CREATED -> VALIDATING (structural spec validation) -> QUEUED.
        # Validation happens synchronously at submission; only valid jobs queue.
        engine.store.transition(
            job_id, EngineJobState.VALIDATING, event_type="job.validating",
            event_source="api",
        )
        from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec
        seg = ClipSegmentSpec(start_ms=0, end_ms=req.duration_ms, source_media_id=req.source_media_path)
        spec = ClipSpecification(
            spec_id=f"spec_{job_id}", source_media_id=req.source_media_path,
            segments=[seg], target_aspect_ratio=req.target_aspect_ratio,
        )
        try:
            engine.spec_validator.raise_if_invalid(spec, source_duration_ms=req.duration_ms)
        except Exception as e:
            engine.store.transition(
                job_id, EngineJobState.FAILED, event_type="job.validation_failed",
                event_source="api", error=str(e), error_message=str(e),
            )
            raise HTTPException(status_code=422, detail=f"Clip specification invalid: {e}")
        engine.store.transition(
            job_id, EngineJobState.QUEUED, event_type="job.queued",
            event_source="api", metadata={"validated": True},
        )
        return {"job": engine.store.get_job(job_id)}

    # -- system state -------------------------------------------------------

    @router.get("/state")
    def get_engine_state(tenant: AuthenticatedTenant = Depends(_tenant)):
        return engine.system_state()

    # -- jobs listing / detail ---------------------------------------------

    @router.get("/jobs")
    def list_engine_jobs(tenant: AuthenticatedTenant = Depends(_tenant), limit: int = 100):
        jobs = engine.store.list_jobs(tenant.tenant_id, limit=min(limit, 500))
        return {"jobs": jobs, "count": len(jobs)}

    @router.get("/jobs/{job_id}")
    def get_engine_job(job_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        job = engine.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Engine job '{job_id}' not found")
        authenticator.authorize_tenant_access(tenant, job["tenant_id"])
        events = engine.store.list_events(job_id, limit=500)
        return {"job": job, "events": events}

    # -- events stream ------------------------------------------------------

    @router.get("/events")
    def list_engine_events(tenant: AuthenticatedTenant = Depends(_tenant), limit: int = 200):
        # Tenant scoping: filter events to this tenant's jobs.
        jobs = {j["job_id"] for j in engine.store.list_jobs(tenant.tenant_id, limit=1000)}
        events = engine.store.list_events(limit=min(limit, 1000))
        scoped = [e for e in events if e.get("job_id") in jobs]
        return {"events": scoped[:limit], "count": len(scoped)}

    # -- actions ------------------------------------------------------------

    @router.post("/jobs/{job_id}/retry")
    def retry_engine_job(job_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        job = engine.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        authenticator.authorize_tenant_access(tenant, job["tenant_id"])
        try:
            return {"job": engine.retry_job(job_id)}
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_engine_job(job_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        job = engine.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        authenticator.authorize_tenant_access(tenant, job["tenant_id"])
        try:
            return {"job": engine.cancel_job(job_id)}
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    # -- system controls ----------------------------------------------------

    @router.post("/pause")
    def pause_engine(tenant: AuthenticatedTenant = Depends(_tenant)):
        engine.pause()
        return {"paused": True}

    @router.post("/resume")
    def resume_engine(tenant: AuthenticatedTenant = Depends(_tenant)):
        engine.resume()
        return {"paused": False}

    @router.post("/workers/{worker_id}/stop")
    def stop_worker(worker_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        if not engine.stop_worker(worker_id):
            raise HTTPException(status_code=404, detail="Worker not found")
        return {"worker_id": worker_id, "state": "offline"}

    @router.post("/workers/{worker_id}/start")
    def start_worker(worker_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        if not engine.start_worker(worker_id):
            raise HTTPException(status_code=409, detail="Worker already running")
        return {"worker_id": worker_id, "state": "idle"}

    # -- real test source ---------------------------------------------------
    # Generates a REAL short video file via FFmpeg (color source + tone) so the
    # pipeline can render with measurable progress without requiring an upload.

    class TestSourceRequest(BaseModel):
        duration_seconds: int = 5
        target_aspect_ratio: str = "9:16"

    @router.post("/test-source")
    def generate_test_source(req: TestSourceRequest, tenant: AuthenticatedTenant = Depends(_tenant)):
        dur = max(1, min(req.duration_seconds, 60))
        upload_dir = os.path.join(local_storage_base_dir, "tenants", tenant.tenant_id, "engine_sources")
        os.makedirs(upload_dir, exist_ok=True)
        name = f"testsrc_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
        out_path = os.path.join(upload_dir, name)

        # 9:16 -> 1080x1920, else derive a 1920-long-edge frame.
        ratio = req.target_aspect_ratio
        if ratio == "9:16":
            w, h = 1080, 1920
        elif ratio == "16:9":
            w, h = 1920, 1080
        elif ratio == "1:1":
            w, h = 1080, 1080
        else:
            w, h = 1080, 1920

        args = [
            "-y",
            "-f", "lavfi",
            "-i", f"testsrc2=size={w}x{h}:rate=30",
            "-f", "lavfi",
            "-i", "sine=frequency=440:sample_rate=44100",
            "-t", str(dur),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-strict", "experimental",
            "-shortest",
            out_path,
        ]
        try:
            result = subprocess.run(["ffmpeg"] + args, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise HTTPException(status_code=503, detail="FFmpeg not available to generate test source")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Test source generation timed out")
        if result.returncode != 0 or not os.path.exists(out_path):
            raise HTTPException(status_code=500, detail=f"FFmpeg failed: {result.stderr[-400:]}")

        # Probe real duration.
        duration_ms = dur * 1000
        try:
            from media_service.inspect.media_inspector import MediaInspector
            inspector = MediaInspector(ffprobe_binary=ffprobe_binary)
            probed = inspector.inspect(out_path)
            if probed.duration_ms:
                duration_ms = probed.duration_ms
        except Exception:
            pass

        return {
            "source_media_path": out_path,
            "filename": name,
            "duration_ms": duration_ms,
            "file_size_bytes": os.path.getsize(out_path),
        }

    return router
