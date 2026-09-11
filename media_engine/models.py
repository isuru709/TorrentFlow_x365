from pydantic import BaseModel
from typing import List, Optional

class MediaJob(BaseModel):
    """A yt-dlp download job — mirrors TorrentInfo's shape for UI compatibility."""
    id: str
    name: str
    state: str                    # "probing" | "downloading" | "processing" | "completed" | "error" | "cancelled"
    progress: float               # 0.0–100.0
    download_rate: float          # bytes/sec
    upload_rate: float = 0        # always 0 for yt-dlp
    num_peers: int = 0            # always 0
    num_seeds: int = 0            # always 0
    total_size: int               # bytes (from probe, may be 0 if unknown)
    downloaded: int               # bytes downloaded so far
    uploaded: int = 0
    ratio: float = 0.0
    eta: int                      # seconds, -1 if unknown
    save_path: str
    added_time: float
    files_available: bool = True
    # yt-dlp specific
    job_type: str = "media"       # "media" (vs "torrent" for torrent jobs)
    thumbnail: str = ""
    url: str = ""
    error_message: str = ""
    is_playlist: bool = False

class FormatInfo(BaseModel):
    format_id: str
    ext: str
    resolution: str               # "1080p", "720p", "audio only", etc.
    fps: Optional[float]
    vcodec: str
    acodec: str
    filesize: Optional[int]       # bytes, None if unknown
    tbr: Optional[float]          # total bitrate kbps
    format_note: str
    is_default: bool = False      # pre-selected best format

class ProbeResult(BaseModel):
    title: str
    duration: Optional[int]       # seconds
    thumbnail: Optional[str]
    uploader: str
    formats: List[FormatInfo]
    subtitles: List[str]          # language codes: ["en", "es", ...]
    url: str
    extractor: str                # "youtube", "twitter", etc.
    is_playlist: bool = False     # true if url points to a playlist
    playlist_count: Optional[int] = 0 # number of videos in playlist
