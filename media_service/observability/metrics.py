import time
import threading
import resource
import shutil
import os
from typing import Dict, Any, List


class MetricsCollector:
    """Production metrics collector tracking request latency, job counts,
    rendering durations, errors, and system resource telemetry using Python standard library.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Counters
        self.request_count: int = 0
        self.request_status_counts: Dict[int, int] = {}
        self.jobs_submitted: int = 0
        self.jobs_completed: int = 0
        self.jobs_failed: int = 0
        self.ffmpeg_failures: int = 0
        self.storage_failures: int = 0
        self.webhook_failures: int = 0
        self.webhook_retries: int = 0
        self.rate_limit_events: int = 0
        self.auth_failures: int = 0
        self.tenant_isolation_violations: int = 0
        
        # Histograms / latencies (stored as samples)
        self.request_durations_ms: List[float] = []
        self.render_durations_ms: List[float] = []
        self.max_samples = 1000

    def record_request(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self.request_count += 1
            self.request_status_counts[status_code] = self.request_status_counts.get(status_code, 0) + 1
            self.request_durations_ms.append(duration_ms)
            if len(self.request_durations_ms) > self.max_samples:
                self.request_durations_ms.pop(0)

    def record_job_submitted(self) -> None:
        with self._lock:
            self.jobs_submitted += 1

    def record_job_completed(self, duration_ms: float) -> None:
        with self._lock:
            self.jobs_completed += 1
            self.render_durations_ms.append(duration_ms)
            if len(self.render_durations_ms) > self.max_samples:
                self.render_durations_ms.pop(0)

    def record_job_failed(self) -> None:
        with self._lock:
            self.jobs_failed += 1

    def record_ffmpeg_failure(self) -> None:
        with self._lock:
            self.ffmpeg_failures += 1

    def record_storage_failure(self) -> None:
        with self._lock:
            self.storage_failures += 1

    def record_webhook_failure(self) -> None:
        with self._lock:
            self.webhook_failures += 1

    def record_webhook_retry(self) -> None:
        with self._lock:
            self.webhook_retries += 1

    def record_rate_limit(self) -> None:
        with self._lock:
            self.rate_limit_events += 1

    def record_auth_failure(self) -> None:
        with self._lock:
            self.auth_failures += 1

    def record_tenant_isolation_violation(self) -> None:
        with self._lock:
            self.tenant_isolation_violations += 1

    @staticmethod
    def _calculate_percentile(samples: List[float], percentile: float) -> float:
        if not samples:
            return 0.0
        sorted_samples = sorted(samples)
        k = (len(sorted_samples) - 1) * (percentile / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_samples) - 1)
        d = k - f
        return sorted_samples[f] * (1.0 - d) + sorted_samples[c] * d

    def get_system_telemetry(self) -> Dict[str, Any]:
        """Collects current host/process memory and disk telemetry."""
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # maxrss is in kilobytes on Linux
        memory_rss_bytes = rusage.ru_maxrss * 1024
        disk_usage = shutil.disk_usage("/")
        disk_percent = round((disk_usage.used / disk_usage.total) * 100.0, 2) if disk_usage.total > 0 else 0.0
        return {
            "process_memory_max_rss_bytes": memory_rss_bytes,
            "user_cpu_time_seconds": round(rusage.ru_utime, 3),
            "system_cpu_time_seconds": round(rusage.ru_stime, 3),
            "disk_free_bytes": disk_usage.free,
            "disk_total_bytes": disk_usage.total,
            "disk_usage_percent": disk_percent,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Returns structured JSON summary of metrics and latency percentiles."""
        with self._lock:
            req_samples = list(self.request_durations_ms)
            render_samples = list(self.render_durations_ms)

            summary = {
                "requests": {
                    "total": self.request_count,
                    "by_status": dict(self.request_status_counts),
                    "p50_latency_ms": round(self._calculate_percentile(req_samples, 50), 2),
                    "p95_latency_ms": round(self._calculate_percentile(req_samples, 95), 2),
                    "p99_latency_ms": round(self._calculate_percentile(req_samples, 99), 2),
                },
                "jobs": {
                    "submitted": self.jobs_submitted,
                    "completed": self.jobs_completed,
                    "failed": self.jobs_failed,
                    "p50_render_duration_ms": round(self._calculate_percentile(render_samples, 50), 2),
                    "p95_render_duration_ms": round(self._calculate_percentile(render_samples, 95), 2),
                    "p99_render_duration_ms": round(self._calculate_percentile(render_samples, 99), 2),
                },
                "failures": {
                    "ffmpeg_failures": self.ffmpeg_failures,
                    "storage_failures": self.storage_failures,
                    "webhook_failures": self.webhook_failures,
                    "webhook_retries": self.webhook_retries,
                    "rate_limit_events": self.rate_limit_events,
                    "auth_failures": self.auth_failures,
                    "tenant_isolation_violations": self.tenant_isolation_violations,
                },
                "system": self.get_system_telemetry(),
            }
            return summary

    def to_prometheus_format(self) -> str:
        """Renders metrics in Prometheus text exposition format."""
        summary = self.get_summary()
        lines = [
            "# HELP oracle_clip_requests_total Total HTTP requests handled",
            "# TYPE oracle_clip_requests_total counter",
            f"oracle_clip_requests_total {summary['requests']['total']}",
            "# HELP oracle_clip_jobs_submitted_total Total render jobs submitted",
            "# TYPE oracle_clip_jobs_submitted_total counter",
            f"oracle_clip_jobs_submitted_total {summary['jobs']['submitted']}",
            "# HELP oracle_clip_jobs_completed_total Total render jobs completed successfully",
            "# TYPE oracle_clip_jobs_completed_total counter",
            f"oracle_clip_jobs_completed_total {summary['jobs']['completed']}",
            "# HELP oracle_clip_jobs_failed_total Total render jobs failed",
            "# TYPE oracle_clip_jobs_failed_total counter",
            f"oracle_clip_jobs_failed_total {summary['jobs']['failed']}",
            "# HELP oracle_clip_request_duration_ms_p50 P50 request latency in milliseconds",
            "# TYPE oracle_clip_request_duration_ms_p50 gauge",
            f"oracle_clip_request_duration_ms_p50 {summary['requests']['p50_latency_ms']}",
            "# HELP oracle_clip_request_duration_ms_p95 P95 request latency in milliseconds",
            "# TYPE oracle_clip_request_duration_ms_p95 gauge",
            f"oracle_clip_request_duration_ms_p95 {summary['requests']['p95_latency_ms']}",
            "# HELP oracle_clip_render_duration_ms_p50 P50 render duration in milliseconds",
            "# TYPE oracle_clip_render_duration_ms_p50 gauge",
            f"oracle_clip_render_duration_ms_p50 {summary['jobs']['p50_render_duration_ms']}",
            "# HELP oracle_clip_failures_total Total failure counts by type",
            "# TYPE oracle_clip_failures_total counter",
            f'oracle_clip_failures_total{{type="ffmpeg"}} {summary["failures"]["ffmpeg_failures"]}',
            f'oracle_clip_failures_total{{type="storage"}} {summary["failures"]["storage_failures"]}',
            f'oracle_clip_failures_total{{type="webhook"}} {summary["failures"]["webhook_failures"]}',
            f'oracle_clip_failures_total{{type="rate_limit"}} {summary["failures"]["rate_limit_events"]}',
            f'oracle_clip_failures_total{{type="auth"}} {summary["failures"]["auth_failures"]}',
            f'oracle_clip_failures_total{{type="tenant_isolation"}} {summary["failures"]["tenant_isolation_violations"]}',
        ]
        return "\n".join(lines) + "\n"


# Global metrics collector instance
metrics_collector = MetricsCollector()
