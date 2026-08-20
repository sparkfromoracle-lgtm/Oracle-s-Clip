# Oracle Clip Production Hub — Media Service

High-performance, deterministic media processing, opportunity generation, clip specification validation, rendering, and quality verification service for Oracle Clip Production Hub.

---

## 1. Sealed Architecture Pipeline

The system strictly executes the deterministic sealed pipeline:

```
ContentOpportunity (Phase 13.1)
  ↓
ClipSpecification (Phase 13.2)
  ↓
ClipSpecificationValidator
  ↓
RendererAdapter (FFmpeg / Mock)
  ↓
RenderJob & RenderedAsset
  ↓
QualityChecker (Phase 13.4)
  ↓
QualityReport
  ↓
GuardianHook (Publication Decision)
  ↓
Orchestration / Secure Webhooks (Base44)
```

---

## 2. Core Features & Capabilities

- **Zero-LLM Pipeline**: Complete end-to-end clip generation and validation without relying on commercial LLMs.
- **Fail-Closed Production Mode**: Validates binaries (FFmpeg/ffprobe), authentication keys, webhook secrets, and storage configurations at startup.
- **Safe Media Subprocess Execution**: Subprocesses are executed with controlled argument arrays (no `shell=True`), timeout guarantees, and sanitized error captures.
- **Tenant Isolation & Security**: Service API key authentication via timing-safe comparisons (`hmac.compare_digest`), strict tenant context propagation, and cross-tenant access rejection (`TenantIsolationError`).
- **HMAC-SHA256 Webhook Security**: Secure payload signing and inbound verification with timestamp-based replay protection.
- **Structured Observability**: JSON logs with request correlation IDs, tenant scopes, and recursive credential/secret redaction.

---

## 3. Quick Start (Development)

### Requirements
- Python 3.11+
- FFmpeg & ffprobe (or mock mode in development)

### Setup & Run
```bash
# Install dependencies
pip install -r requirements.txt

# Run test suite
PYTHONPATH=. pytest tests/ -v

# Run FastAPI media service
python3 -m uvicorn media_service.api.app:app --host 0.0.0.0 --port 3000 --reload
```

---

## 4. API Endpoints

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/health` | Liveness health check | No |
| `GET` | `/ready` | Production dependency readiness probe | No |
| `GET` | `/v1/config/summary` | Sanitized configuration summary | Yes (`X-API-Key`) |
| `POST` | `/v1/opportunities/generate` | Generates candidate content opportunities | Yes (`X-API-Key`) |
| `POST` | `/v1/clip-specs/validate` | Validates structural clip specification | Yes (`X-API-Key`) |
| `POST` | `/v1/render-jobs` | Submits and renders clip job | Yes (`X-API-Key`) |
| `GET` | `/v1/render-jobs/{job_id}` | Retrieves render job status | Yes (`X-API-Key`) |
| `POST` | `/v1/quality/check` | Evaluates quality metrics on rendered asset | Yes (`X-API-Key`) |
| `POST` | `/v1/guardian/evaluate` | Evaluates Guardian publication policy | Yes (`X-API-Key`) |
| `POST` | `/v1/webhooks/inbound` | Inbound webhook verification & handler | HMAC-SHA256 (`X-Webhook-Signature`) |

---

## 5. Running with Docker

```bash
docker-compose up --build
```
