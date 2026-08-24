import React from 'react';
import { Cpu } from 'lucide-react';
import { EngineRoomState } from '../../hooks/useEngineRoom';
import { WORKER_STATE_STYLES } from './stages';

/**
 * WorkerGrid — renders the REAL worker threads registered in the engine.
 *
 * Architectural truth: the number of cards equals the configured worker count
 * (default 2). No fake workers. No CPU/GPU utilization is shown — those metrics
 * are not measured by the engine, so they are reported as N/A.
 */
export const WorkerGrid: React.FC<{ engine: EngineRoomState }> = ({ engine }) => {
  const workers = engine.system?.workers ?? [];

  if (workers.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-4">
        <p className="text-xs font-mono text-slate-500">No workers registered.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Cpu className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-semibold text-slate-200">Worker Pool</h3>
        <span className="text-[10px] font-mono text-slate-500 ml-auto">{workers.length} workers</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {workers.map((w) => {
          const style = WORKER_STATE_STYLES[w.state] ?? WORKER_STATE_STYLES.offline;
          return (
            <div key={w.worker_id} className="rounded border border-slate-800 bg-slate-900/40 p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono font-bold text-slate-300">{w.worker_id.toUpperCase()}</span>
                <span className={`flex items-center gap-1.5 text-[10px] font-mono ${style.text}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                  {style.label}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-1 text-[10px] font-mono">
                <Metric label="JOBS DONE" value={String(w.jobs_completed)} />
                <Metric label="JOBS FAILED" value={String(w.jobs_failed)} />
                <Metric label="CPU" value="N/A" />
                <Metric label="GPU" value="N/A" />
              </div>
              {w.current_job_id && (
                <div className="text-[10px] font-mono text-indigo-300 truncate">
                  ▸ {w.current_job_id}
                </div>
              )}
              <div className="flex gap-1.5">
                <button
                  onClick={() => void engine.stopWorker(w.worker_id)}
                  disabled={w.state === 'offline'}
                  className="flex-1 text-[10px] font-mono px-2 py-1 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 disabled:opacity-30"
                >
                  STOP
                </button>
                <button
                  onClick={() => void engine.startWorker(w.worker_id)}
                  disabled={w.state !== 'offline'}
                  className="flex-1 text-[10px] font-mono px-2 py-1 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 disabled:opacity-30"
                >
                  START
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-[10px] font-mono text-slate-600">
        CPU / GPU utilization: NOT MONITORED — the engine does not measure hardware telemetry.
      </p>
    </div>
  );
};

const Metric: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="flex justify-between px-1.5 py-1 rounded bg-slate-950/50">
    <span className="text-slate-600">{label}</span>
    <span className="text-slate-400">{value}</span>
  </div>
);
