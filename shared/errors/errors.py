from typing import Any, Dict, Optional


class OracleClipError(Exception):
    """Base error class for Oracle Clip system."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(OracleClipError):
    """Raised when data validation fails."""
    pass


class ClipSpecificationValidationError(ValidationError):
    """Raised when a ClipSpecification fails structural validation."""
    pass


class ConfigurationError(OracleClipError):
    """Raised when environment or runtime configuration is invalid or missing."""
    pass


class SecurityError(OracleClipError):
    """Raised for authentication, authorization, or signature errors."""
    pass


class RateLimitExceededError(OracleClipError):
    """Raised when request rate limit is exceeded."""
    pass


class AuthenticationError(SecurityError):
    """Raised when authentication credentials are invalid or missing."""
    pass


class TenantIsolationError(SecurityError):
    """Raised when a tenant attempts cross-tenant access."""
    pass


class WebhookVerificationError(SecurityError):
    """Raised when inbound or outbound webhook signatures are invalid, expired, or tampered."""
    pass


class RenderingError(OracleClipError):
    """Raised when media rendering fails."""
    pass


class StorageError(OracleClipError):
    """Raised when storage operations fail."""
    pass


class TranscriptionError(OracleClipError):
    """Raised when ASR transcription fails."""
    pass


class EmbeddingError(OracleClipError):
    """Raised when visual or text embedding operations fail."""
    pass


class CircuitBreakerOpenError(OracleClipError):
    """Raised when an operation is rejected by an open circuit breaker."""
    pass


class BulkheadFullError(OracleClipError):
    """Raised when a bulkhead concurrency limit is exceeded."""
    pass


class ResourceNotFoundError(OracleClipError):
    """Raised when a requested resource is not found."""
    pass


class DependencyUnavailableError(OracleClipError):
    """Raised when a required production dependency (FFmpeg, ASR, etc.) is unavailable."""
    pass
