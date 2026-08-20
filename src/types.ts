export interface AgentStatus {
  name: string;
  role: string;
  status: 'ACTIVE' | 'POLICY' | 'IDLE' | 'STANDBY';
  color: string;
}

export interface ReadinessCheck {
  id: string;
  name: string;
  path: string;
  status: 'healthy' | 'warning' | 'error';
  latencyMs: number;
  details: string;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  category: 'AUTH' | 'SEC' | 'WARN' | 'OK' | 'FFEXEC' | 'JOB';
  message: string;
  tenantId?: string;
  detail?: string;
}

export interface PipelineStep {
  id: string;
  name: string;
  subtitle: string;
  icon: string;
  status: 'completed' | 'active' | 'pending' | 'warning';
  activeColor: string;
  description: string;
  contract: string;
}

export interface ClipSegment {
  startTime: number;
  endTime: number;
  speaker?: string;
  transcript?: string;
  relevanceScore?: number;
}

export interface ClipSpec {
  specVersion: string;
  tenantId: string;
  sourceMediaId: string;
  sourceDurationSeconds: number;
  segments: ClipSegment[];
  outputFormat: 'mp4' | 'webm';
  aspectRatio: '9:16' | '16:9' | '1:1';
  targetBitrateKbps: number;
}
