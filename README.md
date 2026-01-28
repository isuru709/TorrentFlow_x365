# ⚡ High-Speed Torrent Downloader

Modern, high-performance torrent downloader built with Python, FastAPI, and libtorrent. Features real-time WebSocket updates, RESTful API, and beautiful web interface.

## 🚀 Features

- **High Performance**: Built on libtorrent with optimized settings for maximum speed
- **Real-time Updates**: WebSocket connection for live torrent status
- **Modern API**: RESTful API with FastAPI and automatic documentation
- **Web Interface**: Beautiful, responsive UI for managing downloads
- **DHT Support**: Trackerless torrent support with distributed hash table
- **Sequential Downloads**: Option to download files in order (great for streaming)
- **Docker Support**: Easy deployment with Docker Compose
- **Resume Support**: Automatically resume interrupted downloads
- **Multiple Formats**: Support for magnet links and .torrent files

## 📋 Requirements

- Python 3.11+
- Docker & Docker Compose (for container deployment)
- Or: Linux server with root access (for manual deployment)

## 🐳 Quick Start (Docker)

1. **Clone or download this folder**

2. **Configure environment**:
   ```bash
   cp .env.example .env
   nano .env  # Edit settings
   ```

3. **Start the service**:
   ```bash
   docker compose up -d
   ```

4. **Access the application**:
   - Web Interface: http://localhost:8080
   - API Docs: http://localhost:8080/docs

## 🛠️ Manual Installation

See [DEPLOYMENT_STEPS.txt](DEPLOYMENT_STEPS.txt) for detailed manual installation instructions.

## 📡 API Endpoints

### Add Torrent (Magnet)
```bash
POST /api/download
Content-Type: application/json

{
  "magnet": "magnet:?xt=urn:btih:...",
  "save_path": "/custom/path",  # optional
  "sequential": false            # optional
}
```

### Upload Torrent File
```bash
POST /api/upload-torrent
Content-Type: multipart/form-data

file: <.torrent file>
sequential: false  # optional
```

### List All Torrents
```bash
GET /api/torrents
```

### Get Torrent Info
```bash
GET /api/torrents/{torrent_id}
```

### Remove Torrent
```bash
DELETE /api/torrents/{torrent_id}?delete_files=false
```

### Pause/Resume
```bash
POST /api/torrents/{torrent_id}/pause
POST /api/torrents/{torrent_id}/resume
```

### WebSocket (Real-time Updates)
```javascript
ws://localhost:8080/ws
```

## 🔧 Configuration

Edit `.env` file or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DOWNLOAD_DIR` | `/srv/torrent-downloader/downloads` | Download directory |
| `TORRENT_DIR` | `/srv/torrent-downloader/torrents` | Torrent files directory |
| `MAX_DOWNLOAD_RATE` | `0` | Max download speed (0=unlimited, bytes/s) |
| `MAX_UPLOAD_RATE` | `0` | Max upload speed (0=unlimited, bytes/s) |
| `MAX_CONNECTIONS` | `200` | Maximum peer connections |
| `LISTEN_PORT_START` | `6881` | Start of port range |
| `LISTEN_PORT_END` | `6889` | End of port range |
| `DHT_ENABLED` | `true` | Enable DHT (trackerless torrents) |

## 🎯 Usage Examples

### Using cURL

**Add magnet link**:
```bash
curl -X POST http://localhost:8080/api/download \
  -H "Content-Type: application/json" \
  -d '{"magnet": "magnet:?xt=urn:btih:..."}'
```

**List torrents**:
```bash
curl http://localhost:8080/api/torrents
```

**Upload torrent file**:
```bash
curl -X POST http://localhost:8080/api/upload-torrent \
  -F "file=@ubuntu.torrent"
```

### Using Python

```python
import requests

# Add magnet
response = requests.post(
    "http://localhost:8080/api/download",
    json={"magnet": "magnet:?xt=urn:btih:..."}
)
print(response.json())

# List torrents
torrents = requests.get("http://localhost:8080/api/torrents").json()
for torrent in torrents:
    print(f"{torrent['name']}: {torrent['progress']:.1f}%")
```

## 📊 Performance Tuning

For maximum performance:

1. **Increase system limits** (see DEPLOYMENT_STEPS.txt)
2. **Use SSD** for download directory
3. **Increase cache size** in main.py:
   ```python
   'cache_size': 16384,  # 16GB cache
   ```
4. **Optimize connections**:
   ```python
   'connections_limit': 500,
   'connection_speed': 1000,
   ```

## 🔒 Security

- **Firewall**: Only open necessary ports (80, 443, 6881-6889)
- **Authentication**: Set `REQUIRE_AUTH=true` and `API_KEY` in .env
- **SSL**: Use nginx with Let's Encrypt for HTTPS
- **Rate Limiting**: Configure upload limits to avoid ISP throttling

## 📝 Logs

**Docker**:
```bash
docker compose logs -f
```

**Manual**:
```bash
journalctl -u torrent-downloader -f
tail -f /var/log/torrent-downloader.log
```

## 🐛 Troubleshooting

### No peers connecting
- Check firewall rules
- Ensure ports 6881-6889 are open (TCP & UDP)
- Verify DHT is enabled
- Try adding trackers manually

### Slow download speeds
- Increase MAX_CONNECTIONS
- Check your ISP isn't throttling BitTorrent
- Use torrents with more seeds
- Disable upload rate limit temporarily

### High CPU/Memory usage
- Reduce cache_size
- Lower connections_limit
- Pause some torrents

## 🤝 Contributing

Feel free to open issues or submit pull requests!

## 📄 License

MIT License - free to use and modify

## 🌟 Credits

- Built with [libtorrent](https://www.libtorrent.org/)
- [FastAPI](https://fastapi.tiangolo.com/)
- Modern web technologies

---

**Made with ❤️ for the community**
