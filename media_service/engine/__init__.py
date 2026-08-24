"""Real execution engine for the Engine Room.

This package implements the canonical production pipeline as an asynchronous,
persisted, event-sourced execution system:

    DATABASE / JOB STATE  ->  EVENTS  ->  ORCHESTRATOR  ->  WORKERS  ->  REAL-TIME STATE  ->  UI

Every state surfaced to the Engine Room UI is backed by a row in the durable
SQLite store. There is no mock/animation layer: workers are real background
threads that execute real pipeline stages (validation, opportunity generation,
FFmpeg rendering, quality checks, rights checks, packaging, scheduling,
publishing), emitting a structured event on every transition. The UI polls the
persisted state and reconstructs the exact same view on refresh.

No fabricated telemetry: hardware metrics (CPU/GPU/network/...) are never
invented. Render progress is only reported when FFmpeg's ``time=`` output makes
it measurable; otherwise the stage is shown as ACTIVE.
"""

from media_service.engine.states import EngineJobState, SystemState, WorkerState, EngineStateMachine
from media_service.engine.engine_store import EngineStore
from media_service.engine.engine import Engine

__all__ = [
    "EngineJobState",
    "SystemState",
    "WorkerState",
    "EngineStateMachine",
    "EngineStore",
    "Engine",
]
