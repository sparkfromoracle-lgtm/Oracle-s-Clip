import React, { useState } from 'react';
import { AuditLogEntry } from '../types';
import { Shield, CheckCircle2, AlertTriangle, Key, Terminal, Search, Filter, Download, Check } from 'lucide-react';

interface SecurityAuditLogProps {
  logs: AuditLogEntry[];
  onAddCustomLog?: (entry: AuditLogEntry) => void;
}

export const SecurityAuditLog: React.FC<SecurityAuditLogProps> = ({ logs }) => {
  const [filter, setFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [hasDownloaded, setHasDownloaded] = useState<boolean>(false);

  const filteredLogs = logs.filter((log) => {
    const matchesFilter = filter === 'ALL' || log.category === filter;
    const matchesSearch =
      searchTerm === '' ||
      log.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.category.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const handleDownloadAuditLog = () => {
    const dumpPayload = {
      exportMetadata: {
        system: 'Oracle Clip Production Hub',
        pipeline: 'Sealed Architecture Canonical V13.7',
        exportedAt: new Date().toISOString(),
        totalRecords: logs.length,
        activeFilter: filter,
        searchQuery: searchTerm || null,
        securityProfile: {
          isolation: 'SEALED',
          hmacVerification: 'CONSTANT_TIME_HMAC_SHA256',
          ffmpegSandbox: 'ARGV_RESTRICTED_SUBPROCESS',
          aiGateway: 'FAIL_CLOSED',
        },
      },
      auditLogs: filteredLogs,
    };

    const blob = new Blob([JSON.stringify(dumpPayload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    link.href = url;
    link.download = `oracle-audit-dump-${timestamp}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setHasDownloaded(true);
    setTimeout(() => setHasDownloaded(false), 2500);
  };

  const getCategoryBadge = (category: AuditLogEntry['category']) => {
    switch (category) {
      case 'AUTH':
        return <span className="text-indigo-400 font-bold">AUTH</span>;
      case 'SEC':
        return <span className="text-emerald-400 font-bold">SEC</span>;
      case 'WARN':
        return <span className="text-amber-400 font-bold">WARN</span>;
      case 'OK':
        return <span className="text-emerald-400 font-bold">OK</span>;
      case 'FFEXEC':
        return <span className="text-cyan-400 font-bold">FFEXEC</span>;
      case 'JOB':
        return <span className="text-purple-400 font-bold">JOB</span>;
      default:
        return <span className="text-slate-400">{category}</span>;
    }
  };

  return (
    <div className="flex flex-col bg-[#0f172a] rounded-2xl border border-slate-800 overflow-hidden h-full">
      {/* Card Header */}
      <div className="px-4 py-3 border-b border-slate-800 flex justify-between items-center bg-slate-900/40 shrink-0">
        <div className="flex items-center gap-2">
          <Shield className="w-3.5 h-3.5 text-indigo-400" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            Security Integrity Audit
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            id="download-audit-log-btn"
            onClick={handleDownloadAuditLog}
            className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 hover:border-slate-600 text-slate-300 hover:text-white px-2.5 py-1 rounded text-[9px] font-mono transition-colors shadow-sm"
            title="Download audit log JSON dump for offline forensics"
          >
            {hasDownloaded ? (
              <>
                <Check className="w-3 h-3 text-emerald-400" />
                <span className="text-emerald-400 font-semibold">DOWNLOADED</span>
              </>
            ) : (
              <>
                <Download className="w-3 h-3 text-indigo-400" />
                <span>DOWNLOAD AUDIT LOG</span>
              </>
            )}
          </button>
          <span className="text-[9px] text-emerald-400 font-mono font-bold bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded">
            COMPLETED
          </span>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="px-4 py-2 bg-slate-950/50 border-b border-slate-800/80 flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-1">
          {['ALL', 'AUTH', 'SEC', 'WARN', 'OK'].map((cat) => (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className={`text-[9px] px-2 py-0.5 rounded font-mono font-semibold transition-colors ${
                filter === cat
                  ? 'bg-indigo-600 text-white'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200 border border-slate-800'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
        <div className="relative">
          <input
            type="text"
            placeholder="Search audit trail..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded px-2 py-0.5 text-[10px] text-slate-300 font-mono focus:outline-none focus:border-indigo-500 w-32 md:w-40"
          />
        </div>
      </div>

      {/* Audit Log Stream */}
      <div className="p-4 font-mono text-[11px] leading-relaxed overflow-y-auto space-y-2 flex-1">
        {filteredLogs.map((log) => (
          <div key={log.id} className="text-slate-400 flex items-start gap-2 hover:bg-slate-900/40 p-0.5 rounded">
            <span className="text-slate-600 shrink-0 select-none">[{log.timestamp}]</span>
            <span className="shrink-0">-</span>
            <span className="shrink-0">{getCategoryBadge(log.category)}:</span>
            <span className="text-slate-300 flex-1">{log.message}</span>
            {log.tenantId && (
              <span className="text-[9px] text-indigo-400 bg-slate-900 px-1 py-0.2 rounded border border-slate-800 shrink-0">
                {log.tenantId}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
