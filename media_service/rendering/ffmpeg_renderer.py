import abc
import os
import subprocess
from typing import Optional
from shared.contracts.jobs import ClipSpecification, RenderJob, RenderedAsset
from shared.contracts.enums import JobStatus
from shared.errors.errors import RenderingError, DependencyUnavailableError
from shared.hashing.content_hash import compute_content_hash


class RendererAdapter(abc.ABC):
    """Abstract rendering adapter boundary."""

    @abc.abstractmethod
    def render(self, job: RenderJob, source_media_path: str, output_path: str) -> RenderedAsset:
        pass


class MockRendererAdapter(RendererAdapter):
    """Deterministic mock renderer adapter for testing."""

    def render(self, job: RenderJob, source_media_path: str, output_path: str) -> RenderedAsset:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Create a tiny mock output file
        total_duration = sum(s.end_ms - s.start_ms for s in job.spec.segments)
        with open(output_path, "wb") as f:
            f.write(f"MOCK_RENDERED_MEDIA:{job.job_id}:{total_duration}".encode("utf-8"))

        content_hash = compute_content_hash(f"MOCK_RENDERED_MEDIA:{job.job_id}:{total_duration}")

        return RenderedAsset(
            asset_id=f"asset_{job.job_id}",
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            storage_path=output_path,
            duration_ms=total_duration,
            width=1080,
            height=1920,
            bitrate=2_000_000,
            file_size_bytes=os.path.getsize(output_path),
            content_hash=content_hash,
            metadata={"mock": True, "target_aspect_ratio": job.spec.target_aspect_ratio},
        )


class FFmpegRendererAdapter(RendererAdapter):
    """Production FFmpeg rendering adapter using controlled subprocess calls."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg", timeout_seconds: int = 120):
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout_seconds = timeout_seconds
        from media_service.rendering.ffmpeg_exec import FFmpegCommandExecutor
        self.executor = FFmpegCommandExecutor(ffmpeg_binary=ffmpeg_binary)

    def render(self, job: RenderJob, source_media_path: str, output_path: str) -> RenderedAsset:
        if not os.path.exists(source_media_path):
            raise FileNotFoundError(f"Source media file not found: {source_media_path}")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        segments = job.spec.segments
        if not segments:
            raise RenderingError("No segments provided in ClipSpecification")

        seg0 = segments[0]
        start_sec = seg0.start_ms / 1000.0
        dur_sec = (seg0.end_ms - seg0.start_ms) / 1000.0

        # Safe argument list without shell=True
        ffmpeg_args = [
            "-y",
            "-ss", str(start_sec),
            "-i", source_media_path,
            "-t", str(dur_sec),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-strict", "experimental",
            output_path,
        ]

        self.executor.execute_ffmpeg(
            args=ffmpeg_args,
            timeout_seconds=self.timeout_seconds,
            job_id=job.job_id,
        )

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RenderingError(f"FFmpeg produced empty or missing output at {output_path}")

        file_size = os.path.getsize(output_path)
        with open(output_path, "rb") as f:
            chash = compute_content_hash(f.read())

        total_duration = sum(s.end_ms - s.start_ms for s in segments)

        return RenderedAsset(
            asset_id=f"asset_{job.job_id}",
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            storage_path=output_path,
            duration_ms=total_duration,
            width=1080,
            height=1920,
            bitrate=2_500_000,
            file_size_bytes=file_size,
            content_hash=chash,
            metadata={"renderer": "ffmpeg", "segments_count": len(segments)},
        )
