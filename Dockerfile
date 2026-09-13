FROM python:3.13-slim

LABEL maintainer="torrent-downloader"
LABEL description="TorrentFlow x365 — High-Speed Torrent Downloader"

# Install system dependencies including libtorrent
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-libtorrent \
    curl \
    ffmpeg \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

# Make system-installed libtorrent visible to the container's Python
ENV PYTHONPATH="/usr/lib/python3/dist-packages"

# Create app directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create yt-dlp plugin directory for community plugins
RUN mkdir -p /root/.yt-dlp/plugins

# Copy application code
COPY main.py .
COPY cleanup.py .
COPY media_routes.py .
COPY media_engine/ ./media_engine/
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

# Auto-upgrade yt-dlp and tools on every startup (before Python imports),
# then start the application. This ensures dynos always have the latest
# extractors/fixes after daily restarts — mirrors VB.NET client's yt-dlp -U.
CMD pip install --upgrade --quiet yt-dlp streamlink gallery-dl curl_cffi 2>/dev/null; \
    python -c "import yt_dlp; print(f'yt-dlp version: {yt_dlp.version.__version__}')"; \
    uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1

