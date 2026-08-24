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

// -- Render Job types for dashboard / history / export -----------------------

export interface RenderJobSummary {
  job_id: string;
  tenant_id: string;
  status: string;
  output_path?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  progress?: number;
  google_sheet_exported_at?: string | null;
  google_sheet_row_id?: string | null;
  spec?: {
    spec_id: string;
    source_media_id: string;
    target_aspect_ratio: string;
    segments: { start_ms: number; end_ms: number; source_media_id?: string }[];
  };
  metadata?: Record<string, unknown>;
}

export interface ActiveJobsResponse {
  jobs: RenderJobSummary[];
  count: number;
}

export interface HistoryResponse {
  jobs: RenderJobSummary[];
  total: number;
  counts: Record<string, number>;
  limit: number;
  offset: number;
}

export interface GoogleSheetsStatusResponse {
  configured: boolean;
  authorized: boolean;
}

export interface GoogleSheetsExportResult {
  status: 'success' | 'partial' | 'failed';
  exported: number;
  updated: number;
  failed: number;
  errors: string[];
}

export interface BatchProcessResponse {
  total: number;
  completed: number;
  failed: number;
  clips: Array<Record<string, unknown>>;
}

// -- Social Publishing types -------------------------------------------------

export interface PlatformCapability {
  platform: string;
  supports_video: boolean;
  supports_caption: boolean;
  supports_title: boolean;
  supports_hashtags: boolean;
  supports_privacy: boolean;
  supports_scheduling: boolean;
  supports_thumbnail: boolean;
  max_video_duration_seconds: number | null;
  supported_aspect_ratios: string[];
  oauth_scopes: string[];
  implementation_status: 'working' | 'partially_implemented' | 'not_implemented' | 'blocked';
}

export interface ConnectedAccountResponse {
  account_id: string;
  platform: string;
  display_name: string;
  platform_user_id: string;
  status: string;
  connected_at: string;
  scopes: string[];
}

export interface SocialPostResponse {
  post_id: string;
  tenant_id: string;
  render_job_id: string;
  rendered_asset_id: string;
  platform: string;
  account_id: string;
  platform_post_id: string | null;
  status: string;
  title: string | null;
  caption: string | null;
  hashtags: string[];
  privacy: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  error_message: string | null;
  retry_count: number;
  post_url: string | null;
  auto_publish: boolean;
  compliance_verdict: string | null;
  compliance_reasons: string[];
  created_at: string | null;
  updated_at: string | null;
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

  getRenderJob: (jobId: string) => request<{ job: RenderJobSummary }>(`/v1/render-jobs/${jobId}`),

  // Active jobs (real-time dashboard source)
  getActiveJobs: () => request<ActiveJobsResponse>('/v1/render-jobs/active'),

  // History (paginated, filterable)
  getJobHistory: (params?: { status?: string; search?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.search) qs.set('search', params.search);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const suffix = qs.toString() ? `?${qs}` : '';
    return request<HistoryResponse>(`/v1/render-jobs/history${suffix}`);
  },

  // Google Sheets export
  getGoogleSheetsStatus: () => request<GoogleSheetsStatusResponse>('/v1/integrations/google/status'),
  startGoogleAuth: () => request<{ auth_url: string }>('/v1/integrations/google/auth'),
  exportToGoogleSheets: (jobIds?: string[]) =>
    request<{ result: GoogleSheetsExportResult }>('/v1/export/google-sheets', {
      method: 'POST',
      body: JSON.stringify({ job_ids: jobIds ?? null }),
    }),

