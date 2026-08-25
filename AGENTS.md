# Base44 dev environment notes

- Two processes: React/Vite UI (`src/`, host port 3000) and FastAPI media service (`media_service/`, host port 8000). The UI calls the API via `VITE_API_URL`.
- Dev stack: `docker compose -f docker-compose.base44.yml up -d` (source bind-mounted, `--reload` / vite HMR).
- The API uses real FFmpeg for rendering when the binary is available (installed in the compose container). Set `RENDERER_MODE=mock` to force the mock renderer (used in tests via conftest.py).
- The API is fail-closed in `ENVIRONMENT=production` (requires real API_KEYS, WEBHOOK_SECRET, ffmpeg/ffprobe, real ASR/CLIP providers). Dev compose uses `ENVIRONMENT=development` with mock ASR/CLIP providers and local storage; ffmpeg is installed at container start and used for real rendering.
- No external credentials required for core functionality. Health: `curl localhost:8000/health`.
- Tests: `docker compose -f docker-compose.base44.yml exec api pytest` (152 tests, all passing).
- Frontend: `docker compose -f docker-compose.base44.yml exec web npm run lint && npm run build`.
- Key endpoints: `/v1/media/upload` (video upload), `/v1/render-jobs` (create+render), `/v1/render-jobs/{id}/download` (download output), `/v1/rights/update` (provenance), `/v1/scheduler/evaluate` (non-spam publishing decision), `/v1/publishing/*` (social publishing), `/v1/export/google-sheets` (export).
- Engine Room endpoints: `/v1/engine/jobs` (create/list), `/v1/engine/jobs/{id}` (detail+events), `/v1/engine/state` (system state), `/v1/engine/events` (event stream), `/v1/engine/test-source` (generate real FFmpeg test video), `/v1/engine/jobs/{id}/export` (download real rendered file), `/v1/engine/jobs/{id}/output` (validate real output), `/v1/engine/jobs/{id}/publish-gate` (separate compliance decisions: publishability, ai_disclosure, monetization, account_risk, api_status), `/v1/engine/readiness` (production readiness: engine, renderer, storage, workers, publishing, compliance, export), `/v1/engine/jobs/{id}/retry`, `/v1/engine/jobs/{id}/cancel`, `/v1/engine/pause`, `/v1/engine/resume`, `/v1/engine/workers/{id}/stop`, `/v1/engine/workers/{id}/start`.
- Vite `allowedHosts: true` — accepts the preview's external hostname.
