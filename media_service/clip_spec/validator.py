from dataclasses import dataclass
from typing import List, Optional
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec
from shared.errors.errors import ClipSpecificationValidationError


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: List[str]


class ClipSpecificationValidator:
    """Phase 13.2: Structural Clip Specification Validator.
    
    Invariants:
    - Pure structural validation
    - Side-effect free (no mutation of inputs)
    - Deterministic
    - Non-empty source_media_id and schema_version
    - version >= 1
    - At least one segment required
    - Integer timestamps: start_ms >= 0, end_ms > start_ms
    - Optional duration bounds check
    """

    def __init__(self, min_segment_duration_ms: int = 100, max_total_duration_ms: Optional[int] = None):
        self.min_segment_duration_ms = min_segment_duration_ms
        self.max_total_duration_ms = max_total_duration_ms

    def validate(self, spec: ClipSpecification, source_duration_ms: Optional[int] = None) -> ValidationResult:
        errors: List[str] = []

        if not spec:
            return ValidationResult(is_valid=False, errors=["ClipSpecification cannot be None"])

        if not getattr(spec, "source_media_id", None) or not str(spec.source_media_id).strip():
            errors.append("source_media_id is required and cannot be empty")

        if not getattr(spec, "schema_version", None) or not str(spec.schema_version).strip():
            errors.append("schema_version is required and cannot be empty")

        if getattr(spec, "version", 0) < 1:
            errors.append(f"version must be >= 1, got {getattr(spec, 'version', None)}")

        segments = getattr(spec, "segments", None)
        if not segments or not isinstance(segments, list) or len(segments) == 0:
            errors.append("At least one ClipSegmentSpec is required")
        else:
            total_duration = 0
            for idx, seg in enumerate(segments):
                if not isinstance(seg, ClipSegmentSpec) and not hasattr(seg, "start_ms"):
                    errors.append(f"Segment {idx} is not a valid ClipSegmentSpec")
                    continue

                start_ms = seg.start_ms
                end_ms = seg.end_ms

                if not isinstance(start_ms, int) or isinstance(start_ms, bool):
                    errors.append(f"Segment {idx} start_ms must be an integer, got {type(start_ms).__name__}")
                elif start_ms < 0:
                    errors.append(f"Segment {idx} start_ms must be >= 0, got {start_ms}")

                if not isinstance(end_ms, int) or isinstance(end_ms, bool):
                    errors.append(f"Segment {idx} end_ms must be an integer, got {type(end_ms).__name__}")
                elif isinstance(start_ms, int) and not isinstance(start_ms, bool) and end_ms <= start_ms:
                    errors.append(f"Segment {idx} end_ms ({end_ms}) must be strictly greater than start_ms ({start_ms})")
                elif isinstance(start_ms, int) and not isinstance(start_ms, bool):
                    duration = end_ms - start_ms
                    if duration < self.min_segment_duration_ms:
                        errors.append(f"Segment {idx} duration ({duration}ms) is less than minimum allowed ({self.min_segment_duration_ms}ms)")
                    total_duration += duration

                if source_duration_ms is not None and source_duration_ms > 0:
                    if isinstance(end_ms, int) and not isinstance(end_ms, bool) and end_ms > source_duration_ms:
                        errors.append(f"Segment {idx} end_ms ({end_ms}) exceeds source media duration ({source_duration_ms}ms)")

            if self.max_total_duration_ms and total_duration > self.max_total_duration_ms:
                errors.append(f"Total clip duration ({total_duration}ms) exceeds maximum allowed ({self.max_total_duration_ms}ms)")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    def raise_if_invalid(self, spec: ClipSpecification, source_duration_ms: Optional[int] = None) -> None:
        res = self.validate(spec, source_duration_ms=source_duration_ms)
        if not res.is_valid:
            raise ClipSpecificationValidationError(
                f"Clip specification validation failed: {'; '.join(res.errors)}",
                details={"errors": res.errors, "spec_id": getattr(spec, "spec_id", None)},
            )
