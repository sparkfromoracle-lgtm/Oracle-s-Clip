import React from 'react';
import { ShieldCheck, RefreshCw, Terminal, Sliders, CheckCircle2, Play, Eye } from 'lucide-react';

interface HeaderProps {
  onOpenValidator: () => void;
  onTriggerAuditScan: () => void;
  activeTab: 'dashboard' | 'logs' | 'contracts' | 'simulator';
  setActiveTab: (tab: 'dashboard' | 'logs' | 'contracts' | 'simulator') => void;
  isAuditing: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  onOpenValidator,
  onTriggerAuditScan,
  activeTab,
  setActiveTab,
  isAuditing,
}) => {
  return (
    <header className="h-14 bg-[#0f172a] border-b border-slate-800 flex items-center justify-between px-6 shrink-0 select-none">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-indigo-600 rounded flex items-center justify-center font-bold text-white italic text-base shadow-sm">
            O
          </div>
          <div className="flex items-baseline">
            <h1 className="font-semibold text-lg tracking-tight text-white">ORACLE’S CLIP</h1>
            <span className="text-slate-500 font-normal ml-2 text-xs tracking-wider font-mono">| PRODUCTION HUB</span>
          </div>
        </div>

        {/* View Switcher Tabs */}
        <div className="hidden md:flex items-center bg-slate-900/80 p-1 rounded-lg border border-slate-800 text-xs ml-4">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`px-3 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeTab === 'dashboard'
                ? 'bg-indigo-600 text-white font-medium shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Telemetry</span>
          </button>
          <button
            onClick={() => setActiveTab('simulator')}
            className={`px-3 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeTab === 'simulator'
                ? 'bg-indigo-600 text-white font-medium shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Play className="w-3.5 h-3.5" />
            <span>Clip Validator</span>
          </button>
          <button
            onClick={() => setActiveTab('contracts')}
            className={`px-3 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeTab === 'contracts'
                ? 'bg-indigo-600 text-white font-medium shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Eye className="w-3.5 h-3.5" />
            <span>Architecture</span>
          </button>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* Quick action buttons */}
        <button
          onClick={onTriggerAuditScan}
          disabled={isAuditing}
          className="hidden sm:flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-mono px-2.5 py-1 rounded text-slate-300 transition-colors disabled:opacity-50"
          title="Run instant security and readiness verification"
        >
          <RefreshCw className={`w-3 h-3 text-indigo-400 ${isAuditing ? 'animate-spin' : ''}`} />
          <span>{isAuditing ? 'AUDITING...' : 'VERIFY ALL'}</span>
        </button>

        <div className="flex gap-2 items-center bg-emerald-500/10 px-3 py-1 rounded border border-emerald-500/30">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
          <span className="text-xs font-mono text-emerald-400 tracking-wide font-semibold">SYSTEM HARDENED</span>
        </div>

        <div className="text-xs text-slate-400 font-mono hidden sm:block border-l border-slate-800 pl-4">
          <span className="text-slate-600 font-semibold mr-1">BUILD:</span>
          <span className="text-slate-300">v13.7-FINAL</span>
        </div>
      </div>
    </header>
  );
};
