"""
TorrentFlow x365 — High-Speed Torrent Downloader API
Modern async torrent client with real-time WebSocket updates
"""

import os
import asyncio
import logging
import time
import uuid
import json
import zipfile
import re
from pathlib import Path
from typing import Dict, List, Optional, Set
from contextlib import asynccontextmanager

try:
    import libtorrent as lt
    LIBTORRENT_AVAILABLE = True
except ImportError:
    lt = None
    LIBTORRENT_AVAILABLE = False

import httpx
from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    UploadFile, File, HTTPException, BackgroundTasks, Request
)
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# -----------------------
# Configuration
# -----------------------
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")

if LOG_FORMAT == "json":
    import json as _json

    class JsonFormatter(logging.Formatter):
        def format(self, record):
            return _json.dumps({
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            })

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)
else:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

logger = logging.getLogger('torrent-api')

if not LIBTORRENT_AVAILABLE:
    logger.warning(
        "libtorrent is NOT installed. Torrent functionality will be unavailable. "
        "Install via system package manager: apt-get install python3-libtorrent"
    )

# Directories
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/srv/torrent-downloader/downloads"))
TORRENT_DIR = Path(os.getenv("TORRENT_DIR", "/srv/torrent-downloader/torrents"))
TEMP_DIR = Path(os.getenv("TEMP_DIR", "/srv/torrent-downloader/temp"))
STATE_DIR = Path(os.getenv("STATE_DIR", "/srv/torrent-downloader/state"))

# Create directories
for directory in [DOWNLOAD_DIR, TORRENT_DIR, TEMP_DIR, STATE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Settings
MAX_DOWNLOAD_RATE = int(os.getenv("MAX_DOWNLOAD_RATE", "0"))  # 0 = unlimited (bytes/s)
MAX_UPLOAD_RATE = int(os.getenv("MAX_UPLOAD_RATE", "0"))  # 0 = unlimited (bytes/s)
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", "1000"))  # Seedbox-level connections
LISTEN_PORT_START = int(os.getenv("LISTEN_PORT_START", "6881"))
LISTEN_PORT_END = int(os.getenv("LISTEN_PORT_END", "6889"))
DHT_ENABLED = os.getenv("DHT_ENABLED", "true").lower() == "true"
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "false").lower() == "true"
API_KEY = os.getenv("API_KEY", "")

# -----------------------
# Models
# -----------------------
class TorrentAddRequest(BaseModel):
    url: str = Field(..., description="Magnet link, torrent URL, or info hash")
    save_path: Optional[str] = Field(None, description="Custom save path")
    sequential: bool = Field(False, description="Download sequentially")
    
    # Backwards compatibility
    magnet: Optional[str] = Field(None, description="Deprecated: use 'url' instead")
    
    def get_url(self) -> str:
        """Get the URL, supporting both 'url' and 'magnet' fields"""
        return self.url if self.url else (self.magnet or "")

class TorrentInfo(BaseModel):
    id: str
    name: str
    state: str
    progress: float
    download_rate: float
    upload_rate: float
    num_peers: int
    num_seeds: int
    total_size: int
    downloaded: int
    uploaded: int
    ratio: float
    eta: int
    save_path: str
    added_time: float

class TorrentFileInfo(BaseModel):
    path: str
    size: int
    progress: float

