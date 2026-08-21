from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from shared.contracts.enums import JobStatus, QualityVerdict


@dataclass(frozen=True)
class WebhookPayload:
    event_type: str
    tenant_id: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    event_id: Optional[str] = None


@dataclass(frozen=True)
class OrchestrationClipTask:
    task_id: str
    tenant_id: str
    source_media_id: str
    status: JobStatus = JobStatus.PENDING
    opportunity_id: Optional[str] = None
    spec_id: Optional[str] = None
    job_id: Optional[str] = None
    asset_id: Optional[str] = None
    quality_verdict: Optional[QualityVerdict] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntegrationHints:
    """Phase 13.7: Provider-agnostic orchestration hints for the frontend/integration layer.

    Describes the contract surface any orchestration-facing layer (Base44 in dev,
    or any other integration host) consumes. The hints carry no provider-specific
    runtime dependency: they are static metadata about the pipeline's event
    vocabulary and API prefix. Heavy media processing is never delegated to the
    integration layer.
    """
    collection_name: str = "oracle_clips"
    endpoint_prefix: str = "/v1"
    webhook_event_types: List[str] = field(
        default_factory=lambda: [
            "clip.opportunity.detected",
            "clip.spec.created",
            "clip.rendered",
            "clip.quality.checked",
            "clip.guardian.decided",
        ]
    )
