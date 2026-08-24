/** Canonical stage definitions for the Engine Room.

The stage order mirrors the backend ``EngineJobState`` lifecycle exactly. The
UI never invents stages — it derives each stage's status from the job's real
persisted state.
*/

export interface StageDef {
  key: string;
  label: string;
  short: string;
}

// The full ordered pipeline. Publishing stages are conditional on the job
// requesting publication.
export const PIPELINE_STAGES: StageDef[] = [
  { key: 'created', label: 'Created', short: 'CRT' },
  { key: 'validating', label: 'Validating', short: 'VAL' },
  { key: 'queued', label: 'Queued', short: 'QUE' },
  { key: 'assigned', label: 'Assigned', short: 'ASG' },
  { key: 'processing', label: 'Processing', short: 'PRC' },
  { key: 'rendering', label: 'Rendering', short: 'RND' },
  { key: 'quality_check', label: 'Quality Check', short: 'QLT' },
  { key: 'rights_check', label: 'Rights Check', short: 'RGT' },
  { key: 'packaging', label: 'Packaging', short: 'PKG' },
  { key: 'scheduled', label: 'Scheduled', short: 'SCH' },
  { key: 'publishing', label: 'Publishing', short: 'PUB' },
  { key: 'published', label: 'Published', short: 'PSD' },
  { key: 'analyzing', label: 'Analytics', short: 'ANL' },
  { key: 'completed', label: 'Completed', short: 'DONE' },
];

export type StageStatus =
  | 'done'
  | 'active'
  | 'pending'
  | 'skipped'
  | 'blocked'
  | 'failed'
  | 'not_connected';

const ORDER = PIPELINE_STAGES.map((s) => s.key);

/**
 * Compute the real status of each pipeline stage for a job, from its persisted
 * state. No fabrication: progress is only "active %" when the backend reports
 * `progress_measurable`; otherwise the active stage shows ACTIVE.
 */
export function stageStatuses(job: {
  state: string;
  publish: number | boolean;
  progress: number;
  progress_measurable: number | boolean;
  publish_status: string | null;
  analytics_status: string | null;
  error_message: string | null;
}): { stage: StageDef; status: StageStatus; progress?: number }[] {
  const state = job.state;
  const wantsPublish = Boolean(job.publish);
  const stateIdx = ORDER.indexOf(state);
  const failed = state === 'failed';
  const cancelled = state === 'cancelled';
  const blocked = state === 'blocked';
  const terminal = state === 'completed';

  return PIPELINE_STAGES.map((stage) => {
    const idx = ORDER.indexOf(stage.key);

    // Publishing stages are skipped for non-publish jobs.
    if ((stage.key === 'publishing' || stage.key === 'published') && !wantsPublish) {
      return { stage, status: 'skipped' as StageStatus };
    }

    // Analytics stage: show not_connected when the backend reports it.
    if (stage.key === 'analyzing' && job.analytics_status === 'not_connected' && idx <= stateIdx) {
      return { stage, status: 'not_connected' as StageStatus };
    }

    if (cancelled) {
      return { stage, status: 'pending' as StageStatus };
    }

    if (failed) {
      // stages before the failure point are done; the failure is on the current
      // stage (the one that didn't complete). We mark the active-at-failure stage
      // as failed and later stages pending.
      if (idx < stateIdx) return { stage, status: 'done' as StageStatus };
      if (idx === stateIdx) return { stage, status: 'failed' as StageStatus };
      return { stage, status: 'pending' as StageStatus };
    }

    if (blocked) {
      // BLOCKED happens at publishing (no authorized account).
      if (stage.key === 'publishing') return { stage, status: 'blocked' as StageStatus };
      if (idx < stateIdx) return { stage, status: 'done' as StageStatus };
      return { stage, status: 'pending' as StageStatus };
    }

    if (terminal) {
      // Completed: real stages done; publishing stages reflect real publish_status.
      if (stage.key === 'publishing') {
        return { stage, status: (job.publish_status === 'published' ? 'done' : 'skipped') as StageStatus };
      }
      if (stage.key === 'published') {
        return { stage, status: (job.publish_status === 'published' ? 'done' : 'skipped') as StageStatus };
      }
      if (stage.key === 'analyzing') {
        return { stage, status: (job.analytics_status === 'not_connected' ? 'not_connected' : 'done') as StageStatus };
      }
      return { stage, status: 'done' as StageStatus };
    }

    // In-flight job.
    if (idx < stateIdx) return { stage, status: 'done' as StageStatus };
    if (idx === stateIdx) {
      const isActive = ['processing', 'rendering', 'quality_check', 'rights_check', 'packaging', 'scheduled', 'publishing', 'published', 'analyzing', 'assigned', 'queued', 'validating'].includes(stage.key);
      if (stage.key === 'rendering' && job.progress_measurable && job.progress > 0) {
        return { stage, status: 'active' as StageStatus, progress: job.progress };
      }
      return { stage, status: (isActive ? 'active' : 'active') as StageStatus };
    }
    return { stage, status: 'pending' as StageStatus };
  });
}

