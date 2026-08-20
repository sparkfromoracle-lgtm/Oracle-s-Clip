import React, { useState } from 'react';
import { AgentStatus } from '../types';
import { Folder, FileCode, Shield, Zap, Radio, CheckCircle, Database, Server, Lock } from 'lucide-react';

interface SidebarProps {
  onSelectFile: (fileName: string) => void;
  selectedFile: string;
}

export const Sidebar: React.FC<SidebarProps> = ({ onSelectFile, selectedFile }) => {
  const [activeAgents] = useState<AgentStatus[]>([
    { name: 'Spark', role: 'Deterministic Generator', status: 'ACTIVE', color: 'text-emerald-400' },
    { name: 'Guardian', role: 'Safety & Policy Verifier', status: 'POLICY', color: 'text-indigo-400' },
    { name: 'Pulse', role: 'Render Subprocess Queue', status: 'IDLE', color: 'text-slate-400' },
  ]);

  const repoFiles = [
    { name: 'media-service/', isDir: true, indent: 0 },
    { name: 'vector_index_service/', isDir: true, indent: 0 },
    { name: 'rendering/ffmpeg_exec.py', isDir: false, indent: 1, tag: 'CORE' },
    { name: 'orchestration/', isDir: true, indent: 0 },
    { name: 'tests/', isDir: true, indent: 0 },
    { name: 'orchestration_contracts.py', isDir: false, indent: 0, highlight: true },
    { name: '.env.example', isDir: false, indent: 0 },
  ];

  return (
    <aside className="w-64 bg-[#020617] border-r border-slate-800 flex flex-col shrink-0 select-none overflow-hidden h-full">
      {/* Repo Hierarchy */}
      <div className="p-4 border-b border-slate-800 bg-slate-900/20">
        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3 flex items-center justify-between">
          <span>Repository Hierarchy</span>
          <span className="text-[9px] text-slate-600 font-mono">LOCKED</span>
        </div>
        <div className="space-y-1 font-mono text-[11px] text-slate-400">
          {repoFiles.map((item, idx) => (
            <button
              key={idx}
              onClick={() => !item.isDir && onSelectFile(item.name)}
              className={`w-full text-left flex items-center justify-between py-1 px-1.5 rounded transition-all ${
                item.indent > 0 ? 'ml-3 w-[calc(100%-12px)]' : ''
              } ${
                selectedFile === item.name
                  ? 'bg-indigo-950/70 border border-indigo-700/60 text-white'
                  : 'hover:bg-slate-800/80 hover:text-slate-200'
              }`}
            >
              <div className="flex items-center gap-2 truncate">
                {item.isDir ? (
                  <span className="text-amber-500 text-xs">📁</span>
                ) : item.highlight ? (
                  <span className="text-indigo-400 text-xs">📄</span>
                ) : (
                  <span className="text-slate-500 text-xs">📄</span>
                )}
                <span className={`truncate ${item.highlight ? 'text-indigo-400 font-medium' : ''}`}>
                  {item.name}
                </span>
              </div>
              {item.tag && (
                <span className="text-[9px] px-1 py-0.2 bg-slate-800 text-slate-400 rounded font-sans scale-90">
                  {item.tag}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* System Agents */}
      <div className="flex-1 p-4 flex flex-col gap-6 overflow-y-auto">
        <div>
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3 flex items-center justify-between">
            <span>System Agents</span>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          </div>
          <div className="space-y-2">
            {activeAgents.map((agent) => (
              <div
                key={agent.name}
                className="flex items-center justify-between bg-slate-900/50 p-2 rounded border border-slate-800 hover:border-slate-700 transition-colors"
              >
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-slate-200">{agent.name}</span>
                  <span className="text-[9px] text-slate-500">{agent.role}</span>
                </div>
                <span
                  className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                    agent.status === 'ACTIVE'
                      ? 'text-emerald-400 bg-emerald-950/40 border border-emerald-800/40'
                      : agent.status === 'POLICY'
                      ? 'text-indigo-400 bg-indigo-950/40 border border-indigo-800/40'
                      : 'text-slate-500 bg-slate-800/40'
                  }`}
                >
                  {agent.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Security Controls */}
        <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800/80 space-y-2">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
            <Lock className="w-3 h-3 text-indigo-400" />
            <span>Isolation Layer</span>
          </div>
          <div className="text-[11px] font-mono text-slate-400 space-y-1">
            <div className="flex justify-between">
              <span className="text-slate-500">HMAC Timing:</span>
              <span className="text-emerald-400">Constant-Time</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Subprocess:</span>
              <span className="text-emerald-400">Restricted</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Circuit:</span>
              <span className="text-indigo-400">Fail-Closed</span>
            </div>
          </div>
        </div>
      </div>

      {/* Zero-LLM Execution Meter */}
      <div className="p-4 border-t border-slate-800 bg-slate-950/40">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1.5">
          <span className="text-slate-400 font-medium">Zero-LLM Execution</span>
          <span className="text-[10px] font-mono text-indigo-400 font-bold">100% DETERMINISTIC</span>
        </div>
        <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
          <div className="w-full bg-indigo-500 h-full rounded-full animate-pulse"></div>
        </div>
        <div className="flex justify-between items-center mt-2 text-[9px] text-slate-500 font-mono">
          <span>PIPELINE: V13.7</span>
          <span>LATENCY: &lt;18ms</span>
        </div>
      </div>
    </aside>
  );
};
