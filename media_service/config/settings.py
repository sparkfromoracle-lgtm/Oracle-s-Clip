import os
import shutil
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from shared.errors.errors import ConfigurationError


class Settings(BaseModel):
    """Production Settings for Oracle Clip Media Service."""
    environment: str = Field(default="development")
    api_port: int = Field(default=3000)
    api_host: str = Field(default="0.0.0.0")

    # API Keys & Auth: mapping of api_key -> tenant_id or comma-separated "key:tenant"
    api_keys: Dict[str, str] = Field(default_factory=dict)
    
    # Webhook Secret for HMAC-SHA256 signing
    webhook_secret: str = Field(default="")
    webhook_timestamp_tolerance_seconds: int = Field(default=300)

    # Media Binaries
    ffmpeg_binary: str = Field(default="ffmpeg")
    ffprobe_binary: str = Field(default="ffprobe")
    rendering_timeout_seconds: int = Field(default=180)

    # Providers
    asr_provider: str = Field(default="mock")  # 'mock', 'local'
    clip_provider: str = Field(default="mock") # 'mock', 'open_clip'
    storage_backend: str = Field(default="local") # 'local', 's3'

    # S3 Object Storage (required if storage_backend == 's3')
    s3_bucket_name: Optional[str] = None
    s3_endpoint_url: Optional[str] = None
    s3_region_name: str = "us-east-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    local_storage_base_dir: str = "/tmp/oracle_clip_storage"

    # Security & Protection
    rate_limit_requests_per_minute: int = Field(default=300)
    max_upload_size_bytes: int = Field(default=500 * 1024 * 1024)
    idempotency_ttl_seconds: int = Field(default=86400)
    max_render_retries: int = Field(default=2)

    # CORS
    cors_allowed_origins: List[str] = Field(default_factory=lambda: ["*"])

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def validate_production(self) -> None:
        """Enforces fail-closed validation for production deployments."""
        if not self.is_production:
            return

        errors: List[str] = []

        # 1. Auth check: must have at least one valid API key configured
        if not self.api_keys:
            errors.append("Production requires at least one configured API key in api_keys")

        # 2. Webhook secret check
        if not self.webhook_secret or len(self.webhook_secret) < 16:
            errors.append("Production requires a strong webhook_secret (minimum 16 chars)")

        # 3. Binaries check: ffmpeg & ffprobe must be found in PATH or executable
        if not shutil.which(self.ffmpeg_binary):
            errors.append(f"FFmpeg binary '{self.ffmpeg_binary}' is not available in system PATH")
        if not shutil.which(self.ffprobe_binary):
            errors.append(f"ffprobe binary '{self.ffprobe_binary}' is not available in system PATH")

        # 4. Storage check: production must not silently use mock or local storage without explicit intent
        if self.storage_backend == "s3":
            if not self.s3_bucket_name:
                errors.append("s3_bucket_name is required when storage_backend is 's3'")
        elif self.storage_backend not in {"s3", "local"}:
            errors.append(f"Unknown storage_backend '{self.storage_backend}'")

        # 5. Providers check: production must strictly use real providers (no mock ASR or mock CLIP)
        if self.asr_provider == "mock":
            errors.append("Production mode requires real asr_provider ('local' or 'faster_whisper'), mock is forbidden")
        elif self.asr_provider not in {"local", "faster_whisper"}:
            errors.append(f"Invalid asr_provider '{self.asr_provider}'")

        if self.clip_provider == "mock":
            errors.append("Production mode requires real clip_provider ('open_clip'), mock is forbidden")
        elif self.clip_provider not in {"open_clip"}:
            errors.append(f"Invalid clip_provider '{self.clip_provider}'")

        if errors:
            raise ConfigurationError(
                f"Production configuration validation failed: {'; '.join(errors)}",
                details={"errors": errors, "environment": self.environment},
            )

    def safe_summary(self) -> Dict[str, Any]:
        """Returns a sanitized configuration summary that NEVER exposes secret values."""
        masked_keys = {
            k[-4:].rjust(len(k), "*") if len(k) >= 4 else "****": v
            for k, v in self.api_keys.items()
        }
        return {
            "environment": self.environment,
            "is_production": self.is_production,
            "api_port": self.api_port,
            "api_host": self.api_host,
            "configured_tenants": list(set(self.api_keys.values())),
            "api_keys_count": len(self.api_keys),
            "masked_key_samples": masked_keys,
            "webhook_secret_configured": bool(self.webhook_secret),
            "webhook_timestamp_tolerance_seconds": self.webhook_timestamp_tolerance_seconds,
            "ffmpeg_binary": self.ffmpeg_binary,
            "ffprobe_binary": self.ffprobe_binary,
            "asr_provider": self.asr_provider,
            "clip_provider": self.clip_provider,
            "storage_backend": self.storage_backend,
            "s3_bucket_name": self.s3_bucket_name,
            "s3_endpoint_url": self.s3_endpoint_url,
            "s3_region_name": self.s3_region_name,
            "local_storage_base_dir": self.local_storage_base_dir,
            "cors_allowed_origins": self.cors_allowed_origins,
        }