# -----------------------
# Torrent Manager
# -----------------------
class TorrentManager:
    def __init__(self):
        self.session = None
        self.torrents: Dict[str, object] = {}
        self.torrent_metadata: Dict[str, dict] = {}
        self.websocket_clients: Set[WebSocket] = set()
        self.completed_torrents: Dict[str, TorrentInfo] = {}
        self.completed_files: Dict[str, dict] = {}
        self._available = LIBTORRENT_AVAILABLE
        self._pending_removals: Set[str] = set()  # torrent IDs being deleted — skip in monitor loop
        
    async def initialize(self):
        """Initialize libtorrent session"""
        if not self._available:
            logger.error("Cannot initialize torrent session — libtorrent not installed")
            return

        logger.info("Initializing libtorrent session...")
        
        # Create session with HIGH-PERFORMANCE seedbox settings
        settings = {
            'enable_dht': DHT_ENABLED,
            'enable_lsd': True,
            'enable_upnp': True,
            'enable_natpmp': True,
            'listen_interfaces': f'0.0.0.0:{LISTEN_PORT_START}',
            'outgoing_interfaces': '',
            'announce_to_all_trackers': True,
            'announce_to_all_tiers': True,
            'auto_manage_interval': 5,
            'max_failcount': 1,
            
            # LOW-SEEDER OPTIMIZATIONS (Keep peers alive longer)
            'peer_timeout': 120,          # Don't drop peers too quickly (default 20)
            'inactivity_timeout': 180,    # Tolerate 3 mins of inactivity
            'connection_speed': 500,      # Give peers more time to handshake
            
            # AGGRESSIVE PERFORMANCE SETTINGS
            'aio_threads': 16,  # More async I/O threads
            'checking_mem_usage': 4096,  # 4GB for hash checking
            'cache_size': 16384,  # 16GB cache (seedbox level)
            'cache_expiry': 60,
            'disk_io_write_mode': 0,  # Enable OS cache
            'disk_io_read_mode': 0,
            
            # CONNECTION OPTIMIZATION
            'optimistic_disk_retry': 600,
            'max_queued_disk_bytes': int(50 * 1024 * 1024),  # 50MB queue
            'send_buffer_watermark': int(10 * 1024 * 1024),  # 10MB send buffer
            'send_buffer_low_watermark': int(5 * 1024 * 1024),
            'send_buffer_watermark_factor': 150,
            
            # AGGRESSIVE CONNECTION SETTINGS
            'connection_speed': 1000,  # Very fast connection attempts
            'connections_limit': int(MAX_CONNECTIONS),
            'connections_slack': 100,
            'unchoke_slots_limit': 100,  # Allow many simultaneous uploads
            'half_open_limit': 200,  # More simultaneous connection attempts
            
            # PEER MANAGEMENT - OPTIMIZED FOR LOW-SEEDER + SEEDING
            'choking_algorithm': 0,  # Fixed slots choking
            'seed_choking_algorithm': 1,  # Fastest upload (prioritize fast peers)
            'peer_turnover': 2,  # Relax turnover so we don't accidentally drop our only seeds
            'peer_turnover_cutoff': 90,  # Drop slowest 10% of peers (int percentage)
            'peer_turnover_interval': 300,  # Check every 5 minutes (more patience)
            'share_mode_target': 3,  # Super seeding ratio target
            'upload_rate_limit': int(MAX_UPLOAD_RATE if MAX_UPLOAD_RATE > 0 else 100 * 1024 * 1024),  # 100MB/s default
            
            # NETWORK SETTINGS
            'mixed_mode_algorithm': 0,  # Prefer TCP
            'enable_outgoing_utp': True,
            'enable_incoming_utp': True,
            'enable_outgoing_tcp': True,
            'enable_incoming_tcp': True,
            
            # BANDWIDTH OPTIMIZATION  
            'rate_limit_ip_overhead': True,
            'download_rate_limit': int(MAX_DOWNLOAD_RATE),
            'strict_super_seeding': False,  # Allow flexible super-seeding
            
            # ALERTS & MONITORING
            'alert_queue_size': 10000,
            'alert_mask': 0x7fffffff,
        }
        
        self.session = lt.session(settings)
        
        # Set rate limits
        if MAX_DOWNLOAD_RATE > 0:
            self.session.set_download_rate_limit(MAX_DOWNLOAD_RATE)
        if MAX_UPLOAD_RATE > 0:
            self.session.set_upload_rate_limit(MAX_UPLOAD_RATE)
        
        # Add DHT routers
        if DHT_ENABLED:
            self.session.add_dht_router("router.bittorrent.com", 6881)
            self.session.add_dht_router("router.utorrent.com", 6881)
            self.session.add_dht_router("dht.transmissionbt.com", 6881)
            self.session.add_dht_router("dht.libtorrent.org", 25401)
        
        logger.info(f"Session initialized. Listening on port {LISTEN_PORT_START}")
        
        # Restore previously active torrents from saved state
        await self.load_all_state()
        
        # Start monitoring task
        asyncio.create_task(self.monitor_torrents())
    
    async def shutdown(self):
        """Cleanup session — save all state before closing"""
        logger.info("Shutting down torrent session...")
        if self.session:
            self.session.pause()
            
            # Save resume data for all torrents
            await self.save_all_state()
            logger.info("All torrent state saved to disk.")
    
    def _require_session(self):
        """Raise an error if the torrent session is not available."""
        if not self._available or self.session is None:
            raise HTTPException(
                status_code=503,
                detail="Torrent engine unavailable. libtorrent is not installed on this server."
            )

    # -----------------------
    # State Persistence
    # -----------------------
    def _serialize_resume_alert(self, alert) -> bytes:
        """Convert a save_resume_data_alert to bencoded bytes.
        
        libtorrent 2.x: alert.params is add_torrent_params → use write_resume_data_buf()
        libtorrent 1.x fallback: alert.resume_data is a dict → bencode directly
        """
        # Try libtorrent 2.x API first (add_torrent_params based)
        if hasattr(alert, 'params'):
            params_obj = alert.params
            if hasattr(lt, 'write_resume_data_buf'):
                return lt.write_resume_data_buf(params_obj)
            elif hasattr(lt, 'write_resume_data'):
                return lt.bencode(lt.write_resume_data(params_obj))
        
        # Fallback: libtorrent 1.x dict-based API
        if hasattr(alert, 'resume_data') and isinstance(alert.resume_data, dict):
            return lt.bencode(alert.resume_data)
        
        raise RuntimeError("Cannot serialize resume data: unsupported libtorrent API")

    async def save_all_state(self):
        """Save resume data + metadata for every torrent so they survive restarts."""
        if not self._available or not self.session:
            return

        logger.info("Saving all torrent state...")
        
        # 1. Save libtorrent resume data for every active torrent
        handles_to_save: Dict[str, object] = {}
        for torrent_id, handle in list(self.torrents.items()):
            # Skip torrents being deleted
            if torrent_id in self._pending_removals:
                continue
            try:
                if handle.is_valid():
                    handle.save_resume_data(
                        lt.save_resume_flags_t.flush_disk_cache
                        | lt.save_resume_flags_t.save_info_dict
                    )
                    handles_to_save[torrent_id] = handle
            except RuntimeError as e:
                logger.warning(f"Could not request resume data for {torrent_id}: {e}")
        
        # 2. Collect resume data alerts (wait up to 10 seconds)
        if handles_to_save and self.session:
            remaining = len(handles_to_save)
            deadline = time.time() + 10
            while remaining > 0 and time.time() < deadline:
                alerts = self.session.pop_alerts()
                for alert in alerts:
                    if isinstance(alert, lt.save_resume_data_alert):
                        # Find which torrent_id this belongs to
                        for tid, h in handles_to_save.items():
                            try:
                                if h.is_valid() and h.info_hash() == alert.handle.info_hash():
                                    resume_path = STATE_DIR / f"{tid}.fastresume"
                                    resume_data = self._serialize_resume_alert(alert)
                                    resume_path.write_bytes(resume_data)
                                    remaining -= 1
                                    logger.debug(f"Saved resume data for {tid}")
                                    break
                            except Exception as e:
                                logger.warning(f"Failed to serialize resume data for {tid}: {e}")
                                remaining -= 1
                                break
                    elif isinstance(alert, lt.save_resume_data_failed_alert):
                        remaining -= 1
                if remaining > 0:
                    await asyncio.sleep(0.1)
        
        # 3. Persist metadata, completed torrents, and completed files as JSON
        self._save_state_json()
        
    def _save_state_json(self):
        """Write the current in-memory state to state.json (no libtorrent calls)."""
        state = {
            "torrent_metadata": {},
            "completed_torrents": {},
            "completed_files": {},
            "active_torrent_ids": list(self.torrents.keys()),
        }
        
        # Serialize torrent_metadata (all string-serializable values)
        for tid, meta in self.torrent_metadata.items():
            state["torrent_metadata"][tid] = {
                k: str(v) if isinstance(v, Path) else v
                for k, v in meta.items()
            }
        
        # Serialize completed torrents
        for tid, info in self.completed_torrents.items():
            state["completed_torrents"][tid] = info.model_dump()
        
        # Serialize completed files
        for tid, entry in self.completed_files.items():
            serialized_files = []
            for f in entry.get("files", []):
                serialized_files.append({
                    "index": f.get("index"),
                    "relative_path": f.get("relative_path", ""),
                    "absolute_path": str(f.get("absolute_path", "")),
                    "size": f.get("size", 0),
                    "media_type": f.get("media_type")
                })
            state["completed_files"][tid] = {
                "files": serialized_files,
                "save_path": str(entry.get("save_path", "")),
                "name": entry.get("name", "download"),
            }
        
        state_path = STATE_DIR / "state.json"
        try:
            state_path.write_text(json.dumps(state, indent=2, default=str))
            logger.info(f"State saved: {len(self.torrents)} active, {len(self.completed_torrents)} completed")
        except OSError as e:
            logger.error(f"Failed to save state.json: {e}")
    
    async def load_all_state(self):
        """Restore torrents from saved state after a restart."""
        if not self._available or not self.session:
            return

        state_path = STATE_DIR / "state.json"
        if not state_path.exists():
            logger.info("No saved state found — starting fresh.")
            return
        
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read state.json: {e}")
            return
        
        saved_metadata = state.get("torrent_metadata", {})
        saved_completed = state.get("completed_torrents", {})
        saved_completed_files = state.get("completed_files", {})
        active_ids = state.get("active_torrent_ids", [])
        
        restored_active = 0
        restored_completed = 0
        
        # 1. Restore completed torrent snapshots (no libtorrent handle needed)
        for tid, info_dict in saved_completed.items():
            try:
                self.completed_torrents[tid] = TorrentInfo(**info_dict)
                restored_completed += 1
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to restore completed torrent {tid}: {e}")
        
        for tid, entry in saved_completed_files.items():
            # Convert absolute_path strings back to Path objects
            files = []
            for f in entry.get("files", []):
                files.append({
                    "index": f.get("index"),
                    "relative_path": f.get("relative_path", ""),
                    "absolute_path": Path(f.get("absolute_path", "")),
                    "size": f.get("size", 0),
                    "media_type": f.get("media_type")
                })
            self.completed_files[tid] = {
                "files": files,
                "save_path": entry.get("save_path", ""),
                "name": entry.get("name", "download"),
            }
        
        # Restore metadata for completed torrents
        for tid, meta in saved_metadata.items():
            if tid not in active_ids:
                self.torrent_metadata[tid] = meta
        
        # 2. Restore active (in-progress) torrents via resume data
        for tid in active_ids:
            meta = saved_metadata.get(tid, {})
            resume_path = STATE_DIR / f"{tid}.fastresume"
            torrent_file_path = meta.get("torrent_file")
            save_path = meta.get("save_path", str(DOWNLOAD_DIR))
            
            try:
                params = {
                    'save_path': save_path,
                    'storage_mode': lt.storage_mode_t.storage_mode_sparse,
                    'flags': lt.torrent_flags.auto_managed,
                }
                
                # Load resume data if available
                if resume_path.exists():
                    try:
                        # In libtorrent 2.x, resume data is opaque bencoded bytes
                        params['resume_data'] = resume_path.read_bytes()
                    except OSError as e:
                        logger.warning(f"Bad resume data for {tid}: {e}")
                
                # Prefer .torrent file, then magnet/info_hash
                added = False
                if torrent_file_path and Path(torrent_file_path).exists():
                    try:
                        params['ti'] = lt.torrent_info(torrent_file_path)
                        handle = self.session.add_torrent(params)
                        added = True
                    except RuntimeError as e:
                        logger.warning(f"Failed to load .torrent for {tid}: {e}")
                
                if not added:
                    # Try to reconstruct from info_hash or original URL
                    info_hash = meta.get('info_hash')
                    url = meta.get('url', '')
                    magnet = None
                    
                    if info_hash:
                        magnet = f"magnet:?xt=urn:btih:{info_hash}"
                    elif url and url.lower().startswith('magnet:'):
                        magnet = url
                    elif meta.get('hash'):
                        magnet = f"magnet:?xt=urn:btih:{meta['hash']}"
                    
                    if magnet:
                        # For magnet + resume data, use add_magnet_uri
                        handle = lt.add_magnet_uri(self.session, magnet, params)
                        added = True
                    else:
                        logger.warning(f"Cannot restore torrent {tid}: no .torrent file or info hash")
                        continue
                
                if added:
                    self.torrents[tid] = handle
                    self.torrent_metadata[tid] = meta
                    self.boost_torrent_speed(handle)
                    restored_active += 1
                    logger.info(f"Restored active torrent {tid}: {meta.get('url', 'unknown')[:60]}")
            except RuntimeError as e:
                logger.error(f"Failed to restore torrent {tid}: {e}")
        
        logger.info(f"State restored: {restored_active} active, {restored_completed} completed")
    
    async def download_torrent_file(self, url: str) -> bytes:
        """Download .torrent file from URL with advanced anti-bot bypass"""
        
        # Extract potential info hash from URL for fallback
        hash_match = re.search(r'([0-9A-Fa-f]{40})', url)
        info_hash = hash_match.group(1) if hash_match else None
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
            'Referer': url.split('/torrent/')[0] if '/torrent/' in url else url.rsplit('/', 1)[0]
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=headers
            ) as client:
                logger.info(f"Downloading torrent from: {url}")
                response = await client.get(url)
                response.raise_for_status()
                
                content = response.content
                
                # Check if it's actually a torrent file (bencode format)
                if not content or len(content) < 20:
                    raise ValueError("Downloaded file is too small to be a valid torrent")
                
                # Torrent files start with 'd' (bencode dictionary)
                if not content.startswith(b'd'):
                    # Try to parse as text to give better error
                    try:
                        text_preview = content[:200].decode('utf-8', errors='ignore')
                        if 'html' in text_preview.lower() or '<' in text_preview:
                            raise ValueError("Received HTML instead of torrent file. The site may be blocking automated downloads.")
                    except ValueError:
                        raise
                    except UnicodeDecodeError:
                        pass
                    raise ValueError("Downloaded file is not a valid torrent file (invalid bencode format)")
                
                logger.info(f"Successfully downloaded torrent file ({len(content)} bytes)")
                return content
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.error(f"403 Forbidden - Site is blocking the download: {url}")
                
                # If we have info hash, suggest converting to magnet
                if info_hash:
                    magnet_suggestion = f"magnet:?xt=urn:btih:{info_hash}&dn=&tr=udp://open.demonii.com:1337/announce&tr=udp://tracker.openbittorrent.com:80&tr=udp://tracker.coppersurfer.tk:6969&tr=udp://glotorrents.pw:6969/announce&tr=udp://tracker.opentrackr.org:1337/announce&tr=udp://torrent.gresille.org:80/announce&tr=udp://p4p.arenabg.com:1337&tr=udp://tracker.leechers-paradise.org:6969"
                    raise HTTPException(
                        status_code=400,
                        detail=f"⚠️ The torrent site is blocking automated downloads.\n\n✅ SOLUTION: Use this magnet link instead:\n\n{magnet_suggestion}\n\n💡 Or visit the torrent page and copy the magnet link manually."
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="⚠️ The torrent site is blocking automated downloads.\n\n✅ SOLUTIONS:\n1. Find and copy the magnet link from the torrent page\n2. Download the .torrent file in your browser and upload it here\n3. Use a different torrent site"
                    )
            elif e.response.status_code == 404:
                raise HTTPException(status_code=400, detail="❌ Torrent not found (404). The link may be expired.")
            else:
                raise HTTPException(status_code=400, detail=f"HTTP {e.response.status_code}: {str(e)}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=400, detail="⏱️ Download timed out. The server may be slow or unavailable.")
        except HTTPException:
            raise
        except (OSError, ValueError) as e:
            logger.error(f"Failed to download torrent file: {e}")
            raise HTTPException(status_code=400, detail=f"Could not download torrent: {str(e)}")
    
    async def add_from_url(self, url: str, save_path: Optional[str] = None, sequential: bool = True) -> str:
        """
        Smart torrent adder - handles magnet links, torrent URLs, and info hashes
        """
        self._require_session()
        
        url = url.strip()
        torrent_id = str(uuid.uuid4())
        
        params = {
            'save_path': str(save_path or (DOWNLOAD_DIR / torrent_id)),
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            'flags': lt.torrent_flags.auto_managed | lt.torrent_flags.duplicate_is_error,
        }
        
        if sequential:
            params['flags'] |= lt.torrent_flags.sequential_download
        
        try:
            # Case 1: Magnet link
            if url.lower().startswith('magnet:'):
                handle = lt.add_magnet_uri(self.session, url, params)
                self.torrents[torrent_id] = handle
                
                # Extract info hash for resume persistence
                info_hash = ''
                try:
                    info_hash = str(handle.info_hash())
                except RuntimeError:
                    pass
                
                self.torrent_metadata[torrent_id] = {
                    'added_time': time.time(),
                    'source': 'magnet',
                    'url': url,
                    'info_hash': info_hash,
                    'save_path': params['save_path'],
                    'stopped_on_complete': False
                }
                
                # Apply speed boost
                self.boost_torrent_speed(handle)
                
                logger.info(f"Added torrent {torrent_id} from magnet link")
                
                # Immediately broadcast to WebSocket clients
                asyncio.create_task(self.broadcast_update())
                
                return torrent_id
            
            # Case 2: HTTP(S) URL - download torrent file
            elif url.lower().startswith(('http://', 'https://')):
                logger.info(f"Downloading torrent file from URL: {url}")
                torrent_data = await self.download_torrent_file(url)
                
                # Save torrent file
                torrent_file = TORRENT_DIR / f"{torrent_id}.torrent"
                torrent_file.write_bytes(torrent_data)
                
                # Add to session
                params['ti'] = lt.torrent_info(str(torrent_file))
                handle = self.session.add_torrent(params)
                
                # Extract info hash for resume persistence
                info_hash = ''
                try:
                    info_hash = str(handle.info_hash())
                except RuntimeError:
                    pass
                
                self.torrents[torrent_id] = handle
                self.torrent_metadata[torrent_id] = {
                    'added_time': time.time(),
                    'source': 'url',
                    'url': url,
                    'info_hash': info_hash,
                    'torrent_file': str(torrent_file),
                    'save_path': params['save_path'],
                    'stopped_on_complete': False
                }
                
                # Apply speed boost
                self.boost_torrent_speed(handle)
                
                logger.info(f"Added torrent {torrent_id} from URL")
                
                # Immediately broadcast to WebSocket clients
                asyncio.create_task(self.broadcast_update())
                
                return torrent_id
            
            # Case 3: Info hash (40 char hex)
            elif len(url) == 40 and all(c in '0123456789abcdefABCDEF' for c in url):
                magnet = f"magnet:?xt=urn:btih:{url}"
                handle = lt.add_magnet_uri(self.session, magnet, params)
                self.torrents[torrent_id] = handle
                self.torrent_metadata[torrent_id] = {
                    'added_time': time.time(),
                    'source': 'hash',
                    'hash': url,
                    'info_hash': url,
                    'save_path': params['save_path'],
                    'stopped_on_complete': False
                }
                
                # Apply speed boost
                self.boost_torrent_speed(handle)
                
                logger.info(f"Added torrent {torrent_id} from info hash")
                
                # Immediately broadcast to WebSocket clients
                asyncio.create_task(self.broadcast_update())
                
                return torrent_id
            
            else:
                raise ValueError("Invalid input. Expected magnet link, HTTP(S) URL, or 40-character info hash")
                
        except HTTPException:
            raise
        except (RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to add torrent: {e}")
            # Cleanup on failure
            if torrent_id in self.torrent_metadata:
                metadata = self.torrent_metadata[torrent_id]
                if 'torrent_file' in metadata:
                    Path(metadata['torrent_file']).unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(e))
    
    def enable_super_seeding(self, torrent_id: str):
        """Enable super-seeding mode for completed torrents to maximize upload speed"""
        if torrent_id not in self.torrents:
            return
        
        handle = self.torrents[torrent_id]
        status = handle.status()
        
        # Only enable for completed torrents
        if status.progress >= 1.0:
            try:
                # Super-seed mode for fast initial distribution
                handle.set_flags(lt.torrent_flags.super_seeding)
                
                # Force reannounce to get more leechers
                handle.force_reannounce()
                
                # Prioritize uploading
                handle.set_upload_limit(-1)  # Unlimited
                handle.set_max_uploads(-1)  # Unlimited slots
                
                logger.info(f"Super-seeding enabled for {status.name}")
            except RuntimeError as e:
                logger.warning(f"Failed to enable super-seeding: {e}")
    
    def boost_torrent_speed(self, handle):
        """Apply seedbox-level optimizations to a torrent handle"""
        # Add comprehensive public tracker list for maximum peer discovery
        public_trackers = [
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://open.stealth.si:80/announce",
            "udp://tracker.torrent.eu.org:451/announce",
            "udp://tracker.bittor.pw:1337/announce",
            "udp://public.popcorn-tracker.org:6969/announce",
            "udp://tracker.dler.org:6969/announce",
            "udp://exodus.desync.com:6969/announce",
            "udp://open.demonii.com:1337/announce",
            "udp://tracker.openbittorrent.com:6969/announce",
            "udp://tracker.coppersurfer.tk:6969/announce",
            "udp://tracker.leechers-paradise.org:6969/announce",
            "udp://tracker.internetwarriors.net:1337/announce",
            "udp://9.rarbg.to:2710/announce",
            "udp://9.rarbg.me:2710/announce",
            "udp://tracker.cyberia.is:6969/announce",
            "udp://retracker.lanta-net.ru:2710/announce",
            "udp://bt.xxx-tracker.com:2710/announce",
            "http://tracker.openbittorrent.com:80/announce",
            "udp://opentor.org:2710/announce",
        ]
        
        try:
            # Add all trackers
            for tracker in public_trackers:
                handle.add_tracker({'url': tracker, 'tier': 0})
            
            # Force announce to all trackers immediately
            handle.force_reannounce()
            
            # Apply HIGH-PERFORMANCE settings for download AND seeding
            handle.set_max_connections(300)  # Per-torrent connection limit (increased)
            handle.set_max_uploads(-1)  # Unlimited upload slots for fast seeding
            
            # Upload optimization for better ratios and faster seeding
            handle.set_upload_limit(-1)  # No upload limit per torrent
            
            # Priority settings
            handle.set_priority(255)  # Maximum priority
            
            logger.info(f"Speed boost applied: {len(public_trackers)} trackers, max connections: 300")
        except RuntimeError as e:
            logger.warning(f"Failed to boost torrent speed: {e}")

    def stop_if_completed(self, torrent_id: str, handle, status):
        """Stop seeding automatically once download finishes (keep files)."""
        metadata = self.torrent_metadata.get(torrent_id, {})
        if metadata.get('stopped_on_complete'):
            return

        try:
            # Snapshot file list and torrent info before removal
            try:
                torrent_info = handle.get_torrent_info()
                files_storage = torrent_info.files()
                files_snapshot = []
                for idx in range(files_storage.num_files()):
                    rel_path = files_storage.file_path(idx)
                    abs_path = Path(metadata.get('save_path', DOWNLOAD_DIR)) / rel_path
                    
                    ext = Path(rel_path).suffix.lower()
                    media_type = None
                    if ext in ('.mp4', '.mkv', '.avi', '.webm', '.mov'):
                        media_type = 'video'
                    elif ext in ('.mp3', '.flac', '.wav', '.m4a', '.ogg'):
                        media_type = 'audio'
                    elif ext in ('.srt', '.vtt', '.ass'):
                        media_type = 'subtitle'
                        
                    files_snapshot.append({
                        "index": idx,
                        "relative_path": rel_path,
                        "absolute_path": abs_path,
                        "size": files_storage.file_size(idx),
                        "media_type": media_type
                    })
            except RuntimeError:
                torrent_info = None
                files_snapshot = []

            # Pause torrent and disable uploads
            handle.pause()
            handle.set_upload_limit(0)
            handle.set_max_uploads(0)
            # Avoid super-seeding flags
            try:
                handle.unset_flags(lt.torrent_flags.super_seeding)
            except (RuntimeError, AttributeError):
                pass

            # Snapshot completed torrent for UI and downloads
            try:
                ratio = status.all_time_upload / max(status.all_time_download, 1)
                save_path = metadata.get('save_path', str(DOWNLOAD_DIR))
                snapshot_time = time.time()
                completed_info = TorrentInfo(
                    id=torrent_id,
                    name=status.name,
                    state="completed",
                    progress=100.0,
                    download_rate=0,
                    upload_rate=0,
                    num_peers=0,
                    num_seeds=0,
                    total_size=status.total_wanted,
                    downloaded=status.total_wanted,
                    uploaded=status.all_time_upload,
                    ratio=ratio,
                    eta=0,
                    save_path=save_path,
                    added_time=metadata.get('added_time', time.time())
                )
                self.completed_torrents[torrent_id] = completed_info
                self.completed_files[torrent_id] = {
                    "files": files_snapshot,
                    "save_path": save_path,
                    "name": torrent_info.name() if torrent_info else status.name,
                }

                # Prebuild zip once to make "Download all" instant
                if len(files_snapshot) > 1:
                    try:
                        self.build_zip_if_needed(
                            torrent_id,
                            files_snapshot,
                            torrent_info.name() if torrent_info else status.name,
                            snapshot_time,
                        )
                    except (OSError, zipfile.BadZipFile) as zip_err:
                        logger.warning(f"Failed to prebuild zip for {torrent_id}: {zip_err}")
            except (RuntimeError, ValueError) as snap_err:
                logger.warning(f"Failed to snapshot completed torrent {torrent_id}: {snap_err}")

            # Remove torrent from session to close all connections, keep files on disk
            try:
                if self.session and handle.is_valid():
                    self.session.remove_torrent(handle)
            except RuntimeError:
                pass

            metadata['stopped_on_complete'] = True
            # Use snapshot_time to keep zip cache freshness aligned
            metadata['completed_at'] = snapshot_time
            self.torrent_metadata[torrent_id] = metadata
            # Also drop from active handle map
            if torrent_id in self.torrents:
                self.torrents.pop(torrent_id, None)
            logger.info(f"Stopped seeding after completion: {status.name}")
        except RuntimeError as e:
            logger.warning(f"Failed to stop seeding for {torrent_id}: {e}")
    
    def add_torrent_file(self, torrent_data: bytes, save_path: Optional[str] = None, sequential: bool = True) -> str:
        """Add torrent from .torrent file"""
        self._require_session()
        
        torrent_id = str(uuid.uuid4())
        torrent_file = TORRENT_DIR / f"{torrent_id}.torrent"
        
        # Save torrent file
        torrent_file.write_bytes(torrent_data)
        
        params = {
            'save_path': str(save_path or (DOWNLOAD_DIR / torrent_id)),
            'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            'ti': lt.torrent_info(str(torrent_file)),
            'flags': lt.torrent_flags.auto_managed | lt.torrent_flags.duplicate_is_error,
        }
        
        if sequential:
            params['flags'] |= lt.torrent_flags.sequential_download
        
        try:
            handle = self.session.add_torrent(params)
            
            # Extract info hash for resume persistence
            info_hash = ''
            try:
                info_hash = str(handle.info_hash())
            except RuntimeError:
                pass
            
            self.torrents[torrent_id] = handle
            self.torrent_metadata[torrent_id] = {
                'added_time': time.time(),
                'info_hash': info_hash,
                'torrent_file': str(torrent_file),
                'save_path': params['save_path'],
                'stopped_on_complete': False
            }
            
            # Apply speed boost
            self.boost_torrent_speed(handle)
            
            logger.info(f"Added torrent {torrent_id} from file")
            
            # Immediately broadcast to WebSocket clients
            asyncio.create_task(self.broadcast_update())
            
            return torrent_id
            
        except RuntimeError as e:
            logger.error(f"Failed to add torrent file: {e}")
            torrent_file.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_torrent(self, torrent_id: str, delete_files: bool = False):
        """Remove a torrent with proper async cleanup.
        
        - Marks torrent as pending-removal so the monitor loop skips it.
        - Removes from libtorrent session (with delete_files flag if requested).
        - Waits for libtorrent's delete alert to confirm file removal.
        - Manually verifies + cleans up any leftover files.
        - Removes .fastresume file and .torrent file.
        - Purges from in-memory dicts and persists state.json.
        - Broadcasts an immediate WebSocket update.
        """
        if torrent_id in self.torrents:
            # 1. Guard: prevent monitor loop from touching this handle
            self._pending_removals.add(torrent_id)
            logger.info(f"[DELETE] Starting removal of active torrent {torrent_id} (delete_files={delete_files})")
            
            try:
                handle = self.torrents[torrent_id]
                metadata = self.torrent_metadata.get(torrent_id, {})
                save_path = metadata.get('save_path', str(DOWNLOAD_DIR))
                
                # Snapshot file paths before removal so we can verify cleanup
                file_paths = []
                try:
                    if handle.is_valid():
                        torrent_info = handle.get_torrent_info()
                        if torrent_info is not None:
                            files_storage = torrent_info.files()
                            for idx in range(files_storage.num_files()):
                                rel_path = files_storage.file_path(idx)
                                file_paths.append(Path(save_path) / rel_path)
                        else:
                            logger.warning(f"No torrent_info available for {torrent_id} (likely magnet with no metadata yet) — falling back to path-based deletion")
                            status = handle.status()
                            if status.name:
                                file_paths.append(Path(save_path) / status.name)
                except Exception as e:
                    logger.warning(f"[DELETE] Could not read metadata for {torrent_id}: {e}")
                
                # 2. Remove from libtorrent session
                try:
                    if delete_files:
                        # Try libtorrent 2.x API first, then 1.x
                        try:
                            self.session.remove_torrent(handle, lt.remove_flags_t.delete_files)
                        except AttributeError:
                            self.session.remove_torrent(handle, lt.options_t.delete_files)
                    else:
                        self.session.remove_torrent(handle)
                    logger.info(f"[DELETE] Torrent {torrent_id} removed from libtorrent session")
                except Exception as e:
                    logger.warning(f"[DELETE] session.remove_torrent failed for {torrent_id}: {e}")
                
                # 3. Wait for libtorrent delete alert (up to 5 seconds)
                try:
                    if delete_files and self.session:
                        deadline = time.time() + 5
                        delete_confirmed = False
                        while time.time() < deadline:
                            alerts = self.session.pop_alerts()
                            for alert in alerts:
                                alert_type = type(alert).__name__
                                if alert_type in ('torrent_deleted_alert', 'torrent_removed_alert'):
                                    delete_confirmed = True
                                    logger.info(f"[DELETE] Received {alert_type} for {torrent_id}")
                                    break
                                elif alert_type == 'torrent_delete_failed_alert':
                                    logger.warning(f"[DELETE] Received torrent_delete_failed_alert for {torrent_id}: {alert.message()}")
                                    delete_confirmed = True  # proceed to manual cleanup
                                    break
                            if delete_confirmed:
                                break
                            await asyncio.sleep(0.1)
                        
                        if not delete_confirmed:
                            logger.warning(f"[DELETE] No delete alert received within 5s for {torrent_id}, proceeding with manual cleanup")
                except Exception as e:
                    logger.warning(f"[DELETE] Error while waiting for deletion alerts: {e}")
                
                # 4. Manual file cleanup — verify libtorrent actually deleted them
                if delete_files:
                    try:
                        leftover_count = 0
                        for fp in file_paths:
                            if fp.exists():
                                try:
                                    if fp.is_dir():
                                        import shutil
                                        shutil.rmtree(fp)
                                    else:
                                        fp.unlink()
                                    leftover_count += 1
                                except OSError as e:
                                    logger.warning(f"[DELETE] Could not remove leftover {fp}: {e}")
                        if leftover_count:
                            logger.info(f"[DELETE] Manually removed {leftover_count} leftover items for {torrent_id}")
                        
                        # Also remove .parts temp files if they exist
                        parts_dir = Path(save_path) / ".parts"
                        if parts_dir.exists():
                            import shutil
                            try:
                                shutil.rmtree(parts_dir)
                                logger.info(f"[DELETE] Removed .parts directory for {torrent_id}")
                            except OSError as e:
                                logger.warning(f"[DELETE] Could not remove .parts directory: {e}")
                        
                        # Clean up empty directories
                        for fp in file_paths:
                            parent = fp.parent
                            while parent != Path(save_path) and parent != parent.parent:
                                try:
                                    parent.rmdir()  # only succeeds if empty
                                    parent = parent.parent
                                except OSError:
                                    break
                    except Exception as e:
                        logger.error(f"[DELETE] Unexpected error during manual file cleanup: {e}")
                
                # 5-7. Remove state files
                try:
                    resume_path = STATE_DIR / f"{torrent_id}.fastresume"
                    if resume_path.exists():
                        resume_path.unlink(missing_ok=True)
                        logger.info(f"[DELETE] Removed resume file {resume_path.name}")
                    
                    if 'torrent_file' in metadata:
                        Path(metadata['torrent_file']).unlink(missing_ok=True)
                        logger.info(f"[DELETE] Removed .torrent file")
                    
                    zip_path = TEMP_DIR / f"{torrent_id}.zip"
                    zip_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"[DELETE] Error cleaning state files: {e}")
                    
            finally:
                # 8. Always purge from all in-memory dicts
                self.torrents.pop(torrent_id, None)
                self.torrent_metadata.pop(torrent_id, None)
                self.completed_torrents.pop(torrent_id, None)
                self.completed_files.pop(torrent_id, None)
                self._pending_removals.discard(torrent_id)
                
                # 9. Persist state.json so torrent doesn't reappear on restart
                try:
                    self._save_state_json()
                except Exception as e:
                    logger.error(f"[DELETE] Failed to save state.json: {e}")
                
                # 10. Broadcast removal to WebSocket clients immediately
                logger.info(f"[DELETE] Cleanup complete for {torrent_id}, broadcasting update")
                await self.broadcast_update()
            
            return

        if torrent_id in self.completed_torrents:
            logger.info(f"[DELETE] Removing completed torrent {torrent_id} (delete_files={delete_files})")
            
            if delete_files:
                entry = self.completed_files.get(torrent_id, {})
                files_entry = entry.get("files", [])
                removed_count = 0
                for file_entry in files_entry:
                    try:
                        fp = Path(file_entry["absolute_path"])
                        if fp.exists():
                            fp.unlink()
                            removed_count += 1
                    except (OSError, KeyError) as e:
                        logger.warning(f"[DELETE] Could not remove completed file: {e}")
                logger.info(f"[DELETE] Removed {removed_count}/{len(files_entry)} completed files")

                # Attempt to clean up empty directories under save_path
                save_path = entry.get("save_path") or self.torrent_metadata.get(torrent_id, {}).get('save_path')
                if save_path:
                    try:
                        p = Path(save_path)
                        for parent in [p] + list(p.parents):
                            if str(parent) == '/':
                                break
                            if parent.exists():
                                try:
                                    parent.rmdir()
                                except OSError:
                                    break
                    except OSError:
                        pass

            # Remove .fastresume file
            resume_path = STATE_DIR / f"{torrent_id}.fastresume"
            resume_path.unlink(missing_ok=True)
            
            # Remove .torrent file
            metadata = self.torrent_metadata.get(torrent_id, {})
            if 'torrent_file' in metadata:
                Path(metadata['torrent_file']).unlink(missing_ok=True)

            # Purge from all in-memory dicts
            self.completed_torrents.pop(torrent_id, None)
            self.completed_files.pop(torrent_id, None)
            self.torrent_metadata.pop(torrent_id, None)

            # Remove cached zip if present
            zip_path = TEMP_DIR / f"{torrent_id}.zip"
            zip_path.unlink(missing_ok=True)
            
            # Persist state.json
            self._save_state_json()

            logger.info(f"[DELETE] Completed torrent {torrent_id} fully cleaned up")
            
            # Broadcast removal
            await self.broadcast_update()
            return

        raise HTTPException(status_code=404, detail="Torrent not found")
    
    def get_torrent_info(self, torrent_id: str) -> TorrentInfo:
        """Get detailed torrent information"""
        if torrent_id not in self.torrents:
            if torrent_id in self.completed_torrents:
                return self.completed_torrents[torrent_id]
            raise HTTPException(status_code=404, detail="Torrent not found")
        
        handle = self.torrents[torrent_id]
        status = handle.status()
        
        # Calculate ETA
        if status.download_rate > 0:
            eta = int((status.total_wanted - status.total_wanted_done) / status.download_rate)
        else:
            eta = -1
        
        # Calculate ratio
        ratio = status.all_time_upload / max(status.all_time_download, 1)
        
        metadata = self.torrent_metadata.get(torrent_id, {})
        
        state_str = str(status.state)
        if not status.has_metadata:
            state_str = "fetching metadata"
            
        return TorrentInfo(
            id=torrent_id,
            name=status.name or torrent_id,
            state=state_str,
            progress=status.progress * 100,
            download_rate=status.download_rate,
            upload_rate=status.upload_rate,
            num_peers=status.num_peers,
            num_seeds=status.num_seeds,
            total_size=status.total_wanted,
            downloaded=status.total_wanted_done,
            uploaded=status.all_time_upload,
            ratio=ratio,
            eta=eta,
            save_path=metadata.get('save_path', str(DOWNLOAD_DIR)),
            added_time=metadata.get('added_time', 0)
        )

    def get_torrent_files(self, torrent_id: str):
        """Return torrent files with absolute paths for download."""
        if torrent_id in self.torrents:
            handle = self.torrents[torrent_id]
            try:
                info = handle.get_torrent_info()
            except RuntimeError as e:
                raise HTTPException(status_code=400, detail=f"Could not read torrent metadata: {e}")

            save_path = Path(self.torrent_metadata.get(torrent_id, {}).get('save_path', str(DOWNLOAD_DIR)))

            files_storage = info.files()
            files = []
            for idx in range(files_storage.num_files()):
                rel_path = files_storage.file_path(idx)
                abs_path = save_path / rel_path
                
                # Determine media type for streaming support
                ext = Path(rel_path).suffix.lower()
                media_type = None
                if ext in ('.mp4', '.mkv', '.avi', '.webm', '.mov'):
                    media_type = 'video'
                elif ext in ('.mp3', '.flac', '.wav', '.m4a', '.ogg'):
                    media_type = 'audio'
                elif ext in ('.srt', '.vtt', '.ass'):
                    media_type = 'subtitle'
                    
                files.append({
                    "index": idx,
                    "relative_path": rel_path,
                    "absolute_path": abs_path,
                    "size": files_storage.file_size(idx),
                    "media_type": media_type
                })

            return files, info.name()

        if torrent_id in self.completed_files:
            entry = self.completed_files[torrent_id]
            return entry.get("files", []), entry.get("name", "download")

        raise HTTPException(status_code=404, detail="Torrent not found or already stopped")

    def build_zip_if_needed(self, torrent_id: str, files: List[dict], torrent_name: str, snapshot_time: float):
        """Return path to a cached zip, rebuilding only when needed."""
        zip_path = TEMP_DIR / f"{torrent_id}.zip"
        safe_base = "".join(c for c in (torrent_name or "download") if c not in "\\/:*?\"<>|").strip() or "download"

        # Reuse cached zip when fresh
        if zip_path.exists() and zip_path.stat().st_size > 0 and zip_path.stat().st_mtime >= snapshot_time:
            return zip_path, safe_base

        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zipf:
            for file_entry in files:
                zipf.write(file_entry["absolute_path"], arcname=file_entry["relative_path"])

        return zip_path, safe_base
    
    def list_torrents(self) -> List[TorrentInfo]:
        """List all torrents"""
        active = [self.get_torrent_info(tid) for tid in self.torrents.keys()]
        completed = list(self.completed_torrents.values())
        return sorted(active + completed, key=lambda t: t.added_time, reverse=True)
    
    def pause_torrent(self, torrent_id: str):
        """Pause a torrent"""
        if torrent_id not in self.torrents:
            raise HTTPException(status_code=404, detail="Torrent not found")
        handle = self.torrents[torrent_id]

        # Keep the torrent paused until the user explicitly resumes it
        try:
            handle.unset_flags(lt.torrent_flags.auto_managed)
        except RuntimeError:
            pass

        handle.pause()
        logger.info(f"Paused torrent {torrent_id}")
    
    def resume_torrent(self, torrent_id: str):
        """Resume a torrent"""
        if torrent_id not in self.torrents:
            raise HTTPException(status_code=404, detail="Torrent not found")
        handle = self.torrents[torrent_id]

        # Re-enable auto management once the user resumes
        try:
            handle.set_flags(lt.torrent_flags.auto_managed)
        except RuntimeError:
            pass

        handle.resume()
        logger.info(f"Resumed torrent {torrent_id}")
    
    async def broadcast_update(self):
        """Immediately broadcast current torrent state to all WebSocket clients"""
        if not self.websocket_clients:
            return
        
        try:
            torrents_data = [info.model_dump() for info in self.list_torrents()]
            disconnected = []
            
            for client in list(self.websocket_clients):
                try:
                    await client.send_json({
                        'type': 'update',
                        'torrents': torrents_data
                    })
                except Exception:
                    disconnected.append(client)
            
            # Remove disconnected clients
            for client in disconnected:
                self.websocket_clients.discard(client)
        except Exception as e:
            logger.error(f"Error broadcasting update: {e}")
    
    async def monitor_torrents(self):
        """Background task to monitor torrents and send updates.
        
        CRITICAL: State saving and WebSocket broadcasting are in separate
        try/except blocks so a failure in one never blocks the other.
        """
        last_state_save = time.time()
        STATE_SAVE_INTERVAL = 60  # Save state every 60 seconds
        
        # Track previous seed/peer counts for logging
        last_peer_counts = {} 
        last_reannounce = {}  
        
        while True:
            try:
                await asyncio.sleep(1.0)  # Update every 1s
            except Exception:
                continue
            
            # --- Phase 1: Check for completed torrents ---
            try:
                for torrent_id, handle in list(self.torrents.items()):
                    # Skip torrents being deleted
                    if torrent_id in self._pending_removals:
                        continue
                    try:
                        if not handle.is_valid():
                            continue
                        status = handle.status()
                        
                        # Peer/Seed tracking (Task 4)
                        prev_counts = last_peer_counts.get(torrent_id, (0, 0))
                        if prev_counts != (status.num_seeds, status.num_peers):
                            logger.info(f"[SWARM] {torrent_id[:8]} | Seeds: {prev_counts[0]}->{status.num_seeds} | Peers: {prev_counts[1]}->{status.num_peers} | State: {status.state}")
                            last_peer_counts[torrent_id] = (status.num_seeds, status.num_peers)
                        
                        # Check for fatal errors (Cleanup-on-failure)
                        err_msg = ""
                        if hasattr(status, 'errc') and status.errc and status.errc.value() != 0:
                            err_msg = status.errc.message()
                        elif hasattr(status, 'error') and status.error and str(status.error) != "":
                            err_msg = str(status.error)
                            
                        if err_msg and "No error" not in err_msg and "Success" not in err_msg:
                            logger.error(f"[SWARM] {torrent_id[:8]} | Fatal Error Detected: {err_msg}")
                            logger.info(f"Triggering automatic cleanup-on-failure for {torrent_id[:8]}")
                            asyncio.create_task(self.remove_torrent(torrent_id, delete_files=True))
                            continue

                        # Periodic re-announce for low-seeder torrents (every 5 mins)
                        now = time.time()
                        last_ann = last_reannounce.get(torrent_id, now)
                        if now - last_ann > 300 and not status.is_finished:
                            try:
                                logger.info(f"[SWARM] {torrent_id[:8]} | Forcing tracker re-announce to find new peers")
                                handle.force_reannounce()
                                last_reannounce[torrent_id] = now
                            except RuntimeError:
                                pass
                        
                        # Stop seeding once complete (keep files)
                        if status.progress >= 1.0:
                            self.stop_if_completed(torrent_id, handle, status)
                    except RuntimeError as e:
                        logger.debug(f"Error checking torrent status: {e}")
            except Exception as e:
                logger.error(f"Error in monitor completion check: {e}")
            
            # --- Phase 2: Periodically save state (isolated) ---
            try:
                now = time.time()
                if now - last_state_save >= STATE_SAVE_INTERVAL:
                    try:
                        await self.save_all_state()
                        last_state_save = now
                    except Exception as e:
                        logger.error(f"Periodic state save failed: {e}")
                        last_state_save = now  # Don't retry every second
            except Exception as e:
                logger.error(f"Error in monitor state save phase: {e}")
            
            # --- Phase 3: WebSocket broadcast (completely isolated from Phase 2) ---
            try:
                if self.websocket_clients:
                    torrents_data = [info.model_dump() for info in self.list_torrents()]
                    client_count = len(self.websocket_clients)
                    logger.debug(f"Broadcasting progress to {client_count} client(s): {len(torrents_data)} torrent(s)")
                    
                    disconnected = []
                    for client in list(self.websocket_clients):
                        try:
                            await client.send_json({
                                'type': 'update',
                                'torrents': torrents_data
                            })
                        except Exception:
                            disconnected.append(client)
                    
                    for client in disconnected:
                        self.websocket_clients.discard(client)
                    
                    sent_count = client_count - len(disconnected)
                    if disconnected:
                        logger.info(f"Broadcast sent to {sent_count}/{client_count} clients ({len(disconnected)} disconnected)")
            except Exception as e:
                logger.error(f"Error in monitor broadcast phase: {e}")

