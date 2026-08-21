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
import { useEngineStatus } from './hooks/useEngineStatus';

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'logs' | 'contracts' | 'simulator'>('dashboard');
  const [selectedFile, setSelectedFile] = useState<string>('orchestration_contracts.py');

  // Single source of truth: live state polled from the media service.
  const engine = useEngineStatus();

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
