import pytest
from shared.contracts.jobs import ClipSpecification, ClipSegmentSpec
from shared.contracts.enums import ClipSpecStatus
from shared.errors.errors import ClipSpecificationValidationError
from media_service.clip_spec.validator import ClipSpecificationValidator


def test_validator_valid_spec():
    validator = ClipSpecificationValidator()
    spec = ClipSpecification(
        spec_id="spec_101",
        source_media_id="src_media_1",
        schema_version="1.0.0",
        version=1,
        segments=[ClipSegmentSpec(start_ms=0, end_ms=10000)],
    )
    res = validator.validate(spec)
    assert res.is_valid is True
    assert len(res.errors) == 0
    # Should not raise
    validator.raise_if_invalid(spec)


def test_validator_missing_source_media_id():
    validator = ClipSpecificationValidator()
    spec = ClipSpecification(
        spec_id="spec_102",
        source_media_id="",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000)],
    )
    res = validator.validate(spec)
    assert res.is_valid is False
    assert any("source_media_id" in e for e in res.errors)
    with pytest.raises(ClipSpecificationValidationError):
        validator.raise_if_invalid(spec)


def test_validator_invalid_version():
    validator = ClipSpecificationValidator()
    spec = ClipSpecification(
        spec_id="spec_103",
        source_media_id="src_1",
        version=0,
        segments=[ClipSegmentSpec(start_ms=0, end_ms=5000)],
    )
    res = validator.validate(spec)
    assert res.is_valid is False
    assert any("version" in e for e in res.errors)


def test_validator_empty_segments():
    validator = ClipSpecificationValidator()
    spec = ClipSpecification(
        spec_id="spec_104",
        source_media_id="src_1",
        segments=[],
    )
    res = validator.validate(spec)
    assert res.is_valid is False
    assert any("At least one" in e for e in res.errors)


def test_validator_invalid_timestamps():
    validator = ClipSpecificationValidator()
    # Negative start
    spec_neg = ClipSpecification(
        spec_id="spec_105",
        source_media_id="src_1",
        segments=[ClipSegmentSpec(start_ms=-100, end_ms=5000)],
    )
    assert validator.validate(spec_neg).is_valid is False

    # End <= start
    spec_inverted = ClipSpecification(
        spec_id="spec_106",
        source_media_id="src_1",
        segments=[ClipSegmentSpec(start_ms=5000, end_ms=3000)],
    )
    assert validator.validate(spec_inverted).is_valid is False


def test_validator_source_duration_bounds():
    validator = ClipSpecificationValidator()
    spec = ClipSpecification(
        spec_id="spec_107",
        source_media_id="src_1",
        segments=[ClipSegmentSpec(start_ms=0, end_ms=15000)],
    )
    res = validator.validate(spec, source_duration_ms=10000)
    assert res.is_valid is False
    assert any("exceeds source media duration" in e for e in res.errors)
