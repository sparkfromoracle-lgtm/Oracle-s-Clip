import React, { useState } from 'react';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { MetricsBar } from './components/MetricsBar';
import { PipelineFlow } from './components/PipelineFlow';
import { SecurityAuditLog } from './components/SecurityAuditLog';
import { SystemReadiness } from './components/SystemReadiness';
import { InteractiveValidator } from './components/InteractiveValidator';
import { ContractViewer } from './components/ContractViewer';
import { Footer } from './components/Footer';
import { AuditLogEntry, PipelineStep } from './types';

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'logs' | 'contracts' | 'simulator'>('dashboard');
  const [selectedFile, setSelectedFile] = useState<string>('orchestration_contracts.py');
  const [isAuditing, setIsAuditing] = useState<boolean>(false);

  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([
    {
      id: 'log-1',
      timestamp: '2024-05-24 09:12',
      category: 'AUTH',
      message: 'Loading API key provider...',
    },
    {
      id: 'log-2',
      timestamp: '2024-05-24 09:12',
      category: 'AUTH',
      message: 'Timing-safe comparison enabled.',
    },
    {
      id: 'log-3',
      timestamp: '2024-05-24 09:13',
      category: 'SEC',
      message: 'HMAC-SHA256 signature verification online.',
    },
    {
      id: 'log-4',
      timestamp: '2024-05-24 09:13',
      category: 'SEC',
      message: 'Stale timestamp threshold set: 300s.',
    },
    {
      id: 'log-5',
      timestamp: '2024-05-24 09:14',
      category: 'WARN',
      message: 'FFmpeg configured for restricted mode.',
    },
    {
      id: 'log-6',
      timestamp: '2024-05-24 09:15',
      category: 'OK',
      message: 'All 15 security checks passed.',
    },
  ]);

  const handleSelectFile = (fileName: string) => {
    setSelectedFile(fileName);
    setActiveTab('contracts');
  };

  const handleTriggerAuditScan = () => {
    setIsAuditing(true);
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0].substring(0, 5);

    setTimeout(() => {
      const newEntries: AuditLogEntry[] = [
        {
          id: `log-${Date.now()}-1`,
          timestamp: `2024-05-24 ${timeStr}`,
          category: 'FFEXEC',
          message: 'Subprocess argv sandbox probe clean; execve arguments sealed.',
        },
        {
          id: `log-${Date.now()}-2`,
          timestamp: `2024-05-24 ${timeStr}`,
          category: 'AUTH',
          message: 'Constant-time verification evaluated tenant principal context.',
          tenantId: 'tenant-oracle-alpha',
        },
        {
          id: `log-${Date.now()}-3`,
          timestamp: `2024-05-24 ${timeStr}`,
          category: 'OK',
          message: 'Zero-LLM deterministic pipeline check: 100% compliant.',
        },
      ];
      setAuditLogs((prev) => [...newEntries, ...prev]);
      setIsAuditing(false);
    }, 600);
  };

  const handleMetricCardClick = (metric: string) => {
    if (metric === 'tests' || metric === 'tenant') {
      handleTriggerAuditScan();
    } else if (metric === 'ffmpeg') {
      setSelectedFile('rendering/ffmpeg_exec.py');
      setActiveTab('contracts');
    } else if (metric === 'gateway') {
      setActiveTab('contracts');
    }
  };

  return (
    <div className="h-screen w-screen bg-[#020617] text-slate-300 font-sans flex flex-col overflow-hidden">
      {/* Top Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onOpenValidator={() => setActiveTab('simulator')}
        onTriggerAuditScan={handleTriggerAuditScan}
        isAuditing={isAuditing}
      />

      {/* Main Workspace */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left Sidebar */}
        <Sidebar onSelectFile={handleSelectFile} selectedFile={selectedFile} />

        {/* Center Canvas */}
        <section className="flex-1 flex flex-col bg-[#020617] overflow-hidden">
          {activeTab === 'dashboard' && (
            <div className="p-6 flex flex-col gap-6 h-full overflow-y-auto">
              {/* Top 4 Metrics */}
              <MetricsBar onCardClick={handleMetricCardClick} />

              {/* Canonical Architecture Pipeline Flow */}
              <PipelineFlow />

              {/* Bottom 2-Column Grid: Security Integrity Audit & System Readiness */}
              <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[220px]">
                <SecurityAuditLog logs={auditLogs} />
                <SystemReadiness onRunProbe={handleTriggerAuditScan} />
              </div>
            </div>
          )}

          {activeTab === 'simulator' && (
            <div className="p-6 h-full flex flex-col overflow-hidden">
              <InteractiveValidator />
            </div>
          )}

          {activeTab === 'contracts' && (
            <div className="p-6 h-full flex flex-col overflow-hidden">
              <ContractViewer initialFile={selectedFile} />
            </div>
          )}
        </section>
      </main>

      {/* Persistent Footer */}
      <Footer />
    </div>
  );
}
