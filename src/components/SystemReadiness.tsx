import React from 'react';
import { ReadinessCheck } from '../types';
import { ReadinessResponse } from '../api/client';
import { Activity, RefreshCw } from 'lucide-react';

interface SystemReadinessProps {
  readiness: ReadinessResponse | null;
  latencyMs: number | null;
  isProbing: boolean;
  error: string | null;
  onRunProbe: () => void;
}

/** Turns the API's /ready payload into display rows. No synthetic values. */
function toChecks(readiness: ReadinessResponse | null): ReadinessCheck[] {
  if (!readiness) return [];
  return Object.entries(readiness.checks).map(([id, raw]) => {
    const check = raw as Record<string, unknown>;
    const ready = check.ready !== false && check.healthy !== false;
    const detailPairs = Object.entries(check)
      .filter(([key]) => key !== 'ready')
      .map(([key, value]) => `${key}=${String(value)}`);
    const path =
      (check.path as string) ||
      (check.base_dir as string) ||
      (check.bucket as string) ||
      (check.provider as string) ||
      (check.backend as string) ||
      id;
    return {
      id,
      name: id.replace(/_/g, ' ').toUpperCase(),
      path: String(path),
      status: ready ? 'healthy' : 'warning',
      latencyMs: 0,
      details: detailPairs.join(' · ') || 'no details reported',
    };
  });
}

export const SystemReadiness: React.FC<SystemReadinessProps> = ({
  readiness,
  latencyMs,
  isProbing,
  error,
  onRunProbe,
}) => {
  const checks = toChecks(readiness);
  const degraded = readiness ? readiness.status !== 'ready' : true;

  return (
    <div className="flex flex-col bg-[#0f172a] rounded-2xl border border-slate-800 overflow-hidden h-full">
      <div className="px-4 py-3 border-b border-slate-800 flex justify-between items-center bg-slate-900/40 shrink-0">
        <div className="flex items-center gap-2">
          <Activity className={`w-3.5 h-3.5 ${degraded ? 'text-amber-400' : 'text-emerald-400'} ${isProbing ? 'animate-pulse' : ''}`} />
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            System Readiness
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`text-[9px] font-mono font-bold px-2 py-0.5 rounded border ${
              !readiness
                ? 'text-rose-400 bg-rose-950/40 border-rose-800/40'
                : degraded
                ? 'text-amber-400 bg-amber-950/40 border-amber-800/40'
                : 'text-emerald-400 bg-emerald-950/40 border-emerald-800/40'
            }`}
          >
            {!readiness ? 'UNREACHABLE' : readiness.status.toUpperCase()}
          </span>
          <button
            onClick={onRunProbe}
            disabled={isProbing}
            className="text-slate-400 hover:text-slate-200 transition-colors p-1 rounded hover:bg-slate-800"
            title="Re-run readiness probe (GET /ready)"
          >
            <RefreshCw className={`w-3 h-3 ${isProbing ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </div>

      <div className="p-4 space-y-4 overflow-y-auto flex-1">
        {checks.length === 0 && (
          <div className="text-[11px] font-mono text-rose-400/90 italic">
            {error || 'Waiting for the first readiness probe...'}
          </div>
        )}
        {checks.map((check) => (
          <div key={check.id} className="flex items-center gap-3 p-1.5 rounded hover:bg-slate-900/30 transition-colors">
            <div
              className={`w-2 h-2 rounded-full shrink-0 ${
                check.status === 'healthy' ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-amber-500'
              }`}
            />
            <div className="flex-1 flex flex-col min-w-0">
              <div className="text-xs text-slate-200 font-medium truncate">{check.name}</div>
              <div className="text-[10px] text-slate-500 truncate" title={check.details}>
                {check.details}
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-[10px] font-mono text-slate-400 italic bg-slate-950 px-2 py-0.5 rounded border border-slate-800/80 max-w-[180px] truncate">
                {check.path}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="px-4 py-2.5 bg-slate-950/60 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-500 shrink-0">
        <span className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${readiness ? (degraded ? 'bg-amber-500' : 'bg-emerald-500') : 'bg-rose-500'}`}></span>
          <span>
            {readiness
              ? `GET /ready → ${readiness.status.toUpperCase()} · ${checks.length} PROBES`
              : 'GET /ready → NO RESPONSE'}
          </span>
        </span>
        <span className="text-indigo-400 font-semibold">
          {latencyMs !== null ? `${latencyMs}ms` : '—'}
        </span>
      </div>
    </div>
  );
};
