import time
import threading
from typing import Dict, Tuple
from shared.errors.errors import RateLimitExceededError


class TokenBucketRateLimiter:
    """Thread-safe sliding window token bucket rate limiter per tenant/key."""

    def __init__(self, requests_per_minute: int = 120, burst_capacity: int = 30):
        self.requests_per_minute = max(1, requests_per_minute)
        self.capacity = max(1, burst_capacity)
        self.fill_rate = self.requests_per_minute / 60.0  # tokens per second
        self._buckets: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last_updated)
        self._lock = threading.Lock()

    def check_and_consume(self, key: str, tokens_needed: float = 1.0) -> Tuple[bool, float]:
        """Checks if key has enough tokens and consumes them.
        
        Returns:
            (allowed: bool, remaining_tokens: float)
        """
        now = time.time()
        with self._lock:
            if key not in self._buckets:
                tokens = float(self.capacity)
                last_updated = now
            else:
                tokens, last_updated = self._buckets[key]
                # Replenish tokens based on elapsed time
                elapsed = now - last_updated
                tokens = min(float(self.capacity), tokens + (elapsed * self.fill_rate))
                last_updated = now

            if tokens >= tokens_needed:
                tokens -= tokens_needed
                self._buckets[key] = (tokens, last_updated)
                return True, tokens
            else:
                self._buckets[key] = (tokens, last_updated)
                return False, tokens

    def enforce(self, key: str, tokens_needed: float = 1.0) -> None:
        """Enforces rate limit, raising RateLimitExceededError if rate exceeded."""
        allowed, remaining = self.check_and_consume(key, tokens_needed)
        if not allowed:
            raise RateLimitExceededError(
                f"Rate limit exceeded for '{key}'. Limit: {self.requests_per_minute} req/min.",
                details={"key": key, "limit_per_min": self.requests_per_minute},
            )

    def reset(self) -> None:
        """Clears all bucket states."""
        with self._lock:
            self._buckets.clear()
