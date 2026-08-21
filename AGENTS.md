# Base44 dev environment notes

- Two processes: React/Vite UI (`src/`, host port 3000) and FastAPI media service (`media_service/`, host port 8000). They are independent — the UI currently makes no calls to the API.
- Dev stack: `docker compose -f docker-compose.base44.yml up -d` (source bind-mounted, `--reload` / vite HMR).
- The API is fail-closed in `ENVIRONMENT=production` (requires real API_KEYS, WEBHOOK_SECRET, ffmpeg/ffprobe). Dev compose uses `ENVIRONMENT=development` with mock ASR/CLIP providers and local storage; ffmpeg is installed at container start.
- No external credentials required. Health: `curl localhost:8000/health`.
- Tests: `docker compose -f docker-compose.base44.yml exec api pytest`.
