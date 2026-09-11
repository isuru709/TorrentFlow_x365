import time
import threading

class ProgressHook:
    """Thread-safe progress bridge between yt-dlp's hook and asyncio loops."""
    def __init__(self):
        self._lock = threading.Lock()
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = 0.0
        self.eta = -1
        self.status = "downloading"
        self.error = None
        self.last_update = time.time()
        
    def hook(self, d: dict):
        with self._lock:
            if d['status'] == 'downloading':
                self.status = "downloading"
                self.downloaded_bytes = d.get('downloaded_bytes', self.downloaded_bytes)
                
                # yt-dlp might provide total_bytes or total_bytes_estimate
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                if total > self.total_bytes:
                    self.total_bytes = total
                    
                self.speed = d.get('speed') or 0.0
                self.eta = d.get('eta') or -1
                self.last_update = time.time()
                
            elif d['status'] == 'finished':
                self.status = "processing" # Next step is ffmpeg merge usually
                self.downloaded_bytes = d.get('total_bytes') or self.downloaded_bytes
                if self.downloaded_bytes > self.total_bytes:
                    self.total_bytes = self.downloaded_bytes
                self.speed = 0.0
                self.eta = 0
                self.last_update = time.time()
                
            elif d['status'] == 'error':
                self.status = "error"
                self.error = str(d.get('error', 'Unknown error'))
                self.speed = 0.0
                self.last_update = time.time()

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "downloaded": self.downloaded_bytes,
                "total": self.total_bytes,
                "speed": self.speed,
                "eta": self.eta,
                "status": self.status,
                "error": self.error
            }
