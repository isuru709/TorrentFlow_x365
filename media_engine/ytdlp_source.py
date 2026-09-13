import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Optional, List, Dict
import yt_dlp

from .models import MediaJob, ProbeResult, FormatInfo
from .progress import ProgressHook

logger = logging.getLogger("yt-dlp-source")

# Check if aria2c is available for multi-connection downloads
ARIA2C_AVAILABLE = shutil.which("aria2c") is not None
if ARIA2C_AVAILABLE:
    logger.info("aria2c found — will use as external downloader for faster downloads")


class DownloadCancelled(Exception):
    pass

class YtDlpSource:
    """Wraps yt-dlp's Python API for a single download job or playlist.
    
    No cookies are used — dynos refresh daily making cookies stale.
    Uses aria2c as external downloader when available for faster multi-connection downloads.
    """

    def __init__(self, job_id: str, url: str, format_id: str,
                 save_dir: Path, embed_subs: bool, is_playlist: bool = False):
        self.job_id = job_id
        self.url = url
        self.format_id = format_id
        self.save_dir = save_dir
        self.embed_subs = embed_subs
        self.is_playlist = is_playlist
        
        self.progress_hook = ProgressHook()
        self._cancel_flag = False
        self._added_time = time.time()
        self._metadata = None
        self._completed_files = []
        self._error = None

    @staticmethod
    def _base_opts() -> dict:
        """Common yt-dlp options for all operations (no cookies, robust defaults)."""
        opts = {
            'quiet': True,
            'no_warnings': True,
            # Retry on failures
            'retries': 10,
            'fragment_retries': 10,
            # Don't check certificates (some sites have issues in containers)
            'nocheckcertificate': True,
            # Geo bypass
            'geo_bypass': True,
            # Use iOS/mweb player clients for YouTube to bypass
            # "Sign in to confirm you're not a bot" on server IPs
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios,mweb'],
                }
            },
        }
        # Use browser impersonation if curl_cffi is available
        # (installed via Dockerfile CMD before Python starts)
        try:
            import curl_cffi  # noqa: F401
            opts['impersonate'] = 'chrome'
        except ImportError:
            pass
        return opts

    @staticmethod
    def probe(url: str, cookie_path: Optional[Path] = None) -> ProbeResult:
        ydl_opts = YtDlpSource._base_opts()
        ydl_opts.update({
            'skip_download': True,
            'extract_flat': 'in_playlist',
        })
        # cookie_path parameter kept for API compatibility but not used
        # Dynos restart daily — cookies go stale, downloads work without them
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            is_playlist = 'entries' in info
            playlist_count = len(info.get('entries', [])) if is_playlist else 0
            
            # If it's a playlist, we might just return the playlist info and not the detailed formats of the first video
            if is_playlist:
                return ProbeResult(
                    title=info.get('title', 'Playlist'),
                    duration=None,
                    thumbnail=None,
                    uploader=info.get('uploader', 'Unknown'),
                    formats=[],
                    subtitles=[],
                    url=url,
                    extractor=info.get('extractor', 'unknown'),
                    is_playlist=True,
                    playlist_count=playlist_count
                )
            
            formats = []
            for f in info.get('formats', []):
                # Filter out useless formats
                if f.get('vcodec') == 'none' and f.get('acodec') == 'none':
                    continue
                    
                formats.append(FormatInfo(
                    format_id=f.get('format_id', ''),
                    ext=f.get('ext', ''),
                    resolution=f.get('format_note') or f.get('resolution') or ('audio only' if f.get('vcodec') == 'none' else 'unknown'),
                    fps=f.get('fps'),
                    vcodec=f.get('vcodec', 'none'),
                    acodec=f.get('acodec', 'none'),
                    filesize=f.get('filesize') or f.get('filesize_approx'),
                    tbr=f.get('tbr'),
                    format_note=f.get('format_note', '')
                ))
            
            # Simple heuristic for best format: typically the one with highest tbr or resolution
            # But usually frontend just shows the list. Let's mark the first one or a specific one as default if needed.
            if formats:
                formats[-1].is_default = True # yt-dlp usually puts best formats at the end
                
            subs = list(info.get('subtitles', {}).keys())
            
            return ProbeResult(
                title=info.get('title', 'Unknown Title'),
                duration=info.get('duration'),
                thumbnail=info.get('thumbnail'),
                uploader=info.get('uploader', 'Unknown'),
                formats=formats,
                subtitles=subs,
                url=url,
                extractor=info.get('extractor', 'unknown'),
                is_playlist=False,
                playlist_count=0
            )

    def _progress_callback(self, d):
        if self._cancel_flag:
            raise DownloadCancelled("Job was cancelled by user.")
        self.progress_hook.hook(d)

    async def start(self) -> None:
        """Begin download in a background thread."""
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
        ydl_opts = YtDlpSource._base_opts()
        ydl_opts.update({
            'outtmpl': str(self.save_dir / '%(title)s.%(ext)s'),
            'progress_hooks': [self._progress_callback],
            'quiet': False,
        })

        # Use aria2c as external downloader if available (faster multi-connection downloads)
        if ARIA2C_AVAILABLE:
            ydl_opts['external_downloader'] = 'aria2c'
            ydl_opts['external_downloader_args'] = {
                'aria2c': [
                    '--min-split-size=1M',
                    '--max-connection-per-server=16',
                    '--split=16',
                    '--max-concurrent-downloads=4',
                ]
            }
            
        if self.is_playlist:
            ydl_opts['format'] = self.format_id or 'bestvideo+bestaudio/best'
            # max 50 videos
            ydl_opts['playlistend'] = 50
        else:
            ydl_opts['format'] = self.format_id or 'bestvideo+bestaudio/best'
            
        if self.embed_subs:
            ydl_opts['writesubtitles'] = True
            ydl_opts['subtitleslangs'] = ['en'] # default to english for now or all
            
        # Post-processors for merging/subtitles
        postprocessors = []
        if self.embed_subs:
            postprocessors.append({
                'key': 'FFmpegEmbedSubtitle',
            })
            
        # Optional: FFmpegVideoConvertor if we want to ensure mp4, but usually bestvideo+bestaudio with merge_output_format is better
        ydl_opts['merge_output_format'] = 'mp4'
            
        if postprocessors:
            ydl_opts['postprocessors'] = postprocessors

        def _run():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    self._metadata = ydl.extract_info(self.url, download=True)
                    self.progress_hook.status = "completed"
            except DownloadCancelled:
                self.progress_hook.status = "cancelled"
            except Exception as e:
                logger.error(f"yt-dlp error: {e}")
                self.progress_hook.status = "error"
                self.progress_hook.error = str(e)
                self._error = str(e)

        # Run in a separate thread so we don't block asyncio
        await asyncio.to_thread(_run)
        
        # After completion, scan the save_dir to populate completed_files
        if self.progress_hook.status == "completed":
            self._scan_files()

    def _scan_files(self):
        self._completed_files = []
        idx = 0
        for p in self.save_dir.rglob('*'):
            if p.is_file():
                self._completed_files.append({
                    "index": idx,
                    "relative_path": p.name,
                    "absolute_path": str(p.absolute()),
                    "size": p.stat().st_size,
                    "media_type": "video/mp4" if p.suffix == '.mp4' else "application/octet-stream"
                })
                idx += 1

    def cancel(self) -> None:
        self._cancel_flag = True

    def get_progress(self) -> MediaJob:
        snap = self.progress_hook.get_snapshot()
        
        # Calculate overall progress
        prog_percent = 0.0
        if snap['total'] > 0:
            prog_percent = (snap['downloaded'] / snap['total']) * 100.0
        elif snap['status'] == 'completed':
            prog_percent = 100.0
            
        name = self.url
        if self._metadata:
            name = self._metadata.get('title', self.url)
            
        return MediaJob(
            id=self.job_id,
            name=name,
            state=snap['status'],
            progress=prog_percent,
            download_rate=snap['speed'],
            total_size=snap['total'],
            downloaded=snap['downloaded'],
            eta=snap['eta'],
            save_path=str(self.save_dir),
            added_time=self._added_time,
            error_message=snap['error'] or "",
            is_playlist=self.is_playlist
        )

    def get_media_files(self) -> List[dict]:
        return self._completed_files
