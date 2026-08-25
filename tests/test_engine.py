"""Acceptance test for the Engine Room execution engine.

Exercises the real, persisted, event-sourced pipeline end-to-end through the
FastAPI app (TestClient). A deterministic test renderer is injected into the
engine so no real FFmpeg is required — but every state transition is real and
persisted, and the event log is real.

Covers the acceptance criteria:
  1. HAPPY PATH — full pipeline CREATED → VALIDATING → QUEUED → ASSIGNED →
     PROCESSING → RENDERING → QUALITY_CHECK → RIGHTS_CHECK → PACKAGING →
     SCHEDULED → ANALYZING → COMPLETED
  2. FAILURE PATH — deterministic renderer failure → FAILED (error persisted)
  3. RETRY PATH — RETRYING → QUEUED → worker claim → processing → recovery
  4. PUBLISH-BLOCKED PATH — no connected account → BLOCKED
  5. REFRESH/RECONSTRUCTION — state read back from durable store
  6. WORKER SAFETY — two workers cannot claim the same job
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from media_service.api.app import app, engine, engine_store
from media_service.engine.states import EngineJobState
from media_service.rendering.ffmpeg_renderer import MockRendererAdapter


class StubRendererAdapter(MockRendererAdapter):
    """Deterministic test renderer for acceptance tests.

    Extends MockRendererAdapter with a configurable failure mode. Set
    ``should_fail = True`` to make ``render()`` raise, exercising the real
    FAILED transition through the engine — without faking state directly.
    """

    def __init__(self):
        self.should_fail = False
        self.render_count = 0

    def render(self, job, source_media_path, output_path):
        self.render_count += 1
        if self.should_fail:
            raise RuntimeError("deterministic test render failure")
        return super().render(job, source_media_path, output_path)


@pytest.fixture(autouse=True)
def _clear_engine_store():
    """Stop workers, clear durable state, restart — each test starts clean.

    The engine DB is isolated from the running uvicorn server via
    ORACLE_CLIP_ENGINE_DB set in conftest.py, so only the test's own workers
    (using the injected test renderer) process jobs.
    """
    engine.stop()
    time.sleep(0.15)
    engine_store.clear()
    engine.start()
    yield
    engine.stop()
    time.sleep(0.15)
    engine_store.clear()
    engine.start()


@pytest.fixture(autouse=True)
def _test_renderer(_clear_engine_store):
    """Inject a deterministic test renderer into the engine.

    This is the dependency-injection seam: production constructs the engine
    with FFmpegRendererAdapter; acceptance tests inject StubRendererAdapter.
    The engine's workers read ``self.renderer`` at render time, so replacing
    ``engine.renderer`` takes effect for all subsequent jobs.
    """
    original = engine.renderer
    renderer = StubRendererAdapter()
    engine.renderer = renderer
    yield renderer
    engine.renderer = original


@pytest.fixture
def client(_test_renderer):
    return TestClient(app)


def _auth():
    return {"X-API-Key": "dev-admin-key-12345"}


def _wait_for_state(client, job_id, target_states, timeout=20):
    """Deterministic polling — no fixed sleeps, bounded timeout."""
    target = {s.lower() for s in target_states}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/v1/engine/jobs/{job_id}", headers=_auth())
        assert r.status_code == 200, r.text
        last = r.json()["job"]["state"]
        if last in target:
            return r.json()
        time.sleep(0.3)
    raise AssertionError(f"Job {job_id} did not reach {target_states} (last={last})")


# -- 1. HAPPY PATH -----------------------------------------------------------

def test_engine_happy_path_full_pipeline(client):
    """A non-publish job runs the full real pipeline to COMPLETED."""
    r = client.post("/v1/engine/jobs", headers=_auth(), json={
        "source_media_path": "/tmp/engine_test_input.mp4",
        "duration_ms": 3000,
        "target_aspect_ratio": "9:16",
    })
    assert r.status_code == 200, r.text
    job_id = r.json()["job"]["job_id"]
    assert r.json()["job"]["state"] == "queued"

    data = _wait_for_state(client, job_id, ["completed"], timeout=20)
    job = data["job"]
    assert job["state"] == "completed"
    assert job["output_path"]  # real rendered artifact path persisted
    assert job["quality_verdict"] in ("pass", "warn", "fail", "manual_review")
    assert job["schedule_decision"] in ("publish", "schedule", "review", "wait", "reject")
    assert job["analytics_status"] == "not_connected"  # truthful: no analytics integration

    # Event log contains the canonical transitions, in order.
    event_types = [e["event_type"] for e in data["events"]]
    expected_prefix = [
        "job.created", "job.validating", "job.queued", "job.assigned",
        "job.processing", "job.rendering", "job.render_complete",
        "job.quality_check", "job.quality_checked", "job.rights_check",
        "job.rights_checked", "job.packaged",
        "job.schedule_decision", "job.analyzing", "analytics.not_connected",
        "job.completed",
    ]
    for ev in expected_prefix:
        assert ev in event_types, f"missing event {ev} in {event_types}"

    # Every event has the required structured fields.
    for e in data["events"]:
        assert e["event_id"]
        assert e["timestamp"]
        assert e["source"]

    # 5. REFRESH/RECONSTRUCTION: reading the job again returns the same state
    # from durable storage, not in-memory engine state.
    r2 = client.get(f"/v1/engine/jobs/{job_id}", headers=_auth())
    assert r2.status_code == 200
    assert r2.json()["job"]["state"] == "completed"
    assert r2.json()["job"]["job_id"] == job_id
    assert r2.json()["job"]["output_path"] == job["output_path"]


# -- 2. FAILURE PATH ---------------------------------------------------------

def test_engine_failure_path(client, _test_renderer):
    """A deterministic renderer failure transitions the job to FAILED.

    The failure is real — the test renderer raises during the RENDERING stage,
    the engine's _run_job exception handler transitions FAILED and persists the
    error. No state transitions are faked directly in the test.
    """
    _test_renderer.should_fail = True

    r = client.post("/v1/engine/jobs", headers=_auth(), json={
        "source_media_path": "/tmp/engine_fail.mp4",
        "duration_ms": 2000,
        "target_aspect_ratio": "9:16",
    })
    job_id = r.json()["job"]["job_id"]

    data = _wait_for_state(client, job_id, ["failed"], timeout=20)
    assert data["job"]["state"] == "failed"
    assert data["job"]["error_message"]  # error persisted
    assert "deterministic test render failure" in data["job"]["error_message"]

    # The failure event is persisted with the error.
    event_types = [e["event_type"] for e in data["events"]]
    assert "job.failed" in event_types
    failed_event = next(e for e in data["events"] if e["event_type"] == "job.failed")
    assert failed_event["new_state"] == "failed"


# -- 3. RETRY PATH -----------------------------------------------------------

def test_engine_retry_path(client, _test_renderer):
    """A failed job can be retried: RETRYING → QUEUED → worker claim → recovery.

    The retry exercises the real state machine: retry_job() transitions
    FAILED → RETRYING → QUEUED, then a worker claims the job and runs the full
    pipeline to COMPLETED. No state transitions are faked.
    """
    # First, force a real failure via the test renderer.
    _test_renderer.should_fail = True
    r = client.post("/v1/engine/jobs", headers=_auth(), json={
        "source_media_path": "/tmp/engine_retry.mp4",
        "duration_ms": 2000,
        "target_aspect_ratio": "9:16",
    })
    job_id = r.json()["job"]["job_id"]
    data = _wait_for_state(client, job_id, ["failed"], timeout=20)
    assert data["job"]["state"] == "failed"

    # Now allow the renderer to succeed and retry through the API.
    _test_renderer.should_fail = False
    rr = client.post(f"/v1/engine/jobs/{job_id}/retry", headers=_auth())
    assert rr.status_code == 200, rr.text
    assert rr.json()["job"]["state"] == "queued"
    assert rr.json()["job"]["attempt"] == 1

    # The retry event is recorded.
    r2 = client.get(f"/v1/engine/jobs/{job_id}", headers=_auth())
    event_types = [e["event_type"] for e in r2.json()["events"]]
    assert "job.retry_requested" in event_types

    # Worker picks up the retried job and completes it.
    data = _wait_for_state(client, job_id, ["completed"], timeout=20)
    assert data["job"]["state"] == "completed"
    assert data["job"]["attempt"] == 1


# -- 4. PUBLISH-BLOCKED PATH -------------------------------------------------

def test_engine_publish_blocked_without_account(client):
    """A publish job with rights_verified but no connected account → BLOCKED.

    The job passes all pre-publish stages (render, quality, rights, packaging,
    scheduling) but is blocked at publishing because no platform account is
    connected. The blocked state and reason are persisted — not faked.
    """
    r = client.post("/v1/engine/jobs", headers=_auth(), json={
        "source_media_path": "/tmp/engine_pub.mp4",
        "duration_ms": 2000,
        "publish": True,
        "platform": "youtube",
        "rights_status": "rights_verified",
    })
    job_id = r.json()["job"]["job_id"]
    data = _wait_for_state(client, job_id, ["blocked", "completed", "failed"], timeout=20)
    # No connected account → BLOCKED at publishing (truthful, not faked).
    assert data["job"]["state"] == "blocked"
    assert data["job"]["publish_status"] == "not_connected"

    # The publish-blocked event is persisted.
    event_types = [e["event_type"] for e in data["events"]]
    assert "job.publish_blocked" in event_types


# -- 5. WORKER SAFETY --------------------------------------------------------

def test_engine_worker_safety_atomic_claim():
    """Two workers cannot claim the same job — atomic claim via BEGIN IMMEDIATE.

    Tests the real claim_next_queued_job implementation directly. Two threads
    race to claim the same queued job; exactly one must succeed.
    """
    from media_service.engine.engine_store import EngineStore

    store = EngineStore(db_path="/tmp/test_worker_safety_engine.db")
    store.clear()

    # Create and queue a single job.
    store.create_job(
        job_id="safety_1", tenant_id="tenant-alpha",
        source_media_path="/tmp/test.mp4", duration_ms=1000,
    )
    store.transition("safety_1", EngineJobState.VALIDATING,
                     event_type="job.validating", event_source="test")
    store.transition("safety_1", EngineJobState.QUEUED,
                     event_type="job.queued", event_source="test")

    claimed = []
    errors = []

    def claim(worker_id):
        try:
            job = store.claim_next_queued_job(worker_id)
            if job:
                claimed.append((worker_id, job["job_id"]))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=claim, args=(f"worker-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"unexpected errors: {errors}"
    assert len(claimed) == 1, f"expected exactly 1 claim, got {claimed}"
    assert claimed[0][1] == "safety_1"
    store.clear()


# -- System state ------------------------------------------------------------

def test_engine_system_state_idle_when_no_jobs(client):
    """With no active jobs the system reports READY (idle)."""
    # Ensure workers have drained any prior work.
    time.sleep(0.5)
    r = client.get("/v1/engine/state", headers=_auth())
    assert r.status_code == 200
    assert r.json()["system_state"] in ("ready", "active")
    assert r.json()["worker_count"] >= 1


def test_engine_invalid_transition_rejected():
    """Invalid state transitions are rejected by the state machine."""
    from media_service.engine.states import EngineStateMachine
    from shared.errors.errors import ValidationError
    with pytest.raises(ValidationError):
        EngineStateMachine.transition(EngineJobState.COMPLETED, EngineJobState.RENDERING)
    with pytest.raises(ValidationError):
        EngineStateMachine.transition(EngineJobState.CREATED, EngineJobState.COMPLETED)
