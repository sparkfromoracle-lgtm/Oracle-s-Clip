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
import { ActiveJobsPanel } from './components/ActiveJobsPanel';
import { JobHistory } from './components/JobHistory';
import { BatchProcessor } from './components/BatchProcessor';
import { PublishingDashboard } from './components/PublishingDashboard';
import { EngineRoom } from './components/engine/EngineRoom';
import { useEngineStatus } from './hooks/useEngineStatus';
import { useRenderJobs } from './hooks/useRenderJobs';

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'rendering' | 'history' | 'generate' | 'publishing' | 'contracts' | 'simulator' | 'engine'>('engine');
  const [selectedFile, setSelectedFile] = useState<string>('orchestration_contracts.py');

  // Single source of truth: live state polled from the media service.
  const engine = useEngineStatus();
  const renderJobs = useRenderJobs();

  const systemStatus: 'ready' | 'degraded' | 'unreachable' = !engine.readiness
    ? 'unreachable'
    : engine.readiness.status === 'ready'
    ? 'ready'
    : 'degraded';

  const handleSelectFile = (fileName: string) => {
    setSelectedFile(fileName);
    setActiveTab('contracts');
  };

  const handleMetricCardClick = (metric: string) => {
    if (metric === 'requests' || metric === 'jobs' || metric === 'tenant') {
      void engine.probe();
    } else if (metric === 'ffmpeg') {
      setSelectedFile('rendering/ffmpeg_exec.py');
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
        onTriggerAuditScan={() => void engine.probe()}
        isAuditing={engine.isProbing}
        systemStatus={systemStatus}
      />

      {/* Main Workspace */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left Sidebar */}
        <Sidebar onSelectFile={handleSelectFile} selectedFile={selectedFile} />

        {/* Center Canvas */}
        <section className="flex-1 flex flex-col bg-[#020617] overflow-hidden">
          {activeTab === 'dashboard' && (
            <div className="p-6 flex flex-col gap-6 h-full overflow-y-auto">
              {/* Live telemetry cards */}
              <MetricsBar
                metrics={engine.metrics}
                readiness={engine.readiness}
                config={engine.config}
                isProbing={engine.isProbing}
                onCardClick={handleMetricCardClick}
              />

              {/* Canonical Architecture Pipeline Flow */}
              <PipelineFlow />

              {/* Bottom 2-Column Grid: real activity stream & readiness probes */}
              <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-[220px]">
                <SecurityAuditLog logs={engine.logs} isStreaming={engine.isProbing} lastProbeAt={engine.lastProbeAt} />
                <SystemReadiness
                  readiness={engine.readiness}
                  latencyMs={engine.readinessLatencyMs}
                  isProbing={engine.isProbing}
                  error={engine.lastError}
                  onRunProbe={() => void engine.probe()}
                />
              </div>
            </div>
          )}

          {activeTab === 'simulator' && (
            <div className="p-6 h-full flex flex-col overflow-hidden">
              <InteractiveValidator onActivity={engine.appendLog} />
            </div>
          )}

          {activeTab === 'engine' && (
            <EngineRoom />
          )}

          {activeTab === 'rendering' && (
            <div className="p-6 flex flex-col gap-6 h-full overflow-hidden">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {[
                  { label: 'ACTIVE', value: renderJobs.activeJobs?.count ?? 0, color: 'text-indigo-400', bg: 'bg-indigo-600/10' },
                  { label: 'COMPLETED', value: renderJobs.history?.counts?.completed ?? 0, color: 'text-emerald-400', bg: 'bg-emerald-600/10' },
                  { label: 'FAILED', value: renderJobs.history?.counts?.failed ?? 0, color: 'text-rose-400', bg: 'bg-rose-600/10' },
                ].map((card) => (
                  <div key={card.label} className={`flex items-center justify-between px-4 py-3 rounded-lg border border-slate-800 ${card.bg}`}>
                    <span className="text-xs font-mono font-bold text-slate-400 tracking-wider">{card.label}</span>
                    <span className={`text-2xl font-bold ${card.color}`}>{card.value}</span>
                  </div>
                ))}
              </div>
              <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-0">
                <ActiveJobsPanel activeJobs={renderJobs.activeJobs} error={renderJobs.error} />
                <JobHistory
                  history={renderJobs.history}
                  isLoading={renderJobs.isLoading}
                  error={renderJobs.error}
                  googleStatus={renderJobs.googleStatus}
                  onRefresh={renderJobs.refreshHistory}
                />
              </div>
            </div>
          )}

          {activeTab === 'history' && (
            <div className="p-6 h-full flex flex-col overflow-hidden">
              <JobHistory
                history={renderJobs.history}
                isLoading={renderJobs.isLoading}
                error={renderJobs.error}
                googleStatus={renderJobs.googleStatus}
                onRefresh={renderJobs.refreshHistory}
              />
            </div>
          )}

          {activeTab === 'generate' && (
            <div className="p-6 h-full flex flex-col overflow-hidden">
              <BatchProcessor />
            </div>
          )}

          {activeTab === 'publishing' && (
            <div className="p-6 h-full flex flex-col overflow-hidden">
              <PublishingDashboard />
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
