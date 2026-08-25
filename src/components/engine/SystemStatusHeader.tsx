import React from 'react';
import { Pause, Play, RefreshCw } from 'lucide-react';
import { EngineRoomState } from '../../hooks/useEngineRoom';
import { SYSTEM_STATE_STYLES } from './stages';

export const SystemStatusHeader: React.FC<{ engine: EngineRoomState }> = ({ engine }) => {
  const sys = engine.system;
  const stateKey = sys?.system_state ?? 'offline';
  const style = SYSTEM_STATE_STYLES[stateKey] ?? SYSTEM_STATE_STYLES.offline;
  const paused = sys?.paused ?? false;

  const counts: Record<string, number> = sys?.counts ?? {};
  const total = Object.values(counts).reduce((a: number, b: number) => a + b, 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${style.dot}`} />
          <h2 className={`text-lg font-bold font-mono tracking-wide ${style.text}`}>{style.label}</h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void (paused ? engine.resume() : engine.pause())}
            className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-mono px-2.5 py-1.5 rounded text-slate-300 transition-colors"
          >
            {paused ? <Play className="w-3.5 h-3.5 text-emerald-400" /> : <Pause className="w-3.5 h-3.5 text-amber-400" />}
            <span>{paused ? 'RESUME' : 'PAUSE'}</span>
          </button>
          <button
            onClick={() => engine.refresh()}
            className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-mono px-2.5 py-1.5 rounded text-slate-300 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5 text-indigo-400" />
            <span>REFRESH</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <Stat label="WORKERS" value={sys?.worker_count ?? 0} />
        <Stat label="ACTIVE JOBS" value={sys?.active_job_count ?? 0} />
        <Stat label="QUEUED" value={counts['queued'] ?? 0} />
        <Stat label="COMPLETED" value={counts['completed'] ?? 0} accent="text-emerald-400" />
        <Stat label="FAILED" value={counts['failed'] ?? 0} accent="text-rose-400" />
        <Stat label="BLOCKED" value={counts['blocked'] ?? 0} accent="text-amber-400" />
      </div>

      {engine.error && (
        <p className="text-[11px] font-mono text-rose-400">engine: {engine.error}</p>
      )}
      {total === 0 && !engine.error && (
        <p className="text-[11px] font-mono text-slate-500">
          No jobs in the system. Submit a production job to begin.
        </p>
      )}
    </div>
  );
};

const Stat: React.FC<{ label: string; value: number; accent?: string }> = ({ label, value, accent }) => (
  <div className="flex flex-col px-3 py-2 rounded border border-slate-800 bg-slate-900/40">
    <span className="text-[10px] font-mono text-slate-500 tracking-wider">{label}</span>
    <span className={`text-xl font-bold font-mono ${accent ?? 'text-slate-200'}`}>{value}</span>
  </div>
);
