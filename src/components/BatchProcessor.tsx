import React, { useState } from 'react';
import { Wand2, Loader2, AlertCircle, CheckCircle2, XCircle, Film, Download } from 'lucide-react';
import { api, TENANT_ID } from '../api/client';
import type { BatchProcessResponse } from '../api/client';

interface BatchClipResult {
  task_id: string;
  job_id?: string;
  status: string;
  error?: string;
  opportunity_score?: number;
  opportunity_reason?: string;
  output_path?: string;
  quality_verdict?: string;
  guardian_approved?: boolean;
}

export const BatchProcessor: React.FC = () => {
  const [sourcePath, setSourcePath] = useState('');
  const [durationMs, setDurationMs] = useState(60000);
  const [maxClips, setMaxClips] = useState(10);
  const [aspectRatio, setAspectRatio] = useState('9:16');
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<BatchProcessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleProcess = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sourcePath.trim()) {
      setError('Source media path is required.');
      return;
    }
    setProcessing(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.batchProcess({
        tenant_id: TENANT_ID || 'tenant_dev',
        source_media_path: sourcePath.trim(),
        duration_ms: durationMs,
        max_clips: maxClips,
        target_aspect_ratio: aspectRatio,
      });
      setResult(res.data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProcessing(false);
    }
  };

  const clips = (result?.clips ?? []) as BatchClipResult[];

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto">
      {/* Input form */}
      <form onSubmit={handleProcess} className="bg-slate-900/40 border border-slate-800 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-4">
          <Wand2 className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold text-slate-200">Autonomous Clip Generation</h3>
          <span className="text-[10px] font-mono text-slate-500">— analyze, select, render, quality-check</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="md:col-span-2">
            <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Source Video Path</label>
            <input
              type="text"
              value={sourcePath}
              onChange={(e) => setSourcePath(e.target.value)}
              placeholder="/tmp/input_video.mp4"
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-700 rounded text-slate-200 placeholder-slate-600 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Duration (ms)</label>
            <input
              type="number"
              value={durationMs}
              onChange={(e) => setDurationMs(Number(e.target.value))}
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-700 rounded text-slate-200 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Max Clips</label>
            <input
              type="number"
              value={maxClips}
              onChange={(e) => setMaxClips(Number(e.target.value))}
              min={1}
              max={50}
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-700 rounded text-slate-200 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Aspect Ratio</label>
            <select
              value={aspectRatio}
              onChange={(e) => setAspectRatio(e.target.value)}
              className="w-full px-3 py-2 text-xs font-mono bg-slate-950 border border-slate-700 rounded text-slate-200 focus:border-indigo-500 focus:outline-none"
            >
              <option value="9:16">9:16 (TikTok / Reels)</option>
              <option value="16:9">16:9 (YouTube)</option>
              <option value="1:1">1:1 (Square)</option>
              <option value="4:5">4:5 (Instagram)</option>
            </select>
          </div>
          <div className="flex items-end">
            <button
              type="submit"
              disabled={processing}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded text-white text-xs font-semibold transition-colors"
            >
              {processing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              <span>{processing ? 'PROCESSING...' : 'GENERATE CLIPS'}</span>
            </button>
          </div>
        </div>
      </form>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 text-rose-400 text-xs bg-rose-950/30 border border-rose-900/50 rounded-lg">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="bg-slate-900/40 border border-slate-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Film className="w-4 h-4 text-indigo-400" />
              <h3 className="text-sm font-semibold text-slate-200">Generated Clips</h3>
            </div>
            <div className="flex items-center gap-3 text-[10px] font-mono">
              <span className="text-emerald-400">{result.completed} completed</span>
              {result.failed > 0 && <span className="text-rose-400">{result.failed} failed</span>}
              <span className="text-slate-500">{result.total} total</span>
            </div>
          </div>

          <div className="space-y-2">
            {clips.map((clip, i) => (
              <div
                key={clip.task_id}
                className={`flex items-start gap-3 p-3 rounded-lg border ${
                  clip.status === 'completed'
                    ? 'border-emerald-800/40 bg-emerald-950/20'
                    : 'border-rose-800/40 bg-rose-950/20'
                }`}
              >
                <div className="shrink-0 mt-0.5">
                  {clip.status === 'completed' ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-400" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-slate-200">Clip {String(i + 1).padStart(2, '0')}</span>
                    <span className="text-[10px] font-mono text-slate-500">{clip.job_id}</span>
                  </div>
                  {clip.opportunity_reason && (
                    <div className="text-[10px] text-slate-400 mt-0.5">{clip.opportunity_reason}</div>
                  )}
                  {clip.opportunity_score !== undefined && (
                    <div className="text-[10px] text-indigo-400 font-mono mt-0.5">
                      Score: {clip.opportunity_score} · Quality: {clip.quality_verdict ?? '--'} · {clip.guardian_approved ? 'Approved' : 'Rejected'}
                    </div>
                  )}
                  {clip.output_path && (
                    <div className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">{clip.output_path}</div>
                  )}
                  {clip.error && (
                    <div className="text-[10px] text-rose-400 font-mono mt-0.5">{clip.error}</div>
                  )}
                </div>
                {clip.status === 'completed' && clip.output_path && (
                  <a
                    href={`${import.meta.env.VITE_API_URL || ''}/v1/render-jobs/${clip.job_id}`}
                    onClick={(e) => e.preventDefault()}
                    className="shrink-0 p-1.5 text-slate-500 hover:text-indigo-400 transition-colors"
                    title="Download clip"
                  >
                    <Download className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
