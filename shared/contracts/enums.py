from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClipSpecStatus(str, Enum):
    """Metadata status enum for Clip Specifications.
    
    Architectural invariant: ClipSpecStatus remains purely metadata.
    It is NOT a lifecycle state machine.
    """
    DRAFT = "draft"
    VALIDATED = "validated"
    REJECTED = "rejected"
    APPROVED = "approved"


class MediaType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"


class ASRProviderType(str, Enum):
    MOCK = "mock"
    FASTER_WHISPER = "faster_whisper"
    WHISPER = "whisper"


class VisualEmbeddingModel(str, Enum):
    CLIP_VIT_B32 = "clip-vit-base-patch32"
    CLIP_VIT_L14 = "clip-vit-large-patch14"
    MOCK = "mock"


class QualityVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    MANUAL_REVIEW = "manual_review"


class StorageBackendType(str, Enum):
    LOCAL = "local"
    S3 = "s3"
    MOCK = "mock"


class RightsStatus(str, Enum):
    """Provenance and rights status for a publishable asset.

    Unknown rights must NEVER silently become publishable.
    """
    RIGHTS_VERIFIED = "rights_verified"
    RIGHTS_UNKNOWN = "rights_unknown"
    RESTRICTED = "restricted"
    EXPIRED = "expired"
    NOT_MONETIZABLE = "not_monetizable"


class ScheduleDecision(str, Enum):
    """Possible scheduler decisions for a candidate clip."""
    PUBLISH = "publish"
    SCHEDULE = "schedule"
    REVIEW = "review"
    WAIT = "wait"
    REJECT = "reject"


class MetricSource(str, Enum):
    """Labels the origin of an analytics or revenue metric."""
    ACTUAL = "actual"
    ESTIMATED = "estimated"
    IMPORTED = "imported"
    USER_ENTERED = "user_entered"
