FROM python:3.13-slim

LABEL maintainer="torrent-downloader"
LABEL description="TorrentFlow x365 — High-Speed Torrent Downloader"

# Install system dependencies including libtorrent
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-libtorrent \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Make system-installed libtorrent visible to the container's Python
ENV PYTHONPATH="/usr/lib/python3/dist-packages"

# Create app directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY web/ ./web/

# Create necessary directories
RUN mkdir -p /downloads /torrents /temp /state

# Use PORT env var (Heroku assigns dynamically), default to 8080
ENV PORT=8080

# Expose ports
EXPOSE ${PORT} 6881-6889

# Health check using curl
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run application (shell form is required for Heroku $PORT expansion)
CMD uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
