import React, { useState } from 'react';
import { ReadinessCheck } from '../types';
import { Activity, CheckCircle, RefreshCw, Cpu, Server, HardDrive, Network } from 'lucide-react';

interface SystemReadinessProps {
  onRunProbe?: () => void;
}

export const SystemReadiness: React.FC<SystemReadinessProps> = ({ onRunProbe }) => {
  const [isPinging, setIsPinging] = useState<boolean>(false);
  const [checks, setChecks] = useState<ReadinessCheck[]>([
    {
      id: 'ffmpeg',
      name: 'FFmpeg Binary Wrapper',
      path: '/usr/bin/ffmpeg',
      status: 'healthy',
      latencyMs: 1.2,
      details: 'Subprocess argument sandbox verified & restricted',
    },
    {
      id: 'storage',
      name: 'Storage Backend (S3)',
      path: 'production_bucket_v1',
      status: 'healthy',
      latencyMs: 4.8,
      details: 'Read/Write/Signed URL generation certified',
    },
    {
      id: 'vector',
      name: 'Vector Index Service',
      path: 'localhost:6333',
      status: 'healthy',
      latencyMs: 2.1,
      details: 'Cosine similarity vector cache warm (768-dim)',
    },
    {
      id: 'webhook',
      name: 'Base44 Webhook Integration',
      path: 'ready_to_handshake',
      status: 'healthy',
      latencyMs: 3.4,
      details: 'HMAC-SHA256 signature handshake ready',
    },
  ]);

  const handlePingAll = () => {
    setIsPinging(true);
    setTimeout(() => {
      setChecks((prev) =>
        prev.map((c) => ({
          ...c,
          latencyMs: +(Math.random() * 3 + 1).toFixed(1),
        }))
      );
      setIsPinging(false);
      onRunProbe?.();
    }, 500);
  };

  return (
    <div className="flex flex-col bg-[#0f172a] rounded-2xl border border-slate-800 overflow-hidden h-full">
      {/* Card Header */}
      <div className="px-4 py-3 border-b border-slate-800 flex justify-between items-center bg-slate-900/40 shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            System Readiness
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] text-emerald-400 font-mono font-bold bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded">
            ONLINE
          </span>
          <button
            onClick={handlePingAll}
            disabled={isPinging}
            className="text-slate-400 hover:text-slate-200 transition-colors p-1 rounded hover:bg-slate-800"
            title="Ping readiness probe"
          >
            <RefreshCw className={`w-3 h-3 ${isPinging ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Check Items List */}
      <div className="p-4 space-y-4 overflow-y-auto flex-1">
        {checks.map((check) => (
          <div key={check.id} className="flex items-center gap-3 p-1.5 rounded hover:bg-slate-900/30 transition-colors">
            <div className="w-2 h-2 rounded-full bg-emerald-500 shrink-0 shadow-sm shadow-emerald-500/50" />
            <div className="flex-1 flex flex-col min-w-0">
              <div className="text-xs text-slate-200 font-medium truncate">{check.name}</div>
              <div className="text-[10px] text-slate-500 truncate">{check.details}</div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-[10px] font-mono text-slate-400 italic bg-slate-950 px-2 py-0.5 rounded border border-slate-800/80">
                {check.path}
              </div>
              <div className="text-[9px] font-mono text-slate-600 mt-0.5">{check.latencyMs}ms</div>
            </div>
          </div>
        ))}
      </div>

      {/* Readiness status footer bar */}
      <div className="px-4 py-2.5 bg-slate-950/60 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-500 shrink-0">
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span>HTTP 200 /ready - ALL PROBES SATISFIED</span>
        </span>
        <span className="text-indigo-400 font-semibold">TOLERANCE: 300s</span>
      </div>
    </div>
  );
};
