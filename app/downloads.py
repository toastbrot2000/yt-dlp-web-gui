"""Task state, the download worker, and background cleanup."""

import asyncio
import logging
import os
import re
import shutil
import threading
import time
import uuid
from typing import Any, Dict

import yt_dlp
# raised from our hooks to abort a task; yt-dlp re-raises it unwrapped by contract
from yt_dlp.utils import DownloadCancelled

from app import probe
from app.config import (
    ALLOWED_EXTRACTORS,
    DOWNLOAD_DIR,
    FILE_TTL_SECONDS,
    MAX_CONCURRENT_DOWNLOADS,
    MAX_FILESIZE_MB,
)

logger = logging.getLogger(__name__)

download_progress: Dict[str, Dict[str, Any]] = {}
cancel_events: Dict[str, threading.Event] = {}

# gates how many run_download bodies execute concurrently
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)

ACTIVE_STATUSES = {"queued", "starting", "downloading", "processing", "cancelling"}
TERMINAL_STATUSES = {"finished", "error", "cancelled"}


def is_task_id(name: str) -> bool:
    try:
        uuid.UUID(name)
        return True
    except ValueError:
        return False


def task_dir(task_id: str) -> str:
    return os.path.join(DOWNLOAD_DIR, task_id)


def cleanup_task(task_id: str):
    try:
        path = task_dir(task_id)
        if os.path.isdir(path):
            shutil.rmtree(path)
            logger.info(f"Deleted task dir for {task_id}")
    except Exception as e:
        logger.error(f"Error deleting task dir for {task_id}: {e}")

    download_progress.pop(task_id, None)
    cancel_events.pop(task_id, None)


def active_task_count() -> int:
    return sum(1 for t in download_progress.values() if t.get("status") in ACTIVE_STATUSES)


# delete stale tasks, their download dirs and expired probe cache entries
async def cleanup_loop():
    while True:
        try:
            now = time.time()

            # prune stale tasks; hooks refresh the timestamp while a download
            # makes progress, so active long downloads are never pruned
            for tid, data in list(download_progress.items()):
                if data.get("timestamp") and now - data["timestamp"] > FILE_TTL_SECONDS:
                    cleanup_task(tid)
                    logger.info(f"Cleanup: Pruned stale task {tid}")

            # orphaned task dirs (e.g. after a restart); only uuid-named dirs
            # are ours, anything else in the (possibly host-mounted) downloads
            # dir is left alone
            for name in os.listdir(DOWNLOAD_DIR):
                path = os.path.join(DOWNLOAD_DIR, name)
                if not os.path.isdir(path) or not is_task_id(name) or name in download_progress:
                    continue
                if now - os.path.getmtime(path) > FILE_TTL_SECONDS:
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info(f"Cleanup: Deleted orphaned task dir {name}")

            probe.evict_expired_cache(now)

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        await asyncio.sleep(600)


def progress_hook(d, task_id):
    task = download_progress.get(task_id)
    if task is None:
        # task entry disappeared; don't crash the hook (it would abort the download)
        return

    cancel_event = cancel_events.get(task_id)
    if cancel_event and cancel_event.is_set():
        raise DownloadCancelled("Download cancelled by user")

    if d['status'] == 'downloading':
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        completed = task.get('_completed_bytes', 0.0)
        prev = task.get('_prev_downloaded', 0)

        # detect fragment boundary: yt-dlp resets downloaded_bytes between
        # streams (e.g. video then audio for mp4)
        if downloaded < prev:
            completed += prev
            task['_completed_bytes'] = completed

        task['_prev_downloaded'] = downloaded

        overall = completed + downloaded
        overall_max = completed + (total or downloaded)

        if overall_max:
            progress_val = min(overall / overall_max * 100, 100)
        else:
            progress_val = 0

        # never drop backwards (fragment boundaries would otherwise regress)
        progress_val = max(progress_val, task.get('progress', 0))

        task.update({
            "status": "downloading",
            "progress": progress_val,
            "filename": os.path.basename(d.get('filename', 'Unknown')),
            "speed": d.get('_speed_str', 'N/A'),
            "eta": d.get('_eta_str', 'N/A'),
            "timestamp": time.time()
        })
    elif d['status'] == 'finished':
        prev = task.get('_prev_downloaded', 0)
        task['_completed_bytes'] = task.get('_completed_bytes', 0.0) + prev
        task['_prev_downloaded'] = 0
        task['status'] = 'processing'
        task['timestamp'] = time.time()
        logger.info(f"Task {task_id} download finished, now processing.")


