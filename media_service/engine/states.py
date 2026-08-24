"""Canonical state model for the execution engine.

Two explicit, validated state machines:

* ``EngineJobState`` — the lifecycle of a single production job, from creation
  through rendering, quality/rights/packaging, scheduling, publishing,
  analytics, and a terminal state.
* ``SystemState`` / ``WorkerState`` — the state of the engine as a whole and of
  each real worker thread.

Every transition is validated against an allow-list. Invalid transitions are
rejected (raise ``ValidationError``) so the persisted state can never reach an
impossible combination.
"""

from enum import Enum
from typing import Set

from shared.errors.errors import ValidationError


class EngineJobState(str, Enum):
    """Lifecycle states for an engine production job."""
    CREATED = "created"
    VALIDATING = "validating"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    PROCESSING = "processing"
    RENDERING = "rendering"
    QUALITY_CHECK = "quality_check"
    RIGHTS_CHECK = "rights_check"
    PACKAGING = "packaging"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# States that are terminal (no outgoing transitions except retry/cancel).
TERMINAL_JOB_STATES = {
    EngineJobState.COMPLETED,
    EngineJobState.FAILED,
    EngineJobState.CANCELLED,
    EngineJobState.BLOCKED,
}

# States that count as "active" (occupying a worker or queued for one).
ACTIVE_JOB_STATES = {
    EngineJobState.VALIDATING,
    EngineJobState.QUEUED,
    EngineJobState.ASSIGNED,
    EngineJobState.PROCESSING,
    EngineJobState.RENDERING,
    EngineJobState.QUALITY_CHECK,
    EngineJobState.RIGHTS_CHECK,
    EngineJobState.PACKAGING,
    EngineJobState.SCHEDULED,
    EngineJobState.PUBLISHING,
    EngineJobState.PUBLISHED,
    EngineJobState.ANALYZING,
    EngineJobState.RETRYING,
}


class SystemState(str, Enum):
    """State of the engine as a whole, derived from workers + jobs."""
    OFFLINE = "offline"
    STARTING = "starting"
    READY = "ready"          # idle — no active jobs, workers healthy
    ACTIVE = "active"        # one or more jobs in flight
    DEGRADED = "degraded"    # some workers in error, others healthy
    PAUSED = "paused"        # paused, no active jobs remaining
    DRAINING = "draining"    # paused, active jobs still finishing
    ERROR = "error"          # all workers offline/error
    RECOVERING = "recovering"
    MAINTENANCE = "maintenance"


class WorkerState(str, Enum):
    """State of a single worker thread."""
    OFFLINE = "offline"
    STARTING = "starting"
    IDLE = "idle"            # alive, waiting for work
    BUSY = "busy"            # executing a job
    ERROR = "error"          # worker thread failed unexpectedly


class EngineStateMachine:
    """Validated transition table for ``EngineJobState``.

    The happy path is linear:
        CREATED -> VALIDATING -> QUEUED -> ASSIGNED -> PROCESSING -> RENDERING
        -> QUALITY_CHECK -> RIGHTS_CHECK -> PACKAGING -> SCHEDULED
        -> (PUBLISHING -> PUBLISHED)? -> ANALYZING -> COMPLETED

    Failure is allowed from any active stage to FAILED. RETRYING returns a
    failed/blocked job to QUEUED. CANCELLED is allowed from any non-terminal
    state. BLOCKED is reached from SCHEDULED/PUBLISHING when publishing cannot
    proceed (no authorized account). PUBLISHED -> ANALYZING -> COMPLETED.
    """

    _TRANSITIONS: dict = {
        EngineJobState.CREATED: {
            EngineJobState.VALIDATING, EngineJobState.CANCELLED, EngineJobState.FAILED,
        },
        EngineJobState.VALIDATING: {
            EngineJobState.QUEUED, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.QUEUED: {
            EngineJobState.ASSIGNED, EngineJobState.CANCELLED, EngineJobState.FAILED,
        },
        EngineJobState.ASSIGNED: {
            EngineJobState.PROCESSING, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.PROCESSING: {
            EngineJobState.RENDERING, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.RENDERING: {
            EngineJobState.QUALITY_CHECK, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.QUALITY_CHECK: {
            EngineJobState.RIGHTS_CHECK, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.RIGHTS_CHECK: {
            EngineJobState.PACKAGING, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.PACKAGING: {
            EngineJobState.SCHEDULED, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.SCHEDULED: {
            EngineJobState.PUBLISHING, EngineJobState.ANALYZING,
            EngineJobState.BLOCKED, EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.PUBLISHING: {
            EngineJobState.PUBLISHED, EngineJobState.BLOCKED,
            EngineJobState.FAILED, EngineJobState.CANCELLED,
        },
        EngineJobState.PUBLISHED: {
            EngineJobState.ANALYZING, EngineJobState.FAILED,
        },
        EngineJobState.ANALYZING: {
            EngineJobState.COMPLETED, EngineJobState.FAILED,
        },
        # Terminal states: only retry/cancel can revive them.
        EngineJobState.FAILED: {
            EngineJobState.RETRYING,
        },
        EngineJobState.BLOCKED: {
            EngineJobState.RETRYING, EngineJobState.CANCELLED,
        },
        EngineJobState.RETRYING: {
            EngineJobState.QUEUED, EngineJobState.FAILED,
        },
        EngineJobState.COMPLETED: set(),
        EngineJobState.CANCELLED: set(),
    }

    @classmethod
    def can_transition(cls, current: EngineJobState, target: EngineJobState) -> bool:
        return target in cls._TRANSITIONS.get(current, set())

    @classmethod
    def transition(cls, current: EngineJobState, target: EngineJobState) -> EngineJobState:
        if not cls.can_transition(current, target):
            raise ValidationError(
                f"Invalid engine job state transition: {current.value} -> {target.value}"
            )
        return target
