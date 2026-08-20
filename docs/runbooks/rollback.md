# Operational Runbook: Rollback Procedures

## 1. Trigger Conditions
Initiate immediate automated or manual rollback if:
- `/ready` endpoint reports `status: not_ready` for > 3 consecutive probes.
- Rate of HTTP 5xx responses exceeds 0.5% of total requests over 3 minutes.
- FFmpeg render failure counter spikes continuously on `/metrics`.
- Process memory RSS or unhandled error rates violate SLOs.

## 2. Fast Rollback Execution
1. **Traffic Rerouting**: Switch ingress load balancer / proxy routing target immediately back to the previous stable revision.
2. **Persistence State Compatibility**:
   - `DurableJobStore` and `IdempotencyStore` schemas are append-friendly and backward-compatible with WAL mode.
   - No destructive database migration rollback is required.
3. **Verification**:
   - Check `GET /health` and `GET /ready` on the rolled-back revision.
   - Confirm traffic status codes normalized to HTTP 200 on Prometheus `/metrics`.
4. **Post-Incident**:
   - Capture container core dump / structured JSON logs.
   - Open P1 postmortem ticket.
