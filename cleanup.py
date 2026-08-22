#!/usr/bin/env python3
"""
TorrentFlow x365 — Deployment Cleanup Script

Runs as Heroku release phase (before web dyno starts) to wipe all torrent
data so every deploy starts 100% clean.  Also importable by main.py for
the /admin/clean endpoint.

Usage:
    python cleanup.py              # CLI (Heroku release phase)
    from cleanup import run_cleanup  # programmatic
"""

import os
import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - cleanup - %(levelname)s - %(message)s")
logger = logging.getLogger("cleanup")

# Same directory env vars as main.py
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/srv/torrent-downloader/downloads"))
TORRENT_DIR  = Path(os.getenv("TORRENT_DIR",  "/srv/torrent-downloader/torrents"))
TEMP_DIR     = Path(os.getenv("TEMP_DIR",     "/srv/torrent-downloader/temp"))
STATE_DIR    = Path(os.getenv("STATE_DIR",    "/srv/torrent-downloader/state"))

# Dockerfile uses /downloads, /torrents, /temp, /state as defaults
FALLBACK_DIRS = [
    Path("/downloads"),
    Path("/torrents"),
    Path("/temp"),
    Path("/state"),
]


def _wipe_directory(directory: Path) -> dict:
    """Remove all contents of a directory, recreate it empty."""
    result = {"path": str(directory), "files_removed": 0, "dirs_removed": 0, "errors": []}

    if not directory.exists():
        logger.info(f"  [SKIP] {directory} does not exist")
        return result

    for item in list(directory.iterdir()):
        try:
            if item.is_dir():
                shutil.rmtree(item)
                result["dirs_removed"] += 1
                logger.info(f"  [DIR]  Removed {item}")
            else:
                item.unlink()
                result["files_removed"] += 1
                logger.info(f"  [FILE] Removed {item}")
        except OSError as e:
            msg = f"  [ERR]  Could not remove {item}: {e}"
            logger.warning(msg)
            result["errors"].append(msg)

    return result


def run_cleanup() -> dict:
    """Wipe all torrent data directories and state files.

    Returns a summary dict suitable for JSON responses.
    """
    logger.info("=" * 60)
    logger.info("TorrentFlow x365 — DEPLOYMENT CLEANUP")
    logger.info("=" * 60)

    summary = {"directories": [], "state_files": [], "db_redis": "not configured"}

    # 1. Wipe data directories
    all_dirs = set()
    for d in [DOWNLOAD_DIR, TORRENT_DIR, TEMP_DIR, STATE_DIR] + FALLBACK_DIRS:
        all_dirs.add(d.resolve())

    for directory in sorted(all_dirs):
        logger.info(f"Cleaning directory: {directory}")
        result = _wipe_directory(directory)
        summary["directories"].append(result)
        # Recreate the empty directory
        directory.mkdir(parents=True, exist_ok=True)

    # 2. Explicitly remove known state files (in case STATE_DIR != /state)
    state_files = [
        STATE_DIR / "state.json",
        Path("/state/state.json"),
    ]
    # Also catch any stray .fastresume files
    for sd in [STATE_DIR, Path("/state")]:
        if sd.exists():
            state_files.extend(sd.glob("*.fastresume"))

    for sf in set(state_files):
        if sf.exists():
            try:
                sf.unlink()
                logger.info(f"  [STATE] Removed {sf}")
                summary["state_files"].append(str(sf))
            except OSError as e:
                logger.warning(f"  [ERR]   Could not remove {sf}: {e}")

    # 3. Check for DATABASE_URL / REDIS_URL add-ons
    database_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL")

    if database_url:
        logger.info("[DB] DATABASE_URL is set — this app does not use a database, skipping.")
        summary["db_redis"] = "DATABASE_URL set but unused by this app"

    if redis_url:
        logger.info("[REDIS] REDIS_URL is set — this app does not use Redis, skipping.")
        summary["db_redis"] = "REDIS_URL set but unused by this app"

    if not database_url and not redis_url:
        logger.info("[DB/REDIS] No DATABASE_URL or REDIS_URL configured — nothing to clear.")

    # Final summary
    total_files = sum(r["files_removed"] for r in summary["directories"])
    total_dirs = sum(r["dirs_removed"] for r in summary["directories"])
    logger.info("=" * 60)
    logger.info(f"CLEANUP COMPLETE: {total_files} files, {total_dirs} directories removed")
    logger.info("=" * 60)

    summary["total_files_removed"] = total_files
    summary["total_dirs_removed"] = total_dirs
    return summary


if __name__ == "__main__":
    run_cleanup()
