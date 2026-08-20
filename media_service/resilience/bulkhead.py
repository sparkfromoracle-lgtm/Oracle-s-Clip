import threading
from typing import Callable, Any, Optional
from shared.errors.errors import BulkheadFullError


class Bulkhead:
    """Concurrency bulkhead pattern to protect compute resources."""

    def __init__(self, max_concurrent: int = 5, max_queue: int = 10):
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._active_count = 0
        self._lock = threading.Lock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            raise BulkheadFullError(
                f"Bulkhead concurrency limit ({self.max_concurrent}) exceeded."
            )
        try:
            with self._lock:
                self._active_count += 1
            return func(*args, **kwargs)
        finally:
            with self._lock:
                self._active_count -= 1
            self._semaphore.release()
