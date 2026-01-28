# ⚡ QUICK REFERENCE - DEPLOY & TEST

## 🚀 Deploy Optimizations

```bash
cd torrent-downloader
sudo docker compose down
sudo docker compose up -d --build
```

## ✅ Verify It's Working

### 1. Check Logs
```bash
# Should see these messages:
sudo docker compose logs -f | grep -E "(Speed boost|Super-seeding|WebSocket)"

Expected output:
✓ "Speed boost applied: 21 trackers, max connections: 300"
✓ "Super-seeding enabled for <torrent-name>"
✓ "WebSocket client connected"
```

### 2. Test Web Interface
```
Open: http://YOUR_SERVER_IP:8080

Look for:
✓ Upload speed in header: "↓ 25 MB/s | ↑ 15 MB/s"
✓ 🌱 SEEDING badge on completed torrents
✓ Green border/highlight on seeders
✓ Smooth UI updates (every 500ms)
```

### 3. Test API
```bash
# Health check
curl http://localhost:8080/health | jq

Expected:
{
  "status": "healthy",
  "active_torrents": N,
  "dht_enabled": true,
  "storage": {
    "total_gb": XXX,
    "free_gb": XXX,
    ...
  }
}

# Check torrents
curl http://localhost:8080/api/torrents | jq

Look for:
- "num_seeds": >0 for good downloads
- "download_rate": >0 when downloading
- "upload_rate": >0 when seeding
```

## 📊 Performance Checklist

### Download Speed Test:
- [ ] Add popular torrent (100+ seeders)
- [ ] Within 60 seconds, should reach 20-50+ MB/s
- [ ] UI updates smoothly every 500ms
- [ ] Peer count increases quickly

### Upload Speed Test:
- [ ] Wait for download to complete
- [ ] Look for 🌱 SEEDING badge (automatic)
- [ ] Upload speed >0 in header
- [ ] Ratio increases over time
- [ ] Green highlight appears

### UI Responsiveness:
- [ ] Progress bar updates smoothly
- [ ] Speed changes visible within 500ms
- [ ] Add torrent → appears instantly
- [ ] Delete torrent → removes instantly
- [ ] Storage info updates every 30s

## 🔧 Quick Fixes

### Slow Download:
```bash
# Check seeders
curl http://localhost:8080/api/torrents | jq '.[].num_seeds'
# Should be >10 for fast downloads

# Check connections
sudo docker compose logs | grep "Speed boost"
# Should see "max connections: 300"
```

### No Upload Speed:
```bash
# Wait 2 minutes after completion
# Then check logs:
sudo docker compose logs | grep "Super-seeding"
# Should see "Super-seeding enabled"

# Check for leechers:
curl http://localhost:8080/api/torrents | jq '.[].num_peers'
# Need >0 peers to upload
```

### UI Not Updating:
```bash
# Check WebSocket
sudo docker compose logs | grep "WebSocket"
# Should see "client connected"

# Restart if needed:
sudo docker compose restart
```

## 📈 Success Metrics

### Good Performance:
- ✅ Download: 20-100 MB/s (depending on seeders)
- ✅ Upload: 5-50 MB/s (depending on leechers)
- ✅ UI updates: Every 500ms (smooth)
- ✅ Seeding badge: Auto-appears when done
- ✅ Ratio: Increases to >1.0 over time

### Excellent Performance:
- 🚀 Download: 50-120 MB/s (popular torrents)
- 🚀 Upload: 20-100 MB/s (many leechers)
- 🚀 UI: Instant response
- 🚀 Ratio: >2.0 (great seeder!)

## 🎯 What Changed (Summary)

| Setting | Before | After |
|---------|--------|-------|
| Max Connections | 200 | **1000** |
| Cache | 8GB | **16GB** |
| UI Updates | 1000ms | **500ms** |
| Upload Default | 50 MB/s | **100 MB/s** |
| Super-Seeding | Manual | **Auto** |
| Seeding Visual | None | **🌱 Badge** |
| Upload in Header | No | **Yes** |

## 📚 Documentation

Full details:
- **OPTIMIZATION_SUMMARY.md** - Complete overview
- **SPEED_OPTIMIZATIONS.md** - Download speed guide  
- **SEEDING_OPTIMIZATION.md** - Seeding & UI guide
- **DEPLOYMENT_STEPS.txt** - Deployment instructions

## 🆘 Support

Problems?
1. Check logs: `sudo docker compose logs -f`
2. Verify ports: `sudo ufw status`
3. Test API: `curl http://localhost:8080/health`
4. Read docs above

---

**Deploy now and enjoy seedbox-level performance!** ⚡
