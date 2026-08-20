# Operational Runbook: Disaster Recovery & Backup

## 1. Recovery Objectives
- **RPO (Recovery Point Objective)**: < 5 minutes for job metadata; 0 minutes for object storage (using S3 cross-region replication).
- **RTO (Recovery Time Objective)**: < 15 minutes to complete cold cluster redeployment.

## 2. Backup Architecture
1. **Durable Job & Idempotency Stores**:
   - Automated SQLite hot backups run via `sqlite3.backup()` or cron snapshot.
   - Database WAL files and checkpoints synced to secondary cloud object storage bucket every 10 minutes.
2. **Media Output Artifacts**:
   - Stored in primary object storage bucket with multi-region replication.
   - Versioning enabled on destination bucket.

## 3. Disaster Recovery Execution Steps
1. **Infrastructure Provisioning**:
   - Re-deploy Kubernetes / container service stack in recovery region.
2. **Restore Persistence**:
   - Download latest job store backup:
     `aws s3 cp s3://oracle-clip-backups/jobs/latest.db /data/oracle_clip_jobs.db`
3. **Verify Integrity**:
   - Check SQLite database consistency:
     `sqlite3 /data/oracle_clip_jobs.db "PRAGMA integrity_check;"`
4. **Boot Service**:
   - Start media service with `ORACLE_CLIP_JOBS_DB=/data/oracle_clip_jobs.db`.
5. **Execute Smoke Suite**:
   - Run `pytest tests/test_phase1_smoke_suite.py` to confirm full end-to-end functionality.
