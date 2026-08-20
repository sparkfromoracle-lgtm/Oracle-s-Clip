import React from 'react';
import { CheckCircle, ShieldCheck, Terminal, AlertTriangle, Layers, Cpu } from 'lucide-react';

interface MetricsBarProps {
  onCardClick?: (metric: string) => void;
}

export const MetricsBar: React.FC<MetricsBarProps> = ({ onCardClick }) => {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 shrink-0">
      {/* Metric 1: Baseline Tests */}
      <div
        onClick={() => onCardClick?.('tests')}
        className="bg-slate-900/40 p-4 rounded-xl border border-slate-800 hover:border-slate-700 transition-all cursor-pointer group"
      >
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Baseline Tests</div>
          <CheckCircle className="w-4 h-4 text-emerald-500" />
        </div>
        <div className="text-2xl font-mono text-emerald-500 font-bold tracking-tight">
          74 <span className="text-slate-600 text-sm font-normal">/ 74</span>
        </div>
        <div className="text-[10px] text-emerald-500/80 mt-1 font-mono flex items-center gap-1 font-medium">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          100% PASSING (54 UNIT / 20 INTEGRATION)
        </div>
      </div>

      {/* Metric 2: FFmpeg Status */}
      <div
        onClick={() => onCardClick?.('ffmpeg')}
        className="bg-slate-900/40 p-4 rounded-xl border border-slate-800 hover:border-slate-700 transition-all cursor-pointer group"
      >
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">FFmpeg Status</div>
          <Terminal className="w-4 h-4 text-slate-400" />
        </div>
        <div className="text-2xl font-mono text-white font-bold italic tracking-tight">
          STABLE
        </div>
        <div className="text-[10px] text-slate-400 mt-1 font-mono">
          SUBPROCESS EXEC WRAPPER (TIMEOUT 300s)
        </div>
      </div>

      {/* Metric 3: Tenant Context */}
      <div
        onClick={() => onCardClick?.('tenant')}
        className="bg-slate-900/40 p-4 rounded-xl border border-slate-800 hover:border-slate-700 transition-all cursor-pointer group"
      >
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Tenant Context</div>
          <ShieldCheck className="w-4 h-4 text-indigo-400" />
        </div>
        <div className="text-2xl font-mono text-indigo-400 font-bold tracking-tight">
          SEALED
        </div>
        <div className="text-[10px] text-slate-400 mt-1 font-mono">
          ISOLATION HARDENED & HMAC VERIFIED
        </div>
      </div>

      {/* Metric 4: AI Gateway */}
      <div
        onClick={() => onCardClick?.('gateway')}
        className="bg-slate-900/40 p-4 rounded-xl border border-slate-800 hover:border-slate-700 transition-all cursor-pointer group"
      >
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">AI Gateway</div>
          <Cpu className="w-4 h-4 text-slate-500" />
        </div>
        <div className="text-2xl font-mono text-slate-300 font-bold tracking-tight">
          FAIL-CLOSE
        </div>
        <div className="text-[10px] text-slate-500 mt-1 font-mono">
          NO SECRETS DETECTED / ZERO LEAK
        </div>
      </div>
    </div>
  );
};
