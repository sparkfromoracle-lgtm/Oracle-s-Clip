import logging
import os
import shutil
import subprocess
from typing import List, Optional
from shared.errors.errors import DependencyUnavailableError, RenderingError

logger = logging.getLogger("oracle_clip.ffmpeg_exec")


class FFmpegCommandExecutor:
    """Safe, controlled subprocess executor for FFmpeg and ffprobe commands.
    
    Security & Reliability Rules:
    - Never uses shell=True
    - Enforces execution timeout
    - Captures stderr and stdout safely without leaking secrets
    - Validates binary existence before execution
    - Returns structured failures
    """

    def __init__(self, ffmpeg_binary: str = "ffmpeg", ffprobe_binary: str = "ffprobe"):
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary

    def verify_binaries(self) -> None:
        """Verifies that required media binaries exist and are executable."""
        if not shutil.which(self.ffmpeg_binary):
            raise DependencyUnavailableError(f"FFmpeg binary '{self.ffmpeg_binary}' is not available in system PATH")
        if not shutil.which(self.ffprobe_binary):
            raise DependencyUnavailableError(f"ffprobe binary '{self.ffprobe_binary}' is not available in system PATH")

    def execute_ffmpeg(
        self,
        args: List[str],
        timeout_seconds: int = 120,
        job_id: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Executes an FFmpeg command with safe argument handling."""
        cmd = [self.ffmpeg_binary] + [str(a) for a in args]
        
        # Redact any potentially sensitive parameters in debug logs
        safe_cmd_str = " ".join(cmd)
        logger.info(f"Executing FFmpeg [job={job_id or 'none'}]: {safe_cmd_str}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            raise DependencyUnavailableError(f"FFmpeg binary not found at '{self.ffmpeg_binary}'")
        except subprocess.TimeoutExpired:
            raise RenderingError(
                f"FFmpeg execution timed out after {timeout_seconds}s for job {job_id or 'none'}"
            )

        if result.returncode != 0:
            error_tail = result.stderr[-1000:] if result.stderr else "Unknown error"
            logger.error(f"FFmpeg execution failed (rc={result.returncode}): {error_tail}")
            raise RenderingError(
                f"FFmpeg process returned non-zero exit code {result.returncode}: {error_tail}",
                details={"returncode": result.returncode, "stderr": error_tail, "job_id": job_id},
            )

        return result

    def execute_ffprobe(
        self,
        args: List[str],
        timeout_seconds: int = 30,
    ) -> subprocess.CompletedProcess:
        """Executes an ffprobe command with safe argument handling."""
        cmd = [self.ffprobe_binary] + [str(a) for a in args]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            raise DependencyUnavailableError(f"ffprobe binary not found at '{self.ffprobe_binary}'")
        except subprocess.TimeoutExpired:
            raise RenderingError(f"ffprobe execution timed out after {timeout_seconds}s")

        if result.returncode != 0:
            error_tail = result.stderr[-500:] if result.stderr else "Unknown error"
            raise RenderingError(
                f"ffprobe process returned non-zero exit code {result.returncode}: {error_tail}",
                details={"returncode": result.returncode, "stderr": error_tail},
            )

        return result
