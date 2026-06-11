"""API endpoints and the index page."""

import asyncio
import logging
import os
import threading
import time
import urllib.parse
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app import probe
from app.config import MAX_PENDING_DOWNLOADS, STATIC_DIR
from app.downloads import (
    TERMINAL_STATUSES,
    active_task_count,
    cancel_events,
    cleanup_task,
    download_progress,
    run_download,
)
from app.schemas import DownloadRequest, FormatsRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# what the UI needs; internals like filepath stay server-side
PROGRESS_FIELDS = ("status", "progress", "filename", "speed", "eta", "error")


@router.get("/")
async def read_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@router.post("/api/download")
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided.")

    has_video, is_playlist = probe.inspect_url(url)

    # a pure playlist/mix with no single video to fall back to isn't supported yet
    if is_playlist and not has_video:
        raise HTTPException(
            status_code=400,
            detail="Playlists and mixes aren't supported yet. Please paste a link to a single video.",
        )

    if active_task_count() >= MAX_PENDING_DOWNLOADS:
        raise HTTPException(
            status_code=429,
            detail="The server is busy with other downloads. Please try again in a bit.",
        )

    task_id = str(uuid.uuid4())
    # publish the task before scheduling so the first progress poll can't 404;
    # run_download flips it to "starting" once it gets a turn
    download_progress[task_id] = {"status": "queued", "progress": 0, "timestamp": time.time()}
    background_tasks.add_task(run_download, task_id, url, request.format_type, request.quality)

    response = {"task_id": task_id}
    if is_playlist and has_video:
        response["notice"] = (
            "This link is part of a playlist/mix. Only the single video will be "
            "downloaded for now. Full playlist support is coming later."
        )
    return response


@router.post("/api/formats")
async def get_formats(request: FormatsRequest):
    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided.")

    has_video, is_playlist = probe.inspect_url(url)
    if is_playlist and not has_video:
        raise HTTPException(
            status_code=400,
            detail="Playlists and mixes aren't supported yet. Please paste a link to a single video.",
        )

    # serve from cache when fresh to avoid re-probing the source
    cached = probe.get_cached_formats(url)
    if cached:
        return cached

    try:
        # extraction is blocking and network-bound, keep the event loop responsive
        title, heights = await asyncio.to_thread(probe.probe_heights, url)
    except Exception as e:
        logger.error(f"Format probe failed for {url}: {e}")
        raise HTTPException(
            status_code=400,
            detail="Couldn't read available qualities for this link.",
        )

    probe.cache_formats(url, title, heights)
    return {"title": title, "heights": heights}


@router.post("/api/cancel/{task_id}")
async def cancel_download(task_id: str):
    task = download_progress.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    status = task.get("status")
    if status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail="Task has already finished or failed.")

    cancel_event = cancel_events.get(task_id)
    if cancel_event is None:
        cancel_event = threading.Event()
        cancel_events[task_id] = cancel_event
    cancel_event.set()

    if status == "queued":
        task.update({"status": "cancelled", "progress": 0, "timestamp": time.time()})
    else:
        task.update({"status": "cancelling", "timestamp": time.time()})

    return {"status": "ok"}


@router.get("/api/progress/{task_id}")
async def get_progress(task_id: str):
    task = download_progress.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {k: task[k] for k in PROGRESS_FIELDS if k in task}


@router.get("/api/download_file/{task_id}")
async def download_file(task_id: str, background_tasks: BackgroundTasks):
    if task_id not in download_progress:
        raise HTTPException(status_code=404, detail="Task not found")

    task = download_progress[task_id]
    if task.get("status") != "finished" or not task.get("filepath"):
        raise HTTPException(status_code=400, detail="File not ready or failed")

    file_path = task["filepath"]
    if not os.path.exists(file_path):
        # already cleaned up or lost to a restart; drop the dangling task
        cleanup_task(task_id)
        raise HTTPException(status_code=410, detail="File is no longer available.")

    filename = os.path.basename(file_path)

    # url-encode the filename for the content-disposition header (rfc 5987)
    encoded_filename = urllib.parse.quote(filename)

    # clean up the task dir after the response is sent
    background_tasks.add_task(cleanup_task, task_id)

    return FileResponse(
        file_path,
        media_type='application/octet-stream',
        headers={
            "Content-Disposition": f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
        }
    )
