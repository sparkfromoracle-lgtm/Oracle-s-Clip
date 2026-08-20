import pytest
from media_service.rendering.ffmpeg_exec import FFmpegCommandExecutor
from shared.errors.errors import DependencyUnavailableError, RenderingError


def test_ffmpeg_exec_verify_binaries_non_existent():
    executor = FFmpegCommandExecutor(
        ffmpeg_binary="non_existent_ffmpeg_xyz",
        ffprobe_binary="non_existent_ffprobe_xyz",
    )
    with pytest.raises(DependencyUnavailableError):
        executor.verify_binaries()


def test_ffmpeg_exec_execute_non_existent_binary():
    executor = FFmpegCommandExecutor(ffmpeg_binary="non_existent_ffmpeg_xyz")
    with pytest.raises(DependencyUnavailableError):
        executor.execute_ffmpeg(["-version"])


def test_ffmpeg_exec_execute_ffprobe_non_existent():
    executor = FFmpegCommandExecutor(ffprobe_binary="non_existent_ffprobe_xyz")
    with pytest.raises(DependencyUnavailableError):
        executor.execute_ffprobe(["-version"])
