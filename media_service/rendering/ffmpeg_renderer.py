import abc
import os
import subprocess
from typing import Optional
from shared.contracts.jobs import ClipSpecification, RenderJob, RenderedAsset
from shared.contracts.enums import JobStatus
from shared.errors.errors import RenderingError, DependencyUnavailableError
from shared.hashing.content_hash import compute_content_hash
from shared.hashing.checksum_verifier import calculate_sha256


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
        # Cryptographic digest of the artifact actually written to disk.
        checksum, file_size = calculate_sha256(output_path)

        return RenderedAsset(
            asset_id=f"asset_{job.job_id}",
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            storage_path=output_path,
            duration_ms=total_duration,
            width=1080,
            height=1920,
            bitrate=2_000_000,
            file_size_bytes=file_size,
            content_hash=content_hash,
            checksum_sha256=checksum,
            metadata={"mock": True, "target_aspect_ratio": job.spec.target_aspect_ratio},
        )


# Canonical output frame sizes per supported target aspect ratio. The clip
# specification's `target_aspect_ratio` drives the rendered geometry; anything
# not listed here is derived from the ratio against a 1920px long edge.
ASPECT_RATIO_FRAME_SIZES = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "4:3": (1440, 1080),
}


def resolve_target_frame_size(target_aspect_ratio: str) -> tuple:
    """Resolves the output (width, height) for a target aspect ratio string."""
    ratio = (target_aspect_ratio or "9:16").strip()
    if ratio in ASPECT_RATIO_FRAME_SIZES:
        return ASPECT_RATIO_FRAME_SIZES[ratio]

    try:
        w_ratio, h_ratio = (float(part) for part in ratio.split(":", 1))
        if w_ratio <= 0 or h_ratio <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise RenderingError(f"Unsupported target_aspect_ratio '{target_aspect_ratio}'")

    if w_ratio >= h_ratio:
        width, height = 1920, int(round(1920 * h_ratio / w_ratio))
    else:
        height, width = 1920, int(round(1920 * w_ratio / h_ratio))

    # H.264 requires even dimensions.
    return width - (width % 2), height - (height % 2)


class FFmpegRendererAdapter(RendererAdapter):
    """Production FFmpeg rendering adapter using controlled subprocess calls."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg", timeout_seconds: int = 120, ffprobe_binary: str = "ffprobe"):
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout_seconds = timeout_seconds
        from media_service.rendering.ffmpeg_exec import FFmpegCommandExecutor
        from media_service.inspect.media_inspector import MediaInspector
        self.executor = FFmpegCommandExecutor(ffmpeg_binary=ffmpeg_binary)
        self.inspector = MediaInspector(ffprobe_binary=ffprobe_binary)

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

        # Honour the specification's target aspect ratio: scale to fit and pad,
        # so no source content is cropped away and the frame geometry is exact.
        out_w, out_h = resolve_target_frame_size(job.spec.target_aspect_ratio)
        vf = (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

        # Safe argument list without shell=True
        ffmpeg_args = [
            "-y",
            "-ss", str(start_sec),
            "-i", source_media_path,
            "-t", str(dur_sec),
            "-vf", vf,
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

        with open(output_path, "rb") as f:
            chash = compute_content_hash(f.read())
        checksum, file_size = calculate_sha256(output_path)

        # Report the properties of the artifact that was actually produced, so
        # downstream quality checks evaluate real media rather than assumptions.
        probed = self.inspector.inspect(output_path)
        requested_duration = sum(s.end_ms - s.start_ms for s in segments)

        return RenderedAsset(
            asset_id=f"asset_{job.job_id}",
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            storage_path=output_path,
            duration_ms=probed.duration_ms or requested_duration,
            width=probed.width or 0,
            height=probed.height or 0,
            bitrate=probed.bitrate,
            file_size_bytes=file_size,
            content_hash=chash,
            checksum_sha256=checksum,
            metadata={
                "renderer": "ffmpeg",
                "segments_count": len(segments),
                "requested_duration_ms": requested_duration,
                "probed_format": probed.format_name,
                "probed_frame_rate": probed.frame_rate,
                "target_aspect_ratio": job.spec.target_aspect_ratio,
            },
        )
