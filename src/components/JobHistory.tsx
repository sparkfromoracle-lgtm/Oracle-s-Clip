import React, { useState, useCallback } from 'react';
import { History, Search, ChevronLeft, ChevronRight, Download, ExternalLink, AlertCircle } from 'lucide-react';
import type { HistoryResponse, RenderJobSummary, GoogleSheetsStatusResponse } from '../api/client';
import { api } from '../api/client';

interface JobHistoryProps {
  history: HistoryResponse | null;
  isLoading: boolean;
  error: string | null;
  googleStatus: GoogleSheetsStatusResponse | null;
  onRefresh: (params?: { status?: string; search?: string; limit?: number; offset?: number }) => Promise<void>;
}

const PAGE_SIZE = 20;

const STATUS_FILTERS = ['', 'completed', 'failed', 'cancelled'] as const;

function statusColor(status: string): string {
  switch (status) {
    case 'completed': return 'text-emerald-400';
    case 'failed': return 'text-rose-400';
    case 'cancelled': return 'text-amber-400';
    default: return 'text-slate-400';
  }
}

function formatTime(ts?: string | null): string {
  if (!ts) return '--';
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
}

function calcDuration(created?: string | null, completed?: string | null): string {
  if (!created || !completed) return '--';
  try {
    const ms = new Date(completed).getTime() - new Date(created).getTime();
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  } catch {
    return '--';
  }
}

