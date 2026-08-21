import React, { useState } from 'react';
import { PipelineStep } from '../types';
import { Sparkles, Check, ArrowRight, Play, FileJson, Shield, AlertCircle } from 'lucide-react';

interface PipelineFlowProps {
  onStepSelect?: (step: PipelineStep) => void;
}

export const PipelineFlow: React.FC<PipelineFlowProps> = ({ onStepSelect }) => {
  const [selectedStepId, setSelectedStepId] = useState<string>('validator');
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [activeStepIndex, setActiveStepIndex] = useState<number>(-1);

  const steps: PipelineStep[] = [
    {
      id: 'opportunity',
      name: 'Content\nOpportunity',
      subtitle: 'Heuristic Extractor',
      icon: '📦',
      status: 'completed',
      activeColor: 'bg-slate-800 border-slate-700 text-white',
      description: 'Zero-LLM candidate extraction from visual shot boundaries and audio transcripts.',
      contract: 'CandidateOpportunity(source_id, timestamp_ranges, confidence_score, speaker_id)',
    },
    {
      id: 'clipspec',
      name: 'Clip\nSpec',
      subtitle: 'Deterministic Spec',
      icon: '📝',
      status: 'completed',
      activeColor: 'bg-slate-800 border-slate-700 text-white',
      description: 'Standardized declarative clip specification with target aspect ratio and trim timings.',
      contract: 'ClipSpec(spec_version="1.0", tenant_id, segments=[(start, end)], output_format)',
    },
    {
      id: 'validator',
      name: 'Validator',
      subtitle: 'Boundary & Bounds',
      icon: '⚖️',
      status: 'active',
      activeColor: 'bg-indigo-600 border-indigo-400 text-white shadow-indigo-500/20 shadow-md',
      description: 'Strict fail-closed schema, duration bounds, non-overlapping sequence validation.',
      contract: 'ClipSpecValidator.validate(spec) -> ValidationResult(valid=True, errors=[])',
    },
    {
      id: 'renderer',
      name: 'Renderer',
      subtitle: 'FFmpeg Subprocess',
      icon: '⚡',
      status: 'active',
      activeColor: 'bg-slate-800 border-slate-700 text-white',
      description: 'Hardened FFmpeg execution with argv sandboxing, memory caps, and timeout traps.',
      contract: 'FFmpegRendererAdapter.render(spec) -> MediaJob(status="COMPLETED", output_path)',
    },
    {
      id: 'asset',
      name: 'Rendered\nAsset',
      subtitle: 'MP4 / WEBM',
      icon: '🎞️',
      status: 'completed',
      activeColor: 'bg-slate-800 border-slate-700 text-white',
      description: 'Encoded high-fidelity vertical video with synced captions and audio normalization.',
      contract: 'RenderedAsset(storage_uri, sha256_hash, duration_seconds, resolution="1080x1920")',
    },
    {
      id: 'quality',
      name: 'Quality\nChecker',
      subtitle: 'Bitrate & Codec',
      icon: '💎',
      status: 'active',
      activeColor: 'bg-emerald-600 border-emerald-400 text-white shadow-emerald-500/20 shadow-md',
      description: 'Automated video sanity check verifying keyframe pacing, black-frame ratio, and audio sync.',
      contract: 'QualityGate.inspect(asset) -> QualityReport(score=0.98, pass_gate=True)',
    },
    {
      id: 'guardian',
      name: 'Guardian\nHook',
      subtitle: 'Policy Engine',
      icon: '🛡️',
      status: 'active',
      activeColor: 'bg-slate-800 border-slate-700 text-white',
      description: 'Safety compliance, brand watermark alignment, and tenant policy gatekeeper.',
      contract: 'GuardianPolicy.evaluate(asset, tenant_id) -> GuardianResult(approved=True)',
    },
    {
      id: 'publishing',
      name: 'Publishing',
      subtitle: 'Signed Webhook',
      icon: '🌐',
      status: 'completed',
      activeColor: 'bg-indigo-500 border-indigo-400 text-white shadow-indigo-500/20 shadow-md',
      description: 'Dispatches signed webhook event with HMAC-SHA256 timestamp signature to the configured integration host.',
      contract: 'WebhookDispatcher.send_event(event="media.clip.published", hmac_signature)',
    },
  ];

  const handleStepClick = (step: PipelineStep) => {
    setSelectedStepId(step.id);
    onStepSelect?.(step);
  };

  const runPipelineSimulation = () => {
    if (isSimulating) return;
    setIsSimulating(true);
    let current = 0;
    setActiveStepIndex(0);

    const interval = setInterval(() => {
      current++;
      if (current < steps.length) {
        setActiveStepIndex(current);
        setSelectedStepId(steps[current].id);
      } else {
        clearInterval(interval);
        setIsSimulating(false);
        setActiveStepIndex(-1);
      }
    }, 600);
  };

  const selectedStep = steps.find((s) => s.id === selectedStepId) || steps[2];

  return (
    <div className="bg-[#0f172a] rounded-2xl border border-slate-800 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/40">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-300">
            Sealed Architecture Pipeline
          </h2>
          <span className="text-[10px] bg-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded border border-indigo-500/30 uppercase font-mono font-medium">
            Canonical Flow
          </span>
        </div>

        <button
          onClick={runPipelineSimulation}
          disabled={isSimulating}
          className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-xs px-2.5 py-1 rounded text-indigo-300 border border-slate-700 font-mono transition-colors disabled:opacity-50"
        >
          <Play className={`w-3 h-3 ${isSimulating ? 'animate-spin' : ''}`} />
          <span>{isSimulating ? 'TRACING PIPELINE...' : 'TRACE PIPELINE'}</span>
        </button>
      </div>

      {/* Pipeline Visual Flow */}
      <div className="p-6 flex items-center justify-between overflow-x-auto gap-2 select-none">
        {steps.map((step, idx) => {
          const isSelected = selectedStepId === step.id;
          const isCurrentActive = activeStepIndex === idx;

          return (
            <React.Fragment key={step.id}>
              <div
                onClick={() => handleStepClick(step)}
                className="flex flex-col items-center gap-2 min-w-[84px] cursor-pointer group transition-transform"
              >
                <div
                  className={`w-11 h-11 rounded-xl flex items-center justify-center text-sm transition-all duration-300 ${
                    isCurrentActive
                      ? 'ring-2 ring-emerald-400 scale-110 bg-emerald-600 text-white shadow-lg'
                      : isSelected
                      ? 'ring-2 ring-indigo-500 scale-105 ' + step.activeColor
                      : 'bg-slate-800/90 border border-slate-700 text-slate-300 hover:border-slate-500'
                  }`}
                >
                  <span>{step.icon}</span>
                </div>
                <span
                  className={`text-[9px] font-bold text-center leading-tight uppercase font-mono tracking-tight ${
                    isSelected ? 'text-indigo-400' : 'text-slate-400 group-hover:text-slate-200'
                  }`}
                  dangerouslySetInnerHTML={{ __html: step.name.replace('\n', '<br>') }}
                />
              </div>

              {idx < steps.length - 1 && (
                <div className="h-[1px] w-6 md:w-8 bg-slate-800 relative shrink-0">
                  {isCurrentActive && (
                    <div className="absolute top-[-2px] left-0 w-full h-[3px] bg-indigo-500 rounded-full animate-pulse" />
                  )}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Selected Step Contract Drawer */}
      <div className="px-6 py-3 bg-slate-950/70 border-t border-slate-800/80 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-slate-500 font-mono text-[10px] uppercase font-bold tracking-wider">
            STEP [{selectedStep.id.toUpperCase()}]:
          </span>
          <span className="text-slate-300 font-medium">{selectedStep.description}</span>
        </div>
        <div className="font-mono text-[11px] text-indigo-300 bg-slate-900 px-3 py-1 rounded border border-slate-800 truncate max-w-xl">
          {selectedStep.contract}
        </div>
      </div>
    </div>
  );
};
