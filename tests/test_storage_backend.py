import os
import pytest
from media_service.storage.object_storage import (
    LocalStorageBackend,
    S3StorageBackend,
    get_storage_backend,
)
from media_service.config.settings import Settings
from shared.errors.errors import StorageError, ConfigurationError


def test_local_storage_backend(tmp_path):
    backend = LocalStorageBackend(base_dir=str(tmp_path))
    test_bytes = b"sample_video_bytes"

    stored_path = backend.store(
        file_bytes=test_bytes,
        relative_path="tenant_1/video_1.mp4",
    )
    assert os.path.exists(stored_path)
    assert backend.exists("tenant_1/video_1.mp4") is True
    assert backend.get_bytes("tenant_1/video_1.mp4") == test_bytes

    url = backend.generate_download_url("tenant_1/video_1.mp4")
    assert url.startswith("file://")

    # Directory traversal prevention
    with pytest.raises(StorageError):
        backend.store(file_bytes=b"bad", relative_path="../escape.txt")


def test_storage_backend_factory(tmp_path):
    # Local backend
    s_local = Settings(storage_backend="local", local_storage_base_dir=str(tmp_path))
    b_local = get_storage_backend(s_local)
    assert isinstance(b_local, LocalStorageBackend)

    # Unknown backend raises ConfigurationError
    s_unknown = Settings(storage_backend="unsupported_azure")
    with pytest.raises(ConfigurationError):
        get_storage_backend(s_unknown)