export const JobHistory: React.FC<JobHistoryProps> = ({ history, isLoading, error, googleStatus, onRefresh }) => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [offset, setOffset] = useState(0);
  const [selectedJob, setSelectedJob] = useState<RenderJobSummary | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  const jobs = history?.jobs ?? [];
  const total = history?.total ?? 0;
  const counts = history?.counts ?? {};
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  const handleSearch = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
    void onRefresh({ search, status: statusFilter || undefined, limit: PAGE_SIZE, offset: 0 });
  }, [search, statusFilter, onRefresh]);

  const handleStatusFilter = (status: string) => {
    setStatusFilter(status);
    setOffset(0);
    void onRefresh({ search, status: status || undefined, limit: PAGE_SIZE, offset: 0 });
  };

  const handlePage = (dir: 'prev' | 'next') => {
    const newOffset = dir === 'prev' ? Math.max(0, offset - PAGE_SIZE) : offset + PAGE_SIZE;
    setOffset(newOffset);
    void onRefresh({ search, status: statusFilter || undefined, limit: PAGE_SIZE, offset: newOffset });
  };

  const handleExport = async () => {
    setExporting(true);
    setExportResult(null);
    try {
      const res = await api.exportToGoogleSheets();
      const r = res.data.result;
      if (r.status === 'failed') {
        setExportResult(`Export failed: ${r.errors.join(', ')}`);
      } else if (r.status === 'partial') {
        setExportResult(`Partially exported: ${r.exported} new, ${r.updated} updated, ${r.failed} failed`);
      } else {
        setExportResult(`Successfully exported: ${r.exported} new, ${r.updated} updated`);
      }
    } catch (e) {
      setExportResult(`Export error: ${(e as Error).message}`);
    } finally {
      setExporting(false);
      void onRefresh({ search, status: statusFilter || undefined, limit: PAGE_SIZE, offset });
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900/40 border border-slate-800 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/60">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-200">Render Job History</h3>
          <span className="text-[10px] font-mono text-slate-500">({total} total)</span>
        </div>

        {/* Summary counts */}
        <div className="flex items-center gap-3 text-[10px] font-mono">
          {['completed', 'failed', 'cancelled'].map((s) => (
            <span key={s} className={`${statusColor(s)}`}>
              {s.toUpperCase()}: {counts[s] ?? 0}
            </span>
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-slate-800/60 bg-slate-950/30">
        <form onSubmit={handleSearch} className="flex items-center gap-1.5">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by Job ID..."
              className="w-44 pl-7 pr-2 py-1 text-xs font-mono bg-slate-900 border border-slate-700 rounded text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <button type="submit" className="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded text-slate-300 transition-colors">
            Search
          </button>
        </form>

        <div className="flex items-center gap-1">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => handleStatusFilter(s)}
              className={`px-2 py-1 text-[10px] font-mono rounded border transition-colors ${
                statusFilter === s
                  ? 'bg-indigo-600 border-indigo-500 text-white'
                  : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'
              }`}
            >
              {s ? s.toUpperCase() : 'ALL'}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        {/* Google Sheets Export */}
        <button
          onClick={handleExport}
          disabled={exporting || !googleStatus?.configured}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-600/40 rounded text-emerald-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title={googleStatus?.configured ? (googleStatus.authorized ? 'Export completed jobs to Google Sheets' : 'Google Sheets configured but not authorized') : 'Google Sheets not configured'}
        >
          {exporting ? <History className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
          <span>Export to Sheets</span>
        </button>
      </div>

      {/* Export result banner */}
      {exportResult && (
        <div className={`flex items-center gap-2 px-4 py-2 text-xs ${exportResult.startsWith('Export failed') || exportResult.startsWith('Export error') ? 'text-rose-400 bg-rose-950/30' : 'text-emerald-400 bg-emerald-950/30'}`}>
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span>{exportResult}</span>
          <button onClick={() => setExportResult(null)} className="ml-auto text-slate-500 hover:text-slate-300">×</button>
        </div>
      )}

      {/* Job list */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="flex items-center gap-2 px-4 py-3 text-rose-400 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {!error && isLoading && jobs.length === 0 && (
          <div className="flex items-center justify-center h-full text-slate-600 text-xs py-12">
            Loading history...
          </div>
        )}
        {!error && !isLoading && jobs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600 py-12">
            <History className="w-8 h-8 opacity-30" />
            <span className="text-xs font-mono">No completed jobs in history</span>
            <span className="text-[10px] text-slate-700">Render jobs will appear here after completion</span>
          </div>
        )}
        {jobs.map((job) => (
          <button
            key={job.job_id}
            onClick={() => setSelectedJob(selectedJob?.job_id === job.job_id ? null : job)}
            className={`w-full text-left flex items-center gap-3 px-4 py-2.5 border-b border-slate-800/60 transition-colors ${
              selectedJob?.job_id === job.job_id ? 'bg-indigo-950/40' : 'hover:bg-slate-800/30'
            }`}
          >
            <div className={`w-2 h-2 rounded-full shrink-0 ${
              job.status === 'completed' ? 'bg-emerald-500' :
              job.status === 'failed' ? 'bg-rose-500' : 'bg-amber-500'
            }`} />
            <div className="flex-1 min-w-0">
              <div className="font-mono text-xs text-slate-200 truncate">{job.job_id}</div>
              <div className="text-[10px] text-slate-500 truncate">
                {job.spec?.target_aspect_ratio ?? '9:16'} · {formatTime(job.created_at)}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span className="text-[10px] font-mono text-slate-500">{calcDuration(job.created_at, job.completed_at)}</span>
              <span className={`text-[10px] font-mono font-semibold ${statusColor(job.status)}`}>
                {job.status.toUpperCase()}
              </span>
              {job.google_sheet_exported_at && (
                <ExternalLink className="w-3 h-3 text-emerald-500" title="Exported to Google Sheets" />
              )}
            </div>
          </button>
        ))}
      </div>

      {/* Detail panel */}
      {selectedJob && (
        <div className="border-t border-slate-800 bg-slate-950/50 px-4 py-3">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Job Details</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <div><span className="text-slate-500">Job ID:</span> <span className="font-mono text-slate-200">{selectedJob.job_id}</span></div>
            <div><span className="text-slate-500">Status:</span> <span className={`font-mono ${statusColor(selectedJob.status)}`}>{selectedJob.status}</span></div>
            <div><span className="text-slate-500">Started:</span> <span className="font-mono text-slate-300">{formatTime(selectedJob.created_at)}</span></div>
            <div><span className="text-slate-500">Completed:</span> <span className="font-mono text-slate-300">{formatTime(selectedJob.completed_at)}</span></div>
            <div><span className="text-slate-500">Duration:</span> <span className="font-mono text-slate-300">{calcDuration(selectedJob.created_at, selectedJob.completed_at)}</span></div>
            <div><span className="text-slate-500">Render Type:</span> <span className="font-mono text-slate-300">{selectedJob.spec?.target_aspect_ratio ?? '--'}</span></div>
            <div className="col-span-2"><span className="text-slate-500">Output:</span> <span className="font-mono text-slate-300 text-[11px] break-all">{selectedJob.output_path ?? '--'}</span></div>
            {selectedJob.error_message && (
              <div className="col-span-2"><span className="text-slate-500">Error:</span> <span className="font-mono text-rose-400 text-[11px] break-all">{selectedJob.error_message}</span></div>
            )}
            {selectedJob.google_sheet_exported_at && (
              <div className="col-span-2"><span className="text-slate-500">Exported:</span> <span className="font-mono text-emerald-400 text-[11px]">{formatTime(selectedJob.google_sheet_exported_at)}</span></div>
            )}
          </div>
        </div>
      )}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between px-4 py-2 border-t border-slate-800 bg-slate-900/60">
          <span className="text-[10px] font-mono text-slate-500">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handlePage('prev')}
              disabled={!hasPrev}
              className="p-1 rounded border border-slate-700 text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => handlePage('next')}
              disabled={!hasNext}
              className="p-1 rounded border border-slate-700 text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
