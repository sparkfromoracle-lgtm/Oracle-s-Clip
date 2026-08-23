import React from 'react';
import { Activity, Loader2, AlertCircle, CheckCircle2, XCircle, Clock } from 'lucide-react';
import type { ActiveJobsResponse, RenderJobSummary } from '../api/client';

interface ActiveJobsPanelProps {
  activeJobs: ActiveJobsResponse | null;
  error: string | null;
}

function statusBadge(status: string) {
  const map: Record<string, { color: string; bg: string; icon: React.ReactNode }> = {
    pending: { color: 'text-slate-300', bg: 'bg-slate-700/50', icon: <Clock className="w-3 h-3" /> },
    in_progress: { color: 'text-indigo-300', bg: 'bg-indigo-600/20', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    completed: { color: 'text-emerald-300', bg: 'bg-emerald-600/20', icon: <CheckCircle2 className="w-3 h-3" /> },
    failed: { color: 'text-rose-300', bg: 'bg-rose-600/20', icon: <XCircle className="w-3 h-3" /> },
    cancelled: { color: 'text-amber-300', bg: 'bg-amber-600/20', icon: <XCircle className="w-3 h-3" /> },
  };
  const s = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold ${s.color} ${s.bg}`}>
      {s.icon}
      {status.toUpperCase().replace('_', ' ')}
    </span>
  );
}

function formatElapsed(createdAt?: string | null): string {
  if (!createdAt) return '--';
  const start = new Date(createdAt).getTime();
  const elapsed = Date.now() - start;
  if (elapsed < 1000) return 'just now';
  const s = Math.floor(elapsed / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  return `${m}m ${rs}s`;
}

function JobRow({ job }: { job: RenderJobSummary }) {
  const source = job.spec?.source_media_id ?? '--';
  const renderType = job.spec?.target_aspect_ratio ?? '9:16';
  const output = job.output_path ?? '(pending)';

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
      <div className="w-28 shrink-0">
        {statusBadge(job.status)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-mono text-xs text-slate-200 truncate">{job.job_id}</div>
        <div className="text-[10px] text-slate-500 truncate">
          {renderType} · {source}
        </div>
      </div>
      <div className="w-32 shrink-0 text-right">
        <div className="text-[10px] text-slate-400 font-mono">{formatElapsed(job.created_at)}</div>
        <div className="text-[10px] text-slate-600 truncate">{output}</div>
      </div>
    </div>
  );
}

export const ActiveJobsPanel: React.FC<ActiveJobsPanelProps> = ({ activeJobs, error }) => {
  const jobs = activeJobs?.jobs ?? [];
  const count = activeJobs?.count ?? 0;

  return (
    <div className="flex flex-col h-full bg-slate-900/40 border border-slate-800 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/60">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-200">Active Render Jobs</h3>
          {count > 0 && (
            <span className="px-1.5 py-0.5 rounded bg-indigo-600/20 text-indigo-300 text-[10px] font-mono font-bold">
              {count}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${count > 0 ? 'bg-indigo-400 animate-pulse' : 'bg-slate-600'}`} />
          <span className="text-[10px] font-mono text-slate-500">{count > 0 ? 'LIVE' : 'IDLE'}</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="flex items-center gap-2 px-4 py-3 text-rose-400 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {!error && jobs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600 py-12">
            <Activity className="w-8 h-8 opacity-30" />
            <span className="text-xs font-mono">No active render jobs</span>
            <span className="text-[10px] text-slate-700">Jobs will appear here when processing starts</span>
          </div>
        )}
        {jobs.map((job) => (
          <div key={job.job_id}>
            <JobRow job={job} />
          </div>
        ))}
      </div>
    </div>
  );
};
