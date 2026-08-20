import time
from enum import Enum
from typing import Callable, Any, Optional
from shared.errors.errors import CircuitBreakerOpenError


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit Breaker resilience pattern for external dependencies."""

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        half_open_success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_state_change = time.time()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_state_change >= self.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                self._last_state_change = time.time()
        return self._state

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._last_state_change = time.time()
        elif self.state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        if self.state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._last_state_change = time.time()

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN. Requests blocked."
            )
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e
