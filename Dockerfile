FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=3000

# Install system dependencies (FFmpeg, ffprobe, ca-certificates, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user
RUN groupadd -r oracleclip && useradd -r -g oracleclip -d /app oracleclip

# Create working directory and storage directory with appropriate permissions
WORKDIR /app
RUN mkdir -p /app/storage && chown -R oracleclip:oracleclip /app

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=oracleclip:oracleclip . .

# Switch to non-root user
USER oracleclip

# Expose container port
EXPOSE 3000

# Health check using liveness probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/health || exit 1

# Start the FastAPI media service
CMD ["python3", "-m", "uvicorn", "media_service.api.app:app", "--host", "0.0.0.0", "--port", "3000"]
