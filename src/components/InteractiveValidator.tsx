import React, { useState } from 'react';
import { ClipSpec } from '../types';
import { Play, CheckCircle2, AlertOctagon, RefreshCw, FileCheck, Layers, Terminal } from 'lucide-react';

interface InteractiveValidatorProps {
  onValidated?: (spec: ClipSpec, isValid: boolean) => void;
}

export const InteractiveValidator: React.FC<InteractiveValidatorProps> = ({ onValidated }) => {
  const [tenantId, setTenantId] = useState<string>('tenant-enterprise-01');
  const [sourceMediaId, setSourceMediaId] = useState<string>('media-raw-84920');
  const [sourceDuration, setSourceDuration] = useState<number>(300);
  const [aspectRatio, setAspectRatio] = useState<'9:16' | '16:9' | '1:1'>('9:16');
  const [segmentsText, setSegmentsText] = useState<string>(
    JSON.stringify(
      [
        { startTime: 12.5, endTime: 34.2, speaker: 'Host', relevanceScore: 0.95 },
        { startTime: 85.0, endTime: 110.4, speaker: 'Guest', relevanceScore: 0.91 },
      ],
      null,
      2
    )
  );

  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [validationSuccess, setValidationSuccess] = useState<boolean | null>(null);
  const [isEvaluating, setIsEvaluating] = useState<boolean>(false);
  const [simulationResult, setSimulationResult] = useState<any | null>(null);

  const handleValidate = () => {
    setIsEvaluating(true);
    setValidationErrors([]);
    setValidationSuccess(null);
    setSimulationResult(null);

    setTimeout(() => {
      const errors: string[] = [];

      if (!sourceMediaId.trim()) {
        errors.push('source_media_id is required');
      }
      if (!tenantId.trim()) {
        errors.push('tenant_id is required for multi-tenant isolation');
      }
      if (sourceDuration <= 0) {
        errors.push('source_duration_seconds must be > 0');
      }

      let parsedSegments: any[] = [];
      try {
        parsedSegments = JSON.parse(segmentsText);
        if (!Array.isArray(parsedSegments) || parsedSegments.length === 0) {
          errors.push('segments list must contain at least 1 segment');
        } else {
          parsedSegments.forEach((seg, idx) => {
            if (typeof seg.startTime !== 'number' || typeof seg.endTime !== 'number') {
              errors.push(`Segment #${idx + 1}: startTime and endTime must be numeric floats`);
            } else if (seg.startTime < 0) {
              errors.push(`Segment #${idx + 1}: startTime cannot be negative`);
            } else if (seg.endTime <= seg.startTime) {
              errors.push(`Segment #${idx + 1}: endTime (${seg.endTime}) must be greater than startTime (${seg.startTime})`);
            } else if (seg.endTime > sourceDuration) {
              errors.push(
                `Segment #${idx + 1}: endTime (${seg.endTime}s) exceeds source_duration (${sourceDuration}s)`
              );
            }
          });
        }
      } catch (err: any) {
        errors.push(`Invalid JSON format in segments: ${err.message}`);
      }

      const isValid = errors.length === 0;
      setValidationErrors(errors);
      setValidationSuccess(isValid);
      setIsEvaluating(false);

      if (isValid) {
        const spec: ClipSpec = {
          specVersion: '1.0',
          tenantId,
          sourceMediaId,
          sourceDurationSeconds: sourceDuration,
          segments: parsedSegments,
          outputFormat: 'mp4',
          aspectRatio,
          targetBitrateKbps: 4500,
        };
        setSimulationResult({
          status: 'VALIDATED_SEALED',
          jobId: `job-render-${Math.random().toString(36).substring(2, 9)}`,
          contentHash: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
          targetDuration: parsedSegments.reduce((acc, s) => acc + (s.endTime - s.startTime), 0).toFixed(2),
          ffmpegArgvSandbox: [
            '/usr/bin/ffmpeg',
            '-y',
            '-ss',
            String(parsedSegments[0].startTime),
            '-to',
            String(parsedSegments[0].endTime),
            '-i',
            '/isolated_storage/' + sourceMediaId + '.mp4',
            '-vf',
            `scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2`,
            '-c:v',
            'libx264',
            '-b:v',
            '4500k',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '/tmp/rendered_output.mp4',
          ],
        });
        onValidated?.(spec, true);
      } else {
        onValidated?.({} as any, false);
      }
    }, 350);
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
            Validate declarative clip boundaries against tenant isolation constraints and FFmpeg duration bounds.
          </p>
        </div>

        <button
          onClick={handleValidate}
          disabled={isEvaluating}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-mono font-semibold px-4 py-2 rounded-lg transition-colors shadow-lg shadow-indigo-600/30 disabled:opacity-50"
        >
          <Play className={`w-3.5 h-3.5 ${isEvaluating ? 'animate-spin' : ''}`} />
          <span>{isEvaluating ? 'VALIDATING...' : 'VALIDATE & DRY-RUN'}</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
          <label className="block text-[11px] font-mono uppercase text-slate-400 mb-1">Source Duration (sec)</label>
          <input
            type="number"
            value={sourceDuration}
            onChange={(e) => setSourceDuration(Number(e.target.value))}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Segments Editor */}
        <div className="flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <label className="text-[11px] font-mono uppercase text-slate-400">
              Clip Segments (JSON Array)
            </label>
            <span className="text-[10px] text-slate-500 font-mono">STRICT SCHEMA</span>
          </div>
          <textarea
            rows={8}
            value={segmentsText}
            onChange={(e) => setSegmentsText(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 font-mono text-xs text-indigo-300 focus:outline-none focus:border-indigo-500 resize-none leading-relaxed"
          />
        </div>

        {/* Validation Result Box */}
        <div className="flex flex-col bg-slate-950 rounded-xl border border-slate-800 p-4 justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
              <span className="text-xs font-mono text-slate-400 uppercase font-bold">Verification Engine</span>
              {validationSuccess === true && (
                <span className="text-xs font-mono text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>PASS_SEALED</span>
                </span>
              )}
              {validationSuccess === false && (
                <span className="text-xs font-mono text-rose-400 flex items-center gap-1">
                  <AlertOctagon className="w-3.5 h-3.5" />
                  <span>FAIL_CLOSED</span>
                </span>
              )}
            </div>

            {validationErrors.length > 0 ? (
              <div className="space-y-1.5 font-mono text-xs text-rose-400">
                {validationErrors.map((err, i) => (
                  <div key={i} className="flex items-start gap-1.5 bg-rose-950/30 p-1.5 rounded border border-rose-900/40">
                    <span className="font-bold">✕</span>
                    <span>{err}</span>
                  </div>
                ))}
              </div>
            ) : simulationResult ? (
              <div className="space-y-2 font-mono text-xs text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-500">Synthetic Job ID:</span>
                  <span className="text-indigo-400 font-bold">{simulationResult.jobId}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Duration Output:</span>
                  <span className="text-emerald-400 font-bold">{simulationResult.targetDuration}s</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Deterministic Hash:</span>
                  <span className="text-slate-400 truncate max-w-[200px]">{simulationResult.contentHash}</span>
                </div>

                <div className="mt-3 pt-2 border-t border-slate-800/80">
                  <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Generated FFmpeg Subprocess Argv:</div>
                  <div className="bg-slate-900 p-2 rounded text-[10px] text-slate-400 break-all leading-relaxed max-h-24 overflow-y-auto">
                    {simulationResult.ffmpegArgvSandbox.join(' ')}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-slate-500 text-xs font-mono italic py-8 text-center">
                Click &quot;Validate &amp; Dry-Run&quot; to execute deterministic schema inspection and FFmpeg argument sandboxing.
              </div>
            )}
          </div>

          <div className="text-[10px] font-mono text-slate-600 pt-2 border-t border-slate-900 flex justify-between">
            <span>ISOLATION: FAIL-CLOSED</span>
            <span>MEMORY LIMIT: 2048MB</span>
          </div>
        </div>
      </div>
    </div>
  );
};
