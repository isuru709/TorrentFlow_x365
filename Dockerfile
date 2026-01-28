FROM python:3.11-slim

LABEL maintainer="torrent-downloader"
LABEL description="High-Speed Torrent Downloader with libtorrent"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libboost-all-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

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
RUN mkdir -p /downloads /torrents /temp

# Expose ports
EXPOSE 8080 6881-6889

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')"

# Run application with a single worker to keep torrent state consistent
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
