import abc
import os
import shutil
from typing import Optional, Union, TYPE_CHECKING
from shared.contracts.enums import StorageBackendType
from shared.errors.errors import StorageError, DependencyUnavailableError, ConfigurationError

if TYPE_CHECKING:
    from media_service.config.settings import Settings


class ObjectStorageBackend(abc.ABC):
    """Abstract boundary for object storage."""

    @abc.abstractmethod
    def store(self, file_bytes: bytes, relative_path: str, content_type: Optional[str] = None) -> str:
        pass

    @abc.abstractmethod
    def get_bytes(self, relative_path: str) -> bytes:
        pass

    @abc.abstractmethod
    def put_object(self, key: str, local_file_path: str, content_type: Optional[str] = None) -> str:
        pass

    @abc.abstractmethod
    def get_object(self, key: str, download_to_path: str) -> None:
        pass

    @abc.abstractmethod
    def generate_presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        pass

    @abc.abstractmethod
    def generate_download_url(self, relative_path: str, expiration_seconds: int = 3600) -> str:
        pass

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        pass


class LocalStorageBackend(ObjectStorageBackend):
    """Local filesystem storage backend for development/testing."""

    def __init__(self, base_dir: str = "/tmp/oracle_clip_storage", base_directory: Optional[str] = None):
        self.base_directory = base_directory or base_dir
        os.makedirs(self.base_directory, exist_ok=True)

    def _full_path(self, key: str) -> str:
        if not key or not str(key).strip():
            raise StorageError("Storage key cannot be empty")
        
        # Detect traversal patterns explicitly
        key_str = str(key)
        parts = key_str.replace("\\", "/").split("/")
        if any(p == ".." for p in parts) or key_str.startswith("/") or key_str.startswith("\\"):
            raise StorageError(f"Directory traversal attack detected in key: {key}")
        
        clean_key = os.path.normpath(key_str.lstrip("/\\"))
        if clean_key.startswith("..") or "/../" in clean_key or clean_key == "..":
            raise StorageError(f"Directory traversal attack detected in key: {key}")

        base_abs = os.path.abspath(self.base_directory)
        full = os.path.abspath(os.path.join(base_abs, clean_key))
        if not full.startswith(base_abs + os.sep) and full != base_abs:
            raise StorageError(f"Directory traversal violation: {key}")
        return full

    def store(self, file_bytes: bytes, relative_path: str, content_type: Optional[str] = None) -> str:
        dest = self._full_path(relative_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(file_bytes)
        return dest

    def get_bytes(self, relative_path: str) -> bytes:
        src = self._full_path(relative_path)
        if not os.path.exists(src):
            raise StorageError(f"Object not found in local storage: {relative_path}")
        with open(src, "rb") as f:
            return f.read()

    def put_object(self, key: str, local_file_path: str, content_type: Optional[str] = None) -> str:
        dest = self._full_path(key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(local_file_path, dest)
        return f"file://{dest}"

    def get_object(self, key: str, download_to_path: str) -> None:
        src = self._full_path(key)
        if not os.path.exists(src):
            raise StorageError(f"Object not found in local storage: {key}")
        os.makedirs(os.path.dirname(download_to_path), exist_ok=True)
        shutil.copy2(src, download_to_path)

    def generate_presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        return f"file://{self._full_path(key)}"

    def generate_download_url(self, relative_path: str, expiration_seconds: int = 3600) -> str:
        return f"file://{self._full_path(relative_path)}"

    def exists(self, key: str) -> bool:
        try:
            return os.path.exists(self._full_path(key))
        except StorageError:
            return False


class S3StorageBackend(ObjectStorageBackend):
    """Production S3-compatible object storage backend."""

    def __init__(
        self,
        bucket_name: str,
        endpoint_url: Optional[str] = None,
        region_name: str = "us-east-1",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    region_name=self.region_name,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
            except ImportError:
                raise DependencyUnavailableError("boto3 is not installed for S3StorageBackend.")
        return self._client

    def store(self, file_bytes: bytes, relative_path: str, content_type: Optional[str] = None) -> str:
        client = self._get_client()
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        try:
            client.put_object(
                Bucket=self.bucket_name,
                Key=relative_path,
                Body=file_bytes,
                **extra_args,
            )
            return f"s3://{self.bucket_name}/{relative_path}"
        except Exception as e:
            raise StorageError(f"Failed to store {relative_path} in S3: {e}")

    def get_bytes(self, relative_path: str) -> bytes:
        client = self._get_client()
        try:
            resp = client.get_object(Bucket=self.bucket_name, Key=relative_path)
            return resp["Body"].read()
        except Exception as e:
            raise StorageError(f"Failed to get bytes for {relative_path} from S3: {e}")

    def put_object(self, key: str, local_file_path: str, content_type: Optional[str] = None) -> str:
        client = self._get_client()
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        try:
            client.upload_file(local_file_path, self.bucket_name, key, ExtraArgs=extra_args if extra_args else None)
            return f"s3://{self.bucket_name}/{key}"
        except Exception as e:
            raise StorageError(f"Failed to upload {key} to S3: {e}")

    def get_object(self, key: str, download_to_path: str) -> None:
        client = self._get_client()
        os.makedirs(os.path.dirname(download_to_path), exist_ok=True)
        try:
            client.download_file(self.bucket_name, key, download_to_path)
        except Exception as e:
            raise StorageError(f"Failed to download {key} from S3: {e}")

    def generate_presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        client = self._get_client()
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expiration_seconds,
            )
            return url
        except Exception as e:
            raise StorageError(f"Failed to generate presigned URL for {key}: {e}")

    def generate_download_url(self, relative_path: str, expiration_seconds: int = 3600) -> str:
        return self.generate_presigned_url(relative_path, expiration_seconds=expiration_seconds)

    def exists(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception:
            return False


def get_storage_backend(settings: "Settings") -> ObjectStorageBackend:
    """Factory to retrieve configured ObjectStorageBackend."""
    if settings.storage_backend == "local":
        return LocalStorageBackend(base_dir=settings.local_storage_base_dir)
    elif settings.storage_backend == "s3":
        if not settings.s3_bucket_name:
            raise ConfigurationError("s3_bucket_name must be configured when storage_backend is 's3'")
        return S3StorageBackend(
            bucket_name=settings.s3_bucket_name,
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region_name,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    else:
        raise ConfigurationError(f"Unsupported storage backend: '{settings.storage_backend}'")
