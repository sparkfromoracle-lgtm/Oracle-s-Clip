import React, { useEffect, useState, useCallback } from 'react';
import { ShieldCheck } from 'lucide-react';
import { api, ApiError, EngineReadinessResponse } from '../../api/client';

const STATUS_STYLES: Record<string, { dot: string; text: string; bg: string }> = {
  ready: { dot: 'bg-emerald-500', text: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  warning: { dot: 'bg-amber-500', text: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' },
  blocked: { dot: 'bg-rose-500', text: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/20' },
};

const LABELS: Record<string, string> = {
  engine: 'ENGINE',
  renderer: 'RENDERER',
  storage: 'STORAGE',
  workers: 'WORKERS',
  publishing: 'PUBLISHING',
  compliance: 'COMPLIANCE',
  export: 'EXPORT',
};

const ORDER = ['engine', 'renderer', 'storage', 'workers', 'publishing', 'compliance', 'export'];

/**
 * ProductionReadiness — compact status panel using real system information.
 *
 * Each subsystem displays READY, WARNING, or BLOCKED — never hard-coded. The
 * data comes from /v1/engine/readiness which probes the actual runtime.
 */
export const ProductionReadiness: React.FC = () => {
  const [data, setData] = useState<EngineReadinessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const poll = useCallback(async () => {
    try {
      const res = await api.engineReadiness();
      setData(res.data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'readiness unreachable');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void poll();
    const timer = setInterval(() => void poll(), 10000);
    return () => clearInterval(timer);
  }, [poll]);

  const overall = data?.overall ?? 'blocked';
  const overallStyle = STATUS_STYLES[overall] ?? STATUS_STYLES.blocked;

  return (
    <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <ShieldCheck className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-semibold text-slate-200">Production Readiness</h3>
        <span className={`text-[10px] font-mono font-bold ml-auto flex items-center gap-1.5 ${overallStyle.text}`}>
          <span className={`w-2 h-2 rounded-full ${overallStyle.dot}`} />
          {overall.toUpperCase()}
        </span>
      </div>

      {error && <p className="text-[11px] font-mono text-rose-400">{error}</p>}

      {loading && !data && <p className="text-[11px] font-mono text-slate-500">Checking…</p>}

      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {ORDER.map((key) => {
            const check = data.checks[key];
            if (!check) return null;
            const style = STATUS_STYLES[check.status] ?? STATUS_STYLES.blocked;
            return (
              <div key={key} className={`flex flex-col gap-1 px-2.5 py-2 rounded border ${style.bg}`}>
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                  <span className="text-[9px] font-mono font-bold text-slate-400 tracking-wider">{LABELS[key] ?? key.toUpperCase()}</span>
                </div>
                <span className={`text-[10px] font-mono font-bold ${style.text}`}>{check.status.toUpperCase()}</span>
                <span className="text-[8px] font-mono text-slate-600 leading-tight">{check.detail}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
