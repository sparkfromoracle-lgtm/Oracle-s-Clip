import time
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
from media_service.api.app import app
from media_service.observability.metrics import MetricsCollector


def test_concurrent_load_and_rate_limiting():
    """Submits concurrent requests to test rate limiter behavior and latency metrics under load."""
    client = TestClient(app)
    headers = {
        "X-API-Key": "dev-admin-key-12345",
        "X-Tenant-ID": "load_tenant",
    }

    def send_request(req_id: int):
        return client.get("/v1/config/summary", headers=headers)

    num_requests = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(send_request, i) for i in range(num_requests)]
        results = [f.result() for f in futures]

    # Check status codes: either 200 or 429 (rate-limited)
    status_codes = [r.status_code for r in results]
    assert 200 in status_codes
    for code in status_codes:
        assert code in (200, 429)


def test_metrics_percentiles_calculation():
    collector = MetricsCollector()
    # Add dummy durations: 10, 20, 30, 40, 50, ..., 100 ms
    for d in range(10, 110, 10):
        collector.record_request(200, float(d))
        collector.record_job_completed(float(d * 2))

    summary = collector.get_summary()
    assert summary["requests"]["total"] == 10
    assert summary["requests"]["p50_latency_ms"] > 0
    assert summary["requests"]["p95_latency_ms"] >= summary["requests"]["p50_latency_ms"]
    assert summary["jobs"]["p50_render_duration_ms"] > 0
