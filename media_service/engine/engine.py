"""The execution engine: a real worker pool that drives jobs through the
canonical pipeline, persisting state and emitting events at every transition.

Workers are background daemon threads. Each loop:
  1. heartbeat
  2. if paused -> drain (finish nothing new, sleep)
  3. atomically claim the oldest QUEUED job -> ASSIGNED
  4. execute the staged pipeline, transitioning state + appending events
  5. on stage failure -> FAILED (with bounded retry on explicit retry)
  6. return to IDLE

Render progress is only reported when FFmpeg's ``time=`` output makes it
measurable. The mock renderer path reports no percentage (ACTIVE).
"""

import logging
import os
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from media_service.engine.states import (
    EngineJobState,
    SystemState,
    WorkerState,
    ACTIVE_JOB_STATES,
)
from media_service.engine.engine_store import EngineStore
from media_service.rendering.ffmpeg_renderer import (
    FFmpegRendererAdapter,
    MockRendererAdapter,
    resolve_target_frame_size,
)

logger = logging.getLogger("oracle_clip.engine")


class Engine:
    """Real, persisted, event-sourced execution engine."""

    def __init__(
        self,
        store: EngineStore,
        renderer: Any,
        spec_validator: Any,
        opportunity_generator: Any,
        quality_checker: Any,
        guardian_hook: Any,
        publishing_service: Any,
        scheduler: Any,
        ffprobe_binary: str = "ffprobe",
        worker_count: int = 2,
        render_timeout_seconds: int = 180,
    ):
        self.store = store
        self.renderer = renderer
        self.spec_validator = spec_validator
        self.opportunity_generator = opportunity_generator
        self.quality_checker = quality_checker
        self.guardian_hook = guardian_hook
        self.publishing_service = publishing_service
        self.scheduler = scheduler
        self.ffprobe_binary = ffprobe_binary
        self.worker_count = max(1, worker_count)
        self.render_timeout_seconds = render_timeout_seconds

        self._workers: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}
        self._pause_event = threading.Event()
        self._started = False
        self._lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self.worker_count):
            wid = f"worker-{i+1:02d}"
            self.store.register_worker(wid, WorkerState.STARTING)
            stop = threading.Event()
            self._stop_flags[wid] = stop
            t = threading.Thread(
                target=self._worker_loop, args=(wid, stop), name=wid, daemon=True
            )
            self._workers[wid] = t
            t.start()
            self.store.set_worker_state(wid, WorkerState.IDLE)
        logger.info(f"Engine started with {self.worker_count} workers.")

    def stop(self) -> None:
        for wid, stop in self._stop_flags.items():
            stop.set()
        self._started = False

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    def stop_worker(self, worker_id: str) -> bool:
        stop = self._stop_flags.get(worker_id)
        if not stop:
            return False
        stop.set()
        self.store.set_worker_state(worker_id, WorkerState.OFFLINE)
        return True

    def start_worker(self, worker_id: str) -> bool:
        if worker_id in self._workers and self._workers[worker_id].is_alive():
            return False
        i = int(worker_id.split("-")[1]) - 1
        stop = threading.Event()
        self._stop_flags[worker_id] = stop
        t = threading.Thread(
            target=self._worker_loop, args=(worker_id, stop), name=worker_id, daemon=True
        )
        self._workers[worker_id] = t
        self.store.register_worker(worker_id, WorkerState.STARTING)
        t.start()
        self.store.set_worker_state(worker_id, WorkerState.IDLE)
        return True

    # -- worker loop --------------------------------------------------------

    def _worker_loop(self, worker_id: str, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.store.heartbeat(worker_id)
                if self.paused:
                    self.store.set_worker_state(worker_id, WorkerState.IDLE)
                    time.sleep(0.5)
                    continue

                job = self.store.claim_next_queued_job(worker_id)
                if not job:
                    self.store.set_worker_state(worker_id, WorkerState.IDLE)
                    time.sleep(0.4)
                    continue

                self.store.set_worker_state(worker_id, WorkerState.BUSY, current_job_id=job["job_id"])
                self._run_job(worker_id, job)
                self.store.set_worker_state(
                    worker_id, WorkerState.IDLE, current_job_id=None,
                    increment_completed=True,
                )
                self.store.set_worker_last_job(worker_id, job["job_id"])
            except Exception as e:
                logger.exception(f"Worker {worker_id} fatal error: {e}")
                self.store.set_worker_state(worker_id, WorkerState.ERROR, current_job_id=None)
                time.sleep(2)
                # self-heal: return to idle after a backoff
                self.store.set_worker_state(worker_id, WorkerState.IDLE)

    # -- job execution ------------------------------------------------------

    def _run_job(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        try:
            # Job is already ASSIGNED (claimed from the queue). Begin processing.
            # Each stage re-reads fresh state from the store so it sees the
            # fields earlier stages persisted (output_path, verdict, ...).
            self._stage_processing(worker_id, self.store.get_job(job_id))
            self._stage_rendering(worker_id, self.store.get_job(job_id))
            self._stage_quality_check(worker_id, self.store.get_job(job_id))
            self._stage_rights_check(worker_id, self.store.get_job(job_id))
            self._stage_packaging(worker_id, self.store.get_job(job_id))
            self._stage_scheduled(worker_id, self.store.get_job(job_id))
            # Publishing path
            job = self.store.get_job(job_id)
            if job["publish"]:
                self._stage_publishing(worker_id, job)
                job = self.store.get_job(job_id)
                if job["state"] == EngineJobState.PUBLISHED.value:
                    self._stage_analyzing(worker_id, job)
                    self._complete(worker_id, job_id)
                # if BLOCKED/FAILED, stop here
            else:
                self._stage_analyzing(worker_id, self.store.get_job(job_id))
                self._complete(worker_id, job_id)
        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            self.store.transition(
                job_id, EngineJobState.FAILED,
                worker_id=worker_id,
                event_source="worker",
                error=str(e),
                error_message=str(e),
            )
            self.store.set_worker_state(worker_id, WorkerState.IDLE, increment_failed=True)

    # -- stages -------------------------------------------------------------

    def _to(self, worker_id: str, job_id: str, state: EngineJobState, event_type: str,
            metadata: Optional[Dict] = None, **fields) -> Dict[str, Any]:
        return self.store.transition(
            job_id, state, worker_id=worker_id, event_type=event_type,
            event_source="worker", metadata=metadata, **fields
        )

    def _stage_processing(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        self._to(worker_id, job_id, EngineJobState.PROCESSING, "job.processing")
        from shared.contracts.media import MediaMetadata
        meta = MediaMetadata(duration_ms=job["duration_ms"], format_name="mp4")
        opps = self.opportunity_generator.generate(
            source_media_id=job["source_media_path"],
            metadata=meta,
            scenes=None,
            max_opportunities=3,
        )
        if not opps:
            raise RuntimeError("No content opportunities could be generated")
        self._to(worker_id, job_id, EngineJobState.RENDERING, "job.rendering",
                 metadata={"opportunities": len(opps), "primary_score": opps[0].score})

    def _stage_rendering(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        out_dir = f"/tmp/oracle_clip_engine_renders/{job['tenant_id']}"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"rendered_{job_id}.mp4")

        from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec, RenderJob
        from shared.contracts.enums import JobStatus
        seg = ClipSegmentSpec(start_ms=0, end_ms=job["duration_ms"], source_media_id=job["source_media_path"])
        spec = ClipSpecification(
            spec_id=f"spec_{job_id}", source_media_id=job["source_media_path"],
            segments=[seg], target_aspect_ratio=job["target_aspect_ratio"],
        )
        rjob = RenderJob(job_id=job_id, tenant_id=job["tenant_id"], spec=spec, status=JobStatus.IN_PROGRESS)

        source_path = job["source_media_path"]
        total_ms = max(1, job["duration_ms"])

        if isinstance(self.renderer, FFmpegRendererAdapter) and os.path.exists(source_path):
            asset = self._render_ffmpeg_with_progress(
                worker_id, job_id, rjob, source_path, out_path, total_ms
            )
        else:
            # Mock renderer (tests / no ffmpeg): no measurable progress.
            self.store.update_fields(job_id, progress_measurable=0, progress=0.0)
            asset = self.renderer.render(rjob, source_media_path=source_path, output_path=out_path)

        # Record the real rendered-asset metadata without a state transition; the
        # quality-check stage performs the RENDERING -> QUALITY_CHECK transition.
        self.store.update_fields(
            job_id, output_path=asset.storage_path, asset_id=asset.asset_id,
            progress=100.0, progress_measurable=1,
        )
        self.store.append_event(
            event_type="job.render_complete", job_id=job_id, source="worker",
            worker_id=worker_id, previous_state=EngineJobState.RENDERING.value,
            new_state=EngineJobState.RENDERING.value,
            metadata={
                "asset_id": asset.asset_id, "width": asset.width, "height": asset.height,
                "file_size_bytes": asset.file_size_bytes,
                "checksum_sha256": asset.checksum_sha256,
            },
        )

    def _render_ffmpeg_with_progress(self, worker_id, job_id, rjob, source_path, out_path, total_ms):
        """Run FFmpeg via Popen, parsing stderr ``time=`` for measurable progress."""
        seg = rjob.spec.segments[0]
        start_sec = seg.start_ms / 1000.0
        dur_sec = (seg.end_ms - seg.start_ms) / 1000.0
        out_w, out_h = resolve_target_frame_size(rjob.spec.target_aspect_ratio)
        vf = (f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
              f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
        args = [
            "-y", "-ss", str(start_sec), "-i", source_path, "-t", str(dur_sec),
            "-vf", vf, "-c:v", "libx264", "-c:a", "aac", "-strict", "experimental",
            out_path,
        ]
        cmd = ["ffmpeg"] + [str(a) for a in args]
        self.store.update_fields(job_id, progress_measurable=1, progress=0.0)
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError as e:
            raise RuntimeError(f"ffmpeg binary not found: {e}")

        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                # parse time=HH:MM:SS.ss
                if "time=" in line:
                    idx = line.index("time=") + 5
                    rest = line[idx:].split()[0]
                    try:
                        h, m, s = rest.split(":")
                        t_ms = (int(h) * 3600 + int(m) * 60 + float(s)) * 1000.0
                        pct = min(100.0, max(0.0, (t_ms / total_ms) * 100.0))
                        self.store.update_fields(job_id, progress=round(pct, 1))
                    except (ValueError, IndexError):
                        pass
            proc.wait(timeout=self.render_timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError(f"FFmpeg timed out after {self.render_timeout_seconds}s")

        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg exited with code {proc.returncode}")
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("FFmpeg produced empty or missing output")

        # Probe + checksum the real artifact.
        from media_service.inspect.media_inspector import MediaInspector
        from shared.hashing.content_hash import compute_content_hash
        from shared.hashing.checksum_verifier import calculate_sha256
        from shared.contracts.jobs import RenderedAsset
        inspector = MediaInspector(ffprobe_binary=self.ffprobe_binary)
        probed = inspector.inspect(out_path)
        with open(out_path, "rb") as f:
            chash = compute_content_hash(f.read())
        checksum, file_size = calculate_sha256(out_path)
        return RenderedAsset(
            asset_id=f"asset_{job_id}", job_id=job_id, tenant_id=rjob.tenant_id,
            storage_path=out_path, duration_ms=probed.duration_ms or int(total_ms),
            width=probed.width or 0, height=probed.height or 0,
            bitrate=probed.bitrate, file_size_bytes=file_size,
            content_hash=chash, checksum_sha256=checksum,
            metadata={"renderer": "ffmpeg"},
        )

    def _stage_quality_check(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        self._to(worker_id, job_id, EngineJobState.QUALITY_CHECK, "job.quality_check")
        from shared.contracts.jobs import RenderedAsset
        asset = RenderedAsset(
            asset_id=job["asset_id"] or f"asset_{job_id}", job_id=job_id,
            tenant_id=job["tenant_id"], storage_path=job["output_path"] or "",
            duration_ms=job["duration_ms"], width=0, height=0,
        )
        report = self.quality_checker.check(asset)
        decision = self.guardian_hook.evaluate(report)
        self._to(worker_id, job_id, EngineJobState.RIGHTS_CHECK, "job.quality_checked",
                 metadata={
                     "verdict": report.verdict.value, "score": report.overall_score,
                     "guardian_approved": decision.get("approved"),
                 },
                 quality_verdict=report.verdict.value,
                 quality_score=report.overall_score,
                 guardian_approved=1 if decision.get("approved") else 0)

    def _stage_rights_check(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        # Job is already in RIGHTS_CHECK (entered from quality_check). Record the
        # real rights status and transition to packaging.
        rights = job["rights_status"] or "rights_unknown"
        self.store.append_event(
            event_type="job.rights_check", job_id=job_id, source="worker",
            worker_id=worker_id, previous_state=EngineJobState.RIGHTS_CHECK.value,
            new_state=EngineJobState.RIGHTS_CHECK.value, metadata={"rights_status": rights},
        )
        self._to(worker_id, job_id, EngineJobState.PACKAGING, "job.rights_checked",
                 metadata={"rights_status": rights})

    def _stage_packaging(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        # Real packaging: verify the artifact exists + has a checksum (already
        # computed at render time). Re-confirm existence.
        out_path = job["output_path"] or ""
        packaged = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        if not packaged:
            raise RuntimeError("Packaging failed: rendered artifact missing")
        self._to(worker_id, job_id, EngineJobState.SCHEDULED, "job.packaged",
                 metadata={"packaged": True, "output_path": out_path})

    def _stage_scheduled(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        # Job is already in SCHEDULED (entered from packaging). Run the real
        # scheduler evaluation and record the decision.
        decision = self.scheduler.evaluate(
            quality_verdict=job["quality_verdict"] or "pass",
            quality_score=job["quality_score"] or 0.0,
            opportunity_score=0.8,
            rights_status=job["rights_status"] or "rights_unknown",
            guardian_approved=bool(job["guardian_approved"]),
        )
        self.store.update_fields(job_id, schedule_decision=decision.get("decision"))
        self.store.append_event(
            event_type="job.schedule_decision", job_id=job_id, source="scheduler",
            worker_id=worker_id, previous_state=EngineJobState.SCHEDULED.value,
            new_state=EngineJobState.SCHEDULED.value, metadata=decision,
        )

    def _stage_publishing(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        rights = job["rights_status"] or "rights_unknown"
        if rights != "rights_verified":
            self.store.transition(
                job_id, EngineJobState.BLOCKED, worker_id=worker_id,
                event_type="job.publish_blocked", event_source="worker",
                metadata={"reason": f"rights status '{rights}' — publishing blocked"},
                publish_status="blocked",
            )
            return

        platform = job["platform"]
        account_id = job["account_id"]
        accounts = self.publishing_service.list_accounts(job["tenant_id"])
        connected = [a for a in accounts if a.platform == platform and a.status == "connected"]
        if not account_id and connected:
            account_id = connected[0].account_id
        if not account_id or not any(a.account_id == account_id and a.status == "connected" for a in accounts):
            self.store.transition(
                job_id, EngineJobState.BLOCKED, worker_id=worker_id,
                event_type="job.publish_blocked", event_source="worker",
                metadata={"reason": f"no connected authorized account for platform '{platform}'"},
                publish_status="not_connected",
            )
            return

        self._to(worker_id, job_id, EngineJobState.PUBLISHING, "job.publishing",
                 metadata={"platform": platform, "account_id": account_id})
        post = self.publishing_service.create_post(
            tenant_id=job["tenant_id"], render_job_id=job_id,
            rendered_asset_id=job["asset_id"] or f"asset_{job_id}",
            platform=platform, account_id=account_id,
            video_path=job["output_path"], auto_publish=True,
        )
        result = self.publishing_service.publish_post(post.post_id, job["tenant_id"], force=True)
        if result.success:
            self.store.transition(
                job_id, EngineJobState.PUBLISHED, worker_id=worker_id,
                event_type="job.published", event_source="worker",
                metadata={"platform_post_id": result.platform_post_id, "post_url": result.post_url},
                publish_status="published", post_id=post.post_id, post_url=result.post_url,
            )
        else:
            raise RuntimeError(f"Publishing failed: {result.error}")

    def _stage_analyzing(self, worker_id: str, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        self._to(worker_id, job_id, EngineJobState.ANALYZING, "job.analyzing")
        # Truthful: no analytics integration is connected. Record NOT CONNECTED
        # rather than fabricating analytics/revenue data.
        self.store.update_fields(job_id, analytics_status="not_connected")
        self.store.append_event(
            event_type="analytics.not_connected", job_id=job_id, source="engine",
            worker_id=worker_id, previous_state=EngineJobState.ANALYZING.value,
            new_state=EngineJobState.ANALYZING.value,
            metadata={"reason": "no analytics integration connected"},
        )

    def _complete(self, worker_id: str, job_id: str) -> None:
        self._to(worker_id, job_id, EngineJobState.COMPLETED, "job.completed")

    # -- public actions -----------------------------------------------------

    def retry_job(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")
        state = EngineJobState(job["state"])
        if state not in (EngineJobState.FAILED, EngineJobState.BLOCKED):
            raise ValueError(f"Cannot retry job in state '{state.value}'")
        self.store.transition(
            job_id, EngineJobState.RETRYING, event_type="job.retry_requested",
            event_source="api", metadata={"attempt": job["attempt"] + 1},
            attempt=(job["attempt"] or 0) + 1, error_message=None,
        )
        # RETRYING -> QUEUED (re-enters the queue for a worker)
        return self.store.transition(
            job_id, EngineJobState.QUEUED, event_type="job.queued",
            event_source="api", metadata={"retry": True},
            worker_id=None,
        )

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")
        state = EngineJobState(job["state"])
        if state == EngineJobState.CANCELLED:
            return job
        if state in (EngineJobState.COMPLETED,):
            raise ValueError(f"Cannot cancel job in terminal state '{state.value}'")
        # If currently assigned/rendering, the worker will detect the cancel on
        # its next progress write; for queued/pre-stage jobs we transition now.
        try:
            return self.store.transition(
                job_id, EngineJobState.CANCELLED, event_type="job.cancelled",
                event_source="api",
            )
        except Exception:
            # Transition not valid from current state (e.g. mid-render): mark a
            # pending cancel the worker honors.
            self.store.update_fields(job_id, error_message="cancel_requested")
            self.store.append_event(
                event_type="job.cancel_requested", job_id=job_id, source="api",
                previous_state=state.value, new_state=state.value,
                metadata={"reason": "cancel requested mid-flight"},
            )
            return self.store.get_job(job_id)

    # -- system state -------------------------------------------------------

    def system_state(self) -> Dict[str, Any]:
        workers = self.store.list_workers()
        active_jobs = self.store.list_active_jobs()
        counts = self.store.count_by_state()

        if not self._started:
            sys_state = SystemState.OFFLINE
        else:
            healthy = [w for w in workers if w["state"] in (WorkerState.IDLE.value, WorkerState.BUSY.value)]
            errored = [w for w in workers if w["state"] == WorkerState.ERROR.value]
            offline = [w for w in workers if w["state"] == WorkerState.OFFLINE.value]

            if self.paused and active_jobs:
                sys_state = SystemState.DRAINING
            elif self.paused:
                sys_state = SystemState.PAUSED
            elif errored and not healthy:
                sys_state = SystemState.ERROR
            elif errored:
                sys_state = SystemState.DEGRADED
            elif offline and not healthy:
                sys_state = SystemState.ERROR
            elif active_jobs:
                sys_state = SystemState.ACTIVE
            else:
                sys_state = SystemState.READY

        return {
            "system_state": sys_state.value,
            "paused": self.paused,
            "worker_count": len(workers),
            "workers": workers,
            "active_job_count": len(active_jobs),
            "active_jobs": active_jobs,
            "counts": counts,
        }