def load_settings_from_env() -> Settings:
    """Loads configuration settings from environment variables."""
    env = os.environ.get("ENVIRONMENT", os.environ.get("ENV", "development"))
    
    # Parse API_KEYS from env (format: "key1:tenant1,key2:tenant2" or JSON)
    api_keys_raw = os.environ.get("API_KEYS", "")
    api_keys: Dict[str, str] = {}
    if api_keys_raw:
        for pair in api_keys_raw.split(","):
            pair = pair.strip()
            if ":" in pair:
                k, t = pair.split(":", 1)
                if k.strip() and t.strip():
                    api_keys[k.strip()] = t.strip()

    # Fallback to single SERVICE_API_KEY & TENANT_ID if provided
    single_key = os.environ.get("SERVICE_API_KEY")
    single_tenant = os.environ.get("DEFAULT_TENANT_ID", "tenant_default")
    if single_key and single_key not in api_keys:
        api_keys[single_key] = single_tenant

    cors_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

    settings = Settings(
        environment=env,
        api_port=int(os.environ.get("PORT", os.environ.get("API_PORT", 3000))),
        api_host=os.environ.get("API_HOST", "0.0.0.0"),
        api_keys=api_keys,
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        webhook_timestamp_tolerance_seconds=int(os.environ.get("WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", 300)),
        ffmpeg_binary=os.environ.get("FFMPEG_BINARY", "ffmpeg"),
        ffprobe_binary=os.environ.get("FFPROBE_BINARY", "ffprobe"),
        rendering_timeout_seconds=int(os.environ.get("RENDERING_TIMEOUT_SECONDS", 180)),
        asr_provider=os.environ.get("ASR_PROVIDER", "mock"),
        clip_provider=os.environ.get("CLIP_PROVIDER", "mock"),
        storage_backend=os.environ.get("STORAGE_BACKEND", "local"),
        s3_bucket_name=os.environ.get("S3_BUCKET_NAME"),
        s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
        s3_region_name=os.environ.get("S3_REGION_NAME", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        local_storage_base_dir=os.environ.get("LOCAL_STORAGE_BASE_DIR", "/tmp/oracle_clip_storage"),
        rate_limit_requests_per_minute=int(os.environ.get("RATE_LIMIT_REQUESTS_PER_MINUTE", 300)),
        max_upload_size_bytes=int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", 500 * 1024 * 1024)),
        idempotency_ttl_seconds=int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", 86400)),
        max_render_retries=int(os.environ.get("MAX_RENDER_RETRIES", 2)),
        cors_allowed_origins=cors_origins or ["*"],
    )

    return settings