  // Batch / autonomous clip generation
  batchProcess: (body: unknown) =>
    request<BatchProcessResponse>('/v1/orchestration/batch', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Social publishing
  getPublishingCapabilities: () =>
    request<{ platforms: PlatformCapability[] }>('/v1/publishing/capabilities'),

  getConnectedAccounts: () =>
    request<{ accounts: ConnectedAccountResponse[]; count: number }>('/v1/publishing/accounts'),

  startPlatformOAuth: (platform: string, redirectUri?: string) =>
    request<{ auth_url: string }>('/v1/publishing/oauth/start', {
      method: 'POST',
      body: JSON.stringify({ platform, redirect_uri: redirectUri }),
    }),

  handlePlatformOAuthCallback: (platform: string, code: string, redirectUri?: string) =>
    request<{ account_id: string; platform: string; display_name: string; status: string }>(
      '/v1/publishing/oauth/callback',
      { method: 'POST', body: JSON.stringify({ platform, code, redirect_uri: redirectUri }) },
    ),

  disconnectAccount: (accountId: string) =>
    request<{ status: string; account_id: string }>(`/v1/publishing/accounts/${accountId}`, {
      method: 'DELETE',
    }),

  createSocialPost: (body: unknown) =>
    request<{ post: SocialPostResponse }>('/v1/publishing/posts', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  publishSocialPost: (postId: string, force = true) =>
    request<{ success: boolean; platform_post_id?: string; post_url?: string; error?: string }>(
      '/v1/publishing/posts/publish',
      { method: 'POST', body: JSON.stringify({ post_id: postId, force }) },
    ),

  bulkPublish: (body: unknown) =>
    request<{ total: number; succeeded: number; failed: number; results: unknown[] }>(
      '/v1/publishing/posts/bulk',
      { method: 'POST', body: JSON.stringify(body) },
    ),

  retrySocialPost: (postId: string) =>
    request<{ success: boolean; platform_post_id?: string; post_url?: string; error?: string }>(
      `/v1/publishing/posts/${postId}/retry`,
      { method: 'POST' },
    ),

  cancelSocialPost: (postId: string) =>
    request<{ status: string; post_id: string }>(`/v1/publishing/posts/${postId}/cancel`, {
      method: 'POST',
    }),

  listSocialPosts: (params?: { status?: string; platform?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.platform) qs.set('platform', params.platform);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const suffix = qs.toString() ? `?${qs}` : '';
    return request<{ posts: SocialPostResponse[]; total: number; limit: number; offset: number }>(
      `/v1/publishing/posts${suffix}`,
    );
  },

  getSocialPost: (postId: string) =>
    request<{ post: SocialPostResponse }>(`/v1/publishing/posts/${postId}`),

  // Media upload
  uploadMedia: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request<{ source_media_path: string; filename: string; file_size_bytes: number; duration_ms: number }>(
      '/v1/media/upload',
      { method: 'POST', body: formData },
    );
  },

  // Rendered asset download
  getDownloadUrl: (jobId: string) =>
    `${BASE_URL}/v1/render-jobs/${jobId}/download`,

  // Rights / provenance
  updateJobRights: (body: { job_id: string; rights_status: string; rights_owner?: string; rights_source?: string; rights_license?: string; rights_notes?: string }) =>
    request<{ job_id: string; rights_status: string }>('/v1/rights/update', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getJobRights: (jobId: string) =>
    request<{ job_id: string; rights_status: string; rights_owner: string | null; rights_source: string | null; rights_license: string | null; rights_notes: string | null }>(
      `/v1/rights/${jobId}`,
    ),

  // Scheduler
  evaluateSchedule: (body: unknown) =>
    request<{ decision: string; reasons: string[]; autopilot_enabled: boolean }>('/v1/scheduler/evaluate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  setAutopilot: (enabled: boolean) =>
    request<{ autopilot_enabled: boolean }>('/v1/scheduler/autopilot', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  getSchedulerStatus: () =>
    request<{ autopilot_enabled: boolean; min_quality_score: number; min_opportunity_score: number; min_platform_interval_hours: number }>(
      '/v1/scheduler/status',
    ),
};

export const apiConfigured = Boolean(API_KEY);
export const apiBaseUrl = BASE_URL || window.location.origin;
