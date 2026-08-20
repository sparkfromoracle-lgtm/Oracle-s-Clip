# Production Dependencies Specification

This document specifies external runtime and service dependencies for Oracle Clip Media Service.

---

## 1. System Binaries

| Binary | Minimum Version | Purpose | Fail-Closed Policy |
|---|---|---|---|
| `ffmpeg` | 5.0+ | Video segment trimming, filtering, transcoding | Service startup fails if missing in production |
| `ffprobe` | 5.0+ | Video metadata probing, duration/stream extraction | Service startup fails if missing in production |

---

## 2. Python Packages

- **FastAPI (`>=0.110.0`)**: High-performance asynchronous API framework.
- **Pydantic (`>=2.7.0`)**: Schema validation and settings management.
- **Uvicorn (`>=0.28.0`)**: ASGI web server.
- **Pytest (`>=8.0.0`)**: Comprehensive test suite execution.
- **Pillow / OpenCLIP (Optional/Modular)**: Visual frame embedding generation.

---

## 3. Storage Backends

1. **Local Object Storage**: Standard POSIX filesystem with directory traversal protection.
2. **S3 Object Storage**: Amazon S3 / Ceph / MinIO compatible storage backend with presigned download URL generation.

---

## 4. Security & Authentication

- **API Keys**: Shared secret authentication per tenant.
- **Webhooks**: HMAC-SHA256 signature scheme with timestamp replay prevention.
