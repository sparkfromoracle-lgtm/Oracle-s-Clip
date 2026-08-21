from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from shared.contracts.enums import JobStatus, QualityVerdict, ClipSpecStatus


@dataclass(frozen=True)
class ContentOpportunity:
    opportunity_id: str
    source_media_id: str
    start_ms: int
    end_ms: int
    score: float
    reason: str
    template_name: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClipSegmentSpec:
    start_ms: int
    end_ms: int
    source_media_id: Optional[str] = None
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None


@dataclass(frozen=True)
class ClipSpecification:
    spec_id: str
    source_media_id: str
    segments: List[ClipSegmentSpec]
    schema_version: str = "1.0.0"
    version: int = 1
    target_aspect_ratio: str = "9:16"
    status: ClipSpecStatus = ClipSpecStatus.DRAFT
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderJob:
    job_id: str
    tenant_id: str
    spec: ClipSpecification
    status: JobStatus = JobStatus.PENDING
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedAsset:
    asset_id: str
    job_id: str
    storage_path: str
    duration_ms: int
    width: int = 0
    height: int = 0
    tenant_id: Optional[str] = None
    bitrate: Optional[int] = None
    file_size_bytes: Optional[int] = None
    content_hash: Optional[str] = None
    checksum_sha256: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityMetric:
    name: str
    score: float
    threshold: float
    passed: bool
    details: Optional[str] = None


@dataclass(frozen=True)
class QualityReport:
    report_id: str
    asset_id: str
    verdict: QualityVerdict
    overall_score: float
    metrics: List[QualityMetric]
    created_at: str
    summary: str


class MediaJobStateMachine:
    """Deterministic Media Job State Machine.
    
    Allowed transitions:
    PENDING -> IN_PROGRESS
    IN_PROGRESS -> COMPLETED
    IN_PROGRESS -> FAILED
    PENDING -> CANCELLED
    IN_PROGRESS -> CANCELLED
    """
    _VALID_TRANSITIONS = {
        JobStatus.PENDING: {JobStatus.IN_PROGRESS, JobStatus.CANCELLED},
        JobStatus.IN_PROGRESS: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
        JobStatus.COMPLETED: set(),
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }

    @classmethod
    def can_transition(cls, current_status: JobStatus, target_status: JobStatus) -> bool:
        return target_status in cls._VALID_TRANSITIONS.get(current_status, set())

    @classmethod
    def transition(cls, current_status: JobStatus, target_status: JobStatus) -> JobStatus:
        if not cls.can_transition(current_status, target_status):
            from shared.errors.errors import ValidationError
            raise ValidationError(
                f"Invalid job state transition from {current_status.value} to {target_status.value}"
            )
        return target_status
