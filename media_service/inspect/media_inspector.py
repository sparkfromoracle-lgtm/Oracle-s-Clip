import json
import os
import subprocess
from typing import Optional
from shared.contracts.media import MediaMetadata
from shared.errors.errors import DependencyUnavailableError, RenderingError


class MediaInspector:
    """Inspects media files to extract metadata using ffprobe."""

    def __init__(self, ffprobe_binary: str = "ffprobe"):
        self.ffprobe_binary = ffprobe_binary

    def inspect(self, file_path: str) -> MediaMetadata:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Media file not found: {file_path}")

        cmd = [
            self.ffprobe_binary,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            raise DependencyUnavailableError(f"ffprobe binary not found at '{self.ffprobe_binary}'")
        except subprocess.TimeoutExpired:
            raise RenderingError(f"ffprobe inspection timed out for '{file_path}'")

        if result.returncode != 0:
            raise RenderingError(f"ffprobe failed to inspect '{file_path}': {result.stderr}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RenderingError(f"Failed to parse ffprobe JSON output: {e}")

        format_info = data.get("format", {})
        duration_sec = float(format_info.get("duration", 0.0))
        duration_ms = int(duration_sec * 1000)
        format_name = format_info.get("format_name", "unknown")
        bitrate = int(format_info.get("bit_rate")) if format_info.get("bit_rate") else None

        width = None
        height = None
        frame_rate = None
        audio_channels = None
        audio_sample_rate = None

        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")
            if codec_type == "video" and width is None:
                width = stream.get("width")
                height = stream.get("height")
                r_frame_rate = stream.get("r_frame_rate", "")
                if "/" in r_frame_rate:
                    num, den = r_frame_rate.split("/")
                    try:
                        den_val = float(den)
                        if den_val > 0:
                            frame_rate = float(num) / den_val
                    except ValueError:
                        pass
            elif codec_type == "audio" and audio_channels is None:
                audio_channels = stream.get("channels")
                sr = stream.get("sample_rate")
                if sr:
                    try:
                        audio_sample_rate = int(sr)
                    except ValueError:
                        pass

        return MediaMetadata(
            duration_ms=duration_ms,
            format_name=format_name,
            width=width,
            height=height,
            frame_rate=frame_rate,
            bitrate=bitrate,
            audio_channels=audio_channels,
            audio_sample_rate=audio_sample_rate,
            extra={"streams_count": len(data.get("streams", []))},
        )
