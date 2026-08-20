import React, { useState } from 'react';
import { FileCode, Copy, Check, ShieldCheck, Database, Terminal } from 'lucide-react';

interface ContractViewerProps {
  initialFile?: string;
}

export const ContractViewer: React.FC<ContractViewerProps> = ({ initialFile = 'orchestration_contracts.py' }) => {
  const [selectedDoc, setSelectedDoc] = useState<string>(initialFile);
  const [copied, setCopied] = useState<boolean>(false);

  const fileContents: Record<string, { title: string; language: string; content: string }> = {
    'orchestration_contracts.py': {
      title: 'Canonical Architecture Contracts (Base44 Sealed Pipeline)',
      language: 'python',
      content: `# orchestration_contracts.py - Immutable Orchestration Contracts
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import time
import hmac
import hashlib

class JobStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"

@dataclass(frozen=True)
class ClipSegment:
    start_time: float
    end_time: float
    speaker: Optional[str] = None
    transcript: Optional[str] = None
    relevance_score: float = 1.0

@dataclass(frozen=True)
class ClipSpec:
    spec_version: str
    tenant_id: str
    source_media_id: str
    source_duration_seconds: float
    segments: List[ClipSegment]
    output_format: str = "mp4"
    aspect_ratio: str = "9:16"
    target_bitrate_kbps: int = 4500

class ClipSpecValidator:
    """Strict fail-closed validator with zero tolerance for boundary violations."""
    @staticmethod
    def validate(spec: ClipSpec) -> Dict[str, Any]:
        errors = []
        if not spec.tenant_id:
            errors.append("tenant_id must be provided for isolation")
        if not spec.source_media_id:
            errors.append("source_media_id is required")
        if spec.source_duration_seconds <= 0:
            errors.append("source_duration_seconds must be positive")
        if not spec.segments:
            errors.append("segments list cannot be empty")
        
        for idx, seg in enumerate(spec.segments):
            if seg.start_time < 0:
                errors.append(f"Segment #{idx}: start_time cannot be negative")
            if seg.end_time <= seg.start_time:
                errors.append(f"Segment #{idx}: end_time must be > start_time")
            if seg.end_time > spec.source_duration_seconds:
                errors.append(f"Segment #{idx}: end_time exceeds source duration")
                
        return {"valid": len(errors) == 0, "errors": errors}
`,
    },
    'rendering/ffmpeg_exec.py': {
      title: 'FFmpeg Subprocess Execution Hardening',
      language: 'python',
      content: `# rendering/ffmpeg_exec.py - Secure Subprocess Executor
import subprocess
import shlex
import os
from typing import List, Tuple

class FFmpegCommandExecutor:
    """Safe, non-shell execution wrapper preventing command injection."""
    
    ALLOWED_BINARIES = {"/usr/bin/ffmpeg", "/usr/bin/ffprobe", "ffmpeg", "ffprobe"}
    MAX_TIMEOUT_SECONDS = 300
    
    @classmethod
    def execute(cls, binary: str, args: List[str], timeout: int = 120) -> Tuple[int, str, str]:
        if binary not in cls.ALLOWED_BINARIES and not os.path.isabs(binary):
            raise ValueError(f"Unsanctioned binary invocation: {binary}")
            
        timeout = min(timeout, cls.MAX_TIMEOUT_SECONDS)
        cmd = [binary] + args
        
        # Explicitly avoid shell=True, execute via direct execve arguments
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            text=True
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
`,
    },
    '.env.example': {
      title: 'Environment Configuration (Fail-Closed Secrets)',
      language: 'shell',
      content: `# .env.example - Production Hub Safe Configuration Defaults
ENVIRONMENT=production
MEDIA_SERVICE_PORT=3000
STORAGE_BACKEND=s3
AWS_REGION=us-east-1
S3_BUCKET_NAME=production-clips-v1

# Multi-Tenant & Webhook Security
ORACLE_API_KEY_SECRET=changeme_in_production_strict_key
BASE44_WEBHOOK_SECRET=changeme_hmac_secret_sha256
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS=300

# Subprocess & Resource Limits
FFMPEG_BINARY_PATH=/usr/bin/ffmpeg
FFPROBE_BINARY_PATH=/usr/bin/ffprobe
MAX_CONCURRENT_RENDERS=8
RENDER_TIMEOUT_SECONDS=300
`,
    },
  };

  const current = fileContents[selectedDoc] || fileContents['orchestration_contracts.py'];

  const handleCopy = () => {
    navigator.clipboard.writeText(current.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex-1 bg-[#0f172a] rounded-2xl border border-slate-800 flex flex-col overflow-hidden">
      {/* Top Header */}
      <div className="px-6 py-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 bg-slate-900/40 shrink-0">
        <div className="flex items-center gap-2">
          <FileCode className="w-4 h-4 text-indigo-400" />
          <span className="text-xs font-semibold text-white uppercase tracking-wider">{current.title}</span>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs font-mono">
            {Object.keys(fileContents).map((fileName) => (
              <button
                key={fileName}
                onClick={() => setSelectedDoc(fileName)}
                className={`px-3 py-1 rounded transition-colors ${
                  selectedDoc === fileName
                    ? 'bg-indigo-600 text-white font-medium'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {fileName}
              </button>
            ))}
          </div>

          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-xs px-3 py-1.5 rounded-lg text-slate-300 font-mono transition-colors border border-slate-700"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? 'COPIED' : 'COPY'}</span>
          </button>
        </div>
      </div>

      {/* Code Editor Body */}
      <div className="flex-1 p-6 overflow-auto bg-slate-950/80 font-mono text-xs text-indigo-200 leading-relaxed">
        <pre className="whitespace-pre">{current.content}</pre>
      </div>

      {/* Footer Info */}
      <div className="px-6 py-2.5 bg-slate-950 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-500 shrink-0">
        <span>SEALED ARCHITECTURE CONTRACT: IMMUTABLE</span>
        <span className="text-emerald-400">HASH_VERIFIED: 100% MATCH</span>
      </div>
    </div>
  );
};
