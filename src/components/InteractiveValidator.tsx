import React, { useState } from 'react';
import { Play, CheckCircle2, AlertOctagon, FileCheck, Film } from 'lucide-react';
import { ApiError, RenderJobResponse, TENANT_ID, api } from '../api/client';
import { AuditLogEntry } from '../types';

interface InteractiveValidatorProps {
  onActivity?: (category: AuditLogEntry['category'], message: string, tenantId?: string) => void;
}

type Stage = 'idle' | 'validating' | 'rendering' | 'done' | 'failed';

interface SegmentInput {
  start_ms: number;
  end_ms: number;
}

const DEFAULT_SEGMENTS = JSON.stringify(
  [
    { start_ms: 12500, end_ms: 34200 },
    { start_ms: 85000, end_ms: 110400 },
  ],
  null,
  2
);

/**
 * Executes the real backend pipeline: POST /v1/clip-specs/validate followed by
 * POST /v1/render-jobs. Every value shown below comes from the API response.
 */
export const InteractiveValidator: React.FC<InteractiveValidatorProps> = ({ onActivity }) => {
  const [tenantId, setTenantId] = useState<string>(TENANT_ID);
  const [sourceMediaId, setSourceMediaId] = useState<string>('media-raw-84920');
  const [sourceDurationMs, setSourceDurationMs] = useState<number>(300000);
  const [aspectRatio, setAspectRatio] = useState<'9:16' | '16:9' | '1:1'>('9:16');
  const [sourceMediaPath, setSourceMediaPath] = useState<string>('');
  const [segmentsText, setSegmentsText] = useState<string>(DEFAULT_SEGMENTS);

  const [stage, setStage] = useState<Stage>('idle');
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [jobResult, setJobResult] = useState<RenderJobResponse | null>(null);

  const busy = stage === 'validating' || stage === 'rendering';

  const handleRun = async () => {
    setStage('validating');
    setValidationErrors([]);
    setRequestError(null);
    setJobResult(null);

    let segments: SegmentInput[];
    try {
      const parsed = JSON.parse(segmentsText);
      if (!Array.isArray(parsed) || parsed.length === 0) throw new Error('segments must be a non-empty array');
      segments = parsed.map((s: Record<string, number>) => ({
        start_ms: Number(s.start_ms),
        end_ms: Number(s.end_ms),
        source_media_id: sourceMediaId,
      })) as SegmentInput[];
    } catch (e) {
      setValidationErrors([`Invalid segments JSON: ${(e as Error).message}`]);
      setStage('failed');
      return;
    }

    const specId = `spec-${Date.now()}`;
    const spec = {
      spec_id: specId,
      source_media_id: sourceMediaId,
      segments,
      schema_version: '1.0.0',
      version: 1,
      target_aspect_ratio: aspectRatio,
      status: 'draft',
      metadata: {},
    };

    try {
      const validation = await api.validateClipSpec({ spec, source_duration_ms: sourceDurationMs });
      onActivity?.(
        validation.data.is_valid ? 'OK' : 'WARN',
        `POST /v1/clip-specs/validate → ${validation.data.is_valid ? 'VALID' : `${validation.data.errors.length} error(s)`} in ${validation.data ? validation.durationMs.toFixed(1) : '?'}ms`,
        tenantId
      );
      if (!validation.data.is_valid) {
        setValidationErrors(validation.data.errors);
        setStage('failed');
        return;
      }
    } catch (e) {
      const err = e as ApiError;
      setRequestError(`${err.status || 'network'}: ${err.message}`);
      onActivity?.('WARN', `POST /v1/clip-specs/validate failed: ${err.message}`, tenantId);
      setStage('failed');
      return;
    }

    setStage('rendering');
    const jobId = `job-${specId}`;
    try {
      const render = await api.createRenderJob(
        {
          job_id: jobId,
          tenant_id: tenantId,
          spec,
          source_media_path: sourceMediaPath || undefined,
        },
        jobId
      );
      setJobResult(render.data);
      setStage('done');
      onActivity?.(
        'JOB',
        `POST /v1/render-jobs → ${render.data.job.status.toUpperCase()} ${jobId} ` +
          `(${render.data.asset.width}x${render.data.asset.height}, ${render.data.asset.duration_ms}ms, ` +
          `${render.durationMs.toFixed(1)}ms wall)`,
        tenantId
      );
    } catch (e) {
      const err = e as ApiError;
      setRequestError(`${err.status || 'network'}: ${err.message}`);
      setStage('failed');
      onActivity?.('WARN', `POST /v1/render-jobs failed (${err.status}): ${err.message}`, tenantId);
    }
  };

  const stageLabel: Record<Stage, string> = {
    idle: 'VALIDATE & RENDER',
    validating: 'VALIDATING SPEC...',
    rendering: 'RENDERING JOB...',
    done: 'VALIDATE & RENDER',
    failed: 'VALIDATE & RENDER',
  };

  return (
    <div className="flex-1 bg-[#0f172a] rounded-2xl border border-slate-800 p-6 flex flex-col gap-6 overflow-y-auto">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <FileCheck className="w-5 h-5 text-indigo-400" />
            <span>Deterministic Clip Spec Validator</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Runs the live pipeline: structural validation, then a real render job through the orchestrator.
          </p>
        </div>

        <button
          onClick={() => void handleRun()}
          disabled={busy}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-mono font-semibold px-4 py-2 rounded-lg transition-colors shadow-lg shadow-indigo-600/30 disabled:opacity-50"
        >
          <Play className={`w-3.5 h-3.5 ${busy ? 'animate-spin' : ''}`} />
          <span>{stageLabel[stage]}</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div>
          <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">Tenant ID (Isolated)</label>
          <input
            type="text"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">Source Media ID</label>
          <input
            type="text"
            value={sourceMediaId}
            onChange={(e) => setSourceMediaId(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">Source Duration (ms)</label>
          <input
            type="number"
            value={sourceDurationMs}
            onChange={(e) => setSourceDurationMs(Number(e.target.value))}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">Target Aspect Ratio</label>
          <select
            value={aspectRatio}
            onChange={(e) => setAspectRatio(e.target.value as '9:16' | '16:9' | '1:1')}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="9:16">9:16</option>
            <option value="16:9">16:9</option>
            <option value="1:1">1:1</option>
          </select>
        </div>
      </div>

      <div>
        <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">
          Server-side Source Media Path (optional)
        </label>
        <input
          type="text"
          value={sourceMediaPath}
          placeholder="/app/storage/input.mp4 — required when the production FFmpeg renderer is active"
          onChange={(e) => setSourceMediaPath(e.target.value)}
          className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <label className="text-[11px] font-mono uppercase text-slate-400">Clip Segments (JSON Array)</label>
            <span className="text-[10px] text-slate-500 font-mono">STRICT SCHEMA · start_ms / end_ms</span>
          </div>
          <textarea
            rows={8}
            value={segmentsText}
            onChange={(e) => setSegmentsText(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 font-mono text-xs text-indigo-300 focus:outline-none focus:border-indigo-500 resize-none leading-relaxed"
          />
        </div>

        <div className="flex flex-col bg-slate-950 rounded-xl border border-slate-800 p-4 justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
              <span className="text-xs font-mono text-slate-400 uppercase font-bold">Verification Engine</span>
              {stage === 'done' && (
                <span className="text-xs font-mono text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>RENDER COMPLETED</span>
                </span>
              )}
              {stage === 'failed' && (
                <span className="text-xs font-mono text-rose-400 flex items-center gap-1">
                  <AlertOctagon className="w-3.5 h-3.5" />
                  <span>FAIL_CLOSED</span>
                </span>
              )}
              {busy && (
                <span className="text-xs font-mono text-indigo-400 flex items-center gap-1">
                  <Film className="w-3.5 h-3.5 animate-pulse" />
                  <span>{stage === 'validating' ? 'VALIDATING' : 'RENDERING'}</span>
                </span>
              )}
            </div>

            {validationErrors.length > 0 || requestError ? (
              <div className="space-y-1.5 font-mono text-xs text-rose-400">
                {requestError && (
                  <div className="flex items-start gap-1.5 bg-rose-950/30 p-1.5 rounded border border-rose-900/40">
                    <span className="font-bold">✕</span>
                    <span>{requestError}</span>
                  </div>
                )}
                {validationErrors.map((err, i) => (
                  <div key={i} className="flex items-start gap-1.5 bg-rose-950/30 p-1.5 rounded border border-rose-900/40">
                    <span className="font-bold">✕</span>
                    <span>{err}</span>
                  </div>
                ))}
              </div>
            ) : jobResult ? (
              <div className="space-y-2 font-mono text-xs text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-500">Job ID:</span>
                  <span className="text-indigo-400 font-bold">{jobResult.job.job_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Status:</span>
                  <span className="text-emerald-400 font-bold">{jobResult.job.status}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Rendered Duration:</span>
                  <span className="text-emerald-400 font-bold">{(jobResult.asset.duration_ms / 1000).toFixed(2)}s</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Frame Geometry:</span>
                  <span>
                    {jobResult.asset.width}×{jobResult.asset.height}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Artifact Bytes:</span>
                  <span>{jobResult.asset.file_size_bytes ?? '—'}</span>
                </div>
                <div className="mt-3 pt-2 border-t border-slate-800/80">
                  <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">SHA-256 of rendered artifact</div>
                  <div className="bg-slate-900 p-2 rounded text-[10px] text-slate-400 break-all leading-relaxed">
                    {jobResult.asset.checksum_sha256 ?? 'not reported'}
                  </div>
                  <div className="text-[10px] text-slate-500 mt-2 break-all">{jobResult.asset.storage_path}</div>
                </div>
              </div>
            ) : (
              <div className="text-slate-500 text-xs font-mono italic py-8 text-center">
                Click &quot;Validate &amp; Render&quot; to run the live validation and render pipeline.
              </div>
            )}
          </div>

          <div className="text-[10px] font-mono text-slate-600 pt-2 border-t border-slate-900 flex justify-between">
            <span>ISOLATION: FAIL-CLOSED</span>
            <span>IDEMPOTENCY: JOB-SCOPED KEY</span>
          </div>
        </div>
      </div>
    </div>
  );
};
