# Operational Runbook: Production Deployment

## 1. Overview
The Oracle Clip Production Hub is deployed as an immutable container service. It provides deterministic, Zero-LLM media processing, opportunity generation, clip validation, and rendering pipelines.

## 2. Pre-Deployment Verification
Before promoting any release to staging or production:
1. Run full test suite:
   ```bash
   pytest tests/ -v
   ```
2. Verify linting and typing:
   ```bash
   python3 -m pyflakes media_service/ shared/
   ```
3. Verify production fail-closed validation:
   ```bash
   ENVIRONMENT=production pytest tests/test_config.py -v
   ```
4. Verify non-root Docker build:
   ```bash
   docker build -t oracle-clip-media-service:latest -f Dockerfile .
   ```

## 3. Production Environment Variables
All production credentials must be injected via secure secret managers (e.g. Vault, GCP Secret Manager, AWS Secrets Manager).

Required variables:
- `ENVIRONMENT=production`
- `ORACLE_CLIP_API_KEYS={"admin":"prod-sec-key-...", "tenant_1":"prod-key-..."}`
- `ORACLE_CLIP_WEBHOOK_SECRET=prod-webhook-secret-min32chars...`
- `ORACLE_CLIP_STORAGE_BACKEND=s3`
- `AWS_ACCESS_KEY_ID=...`
- `AWS_SECRET_ACCESS_KEY=...`
- `S3_BUCKET_NAME=prod-oracle-clip-assets`
- `FFMPEG_BINARY=/usr/bin/ffmpeg`
- `FFPROBE_BINARY=/usr/bin/ffprobe`

## 4. Deployment Steps (Blue-Green / Rolling)
1. Deploy new container version with health checks enabled.
2. Verify container liveness:
   `GET /health` -> HTTP 200 `{"status": "ok"}`
3. Verify container readiness:
   `GET /ready` -> HTTP 200 `{"status": "ready"}`
4. Execute smoke suite against new instance:
   `pytest tests/test_phase1_smoke_suite.py`
5. Shift traffic from previous deployment to current deployment.
6. Monitor Prometheus `/metrics` for error rates and latency p95/p99 spikes.
