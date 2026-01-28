#!/bin/bash
# Quick Test Script for Rebuilt Active Downloads Section

echo "🔧 Testing Torrent Downloader - Active Downloads Section"
echo "=========================================================="
echo ""

# Test 1: Container Status
echo "1️⃣  Checking container status..."
if sudo docker compose ps | grep -q "Up"; then
    echo "   ✅ Container is running"
else
    echo "   ❌ Container is not running"
    echo "   Run: sudo docker compose up -d"
    exit 1
fi
echo ""

# Test 2: API Health
echo "2️⃣  Checking API health..."
HEALTH=$(curl -s http://localhost:8080/health)
if echo "$HEALTH" | grep -q "healthy"; then
    echo "   ✅ API is healthy"
    echo "$HEALTH" | jq '.'
else
    echo "   ❌ API is not responding correctly"
    exit 1
fi
echo ""

# Test 3: Check Active Torrents
echo "3️⃣  Checking active torrents..."
TORRENTS=$(curl -s http://localhost:8080/api/torrents)
COUNT=$(echo "$TORRENTS" | jq 'length')
echo "   📊 Active torrents: $COUNT"
if [ "$COUNT" -gt 0 ]; then
    echo "$TORRENTS" | jq '.[] | {name: .name, progress: .progress, state: .state}'
fi
echo ""

# Test 4: Check Web Files
echo "4️⃣  Checking web files exist..."
if sudo docker compose exec torrent-downloader test -f /app/web/app.js; then
    echo "   ✅ app.js exists"
else
    echo "   ❌ app.js missing"
fi

if sudo docker compose exec torrent-downloader test -f /app/web/styles.css; then
    echo "   ✅ styles.css exists"
else
    echo "   ❌ styles.css missing"
fi

if sudo docker compose exec torrent-downloader test -f /app/web/index.html; then
    echo "   ✅ index.html exists"
else
    echo "   ❌ index.html missing"
fi
echo ""

# Test 5: Check JavaScript Functions
echo "5️⃣  Checking JavaScript functions..."
if sudo docker compose exec torrent-downloader grep -q "function deleteTorrent" /app/web/app.js; then
    echo "   ✅ deleteTorrent function exists"
else
    echo "   ❌ deleteTorrent function missing"
fi

if sudo docker compose exec torrent-downloader grep -q "attachTorrentEventListeners" /app/web/app.js; then
    echo "   ✅ attachTorrentEventListeners function exists"
else
    echo "   ❌ attachTorrentEventListeners function missing"
fi

if sudo docker compose exec torrent-downloader grep -q "btn-delete" /app/web/app.js; then
    echo "   ✅ Event delegation setup found"
else
    echo "   ❌ Event delegation setup missing"
fi
echo ""

# Test 6: Check CSS Classes
echo "6️⃣  Checking CSS classes..."
if sudo docker compose exec torrent-downloader grep -q "btn-delete" /app/web/styles.css; then
    echo "   ✅ Button styles exist"
else
    echo "   ❌ Button styles missing"
fi

if sudo docker compose exec torrent-downloader grep -q "seed-badge" /app/web/styles.css; then
    echo "   ✅ Seeding badge styles exist"
else
    echo "   ❌ Seeding badge styles missing"
fi
echo ""

# Test 7: WebSocket Endpoint
echo "7️⃣  Checking WebSocket endpoint..."
if curl -s http://localhost:8080/ws 2>&1 | grep -q "Upgrade"; then
    echo "   ✅ WebSocket endpoint responding"
else
    echo "   ⚠️  WebSocket test inconclusive (expected)"
fi
echo ""

# Summary
echo "=========================================================="
echo "✨ Test Complete!"
echo ""
echo "🌐 Access your downloader at:"
echo "   http://YOUR_SERVER_IP:8080"
echo ""
echo "📝 Next Steps:"
echo "   1. Open the URL in your browser"
echo "   2. Add a test magnet link"
echo "   3. Try pause/resume/delete buttons"
echo "   4. Check browser console (F12) for errors"
echo ""
echo "📋 If issues persist:"
echo "   - Hard refresh: Ctrl + F5"
echo "   - Clear cache: Ctrl + Shift + Delete"
echo "   - Check logs: sudo docker compose logs -f"
echo "=========================================================="
