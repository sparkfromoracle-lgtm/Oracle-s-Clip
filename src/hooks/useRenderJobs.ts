import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActiveJobsResponse,
  ApiError,
  HistoryResponse,
  GoogleSheetsStatusResponse,
  api,
} from '../api/client';

export interface RenderJobsState {
  activeJobs: ActiveJobsResponse | null;
  history: HistoryResponse | null;
  googleStatus: GoogleSheetsStatusResponse | null;
  isLoading: boolean;
  error: string | null;
  refreshActive: () => Promise<void>;
  refreshHistory: (params?: { status?: string; search?: string; limit?: number; offset?: number }) => Promise<void>;
  refreshGoogleStatus: () => Promise<void>;
}

/**
 * Polls the media service for real active render jobs and history.
 * The orchestrator's durable job store is the single source of truth —
 * no frontend-only job state is fabricated.
 */
export function useRenderJobs(activePollMs = 3000): RenderJobsState {
  const [activeJobs, setActiveJobs] = useState<ActiveJobsResponse | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [googleStatus, setGoogleStatus] = useState<GoogleSheetsStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const historyParamsRef = useRef<{ status?: string; search?: string; limit?: number; offset?: number }>({});

  const refreshActive = useCallback(async () => {
    try {
      const res = await api.getActiveJobs();
      setActiveJobs(res.data);
      setError(null);
    } catch (e) {
      const err = e as ApiError;
      if (err.status !== 401) setError(err.message);
    }
  }, []);

  const refreshHistory = useCallback(
    async (params?: { status?: string; search?: string; limit?: number; offset?: number }) => {
      const p = params ?? historyParamsRef.current;
      historyParamsRef.current = p;
      setIsLoading(true);
      try {
        const res = await api.getJobHistory(p);
        setHistory(res.data);
        setError(null);
      } catch (e) {
        const err = e as ApiError;
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  const refreshGoogleStatus = useCallback(async () => {
    try {
      const res = await api.getGoogleSheetsStatus();
      setGoogleStatus(res.data);
    } catch {
      // Non-critical — Google Sheets is optional.
    }
  }, []);

  // Poll active jobs at a fast interval; refresh history + google status less often.
  useEffect(() => {
    void refreshActive();
    void refreshHistory();
    void refreshGoogleStatus();
    const activeHandle = window.setInterval(() => void refreshActive(), activePollMs);
    const historyHandle = window.setInterval(() => void refreshHistory(), 15000);
    return () => {
      window.clearInterval(activeHandle);
      window.clearInterval(historyHandle);
    };
  }, [refreshActive, refreshHistory, refreshGoogleStatus, activePollMs]);

  return {
    activeJobs,
    history,
    googleStatus,
    isLoading,
    error,
    refreshActive,
    refreshHistory,
    refreshGoogleStatus,
  };
}
