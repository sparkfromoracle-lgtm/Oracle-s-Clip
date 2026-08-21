import React from 'react';
import { ConfigSummaryResponse, MetricsResponse, ReadinessResponse } from '../api/client';
import { Activity, ShieldCheck, Terminal, Cpu } from 'lucide-react';

interface MetricsBarProps {
  metrics: MetricsResponse | null;
  readiness: ReadinessResponse | null;
  config: ConfigSummaryResponse | null;
  isProbing: boolean;
  onCardClick?: (metric: string) => void;
}

const CARD =
  'bg-slate-900/40 p-4 rounded-xl border border-slate-800 hover:border-slate-700 transition-all cursor-pointer group';

export const MetricsBar: React.FC<MetricsBarProps> = ({ metrics, readiness, config, isProbing, onCardClick }) => {
  const requests = metrics?.requests;
  const jobs = metrics?.jobs;
  const ffmpegCheck = readiness?.checks?.ffmpeg as Record<string, unknown> | undefined;
  const ffmpegHealthy = ffmpegCheck?.healthy === true;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 shrink-0">
      {/* Live request telemetry */}
      <div onClick={() => onCardClick?.('requests')} className={CARD}>
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Requests Served</div>
          <Activity className={`w-4 h-4 text-emerald-500 ${isProbing ? 'animate-pulse' : ''}`} />
        </div>
        <div className="text-2xl font-mono text-emerald-500 font-bold tracking-tight">
          {requests ? requests.total : '—'}
          <span className="text-slate-600 text-sm font-normal">
            {requests ? ` / p95 ${requests.p95_latency_ms.toFixed(0)}ms` : ''}
          </span>
        </div>
        <div className="text-[10px] text-emerald-500/80 mt-1 font-mono flex items-center gap-1 font-medium">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          {requests
            ? `p50 ${requests.p50_latency_ms.toFixed(1)}MS · ${Object.entries(requests.by_status)
                .map(([code, count]) => `${code}×${count}`)
                .join(' ')}`
            : 'TELEMETRY UNAVAILABLE'}
        </div>
      </div>

      {/* Render pipeline throughput */}
      <div onClick={() => onCardClick?.('jobs')} className={CARD}>
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Render Jobs</div>
          <Terminal className="w-4 h-4 text-slate-400" />
        </div>
        <div className="text-2xl font-mono text-white font-bold tracking-tight">
          {jobs ? `${jobs.completed}/${jobs.submitted}` : '—'}
          {jobs && jobs.failed > 0 && <span className="text-rose-400 text-sm font-normal"> · {jobs.failed} failed</span>}
        </div>
        <div className="text-[10px] text-slate-400 mt-1 font-mono">
          {jobs ? `P50 RENDER ${jobs.p50_render_duration_ms.toFixed(1)}MS` : 'NO JOB TELEMETRY'}
        </div>
      </div>

      {/* Tenant / auth context */}
      <div onClick={() => onCardClick?.('tenant')} className={CARD}>
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Tenant Context</div>
          <ShieldCheck className="w-4 h-4 text-indigo-400" />
        </div>
        <div className="text-2xl font-mono text-indigo-400 font-bold tracking-tight">
          {config ? (config.configured_tenants[0] ?? 'NONE') : '—'}
        </div>
        <div className="text-[10px] text-slate-400 mt-1 font-mono">
          {config
            ? `${config.api_keys_count} KEY(S) · WEBHOOK ${config.webhook_secret_configured ? 'SIGNED' : 'UNSET'}`
            : 'AUTH CONTEXT UNKNOWN'}
        </div>
      </div>

      {/* Media engine / provider configuration */}
      <div onClick={() => onCardClick?.('ffmpeg')} className={CARD}>
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Media Engine</div>
          <Cpu className="w-4 h-4 text-slate-500" />
        </div>
        <div
          className={`text-2xl font-mono font-bold tracking-tight ${
            ffmpegHealthy ? 'text-emerald-500' : 'text-amber-400'
          }`}
        >
          {readiness ? (ffmpegHealthy ? 'FFMPEG OK' : 'DEGRADED') : '—'}
        </div>
        <div className="text-[10px] text-slate-500 mt-1 font-mono">
          {config ? `ASR ${config.asr_provider.toUpperCase()} · CLIP ${config.clip_provider.toUpperCase()} · ${config.storage_backend.toUpperCase()}` : 'PROVIDERS UNKNOWN'}
        </div>
      </div>
    </div>
  );
};