export const STAGE_STATUS_STYLES: Record<StageStatus, { dot: string; text: string; bg: string; label: string }> = {
  done: { dot: 'bg-emerald-500', text: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20', label: 'DONE' },
  active: { dot: 'bg-indigo-500 animate-pulse', text: 'text-indigo-300', bg: 'bg-indigo-500/10 border-indigo-500/30', label: 'ACTIVE' },
  pending: { dot: 'bg-slate-700', text: 'text-slate-600', bg: 'bg-slate-900/40 border-slate-800', label: 'PENDING' },
  skipped: { dot: 'bg-slate-700', text: 'text-slate-600', bg: 'bg-transparent border-slate-800 border-dashed', label: 'SKIPPED' },
  blocked: { dot: 'bg-amber-500', text: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30', label: 'BLOCKED' },
  failed: { dot: 'bg-rose-500', text: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/30', label: 'FAILED' },
  not_connected: { dot: 'bg-slate-600', text: 'text-slate-500', bg: 'bg-slate-900/40 border-slate-800', label: 'NOT CONNECTED' },
};

export const SYSTEM_STATE_STYLES: Record<string, { dot: string; text: string; label: string }> = {
  ready: { dot: 'bg-emerald-500', text: 'text-emerald-400', label: 'SYSTEM IDLE / READY' },
  active: { dot: 'bg-indigo-500 animate-pulse', text: 'text-indigo-300', label: 'SYSTEM ACTIVE' },
  degraded: { dot: 'bg-amber-500 animate-pulse', text: 'text-amber-400', label: 'SYSTEM DEGRADED' },
  paused: { dot: 'bg-slate-400', text: 'text-slate-300', label: 'SYSTEM PAUSED' },
  draining: { dot: 'bg-amber-500 animate-pulse', text: 'text-amber-400', label: 'SYSTEM DRAINING' },
  error: { dot: 'bg-rose-500', text: 'text-rose-400', label: 'SYSTEM ERROR' },
  offline: { dot: 'bg-rose-500', text: 'text-rose-400', label: 'SYSTEM OFFLINE' },
  starting: { dot: 'bg-indigo-500 animate-pulse', text: 'text-indigo-300', label: 'SYSTEM STARTING' },
  recovering: { dot: 'bg-amber-500 animate-pulse', text: 'text-amber-400', label: 'SYSTEM RECOVERING' },
  maintenance: { dot: 'bg-slate-400', text: 'text-slate-300', label: 'SYSTEM MAINTENANCE' },
};

export const WORKER_STATE_STYLES: Record<string, { dot: string; text: string; label: string }> = {
  idle: { dot: 'bg-emerald-500', text: 'text-emerald-400', label: 'IDLE' },
  busy: { dot: 'bg-indigo-500 animate-pulse', text: 'text-indigo-300', label: 'ACTIVE' },
  starting: { dot: 'bg-indigo-500 animate-pulse', text: 'text-indigo-300', label: 'STARTING' },
  error: { dot: 'bg-rose-500', text: 'text-rose-400', label: 'ERROR' },
  offline: { dot: 'bg-slate-600', text: 'text-slate-500', label: 'OFFLINE' },
};
