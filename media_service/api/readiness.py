import importlib
import os
import shutil
import subprocess
from typing import Any, Dict
from media_service.config.settings import Settings


class ReadinessProbe:
    """Evaluates production dependency readiness with real probing."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def check_readiness(self) -> Dict[str, Any]:
        checks: Dict[str, Any] = {}
        all_ready = True

        # 1. FFmpeg & ffprobe binary availability and basic execution
        ffmpeg_path = shutil.which(self.settings.ffmpeg_binary)
        ffprobe_path = shutil.which(self.settings.ffprobe_binary)

        ffmpeg_healthy = False
        ffprobe_healthy = False

        if ffmpeg_path:
            try:
                res = subprocess.run(
                    [self.settings.ffmpeg_binary, "-version"],
                    capture_output=True,
                    timeout=5,
                )
                ffmpeg_healthy = res.returncode == 0
            except Exception:
                ffmpeg_healthy = False

        if ffprobe_path:
            try:
                res = subprocess.run(
                    [self.settings.ffprobe_binary, "-version"],
                    capture_output=True,
                    timeout=5,
                )
                ffprobe_healthy = res.returncode == 0
            except Exception:
                ffprobe_healthy = False

        checks["ffmpeg"] = {
            "binary": self.settings.ffmpeg_binary,
            "path": ffmpeg_path or "not_found",
            "available": bool(ffmpeg_path),
            "healthy": ffmpeg_healthy,
        }
        checks["ffprobe"] = {
            "binary": self.settings.ffprobe_binary,
            "path": ffprobe_path or "not_found",
            "available": bool(ffprobe_path),
            "healthy": ffprobe_healthy,
        }
        if not ffmpeg_healthy or not ffprobe_healthy:
            if self.settings.is_production:
                all_ready = False

        # 2. Storage Backend check
        if self.settings.storage_backend == "s3":
            s3_configured = bool(self.settings.s3_bucket_name)
            s3_boto3_ok = bool(importlib.util.find_spec("boto3"))
            s3_ready = s3_configured and s3_boto3_ok
            checks["storage"] = {
                "backend": "s3",
                "bucket": self.settings.s3_bucket_name,
                "configured": s3_configured,
                "driver_available": s3_boto3_ok,
                "ready": s3_ready,
            }
            if not s3_ready and self.settings.is_production:
                all_ready = False
        else:
            try:
                os.makedirs(self.settings.local_storage_base_dir, exist_ok=True)
                test_file = os.path.join(self.settings.local_storage_base_dir, ".probe_test")
                with open(test_file, "w") as f:
                    f.write("probe")
                os.remove(test_file)
                storage_writable = True
            except Exception:
                storage_writable = False

            checks["storage"] = {
                "backend": "local",
                "base_dir": self.settings.local_storage_base_dir,
                "writable": storage_writable,
                "ready": storage_writable,
            }
            if not storage_writable and self.settings.is_production:
                all_ready = False

        # 3. ASR Provider probe
        asr_provider = self.settings.asr_provider
        asr_driver_installed = False
        if asr_provider in {"local", "faster_whisper"}:
            fw_spec = bool(importlib.util.find_spec("faster_whisper"))
            wh_spec = bool(importlib.util.find_spec("whisper"))
            asr_driver_installed = fw_spec or wh_spec
            asr_ready = asr_driver_installed
        elif asr_provider == "mock":
            asr_driver_installed = True
            # In production, mock is forbidden
            asr_ready = not self.settings.is_production
        else:
            asr_ready = False

        checks["asr"] = {
            "provider": asr_provider,
            "driver_installed": asr_driver_installed,
            "ready": asr_ready,
        }
        if not asr_ready and self.settings.is_production:
            all_ready = False

        # 4. CLIP Visual Embedding Provider probe
        clip_provider = self.settings.clip_provider
        clip_driver_installed = False
        if clip_provider == "open_clip":
            oc_spec = bool(importlib.util.find_spec("open_clip"))
            tc_spec = bool(importlib.util.find_spec("torch"))
            clip_driver_installed = oc_spec and tc_spec
            clip_ready = clip_driver_installed
        elif clip_provider == "mock":
            clip_driver_installed = True
            # In production, mock is forbidden
            clip_ready = not self.settings.is_production
        else:
            clip_ready = False

        checks["clip"] = {
            "provider": clip_provider,
            "driver_installed": clip_driver_installed,
            "ready": clip_ready,
        }
        if not clip_ready and self.settings.is_production:
            all_ready = False

        # 5. Vector Index Service probe
        numpy_ok = bool(importlib.util.find_spec("numpy"))
        checks["vector_index"] = {
            "backend": "in_memory_cosine",
            "numpy_accelerated": numpy_ok,
            "ready": numpy_ok,
        }
        if not numpy_ok and self.settings.is_production:
            all_ready = False

        # 6. Security & Auth check
        auth_ok = len(self.settings.api_keys) > 0
        webhook_ok = bool(self.settings.webhook_secret) and (
            len(self.settings.webhook_secret) >= 16 if self.settings.is_production else True
        )
        checks["auth"] = {
            "configured_keys_count": len(self.settings.api_keys),
            "ready": auth_ok or not self.settings.is_production,
        }
        checks["webhooks"] = {
            "secret_configured": bool(self.settings.webhook_secret),
            "ready": webhook_ok or not self.settings.is_production,
        }
        if self.settings.is_production:
            if not auth_ok or not webhook_ok:
                all_ready = False

        return {
            "status": "ready" if all_ready else "degraded",
            "environment": self.settings.environment,
            "is_production": self.settings.is_production,
            "checks": checks,
        }

