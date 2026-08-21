import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  ConfigSummaryResponse,
  MetricsResponse,
  ReadinessResponse,
  api,
} from '../api/client';
import { AuditLogEntry } from '../types';

const MAX_LOG_ENTRIES = 200;

function timestamp(): string {
  return new Date().toISOString().replace('T', ' ').substring(0, 19);
}

let logSeq = 0;
function entry(category: AuditLogEntry['category'], message: string, tenantId?: string): AuditLogEntry {
  logSeq += 1;
  return { id: `log-${Date.now()}-${logSeq}`, timestamp: timestamp(), category, message, tenantId };
}

export interface EngineStatus {
  readiness: ReadinessResponse | null;
  metrics: MetricsResponse | null;
  config: ConfigSummaryResponse | null;
  readinessLatencyMs: number | null;
  metricsLatencyMs: number | null;
  isProbing: boolean;
  lastError: string | null;
  lastProbeAt: string | null;
  logs: AuditLogEntry[];
  probe: () => Promise<void>;
  appendLog: (category: AuditLogEntry['category'], message: string, tenantId?: string) => void;
}

/**
 * Polls the media service for its real state (readiness probe, telemetry and
 * sanitized configuration) and turns each probe into audit-log activity. The
 * "busy engine" visuals in the UI are driven exclusively by this state.
 */
export function useEngineStatus(pollIntervalMs = 10000): EngineStatus {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [config, setConfig] = useState<ConfigSummaryResponse | null>(null);
  const [readinessLatencyMs, setReadinessLatencyMs] = useState<number | null>(null);
  const [metricsLatencyMs, setMetricsLatencyMs] = useState<number | null>(null);
  const [isProbing, setIsProbing] = useState<boolean>(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastProbeAt, setLastProbeAt] = useState<string | null>(null);
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const inFlight = useRef<boolean>(false);

  const pushLogs = useCallback((newEntries: AuditLogEntry[]) => {
    if (newEntries.length === 0) return;
    setLogs((prev) => [...newEntries, ...prev].slice(0, MAX_LOG_ENTRIES));
  }, []);

  const appendLog = useCallback(
    (category: AuditLogEntry['category'], message: string, tenantId?: string) => {
      pushLogs([entry(category, message, tenantId)]);
    },
    [pushLogs]
  );

  const probe = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setIsProbing(true);
    const collected: AuditLogEntry[] = [];

    try {
      const ready = await api.readiness();
      setReadiness(ready.data);
      setReadinessLatencyMs(Math.round(ready.durationMs * 10) / 10);
      const degraded = ready.data.status !== 'ready';
      collected.push(
        entry(
          degraded ? 'WARN' : 'OK',
          `GET /ready -> ${ready.data.status.toUpperCase()} in ${ready.durationMs.toFixed(1)}ms ` +
            `(environment=${ready.data.environment}, checks=${Object.keys(ready.data.checks).length})`
        )
      );
      const notReady = Object.entries(ready.data.checks)
        .filter(([, value]) => value && value.ready === false)
        .map(([name]) => name);
      if (notReady.length > 0) {
        collected.push(entry('WARN', `Dependency probes not ready: ${notReady.join(', ')}`));
      }
      setLastError(null);
    } catch (e) {
      const err = e as ApiError;
      setReadiness(null);
      setLastError(err.message);
      collected.push(entry('WARN', `GET /ready failed: ${err.message}`));
    }

    try {
      const telemetry = await api.metrics();
      setMetrics(telemetry.data);
      setMetricsLatencyMs(Math.round(telemetry.durationMs * 10) / 10);
      collected.push(
        entry(
          'AUTH',
          `X-API-Key accepted on /v1/metrics — ${telemetry.data.requests.total} requests served, ` +
            `${telemetry.data.jobs.completed} render jobs completed, p95 ${telemetry.data.requests.p95_latency_ms.toFixed(1)}ms`
        )
      );
    } catch (e) {
      const err = e as ApiError;
      setMetrics(null);
      collected.push(
        entry(err.status === 401 ? 'AUTH' : 'WARN', `GET /v1/metrics failed (${err.status}): ${err.message}`)
      );
    }

    try {
      const summary = await api.configSummary();
      setConfig(summary.data);
      collected.push(
        entry(
          'SEC',
          `Config sealed: env=${summary.data.environment}, storage=${summary.data.storage_backend}, ` +
            `asr=${summary.data.asr_provider}, clip=${summary.data.clip_provider}, ` +
            `webhook_secret=${summary.data.webhook_secret_configured ? 'configured' : 'absent'}`,
          summary.data.configured_tenants[0]
        )
      );
    } catch (e) {
      const err = e as ApiError;
      setConfig(null);
      collected.push(entry('WARN', `GET /v1/config/summary failed (${err.status}): ${err.message}`));
    }

    pushLogs(collected);
    setLastProbeAt(timestamp());
    setIsProbing(false);
    inFlight.current = false;
  }, [pushLogs]);

  useEffect(() => {
    void probe();
    if (pollIntervalMs <= 0) return;
    const handle = window.setInterval(() => void probe(), pollIntervalMs);
    return () => window.clearInterval(handle);
  }, [probe, pollIntervalMs]);

  return {
    readiness,
    metrics,
    config,
    readinessLatencyMs,
    metricsLatencyMs,
    isProbing,
    lastError,
    lastProbeAt,
    logs,
    probe,
    appendLog,
  };
}
