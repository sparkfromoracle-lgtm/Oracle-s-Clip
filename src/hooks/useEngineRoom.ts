/**
 * useEngineRoom — polls the real execution engine state from the media service.
 *
 * This is NOT a simulation: every value comes from the durable EngineStore via
 * the /v1/engine/* endpoints. Polling reconstructs the same state on refresh.
 * No hard-coded timers animate activity — when there are no active jobs the
 * system reports READY (idle).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, EngineStateResponse, EngineJob, EngineEvent } from '../api/client';

const POLL_MS = 1500;

export interface EngineRoomState {
  system: EngineStateResponse | null;
  jobs: EngineJob[];
  events: EngineEvent[];
  loading: boolean;
  error: string | null;
  lastUpdated: number | null;
  refresh: () => void;
  createJob: (params: {
    source_media_path: string;
    duration_ms: number;
    target_aspect_ratio?: string;
    publish?: boolean;
    platform?: string;
    rights_status?: string;
  }) => Promise<void>;
  generateTestSource: (durationSeconds?: number, aspectRatio?: string) => Promise<{ source_media_path: string; duration_ms: number }>;
  retryJob: (jobId: string) => Promise<void>;
  cancelJob: (jobId: string) => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stopWorker: (workerId: string) => Promise<void>;
  startWorker: (workerId: string) => Promise<void>;
}

export function useEngineRoom(): EngineRoomState {
  const [system, setSystem] = useState<EngineStateResponse | null>(null);
  const [jobs, setJobs] = useState<EngineJob[]>([]);
  const [events, setEvents] = useState<EngineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const [stateRes, jobsRes, eventsRes] = await Promise.all([
        api.engineState(),
        api.engineJobs(100),
        api.engineEvents(150),
      ]);
      setSystem(stateRes.data);
      setJobs(jobsRes.data.jobs);
      setEvents(eventsRes.data.events);
      setError(null);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Engine unreachable';
      setError(msg);
    } finally {
      setLoading(false);
      setLastUpdated(Date.now());
    }
  }, []);

  useEffect(() => {
    void poll();
    timer.current = setInterval(() => void poll(), POLL_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [poll]);

  const createJob = useCallback<EngineRoomState['createJob']>(async (params) => {
    await api.createEngineJob(params);
    void poll();
  }, [poll]);

  const generateTestSource = useCallback<EngineRoomState['generateTestSource']>(
    async (durationSeconds = 4, aspectRatio = '9:16') => {
      const res = await api.generateTestSource({ duration_seconds: durationSeconds, target_aspect_ratio: aspectRatio });
      return { source_media_path: res.data.source_media_path, duration_ms: res.data.duration_ms };
    }, []);

  const retryJob = useCallback(async (jobId: string) => {
    await api.retryEngineJob(jobId);
    void poll();
  }, [poll]);

  const cancelJob = useCallback(async (jobId: string) => {
    await api.cancelEngineJob(jobId);
    void poll();
  }, [poll]);

  const pause = useCallback(async () => { await api.pauseEngine(); void poll(); }, [poll]);
  const resume = useCallback(async () => { await api.resumeEngine(); void poll(); }, [poll]);
  const stopWorker = useCallback(async (id: string) => { await api.stopEngineWorker(id); void poll(); }, [poll]);
  const startWorker = useCallback(async (id: string) => { await api.startEngineWorker(id); void poll(); }, [poll]);

  return {
    system, jobs, events, loading, error, lastUpdated,
    refresh: poll, createJob, generateTestSource, retryJob, cancelJob,
    pause, resume, stopWorker, startWorker,
  };
}
