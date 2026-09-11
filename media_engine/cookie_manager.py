import os
from pathlib import Path
import time
from typing import Optional

# Using the same STATE_DIR as main.py
STATE_DIR = Path(os.getenv("STATE_DIR", "state"))
COOKIE_FILE = STATE_DIR / "cookies.txt"

class CookieManager:
    """Manages yt-dlp authentication cookies."""
    
    @staticmethod
    def save_cookies(cookie_data: bytes) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_bytes(cookie_data)
        
    @staticmethod
    def get_cookie_path() -> Optional[Path]:
        if not COOKIE_FILE.exists():
            return None
        
        # Check age (e.g. valid for 30 days)
        age_seconds = time.time() - COOKIE_FILE.stat().st_mtime
        if age_seconds > 30 * 24 * 60 * 60:
            return None # Cookies too old
            
        return COOKIE_FILE
        
    @staticmethod
    def get_cookie_status() -> dict:
        if not COOKIE_FILE.exists():
            return {"exists": False}
            
        stat = COOKIE_FILE.stat()
        age_seconds = time.time() - stat.st_mtime
        return {
            "exists": True,
            "size_bytes": stat.st_size,
            "age_seconds": int(age_seconds),
            "age_days": int(age_seconds / (24 * 60 * 60)),
            "last_modified": stat.st_mtime
        }