# -----------------------
# Global Manager Instance
# -----------------------
torrent_manager = TorrentManager()

# -----------------------
# FastAPI App
# -----------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    await torrent_manager.initialize()
    yield
    await torrent_manager.shutdown()

app = FastAPI(
    title="TorrentFlow x365",
    description="High-speed async torrent client with real-time WebSocket updates",
    version="2.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# -----------------------
# API Endpoints
# -----------------------
@app.get("/api/info")
async def api_info():
    return {
        "name": "TorrentFlow x365",
        "version": "2.0.0",
        "status": "running",
        "engine": "libtorrent" if LIBTORRENT_AVAILABLE else "unavailable",
    }

@app.get("/health")
async def health_check():
    import shutil
    
    # Get disk usage for download directory
    try:
        disk_usage = shutil.disk_usage(DOWNLOAD_DIR)
        storage_info = {
            "total_gb": round(disk_usage.total / (1024**3), 2),
            "used_gb": round(disk_usage.used / (1024**3), 2),
            "free_gb": round(disk_usage.free / (1024**3), 2),
            "used_percent": round((disk_usage.used / disk_usage.total) * 100, 1)
        }
    except OSError as e:
        logger.error(f"Failed to get disk usage: {e}")
        storage_info = {
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "used_percent": 0
        }
    
    return {
        "status": "healthy",
        "engine": "libtorrent" if LIBTORRENT_AVAILABLE else "unavailable",
        "active_torrents": len(torrent_manager.torrents),
        "completed_torrents": len(torrent_manager.completed_torrents),
        "connected_clients": len(torrent_manager.websocket_clients),
        "dht_enabled": DHT_ENABLED,
        "storage": storage_info
    }

@app.post("/admin/clean")
async def admin_clean(api_key: str = ""):
    """Manually trigger the deployment cleanup process"""
    if REQUIRE_AUTH and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    elif not REQUIRE_AUTH and API_KEY and api_key != API_KEY:
        # If API_KEY is set but REQUIRE_AUTH is false, still require it for admin
        raise HTTPException(status_code=401, detail="Invalid API Key")

    try:
        import cleanup
        result = cleanup.run_cleanup()
        return {"success": True, "message": "Cleanup complete", "details": result}
    except Exception as e:
        logger.error(f"Manual cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _get_dir_size_mb(path: Path) -> float:
    """Recursively calculate directory size in MB safely"""
    total = 0
    if not path.exists():
        return 0.0
    try:
        for f in path.rglob('*'):
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
    except Exception as e:
        logger.warning(f"Error reading size of {path}: {e}")
    return round(total / (1024 * 1024), 2)

@app.get("/admin/disk-usage")
async def admin_disk_usage(api_key: str = ""):
    """Diagnostic endpoint to track down exactly what is consuming space"""
    if REQUIRE_AUTH and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    elif not REQUIRE_AUTH and API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    directories_to_check = {
        "DOWNLOAD_DIR": DOWNLOAD_DIR,
        "TORRENT_DIR": TORRENT_DIR,
        "TEMP_DIR": TEMP_DIR,
        "STATE_DIR": STATE_DIR,
        "SYSTEM_TMP": Path("/tmp"),
        "VAR_TMP": Path("/var/tmp"),
        "PIP_CACHE": Path("/root/.cache"),
        "APT_CACHE": Path("/var/cache/apt"),
        "APP_DIR": Path("/app"),
    }

    breakdown = {}
    total_tracked_mb = 0.0

    for name, path in directories_to_check.items():
        if path.exists():
            size_mb = _get_dir_size_mb(path)
            breakdown[name] = {
                "path": str(path.absolute()),
                "size_mb": size_mb
            }
            total_tracked_mb += size_mb
        else:
            breakdown[name] = {
                "path": str(path.absolute()),
                "size_mb": 0.0,
                "note": "Directory does not exist"
            }
            
    # Include base storage metrics for context
    import shutil
    try:
        disk_usage = shutil.disk_usage(DOWNLOAD_DIR)
        system_total = round(disk_usage.total / (1024**2), 2)
        system_used = round(disk_usage.used / (1024**2), 2)
        system_free = round(disk_usage.free / (1024**2), 2)
    except OSError:
        system_total = system_used = system_free = 0.0

    return {
        "success": True,
        "system_storage_mb": {
            "total": system_total,
            "used": system_used,
            "free": system_free,
        },
        "tracked_total_mb": round(total_tracked_mb, 2),
        "untracked_mb": round(system_used - total_tracked_mb, 2) if system_used > total_tracked_mb else 0.0,
        "breakdown": breakdown
    }

@app.post("/api/download", response_model=dict)
async def add_torrent_download(request: TorrentAddRequest):
    """
    Add torrent from magnet link, torrent URL, or info hash.
    Supports:
    - Magnet links: magnet:?xt=urn:btih:...
    - Torrent URLs: http://site.com/file.torrent
    - Info hashes: 40-character hex string
    """
    try:
        url = request.get_url()
        if not url:
            raise HTTPException(status_code=400, detail="Missing 'url' or 'magnet' field")
        
        torrent_id = await torrent_manager.add_from_url(
            url,
            request.save_path,
            request.sequential
        )
        return {
            "success": True,
            "torrent_id": torrent_id,
            "message": "Torrent added successfully"
        }
    except HTTPException:
        raise
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/upload-torrent", response_model=dict)
async def upload_torrent_file(
    file: UploadFile = File(...),
    save_path: Optional[str] = None,
    sequential: bool = False
):
    """Upload and add .torrent file"""
    if not file.filename or not file.filename.endswith('.torrent'):
        raise HTTPException(status_code=400, detail="Invalid file type. Must be .torrent")
    
    try:
        torrent_data = await file.read()
        torrent_id = torrent_manager.add_torrent_file(torrent_data, save_path, sequential)
        return {
            "success": True,
            "torrent_id": torrent_id,
            "message": "Torrent file uploaded and added"
        }
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/torrents", response_model=List[TorrentInfo])
async def list_all_torrents():
    """List all torrents"""
    torrents = torrent_manager.list_torrents()
    return JSONResponse(content=[t.model_dump() for t in torrents], headers={"Cache-Control": "no-store"})

@app.get("/api/torrents/{torrent_id}", response_model=TorrentInfo)
async def get_torrent(torrent_id: str):
    """Get specific torrent information"""
    return torrent_manager.get_torrent_info(torrent_id)

@app.delete("/api/torrents/{torrent_id}")
async def delete_torrent(torrent_id: str, delete_files: bool = False):
    """Remove a torrent"""
    await torrent_manager.remove_torrent(torrent_id, delete_files)
    return {"success": True, "message": "Torrent removed"}

@app.post("/api/torrents/{torrent_id}/pause")
async def pause_download(torrent_id: str):
    """Pause a torrent"""
    torrent_manager.pause_torrent(torrent_id)
    return {"success": True, "message": "Torrent paused"}

@app.post("/api/torrents/{torrent_id}/resume")
async def resume_download(torrent_id: str):
    """Resume a torrent"""
    torrent_manager.resume_torrent(torrent_id)
    return {"success": True, "message": "Torrent resumed"}


@app.get("/api/torrents/{torrent_id}/download")
async def download_torrent_files(torrent_id: str, background_tasks: BackgroundTasks, file: Optional[str] = None):
    """Download torrent contents. Single file returns directly; multi-file torrents are zipped."""
    files, torrent_name = torrent_manager.get_torrent_files(torrent_id)

    existing_files = []
    for f in files:
        abs_path = Path(f["absolute_path"])
        if abs_path.exists():
            existing_files.append({**f, "absolute_path": abs_path})
    if not existing_files:
        raise HTTPException(status_code=404, detail="No files available yet. The torrent may still be downloading.")

    if file:
        requested = Path(file)
        if requested.is_absolute() or any(part in ("..", "") for part in requested.parts):
            raise HTTPException(status_code=400, detail="Invalid file path")

        for file_entry in existing_files:
            if Path(file_entry["relative_path"]) == requested:
                return FileResponse(
                    file_entry["absolute_path"],
                    filename=Path(file_entry["absolute_path"]).name,
                    media_type="application/octet-stream",
                )

        raise HTTPException(status_code=404, detail="Requested file not found in torrent contents")

    safe_base = "".join(c for c in (torrent_name or "download") if c not in '\\/:*?"<>|').strip() or "download"

    if len(existing_files) == 1:
        file_entry = existing_files[0]
        return FileResponse(
            file_entry["absolute_path"],
            filename=Path(file_entry["absolute_path"]).name,
            media_type="application/octet-stream",
        )

    snapshot_time = torrent_manager.torrent_metadata.get(torrent_id, {}).get('completed_at', time.time())

    try:
        zip_path, safe_base = torrent_manager.build_zip_if_needed(
            torrent_id,
            existing_files,
            torrent_name,
            snapshot_time,
        )

        return FileResponse(
            zip_path,
            filename=f"{safe_base}.zip",
            media_type="application/zip",
        )
    except (OSError, zipfile.BadZipFile) as e:
        # In case of partial/corrupt zip, remove and raise
        (TEMP_DIR / f"{torrent_id}.zip").unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to prepare download: {e}")


@app.get("/api/torrents/{torrent_id}/files")
async def list_torrent_files(torrent_id: str):
    """Return available files for a torrent (completed or in-progress)."""
    files, _ = torrent_manager.get_torrent_files(torrent_id)

    available_files = []
    for file_entry in files:
        abs_path = Path(file_entry["absolute_path"])
        if abs_path.exists():
            available_files.append({
                "index": file_entry.get("index"),
                "relative_path": file_entry["relative_path"],
                "size": file_entry.get("size", 0),
                "media_type": file_entry.get("media_type")
            })

    if not available_files:
        raise HTTPException(status_code=404, detail="No files available yet. The torrent may still be downloading.")

    return available_files

# -----------------------
# Streaming & Downloading
# -----------------------

async def _stream_file_helper(request: Request, id: str, file_index: int, api_key: str, as_attachment: bool = False):
    """Helper for streaming and direct downloading files with Range support"""
    if REQUIRE_AUTH and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    elif not REQUIRE_AUTH and API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
        
    try:
        files, _ = torrent_manager.get_torrent_files(id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
        
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="File index out of bounds")
        
    file_info = files[file_index]
    file_path = Path(file_info["absolute_path"])
    file_size = file_info["size"]
    
    # Parse Range header
    range_header = request.headers.get("Range", "")
    start = 0
    end = file_size - 1
    
    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
                
    # Limit chunk size to 2MB to keep connections fresh and avoid huge memory buffers
    chunk_size = min(end - start + 1, 1024 * 1024 * 2)
    end = start + chunk_size - 1
    
    handle = torrent_manager.torrents.get(id)
    info = None
    if handle and handle.is_valid():
        try:
            info = handle.get_torrent_info()
        except RuntimeError:
            pass

    async def file_streamer():
        bytes_to_read = chunk_size
        current_offset = start
        
        while bytes_to_read > 0:
            if handle and info:
                # Prioritize the piece we need right now
                try:
                    pr = info.map_file(file_index, current_offset, 1)[0]
                    wait_time = 0
                    # Wait up to ~45 seconds for the piece to avoid Heroku 55s timeout
                    while not handle.have_piece(pr.piece) and wait_time < 45:
                        handle.piece_priority(pr.piece, 7)
                        handle.set_piece_deadline(pr.piece, 0, 1) # alert_when_available
                        await asyncio.sleep(0.5)
                        wait_time += 0.5
                    
                    if not handle.have_piece(pr.piece):
                        # Heroku constraint: Break cleanly so the browser issues a new Range request
                        break
                except Exception as e:
                    logger.debug(f"Piece priority error: {e}")
                    
            if not file_path.exists():
                break
                
            try:
                with open(file_path, "rb") as f:
                    f.seek(current_offset)
                    read_size = min(bytes_to_read, 65536)
                    data = f.read(read_size)
                    
                    # If we read null bytes but we know the file isn't finished downloading,
                    # libtorrent might have pre-allocated it sparsely.
                    # Wait, if have_piece is true, data is valid. If we broke early, we don't read.
                    if not data:
                        break
                    yield data
                    current_offset += len(data)
                    bytes_to_read -= len(data)
            except Exception as e:
                logger.error(f"Stream read error: {e}")
                break

    # Determine Content-Type
    ext = file_path.suffix.lower()
    media_types = {
        '.mp4': 'video/mp4', '.webm': 'video/webm', '.mkv': 'video/x-matroska', '.avi': 'video/x-msvideo',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.flac': 'audio/flac'
    }
    content_type = media_types.get(ext, 'application/octet-stream')
    
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
        "Content-Type": content_type
    }
    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        
    if as_attachment:
        filename = file_path.name.encode('utf-8', 'ignore').decode('utf-8')
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        
    return StreamingResponse(
        file_streamer(), 
        status_code=206 if range_header else 200, 
        headers=headers
    )

@app.get("/api/torrents/{id}/stream/{file_index}")
async def stream_file(request: Request, id: str, file_index: int, api_key: str = ""):
    """Stream media file directly with Range support"""
    return await _stream_file_helper(request, id, file_index, api_key, as_attachment=False)

@app.get("/api/torrents/{id}/download/{file_index}")
async def download_file(request: Request, id: str, file_index: int, api_key: str = ""):
    """Download file directly"""
    return await _stream_file_helper(request, id, file_index, api_key, as_attachment=True)

@app.get("/api/torrents/{id}/subtitle/{file_index}")
async def subtitle_file(id: str, file_index: int, api_key: str = ""):
    """Serve subtitle, converting SRT to VTT on the fly for HTML5 compatibility"""
    if REQUIRE_AUTH and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    elif not REQUIRE_AUTH and API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
        
    try:
        files, _ = torrent_manager.get_torrent_files(id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
        
    if file_index < 0 or file_index >= len(files):
        raise HTTPException(status_code=404, detail="File index out of bounds")
        
    file_info = files[file_index]
    file_path = Path(file_info["absolute_path"])
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle file not found on disk yet")
        
    ext = file_path.suffix.lower()
    
    if ext == '.vtt':
        return FileResponse(file_path, media_type="text/vtt")
        
    if ext == '.srt':
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # Convert SRT to VTT
            content = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})', r'\1.\2', content)
            vtt_content = "WEBVTT\n\n" + content
            return StreamingResponse(
                iter([vtt_content.encode('utf-8')]), 
                media_type="text/vtt"
            )
        except Exception as e:
            logger.error(f"Subtitle conversion failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to parse subtitle")
            
    raise HTTPException(status_code=400, detail="Unsupported subtitle format")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time torrent updates"""
    await websocket.accept()
    torrent_manager.websocket_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total: {len(torrent_manager.websocket_clients)}")
    
    try:
        while True:
            # Keep connection alive and handle ping/pong
            await websocket.receive_text()
    except WebSocketDisconnect:
        torrent_manager.websocket_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected. Remaining: {len(torrent_manager.websocket_clients)}")
    except (RuntimeError, ConnectionError) as e:
        logger.error(f"WebSocket error: {e}")
        torrent_manager.websocket_clients.discard(websocket)

# Mount static files for web interface (must be last)
try:
    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
except (OSError, RuntimeError) as e:
    logger.warning(f"Could not mount web interface: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
