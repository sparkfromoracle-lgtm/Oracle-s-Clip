/**
 * Thin typed client for the Oracle Clip media service API.
 *
 * Every panel in the UI reads real state through this module — there are no
 * simulated responses. The API base URL and the tenant API key come from the
 * environment (VITE_API_URL / VITE_API_KEY), never hard-coded.
 */

const BASE_URL: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') || '';
const API_KEY: string = (import.meta.env.VITE_API_KEY as string | undefined) || '';
export const TENANT_ID: string = (import.meta.env.VITE_TENANT_ID as string | undefined) || '';

export interface ReadinessResponse {
  status: 'ready' | 'degraded';
  environment: string;
  is_production: boolean;
  checks: Record<string, Record<string, unknown>>;
}

export interface MetricsResponse {
  requests: {
    total: number;
    by_status: Record<string, number>;
    p50_latency_ms: number;
    p95_latency_ms: number;
    p99_latency_ms?: number;
  };
  jobs: {
    submitted: number;
    completed: number;
    failed: number;
    p50_render_duration_ms: number;
    p95_render_duration_ms?: number;
  };
  security?: Record<string, number>;
}

export interface ConfigSummaryResponse {
  environment: string;
  is_production: boolean;
  asr_provider: string;
  clip_provider: string;
  storage_backend: string;
  ffmpeg_binary: string;
  configured_tenants: string[];
  api_keys_count: number;
  webhook_secret_configured: boolean;
}

export interface ValidationResponse {
  is_valid: boolean;
  errors: string[];
}

export interface RenderJobResponse {
  job: {
    job_id: string;
    tenant_id: string;
    status: string;
    output_path?: string | null;
    error_message?: string | null;
  };
  asset: {
    asset_id: string;
    duration_ms: number;
    width: number;
    height: number;
    bitrate?: number | null;
    file_size_bytes?: number | null;
    checksum_sha256?: string | null;
    storage_path: string;
  };
}

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export interface ApiCallResult<T> {
  data: T;
  durationMs: number;
}

async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<ApiCallResult<T>> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.body) headers['Content-Type'] = 'application/json';
  if (authenticated) {
    if (!API_KEY) {
      throw new ApiError('No API key configured for the UI (set VITE_API_KEY)', 0);
    }
    headers['X-API-Key'] = API_KEY;
  }

  const started = performance.now();
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  } catch (e) {
    throw new ApiError(`Cannot reach media service at ${BASE_URL || 'same origin'}`, 0, e);
  }
  const durationMs = performance.now() - started;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const body = payload as { message?: string; error?: string } | null;
    throw new ApiError(body?.message || body?.error || `HTTP ${response.status}`, response.status, payload);
  }

  return { data: payload as T, durationMs };
}

export const api = {
  readiness: () => request<ReadinessResponse>('/ready', {}, false),
  health: () => request<{ status: string }>('/health', {}, false),
  metrics: () => request<MetricsResponse>('/v1/metrics'),
  configSummary: () => request<ConfigSummaryResponse>('/v1/config/summary'),

  validateClipSpec: (body: unknown) =>
    request<ValidationResponse>('/v1/clip-specs/validate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createRenderJob: (body: unknown, idempotencyKey?: string) =>
    request<RenderJobResponse>('/v1/render-jobs', {
      method: 'POST',
      body: JSON.stringify(body),
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
    }),

  getRenderJob: (jobId: string) => request<{ job: RenderJobResponse['job'] }>(`/v1/render-jobs/${jobId}`),
};

export const apiConfigured = Boolean(API_KEY);
export const apiBaseUrl = BASE_URL || window.location.origin;
