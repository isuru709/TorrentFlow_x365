import os
import asyncio
import logging
import json
import uuid
import shutil
import mimetypes
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from media_engine.models import MediaJob, ProbeResult
from media_engine.ytdlp_source import YtDlpSource

logger = logging.getLogger("media-engine")
media_router = APIRouter(prefix="/api/media", tags=["media"])

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
STATE_DIR = Path(os.getenv("STATE_DIR", "state"))
TEMP_DIR = Path(os.getenv("TEMP_DIR", "temp"))

class ProbeRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None
    embed_subtitles: bool = False
    is_playlist: bool = False

class MediaManager:
    def __init__(self):
        self.jobs: Dict[str, YtDlpSource] = {}
        self.completed_jobs: Dict[str, MediaJob] = {}
        self.completed_files: Dict[str, dict] = {}
        
        self.websocket_clients = set() # Will be shared from main.py
        self.monitor_task = None
        self._load_state()

    def start_monitor(self):
        """Start the background monitor loop. Must be called inside a running event loop."""
        if self.monitor_task is None:
            self.monitor_task = asyncio.create_task(self.monitor_jobs())

    def _load_state(self):
        state_path = STATE_DIR / "state.json"
        if not state_path.exists():
            return
            
        try:
            with open(state_path, "r") as f:
                state = json.load(f)
                
            saved_completed = state.get("media_completed_jobs", {})
            saved_files = state.get("media_completed_files", {})
            
            for jid, info_dict in saved_completed.items():
                try:
                    self.completed_jobs[jid] = MediaJob(**info_dict)
                except Exception as e:
                    logger.warning(f"Failed to load media job {jid}: {e}")
                    
            for jid, files_dict in saved_files.items():
                self.completed_files[jid] = files_dict
                
        except Exception as e:
            logger.error(f"Error loading media state: {e}")

    def _save_state(self):
        state_path = STATE_DIR / "state.json"
        state = {}
        if state_path.exists():
            try:
                with open(state_path, "r") as f:
                    state = json.load(f)
            except Exception:
                pass
                
        state["media_completed_jobs"] = {jid: j.model_dump() for jid, j in self.completed_jobs.items()}
        state["media_completed_files"] = self.completed_files
        
        try:
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save media state: {e}")

    async def probe(self, url: str) -> ProbeResult:
        try:
            # Run blocking probe in thread (no cookies — dynos refresh daily)
            result = await asyncio.to_thread(YtDlpSource.probe, url)
            return result
        except Exception as e:
            logger.error(f"Probe failed: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    async def start_download(self, req: DownloadRequest) -> str:
        job_id = str(uuid.uuid4())
        save_dir = DOWNLOAD_DIR / job_id
        
        source = YtDlpSource(
            job_id=job_id,
            url=req.url,
            format_id=req.format_id or ('bestvideo+bestaudio/best' if not req.is_playlist else None),
            save_dir=save_dir,
            embed_subs=req.embed_subtitles,
            is_playlist=req.is_playlist
        )
        self.jobs[job_id] = source
        
        # Start download task
        asyncio.create_task(source.start())
        return job_id

    async def monitor_jobs(self):
        """Periodically check jobs, move completed, and trigger broadcast."""
        while True:
            try:
                changes = False
                completed = []
                
                for jid, source in list(self.jobs.items()):
                    prog = source.get_progress()
                    if prog.state in ("completed", "error", "cancelled"):
                        self.completed_jobs[jid] = prog
                        files = source.get_media_files()
                        if files:
                            self.completed_files[jid] = {
                                "files": files,
                                "save_path": str(source.save_dir),
                                "name": prog.name
                            }
                        completed.append(jid)
                        changes = True
                        
                for jid in completed:
                    self.jobs.pop(jid, None)
                    
                if changes:
                    self._save_state()
                    
            except Exception as e:
                logger.error(f"Media monitor error: {e}")
                
            await asyncio.sleep(1)

    def list_jobs(self) -> List[MediaJob]:
        res = []
        for jid, source in self.jobs.items():
            res.append(source.get_progress())
        for jid, job in self.completed_jobs.items():
            res.append(job)
        return res

    async def remove_job(self, job_id: str, delete_files: bool = False):
        if job_id in self.jobs:
            source = self.jobs[job_id]
            source.cancel()
            self.jobs.pop(job_id, None)
            
        if job_id in self.completed_jobs:
            self.completed_jobs.pop(job_id, None)
            
        entry = self.completed_files.pop(job_id, None)
        self._save_state()
        
        if delete_files:
            save_path = None
            if entry and "save_path" in entry:
                save_path = entry["save_path"]
            else:
                save_path = str(DOWNLOAD_DIR / job_id)
                
            if save_path:
                sp = Path(save_path)
                if sp.exists() and sp.is_dir():
                    try:
                        shutil.rmtree(sp)
                    except Exception as e:
                        logger.error(f"Failed to delete {sp}: {e}")

# Global instance
media_manager = MediaManager()

@media_router.post("/probe", response_model=ProbeResult)
async def probe_media(req: ProbeRequest):
    return await media_manager.probe(req.url)

@media_router.post("/download")
async def start_media_download(req: DownloadRequest):
    job_id = await media_manager.start_download(req)
    return {"success": True, "job_id": job_id}

@media_router.get("/jobs", response_model=List[MediaJob])
async def list_media_jobs():
    return media_manager.list_jobs()

@media_router.delete("/{job_id}")
async def delete_media_job(job_id: str, delete_files: bool = False):
    await media_manager.remove_job(job_id, delete_files)
    return {"success": True}

@media_router.get("/{job_id}/files")
async def get_media_files(job_id: str):
    if job_id in media_manager.completed_files:
        return media_manager.completed_files[job_id].get("files", [])
    if job_id in media_manager.jobs:
        return media_manager.jobs[job_id].get_media_files()
    raise HTTPException(404, "Job or files not found")

@media_router.get("/{job_id}/download")
async def download_media(job_id: str, file_index: Optional[int] = None):
    files = []
    save_path = None
    name = "media"
    
    if job_id in media_manager.completed_files:
        entry = media_manager.completed_files[job_id]
        files = entry.get("files", [])
        save_path = entry.get("save_path")
        name = entry.get("name", "media")
    elif job_id in media_manager.jobs:
        source = media_manager.jobs[job_id]
        files = source.get_media_files()
        save_path = str(source.save_dir)
        prog = source.get_progress()
        name = prog.name
    else:
        raise HTTPException(status_code=404, detail="Job not found")

    if not files:
        raise HTTPException(status_code=404, detail="No files available")

    # If single file requested
    if file_index is not None:
        try:
            f = next(x for x in files if x["index"] == file_index)
            abs_path = Path(f["absolute_path"])
            if not abs_path.exists():
                raise HTTPException(404, "File not found on disk")
            return FileResponse(
                path=abs_path,
                filename=f["relative_path"],
                media_type=f.get("media_type", "application/octet-stream")
            )
        except StopIteration:
            raise HTTPException(status_code=404, detail="File index not found")
            
    # If no file_index and it's a playlist (multiple files), zip them
    if len(files) > 1:
        zip_path = TEMP_DIR / f"{job_id}.zip"
        if not zip_path.exists():
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for f in files:
                    abs_path = Path(f["absolute_path"])
                    if abs_path.exists():
                        zipf.write(abs_path, f["relative_path"])
        return FileResponse(
            path=zip_path,
            filename=f"{name}.zip",
            media_type="application/zip"
        )
    elif len(files) == 1:
        f = files[0]
        abs_path = Path(f["absolute_path"])
        return FileResponse(
            path=abs_path,
            filename=f["relative_path"],
            media_type=f.get("media_type", "application/octet-stream")
        )

# Helper function to read a file chunk for streaming
def _stream_file_helper(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

@media_router.get("/{job_id}/stream/{file_index}")
async def stream_media(request: Request, job_id: str, file_index: int):
    files = []
    if job_id in media_manager.completed_files:
        files = media_manager.completed_files[job_id].get("files", [])
    elif job_id in media_manager.jobs:
        files = media_manager.jobs[job_id].get_media_files()
        
    try:
        f = next(x for x in files if x["index"] == file_index)
    except StopIteration:
        raise HTTPException(status_code=404, detail="File not found")

    abs_path = Path(f["absolute_path"])
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    file_size = f["size"]
    media_type = f.get("media_type", "video/mp4")
    
    range_header = request.headers.get("Range")
    if not range_header:
        return FileResponse(path=abs_path, media_type=media_type)

    # Parse Range header
    try:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
    except ValueError:
        return FileResponse(path=abs_path, media_type=media_type)

    if start >= file_size or end >= file_size:
        return StreamingResponse(
            status_code=416,
            content=iter([""]),
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Type": media_type,
    }
    
    return StreamingResponse(
        _stream_file_helper(abs_path, start, end),
        status_code=206,
        headers=headers
    )