def run_download(task_id: str, url: str, format_type: str, quality: str = "best"):
    logger.info(f"Starting download for {url} as {format_type} ({quality}) (Task ID: {task_id})")

    def postprocessor_hook(d):
        cancel_event = cancel_events.get(task_id)
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelled("Download cancelled by user")
        if d['status'] == 'finished':
            info = d.get('info_dict')
            task = download_progress.get(task_id)
            if info and task is not None:
                task.update({
                    "status": "processing",
                    "progress": 100,
                    "filename": info.get('filename', 'Unknown'),
                    "filepath": info.get('filepath') or info.get('filename'),
                    "timestamp": time.time()
                })

    out_dir = task_dir(task_id)

    ydl_opts = {
        # isolate each task in its own directory so concurrent tasks never collide
        'outtmpl': os.path.join(out_dir, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: progress_hook(d, task_id)],
        'postprocessor_hooks': [postprocessor_hook],
        'quiet': True,
        'no_warnings': True,
        # single video even if the url has a playlist/mix
        'noplaylist': True,
        # keep wall-clock mtimes (not upload dates) so the orphan sweep ages dirs correctly
        'updatetime': False,
        # a stalled host shouldn't pin a worker thread forever
        'socket_timeout': 30,
        'max_filesize': MAX_FILESIZE_MB * 1024 * 1024,
        'allowed_extractors': ALLOWED_EXTRACTORS,
    }

    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            # needed so EmbedThumbnail can use it as cover art
            'writethumbnail': True,
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                },
                # write scraped title/artist/date/etc into the file tags
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                # embed the thumbnail as id3 cover art
                {'key': 'EmbedThumbnail'},
            ],
        })
    else:  # mp4
        if quality == "best":
            ydl_opts.update({
                'format': 'bestvideo+bestaudio/best',
            })
        else:
            # cap at the requested height; no uncapped fallback so the result
            # never exceeds what the user picked
            ydl_opts.update({
                'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]',
            })
        ydl_opts.update({
            'merge_output_format': 'mp4',
            'writethumbnail': True,
            'postprocessors': [
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                # embed the thumbnail into the mp4 covr atom
                {'key': 'EmbedThumbnail'},
            ],
        })

    # wait for a download slot; the endpoint already published "queued"
    with download_semaphore:
        try:
            task = download_progress.get(task_id)
            if task is None:
                return  # pruned while waiting in the queue
            if task.get("status") == "cancelled":
                return  # cancelled while waiting in the queue

            cancel_event = cancel_events.get(task_id)
            if cancel_event and cancel_event.is_set():
                task.update({"status": "cancelled", "progress": 0, "timestamp": time.time()})
                cancel_events.pop(task_id, None)
                return

            task.update({"status": "starting", "progress": 0, "timestamp": time.time()})

            os.makedirs(out_dir, exist_ok=True)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                # deduce filepath if the hooks missed it
                task = download_progress.get(task_id)
                if task is not None and not task.get('filepath'):
                    if 'requested_downloads' in info:
                        filepath = info['requested_downloads'][0].get('filepath')
                    else:
                        filepath = ydl.prepare_filename(info)

                    # account for the mp3 extension swap from post-processing
                    if format_type == 'mp3' and filepath and not filepath.endswith('.mp3'):
                        filepath = os.path.splitext(filepath)[0] + '.mp3'

                    task['filepath'] = filepath
                    task['filename'] = os.path.basename(filepath) if filepath else 'Unknown'

            cancel_event = cancel_events.get(task_id)
            if cancel_event and cancel_event.is_set():
                shutil.rmtree(out_dir, ignore_errors=True)
                download_progress[task_id] = {
                    "status": "cancelled",
                    "progress": 0,
                    "timestamp": time.time()
                }
                cancel_events.pop(task_id, None)
                return

            task = download_progress.get(task_id)
            if task is not None:
                filepath = task.get('filepath')
                if filepath and os.path.exists(filepath):
                    task.update({
                        "status": "finished",
                        "progress": 100,
                        "timestamp": time.time()
                    })
                else:
                    # e.g. the size cap stopped the download without raising
                    task.update({
                        "status": "error",
                        "error": "Download did not produce a file (it may exceed the server's size limit).",
                        "timestamp": time.time()
                    })

        except DownloadCancelled:
            logger.info(f"Task {task_id} cancelled by user.")
            shutil.rmtree(out_dir, ignore_errors=True)
            download_progress[task_id] = {
                "status": "cancelled",
                "progress": 0,
                "timestamp": time.time()
            }
            cancel_events.pop(task_id, None)

        except Exception as e:
            logger.exception(f"Error downloading {url} (task {task_id})")
            # drop partial files now rather than waiting for the stale sweep
            shutil.rmtree(out_dir, ignore_errors=True)
            if isinstance(e, yt_dlp.utils.DownloadError):
                # extractor messages ("Video unavailable", ...) are safe and useful
                message = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
                message = re.sub(r'^ERROR:\s*', '', message)
            else:
                # anything else may leak paths or internals
                message = "Download failed due to an internal server error."
            download_progress[task_id] = {
                "status": "error",
                "progress": 0,
                "error": message,
                "timestamp": time.time()
            }
