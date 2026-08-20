# Deployment Guide — Oracle Clip Production Hub

This document details deployment guidelines, environment configuration, container lifecycle, and security controls for Oracle Clip Media Service.

---

## 1. Prerequisites

- Linux container runtime (Docker, Kubernetes, AWS ECS, or Cloud Run)
- FFmpeg and ffprobe binaries installed and available in the system `$PATH`
- Python 3.11+

---

## 2. Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | string | `development` | Setting `production` enforces fail-closed validation |
| `PORT` | integer | `3000` | HTTP listening port |
| `API_KEYS` | string | `""` | Comma-separated `key:tenant` pairs (e.g. `k1:t1,k2:t2`) |
| `WEBHOOK_SECRET` | string | `""` | Secret for HMAC-SHA256 signature verification (min 16 chars) |
| `WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS` | integer | `300` | Maximum age allowed for webhook timestamps |
| `FFMPEG_BINARY` | string | `ffmpeg` | Path or binary name for FFmpeg |
| `FFPROBE_BINARY` | string | `ffprobe` | Path or binary name for ffprobe |
| `RENDERING_TIMEOUT_SECONDS` | integer | `180` | Subprocess rendering timeout |
| `STORAGE_BACKEND` | string | `local` | `local` or `s3` |
| `LOCAL_STORAGE_BASE_DIR` | string | `/app/storage` | Path for local storage backend |
| `S3_BUCKET_NAME` | string | `""` | AWS S3 Bucket (if `STORAGE_BACKEND=s3`) |
| `S3_REGION_NAME` | string | `us-east-1` | AWS S3 Region |
| `CORS_ALLOWED_ORIGINS` | string | `*` | Allowed CORS origins (comma-separated) |

---

## 3. Production Hardening Checklist

- [x] **No Default Credentials**: Must supply production API keys and webhook secret.
- [x] **Fail-Closed Startup**: Service aborts immediately if FFmpeg/ffprobe is missing or if credentials are unconfigured in production.
- [x] **Tenant Scoping**: All operations require valid `X-API-Key` headers; cross-tenant operations are strictly denied (HTTP 403).
- [x] **Tamper-Proof Webhooks**: Webhook signatures are checked using constant-time `hmac.compare_digest` with replay timestamps.
- [x] **Non-Root Execution**: Container runs under dedicated unprivileged user `oracleclip`.
- [x] **Redacted Logs**: Structured JSON logs automatically scrub secrets, tokens, and credentials.
