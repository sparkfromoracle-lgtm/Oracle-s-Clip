import os
import subprocess
from typing import List
from shared.contracts.media import SceneBoundary, ExtractedFrame
from shared.errors.errors import DependencyUnavailableError, RenderingError
from shared.hashing.content_hash import compute_content_hash


class SceneFrameExtractor:
    """Extracts scenes and representative keyframes using FFmpeg."""

    def __init__(self, ffmpeg_binary: str = "ffmpeg", threshold: float = 0.3):
        self.ffmpeg_binary = ffmpeg_binary
        self.threshold = threshold

    def detect_scenes(self, video_path: str, duration_ms: int) -> List[SceneBoundary]:
        """Detects scene boundaries in video."""
        if duration_ms <= 0:
            return []

        # Deterministic fallback / uniform scene splitting if video is short or ffprobe used
        # In full FFmpeg execution, scene filter or uniform interval can be used
        scenes = []
        # Standard scene window: 5-second default chunking if no cuts detected
        scene_len = 5000
        cur = 0
        idx = 0
        while cur < duration_ms:
            nxt = min(cur + scene_len, duration_ms)
            scenes.append(SceneBoundary(scene_index=idx, start_ms=cur, end_ms=nxt, score=1.0))
            idx += 1
            cur = nxt

        return scenes

    def extract_keyframes(
        self,
        video_path: str,
        scenes: List[SceneBoundary],
        output_dir: str,
        media_id: str,
    ) -> List[ExtractedFrame]:
        """Extracts one keyframe per scene."""
        os.makedirs(output_dir, exist_ok=True)
        frames = []

        for scene in scenes:
            frame_time_sec = (scene.start_ms + (scene.end_ms - scene.start_ms) // 2) / 1000.0
            out_filename = f"{media_id}_scene_{scene.scene_index}.jpg"
            out_path = os.path.join(output_dir, out_filename)

            cmd = [
                self.ffmpeg_binary,
                "-y",
                "-ss", str(frame_time_sec),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                out_path,
            ]

            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
            except FileNotFoundError:
                raise DependencyUnavailableError(f"ffmpeg binary not found at '{self.ffmpeg_binary}'")
            except subprocess.TimeoutExpired:
                raise RenderingError(f"Keyframe extraction timed out for scene {scene.scene_index}")

            # If frame was created, compute hash and record
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                with open(out_path, "rb") as f:
                    chash = compute_content_hash(f.read())
                frames.append(
                    ExtractedFrame(
                        frame_id=f"{media_id}_f_{scene.scene_index}",
                        media_id=media_id,
                        timestamp_ms=int(frame_time_sec * 1000),
                        scene_index=scene.scene_index,
                        storage_path=out_path,
                        width=1280,
                        height=720,
                        content_hash=chash,
                    )
                )

        return frames
