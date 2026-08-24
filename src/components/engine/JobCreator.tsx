import React, { useState } from 'react';
import { Film, Loader2, Send } from 'lucide-react';
import { EngineRoomState } from '../../hooks/useEngineRoom';

/**
 * JobCreator — submits a REAL job to the execution engine.
 *
 * "Generate test source" creates a real short FFmpeg video file on the server;
 * the submitted job then renders that real file with measurable progress. No
 * mock data is sent.
 */
export const JobCreator: React.FC<{ engine: EngineRoomState }> = ({ engine }) => {
  const [duration, setDuration] = useState(4);
  const [aspect, setAspect] = useState('9:16');
  const [publish, setPublish] = useState(false);
  const [platform, setPlatform] = useState('youtube');
  const [rights, setRights] = useState('rights_unknown');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const src = await engine.generateTestSource(duration, aspect);
      await engine.createJob({
        source_media_path: src.source_media_path,
        duration_ms: src.duration_ms,
        target_aspect_ratio: aspect,
        publish,
        platform: publish ? platform : undefined,
        rights_status: rights,
      });
      setMsg('Job submitted — entered the queue.');
    } catch (e) {
      setMsg(`Failed: ${e instanceof Error ? e.message : 'unknown error'}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-[#0f172a] p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Film className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-semibold text-slate-200">New Production Job</h3>
        <span className="text-[10px] font-mono text-slate-500 ml-auto">real FFmpeg source</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-slate-500 uppercase">Duration (s)</span>
          <input
            type="number" min={1} max={60} value={duration}
            onChange={(e) => setDuration(Math.max(1, Math.min(60, Number(e.target.value))))}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-slate-500 uppercase">Aspect</span>
          <select value={aspect} onChange={(e) => setAspect(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono">
            <option value="9:16">9:16</option>
            <option value="16:9">16:9</option>
            <option value="1:1">1:1</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-slate-500 uppercase">Rights</span>
          <select value={rights} onChange={(e) => setRights(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono">
            <option value="rights_unknown">rights_unknown</option>
            <option value="rights_verified">rights_verified</option>
            <option value="restricted">restricted</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-mono text-slate-500 uppercase">Publish</span>
          <div className="flex items-center gap-2 h-[34px]">
            <input id="pub" type="checkbox" checked={publish}
              onChange={(e) => setPublish(e.target.checked)}
              className="accent-indigo-500 w-4 h-4" />
            <select value={platform} onChange={(e) => setPlatform(e.target.value)} disabled={!publish}
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-200 font-mono disabled:opacity-40">
              <option value="youtube">youtube</option>
              <option value="tiktok">tiktok</option>
              <option value="instagram">instagram</option>
            </select>
          </div>
        </label>
      </div>

      {publish && (
        <p className="text-[10px] font-mono text-amber-400/80">
          Publishing requires a connected, authorized account — otherwise the job
          will BLOCK at the publishing stage (truthful, not faked).
        </p>
      )}

      <button
        onClick={submit} disabled={busy}
        className="flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded px-3 py-2 transition-colors"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        <span>{busy ? 'Submitting…' : 'Create & Queue Job'}</span>
      </button>
      {msg && <p className="text-[11px] font-mono text-slate-400">{msg}</p>}
    </div>
  );
};
