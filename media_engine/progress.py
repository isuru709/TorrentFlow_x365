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
        
        self.current_file = None
        self.completed_bytes = 0
        self.current_file_downloaded = 0
        self.current_file_total = 0
        
    def hook(self, d: dict):
        with self._lock:
            filename = d.get('filename')
            
            if self.current_file != filename:
                # Switched to a new file (e.g. video finished, now downloading audio)
                if self.current_file is not None:
                    self.completed_bytes += self.current_file_total
                self.current_file = filename
                self.current_file_total = 0
                self.current_file_downloaded = 0
                
            if d['status'] == 'downloading':
                self.status = "downloading"
                self.current_file_downloaded = d.get('downloaded_bytes', self.current_file_downloaded)
                
                # yt-dlp might provide total_bytes or total_bytes_estimate
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                if total > self.current_file_total:
                    self.current_file_total = total
                    
                self.downloaded_bytes = self.completed_bytes + self.current_file_downloaded
                self.total_bytes = self.completed_bytes + self.current_file_total
                
                self.speed = d.get('speed') or 0.0
                self.eta = d.get('eta') or -1
                self.last_update = time.time()
                
            elif d['status'] == 'finished':
                self.status = "processing" # Next step is ffmpeg merge usually
                self.current_file_downloaded = d.get('total_bytes') or self.current_file_downloaded
                if self.current_file_downloaded > self.current_file_total:
                    self.current_file_total = self.current_file_downloaded
                    
                self.downloaded_bytes = self.completed_bytes + self.current_file_downloaded
                self.total_bytes = self.completed_bytes + self.current_file_total
                
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
