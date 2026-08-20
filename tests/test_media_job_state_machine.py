import pytest
from shared.contracts.enums import JobStatus
from shared.contracts.jobs import MediaJobStateMachine
from shared.errors.errors import ValidationError


def test_media_job_state_machine_valid_transitions():
    assert MediaJobStateMachine.can_transition(JobStatus.PENDING, JobStatus.IN_PROGRESS) is True
    assert MediaJobStateMachine.can_transition(JobStatus.PENDING, JobStatus.CANCELLED) is True
    assert MediaJobStateMachine.can_transition(JobStatus.IN_PROGRESS, JobStatus.COMPLETED) is True
    assert MediaJobStateMachine.can_transition(JobStatus.IN_PROGRESS, JobStatus.FAILED) is True
    assert MediaJobStateMachine.can_transition(JobStatus.IN_PROGRESS, JobStatus.CANCELLED) is True

    # Transition helper
    assert MediaJobStateMachine.transition(JobStatus.PENDING, JobStatus.IN_PROGRESS) == JobStatus.IN_PROGRESS


def test_media_job_state_machine_invalid_transitions():
    assert MediaJobStateMachine.can_transition(JobStatus.COMPLETED, JobStatus.IN_PROGRESS) is False
    assert MediaJobStateMachine.can_transition(JobStatus.FAILED, JobStatus.PENDING) is False
    assert MediaJobStateMachine.can_transition(JobStatus.CANCELLED, JobStatus.IN_PROGRESS) is False

    with pytest.raises(ValidationError):
        MediaJobStateMachine.transition(JobStatus.COMPLETED, JobStatus.IN_PROGRESS)
