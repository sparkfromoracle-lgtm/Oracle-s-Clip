import React from 'react';
import { Terminal } from 'lucide-react';
import { EngineEvent } from '../../api/client';

const EVENT_TONE: Record<string, string> = {
  'job.created': 'text-slate-400',
  'job.queued': 'text-slate-300',
  'job.assigned': 'text-indigo-300',
  'job.processing': 'text-indigo-300',
  'job.rendering': 'text-indigo-300',
  'job.render_complete': 'text-indigo-300',
  'job.quality_check': 'text-cyan-300',
  'job.quality_checked': 'text-cyan-300',
  'job.rights_check': 'text-amber-300',
  'job.rights_checked': 'text-amber-300',
  'job.packaged': 'text-slate-300',
  'job.scheduled': 'text-slate-300',
  'job.schedule_decision': 'text-slate-300',
  'job.publishing': 'text-fuchsia-300',
  'job.published': 'text-emerald-300',
  'job.publish_blocked': 'text-amber-400',
  'job.analyzing': 'text-slate-400',
  'analytics.not_connected': 'text-slate-500',
  'job.completed': 'text-emerald-400',
  'job.failed': 'text-rose-400',
  'job.retry_requested': 'text-amber-300',
  'job.cancelled': 'text-slate-400',
  'job.cancel_requested': 'text-slate-400',
  'job.validation_failed': 'text-rose-400',
};

export const EventStream: React.FC<{ events: EngineEvent[] }> = ({ events }) => {
  return (
    <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-4 flex flex-col gap-2 h-full min-h-0">
      <div className="flex items-center gap-2 shrink-0">
        <Terminal className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-semibold text-slate-200">Event Stream</h3>
        <span className="text-[10px] font-mono text-slate-500 ml-auto">{events.length} events</span>
      </div>
      <div className="flex-1 overflow-y-auto font-mono text-[11px] flex flex-col gap-0.5 min-h-0">
        {events.length === 0 && (
          <p className="text-slate-600 py-4 text-center">No events yet.</p>
        )}
        {events.map((e) => (
          <div key={e.event_id} className="flex gap-2 py-0.5 border-b border-slate-900/60">
            <span className="text-slate-600 shrink-0">{e.timestamp.slice(11, 19)}</span>
            <span className={`shrink-0 ${EVENT_TONE[e.event_type] ?? 'text-slate-400'}`}>{e.event_type}</span>
            {e.worker_id && <span className="text-slate-600 shrink-0">[{e.worker_id}]</span>}
            {e.job_id && <span className="text-slate-700 truncate">{e.job_id.slice(0, 18)}</span>}
            {e.error && <span className="text-rose-400 truncate">err: {e.error.slice(0, 60)}</span>}
          </div>
        ))}
      </div>
    </div>
  );
};
