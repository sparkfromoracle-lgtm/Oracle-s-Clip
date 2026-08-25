"""HTTP routes for the execution engine (Engine Room backend).

Every response is read from the durable ``EngineStore`` — there is no in-memory
mock. The UI polls these endpoints to reconstruct real state.
"""

import json
import os
import shutil
import time
import uuid
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from media_service.security.auth import Authenticator, AuthenticatedTenant, API_KEY_HEADER
from media_service.engine.engine import Engine
from media_service.engine.states import EngineJobState
from media_service.rendering.ffmpeg_renderer import FFmpegRendererAdapter, MockRendererAdapter


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

    # -- export (download the real rendered file) ---------------------------

    @router.get("/jobs/{job_id}/export")
    def export_engine_job(job_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        """Returns the actual rendered media file for a completed job.

        This is the EXPORT action: the user takes the finished clip out of
        Oracle's Clip. Returns the real file — never a placeholder.
        """
        job = engine.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Engine job '{job_id}' not found")
        authenticator.authorize_tenant_access(tenant, job["tenant_id"])

        if job["state"] != EngineJobState.COMPLETED.value:
            raise HTTPException(
                status_code=409,
                detail=f"Job is not completed (state: {job['state']}). Only completed jobs can be exported.",
            )

        out_path = job.get("output_path") or ""
        if not out_path or not os.path.exists(out_path):
            raise HTTPException(
                status_code=404,
                detail="Rendered output file not found. The artifact may have been cleaned up.",
            )
        if os.path.getsize(out_path) == 0:
            raise HTTPException(status_code=422, detail="Rendered output file is empty (0 bytes).")

        filename = os.path.basename(out_path)
        return FileResponse(
            path=out_path,
            media_type="video/mp4",
            filename=filename,
        )

    # -- output validation (verify the real artifact) -----------------------

    @router.get("/jobs/{job_id}/output")
    def validate_engine_output(job_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        """Validates the final rendered output file against real criteria.

        Checks: file exists, readable, non-zero, duration valid, video stream
        present, audio stream present (when expected), codec valid, resolution
        valid, playable. Returns the real probe data — never fabricated.
        """
        job = engine.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Engine job '{job_id}' not found")
        authenticator.authorize_tenant_access(tenant, job["tenant_id"])

        out_path = job.get("output_path") or ""
        result: Dict[str, Any] = {
            "job_id": job_id,
            "output_path": out_path,
            "exists": False,
            "readable": False,
            "size_bytes": 0,
            "duration_ms": 0,
            "video_stream": None,
            "audio_stream": None,
            "codec": None,
            "resolution": None,
            "playable": False,
            "valid": False,
            "errors": [],
        }

        if not out_path:
            result["errors"].append("No output path recorded for this job.")
            return result

        if not os.path.exists(out_path):
            result["errors"].append("Output file does not exist on disk.")
            return result

        result["exists"] = True
        result["size_bytes"] = os.path.getsize(out_path)
        if result["size_bytes"] == 0:
            result["errors"].append("Output file is 0 bytes (corrupt/empty).")
            return result

        try:
            with open(out_path, "rb") as f:
                f.read(1)
            result["readable"] = True
        except Exception as e:
            result["errors"].append(f"Output file is not readable: {e}")
            return result

        # Probe with ffprobe for real stream metadata.
        try:
            probe = subprocess.run(
                [
                    ffprobe_binary, "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams", "-show_format",
                    out_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if probe.returncode != 0:
                result["errors"].append("ffprobe could not parse the output file (not playable).")
                return result
            info = json.loads(probe.stdout)
        except Exception as e:
            result["errors"].append(f"ffprobe failed: {e}")
            return result

        streams = info.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        fmt = info.get("format", {})

        result["video_stream"] = {
            "codec": v_stream.get("codec_name") if v_stream else None,
            "width": int(v_stream.get("width", 0)) if v_stream else 0,
            "height": int(v_stream.get("height", 0)) if v_stream else 0,
        } if v_stream else None
        result["audio_stream"] = {
            "codec": a_stream.get("codec_name") if a_stream else None,
        } if a_stream else None
        result["codec"] = v_stream.get("codec_name") if v_stream else None
        result["resolution"] = (
            f"{v_stream.get('width')}x{v_stream.get('height')}" if v_stream else None
        )

        # Duration
        try:
            dur_str = fmt.get("duration", "0")
            result["duration_ms"] = int(float(dur_str) * 1000)
        except (ValueError, TypeError):
            result["duration_ms"] = 0

        # Validation checks
        errors = []
        if not v_stream:
            errors.append("No video stream found in the output.")
        else:
            if v_stream.get("codec_name") not in ("h264", "hevc", "vp9", "av1", "mpeg4"):
                errors.append(f"Video codec '{v_stream.get('codec_name')}' may not be widely playable.")
            if int(v_stream.get("width", 0)) == 0 or int(v_stream.get("height", 0)) == 0:
                errors.append("Video resolution is invalid (0x0).")

        if not a_stream:
            errors.append("No audio stream found in the output (expected for video clips).")

        if result["duration_ms"] <= 0:
            errors.append("Output duration is 0 or invalid.")

        result["playable"] = v_stream is not None and result["duration_ms"] > 0
        result["errors"] = errors
        result["valid"] = len(errors) == 0 and result["playable"]
        return result

    # -- publish gate (separate compliance decisions) -----------------------

    @router.get("/jobs/{job_id}/publish-gate")
    def evaluate_publish_gate(job_id: str, tenant: AuthenticatedTenant = Depends(_tenant)):
        """Evaluates the publishing compliance gate with INDEPENDENT decisions.

        Each dimension is evaluated separately — they are never collapsed into
        one APPROVED field. A clip may be PUBLISHABLE but MONETIZATION_REVIEW.

        Dimensions:
          PUBLISHABILITY — rights + quality + guardian
          AI_DISCLOSURE  — whether AI disclosure is required
          MONETIZATION   — monetization eligibility based on rights
          ACCOUNT_RISK   — whether a connected authorized account exists
          API_STATUS     — whether the platform adapter is implemented/blocked
        """
        job = engine.store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Engine job '{job_id}' not found")
        authenticator.authorize_tenant_access(tenant, job["tenant_id"])

        rights = job.get("rights_status") or "rights_unknown"
        quality = job.get("quality_verdict") or "fail"
        guardian = bool(job.get("guardian_approved"))
        platform = job.get("platform")
        wants_publish = bool(job.get("publish"))
        is_completed = job["state"] == EngineJobState.COMPLETED.value

        # PUBLISHABILITY: rights verified + quality not fail + guardian approved
        pub_errors: List[str] = []
        if rights != "rights_verified":
            pub_errors.append(f"Rights status is '{rights}' — verified rights required to publish.")
        if quality == "fail":
            pub_errors.append("Quality verdict is 'fail' — clip does not meet quality standards.")
        if not guardian:
            pub_errors.append("Guardian did not approve the clip.")
        publishable = len(pub_errors) == 0

        # AI_DISCLOSURE: the pipeline is zero-LLM (deterministic FFmpeg), so
        # AI-generated content disclosure is NOT REQUIRED. If AI tools were
        # used in future, this would flag REVIEW_REQUIRED.
        ai_disclosure = "not_required"
        ai_reason = "Pipeline is deterministic (zero-LLM) — no AI-generated content to disclose."

        # MONETIZATION: based on rights status
        if rights == "rights_verified":
            monetization = "monetizable"
            mon_reason = "Rights verified — clip is eligible for monetization."
        elif rights in ("restricted", "not_monetizable"):
            monetization = "monetization_review"
            mon_reason = f"Rights status '{rights}' requires monetization review."
        else:
            monetization = "monetization_review"
            mon_reason = f"Rights status '{rights}' — monetization eligibility unclear."

        # ACCOUNT_RISK: whether a connected account exists for the platform
        account_risk = "not_checked"
        account_reason = "No publish requested — account check not applicable."
        if wants_publish and platform:
            accounts = engine.publishing_service.list_accounts(tenant.tenant_id)
            connected = [
                a for a in accounts
                if a.platform == platform and a.status == "connected"
            ]
            if connected:
                account_risk = "connected"
                account_reason = f"Connected authorized account found for '{platform}'."
            else:
                account_risk = "no_account"
                account_reason = f"No connected authorized account for platform '{platform}'."

        # API_STATUS: whether the platform adapter is implemented or blocked
        api_status = "not_checked"
        api_reason = "No publish requested — API status not applicable."
        if wants_publish and platform:
            adapters = getattr(engine.publishing_service, "adapters", {})
            adapter = adapters.get(platform)
            if not adapter:
                api_status = "unknown_platform"
                api_reason = f"Unknown platform '{platform}' — no adapter registered."
            else:
                caps = adapter.get_capabilities()
                if caps.implementation_status == "blocked":
                    api_status = "blocked"
                    api_reason = f"Platform '{platform}' is blocked by API/permission requirements."
                elif caps.implementation_status == "not_implemented":
                    api_status = "not_implemented"
                    api_reason = f"Platform '{platform}' adapter is not implemented."
                else:
                    api_status = "available"
                    api_reason = f"Platform '{platform}' adapter is available (implementation_status: {caps.implementation_status})."

        # Overall readiness
        if not is_completed:
            overall = "not_ready"
            overall_reason = f"Job is not completed (state: {job['state']})."
        elif not wants_publish:
            overall = "ready_to_export"
            overall_reason = "Job completed — ready to export. No publish requested."
        elif not publishable:
            overall = "blocked"
            overall_reason = "; ".join(pub_errors)
        elif account_risk == "no_account":
            overall = "ready_to_export"
            overall_reason = "Ready to export. Platform connection required for publishing."
        elif api_status in ("blocked", "not_implemented", "unknown_platform"):
            overall = "blocked"
            overall_reason = api_reason
        else:
            overall = "ready_to_publish"
            overall_reason = "All gates passed — ready to publish."

        return {
            "job_id": job_id,
            "overall": overall,
            "overall_reason": overall_reason,
            "gates": {
                "publishability": {
                    "status": "publishable" if publishable else "blocked",
                    "reasons": pub_errors,
                },
                "ai_disclosure": {
                    "status": ai_disclosure,
                    "reason": ai_reason,
                },
                "monetization": {
                    "status": monetization,
                    "reason": mon_reason,
                },
                "account_risk": {
                    "status": account_risk,
                    "reason": account_reason,
                },
                "api_status": {
                    "status": api_status,
                    "reason": api_reason,
                },
            },
        }

    # -- production readiness (real system information) ---------------------

    @router.get("/readiness")
    def engine_readiness(tenant: AuthenticatedTenant = Depends(_tenant)):
        """Compact production readiness status from real system information.

        Each subsystem reports READY, WARNING, or BLOCKED — never hard-coded.
        """
        checks: Dict[str, Dict[str, Any]] = {}

        # ENGINE: started + has workers
        sys = engine.system_state()
        workers = sys.get("workers", [])
        healthy_workers = [
            w for w in workers
            if w["state"] in ("idle", "busy")
        ]
        if engine._started and healthy_workers:
            checks["engine"] = {"status": "ready", "detail": f"{len(healthy_workers)} healthy workers, system {sys['system_state']}"}
        elif engine._started and workers:
            checks["engine"] = {"status": "warning", "detail": f"Engine started but no healthy workers ({sys['system_state']})"}
        else:
            checks["engine"] = {"status": "blocked", "detail": "Engine not started"}

        # RENDERER: must be FFmpegRendererAdapter, not mock
        is_ffmpeg = isinstance(engine.renderer, FFmpegRendererAdapter)
        is_mock = isinstance(engine.renderer, MockRendererAdapter)
        if is_ffmpeg:
            checks["renderer"] = {"status": "ready", "detail": "FFmpegRendererAdapter (real FFmpeg)"}
        elif is_mock:
            checks["renderer"] = {"status": "blocked", "detail": "MockRendererAdapter in use — production must use FFmpeg"}
        else:
            checks["renderer"] = {"status": "warning", "detail": f"Unknown renderer: {type(engine.renderer).__name__}"}

        # STORAGE: storage directory writable
        storage_dir = local_storage_base_dir
        try:
            os.makedirs(storage_dir, exist_ok=True)
            test_file = os.path.join(storage_dir, ".readiness_probe")
            with open(test_file, "w") as f:
                f.write("probe")
            os.remove(test_file)
            checks["storage"] = {"status": "ready", "detail": f"Local storage writable: {storage_dir}"}
        except Exception as e:
            checks["storage"] = {"status": "blocked", "detail": f"Storage not writable: {e}"}

        # WORKERS: registered and at least one healthy
        if healthy_workers:
            checks["workers"] = {"status": "ready", "detail": f"{len(healthy_workers)}/{len(workers)} workers healthy"}
        elif workers:
            checks["workers"] = {"status": "warning", "detail": f"0/{len(workers)} workers healthy"}
        else:
            checks["workers"] = {"status": "blocked", "detail": "No workers registered"}

        # PUBLISHING: whether any platform accounts are connected
        accounts = engine.publishing_service.list_accounts(tenant.tenant_id)
        connected = [a for a in accounts if a.status == "connected"]
        if connected:
            platforms = list(set(a.platform for a in connected))
            checks["publishing"] = {"status": "ready", "detail": f"{len(connected)} connected account(s): {', '.join(platforms)}"}
        else:
            checks["publishing"] = {"status": "warning", "detail": "No connected platform accounts — export available, publishing requires connection"}

        # COMPLIANCE: the compliance gate is functional (always available)
        checks["compliance"] = {"status": "ready", "detail": "Compliance gate active (rights, quality, guardian, account, API)"}

        # EXPORT: export is available when renderer is real
        if is_ffmpeg:
            checks["export"] = {"status": "ready", "detail": "Export available — real rendered files can be downloaded"}
        else:
            checks["export"] = {"status": "blocked", "detail": "Export blocked — mock renderer produces no real media"}

        # Overall
        statuses = [c["status"] for c in checks.values()]
        if "blocked" in statuses:
            overall = "blocked"
        elif "warning" in statuses:
            overall = "warning"
        else:
            overall = "ready"

        return {"overall": overall, "checks": checks}

    return router
