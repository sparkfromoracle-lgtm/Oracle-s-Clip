# Operational Runbook: Incident Response & Troubleshooting

## 1. Severity Classification
- **P0 - Outage**: API unavailable, `/health` failing, complete inability to render clips.
- **P1 - Critical**: High failure rate in rendering, webhook delivery failure across all tenants, storage unavailable.
- **P2 - Degraded**: High latency (p99 > 5000ms), single tenant rate limit loop, transient disk pressure.

## 2. Diagnostics & Telemetry

### Inspect Structured Logs
All logs are emitted as single-line JSON objects with automatic secret redaction:
```bash
# Filter error-level events
kubectl logs -l app=oracle-clip-media-service --tail=200 | jq 'select(.level=="ERROR")'
```

### Inspect Prometheus Metrics
Fetch live operational metrics from `/metrics`:
- `oracle_clip_failures_total{type="ffmpeg"}`
- `oracle_clip_failures_total{type="storage"}`
- `oracle_clip_failures_total{type="webhook"}`
- `oracle_clip_failures_total{type="rate_limit"}`
- `oracle_clip_failures_total{type="auth"}`
- `oracle_clip_failures_total{type="tenant_isolation"}`

### Diagnostics Matrix
| Symptom | Probable Cause | Action |
| :--- | :--- | :--- |
| HTTP 401 Unauthorized | Missing / invalid API key or header `X-API-Key` | Validate tenant key in secret store |
| HTTP 403 Forbidden | Tenant isolation violation | Ensure tenant token matches requested `tenant_id` |
| HTTP 429 Too Many Requests | Rate limit bucket exhausted | Verify tenant RPM config or scale limits |
| HTTP 503 Dependency Unavailable | FFmpeg or storage offline | Check `/ready` output to identify missing binary/volume |
| Render fails with `RenderingError` | Corrupted media source or bad timestamps | Validate input video with `ffprobe` and check spec boundaries |

## 3. Secret Redaction Guarantee
Structured logs automatically scrub and redact all sensitive keys (`api_key`, `secret`, `authorization`, `token`, `password`, `signature`). Never disable logging filters in production.
