import React from 'react';
import { RotateCcw, X, AlertTriangle, CheckCircle2, ExternalLink } from 'lucide-react';
import { EngineJob } from '../../api/client';
import { stageStatuses, STAGE_STATUS_STYLES, StageStatus } from './stages';

const STATE_BADGE: Record<string, string> = {
  completed: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  failed: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  blocked: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  cancelled: 'text-slate-400 bg-slate-700/20 border-slate-700',
};

export interface JobBoardProps {
  jobs: EngineJob[];
  onRetry: (id: string) => void;
  onCancel: (id: string) => void;
}

export const JobBoard: React.FC<JobBoardProps> = ({ jobs, onRetry, onCancel }) => {
  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-6 text-center">
        <p className="text-sm font-mono text-slate-500">No jobs. System is idle.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {jobs.map((job) => (
        <JobCard key={job.job_id} job={job} onRetry={onRetry} onCancel={onCancel} />
      ))}
    </div>
  );
};

const JobCard: React.FC<{ job: EngineJob; onRetry: (id: string) => void; onCancel: (id: string) => void }> = ({ job, onRetry, onCancel }) => {
  const stages = stageStatuses(job);
  const activeStage = stages.find((s) => s.status === 'active');
  const isTerminal = ['completed', 'failed', 'blocked', 'cancelled'].includes(job.state);
  const canRetry = job.state === 'failed' || job.state === 'blocked';
  const canCancel = !isTerminal;

  return (
    <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-3 flex flex-col gap-2.5">
      {/* header */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-mono font-bold text-slate-200">{job.job_id}</span>
        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${STATE_BADGE[job.state] ?? 'text-indigo-300 bg-indigo-500/10 border-indigo-500/20'}`}>
          {job.state.toUpperCase()}
        </span>
        {job.worker_id && (
          <span className="text-[10px] font-mono text-slate-500">▸ {job.worker_id}</span>
        )}
        {job.attempt > 0 && (
          <span className="text-[10px] font-mono text-amber-400">attempt {job.attempt + 1}</span>
        )}
        <span className="text-[10px] font-mono text-slate-600 ml-auto">{job.target_aspect_ratio}</span>
        {canCancel && (
          <button onClick={() => onCancel(job.job_id)} title="Cancel"
            className="text-slate-500 hover:text-rose-400 transition-colors">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        {canRetry && (
          <button onClick={() => onRetry(job.job_id)} title="Retry"
            className="text-slate-500 hover:text-indigo-400 transition-colors">
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* stage rail */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {stages.map(({ stage, status, progress }, i) => {
          const s = STAGE_STATUS_STYLES[status as StageStatus];
          return (
            <React.Fragment key={stage.key}>
              <div className={`flex flex-col items-center gap-1 px-2 py-1.5 rounded border ${s.bg} min-w-[64px]`}>
                <span className={`w-2 h-2 rounded-full ${s.dot}`} />
                <span className={`text-[9px] font-mono font-bold ${s.text}`}>{stage.short}</span>
                <span className="text-[8px] font-mono text-slate-600">{s.label}</span>
                {status === 'active' && progress != null && (
                  <span className="text-[9px] font-mono text-indigo-300">{progress.toFixed(0)}%</span>
                )}
              </div>
              {i < stages.length - 1 && <div className="w-2 h-px bg-slate-800 shrink-0" />}
            </React.Fragment>
          );
        })}
      </div>

      {/* footer details */}
      <div className="flex items-center gap-3 flex-wrap text-[10px] font-mono text-slate-500">
        {activeStage && (
          <span className="text-indigo-300">
            {activeStage.stage.label}
            {activeStage.stage.key === 'rendering' && activeStage.progress != null
              ? ` ${activeStage.progress.toFixed(0)}%`
              : ''}
          </span>
        )}
        {job.quality_verdict && <span>quality: {job.quality_verdict}</span>}
        {job.schedule_decision && <span>sched: {job.schedule_decision}</span>}
        {job.publish_status && <span>publish: {job.publish_status}</span>}
        {job.analytics_status && <span>analytics: {job.analytics_status}</span>}
        {job.post_url && (
          <a href={job.post_url} target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline flex items-center gap-0.5">
            post <ExternalLink className="w-2.5 h-2.5" />
          </a>
        )}
        {job.state === 'completed' && (
          <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> completed</span>
        )}
        {job.error_message && (
          <span className="text-rose-400 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> {job.error_message}</span>
        )}
      </div>
    </div>
  );
};
