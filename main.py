import os
import re
import uuid
import shutil
import logging
import asyncio
import threading
import time
import urllib.parse
from typing import Dict, Any, Literal
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
# how many downloads run at once; the rest wait in a queue
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "1"))
# running + queued cap; beyond it new download requests get a 429
MAX_PENDING_DOWNLOADS = int(os.getenv("MAX_PENDING_DOWNLOADS", "10"))
MAX_FILESIZE_MB = int(os.getenv("MAX_FILESIZE_MB", "5120"))
FILE_TTL_SECONDS = int(os.getenv("FILE_TTL_MINUTES", "60")) * 60
# optional comma-separated host allowlist (DNS-rebinding protection)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]


def is_task_id(name: str) -> bool:
    try:
        uuid.UUID(name)
        return True
    except ValueError:
        return False


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

            # evict expired format probe entries
            for url, entry in list(format_cache.items()):
                if now - entry["timestamp"] > FORMAT_CACHE_TTL:
                    format_cache.pop(url, None)

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # keep a reference so the task can't be garbage-collected mid-flight
    cleanup = asyncio.create_task(cleanup_loop())
    yield
    cleanup.cancel()

app = FastAPI(title="yt-dlp Web GUI", lifespan=lifespan)


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


# no CORS middleware on purpose: the frontend is served from this same origin,
# so cross-origin pages get no permission to drive the (unauthenticated) API

# optional Host-header allowlist (DNS-rebinding protection)
if ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

STATIC_DIR = os.path.join(os.getcwd(), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

download_progress: Dict[str, Dict[str, Any]] = {}
cancel_events: Dict[str, threading.Event] = {}

# gates how many run_download bodies execute concurrently
download_semaphore = threading.Semaphore(MAX_CONCURRENT_DOWNLOADS)


class CancelledError(Exception):
    pass


ACTIVE_STATUSES = {"queued", "starting", "downloading", "processing", "cancelling"}
TERMINAL_STATUSES = {"finished", "error", "cancelled"}

# cache probed formats so repeated polls for a url don't re-hit the source site
FORMAT_CACHE_TTL = 600
FORMAT_CACHE_MAX = 256
format_cache: Dict[str, Dict[str, Any]] = {}

# drop the catch-all generic extractor so unsupported urls fail fast (no ssrf surface)
ALLOWED_EXTRACTORS = ['default', '-generic']


class DownloadRequest(BaseModel):
    url: str
    format_type: Literal["mp4", "mp3"]
    # "best" or any probed height; validated so nothing else can be injected
    # into yt-dlp's format selector
    quality: str = "best"

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: str) -> str:
        if v == "best":
            return v
        if v.isdigit() and 144 <= int(v) <= 4320:
            return v
        raise ValueError("quality must be 'best' or a video height between 144 and 4320")


class FormatsRequest(BaseModel):
    url: str


def inspect_url(url: str):
    """returns (has_video, is_playlist_context) for the given url."""
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
    except Exception:
        # if we can't parse it, let yt-dlp decide
        return (True, False)

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    has_video = bool(qs.get("v"))
    if host in ("youtu.be", "www.youtu.be") and path.strip("/"):
        has_video = True  # youtu.be/<id>
    if path.startswith("/shorts/") or path.startswith("/embed/"):
        has_video = True

    is_playlist_context = bool(qs.get("list")) or path.startswith("/playlist")
    return (has_video, is_playlist_context)


def probe_heights(url: str):
    """returns (title, heights) for a url without downloading; raises on extraction error."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        # noplaylist doesn't apply to pure playlist urls; never probe more than one entry
        'playlist_items': '1',
        'skip_download': True,
        # bound the probe so a slow host can't tie up a worker
        'socket_timeout': 8,
        'allowed_extractors': ALLOWED_EXTRACTORS,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # a playlist/mix url yields entries; probe the first concrete video
    if info.get('entries'):
        entries = [e for e in info['entries'] if e]
        info = entries[0] if entries else info

    heights = set()
    for f in info.get('formats', []) or []:
        if f.get('vcodec') and f.get('vcodec') != 'none' and f.get('height'):
            heights.add(int(f['height']))

    return info.get('title', 'Unknown'), sorted(heights, reverse=True)


def progress_hook(d, task_id):
    task = download_progress.get(task_id)
    if task is None:
        # task entry disappeared; don't crash the hook (it would abort the download)
        return

    cancel_event = cancel_events.get(task_id)
    if cancel_event and cancel_event.is_set():
        raise CancelledError("Download cancelled by user")

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
            raise CancelledError("Download cancelled by user")
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

        except CancelledError:
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


@app.post("/api/download")
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided.")

    has_video, is_playlist = inspect_url(url)

    # a pure playlist/mix with no single video to fall back to isn't supported yet
    if is_playlist and not has_video:
        raise HTTPException(
            status_code=400,
            detail="Playlists and mixes aren't supported yet. Please paste a link to a single video.",
        )

    active = sum(1 for t in download_progress.values() if t.get("status") in ACTIVE_STATUSES)
    if active >= MAX_PENDING_DOWNLOADS:
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


@app.post("/api/formats")
async def get_formats(request: FormatsRequest):
    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided.")

    has_video, is_playlist = inspect_url(url)
    if is_playlist and not has_video:
        raise HTTPException(
            status_code=400,
            detail="Playlists and mixes aren't supported yet. Please paste a link to a single video.",
        )

    # serve from cache when fresh to avoid re-probing the source
    cached = format_cache.get(url)
    if cached and time.time() - cached["timestamp"] < FORMAT_CACHE_TTL:
        return {"title": cached["title"], "heights": cached["heights"]}

    try:
        # extraction is blocking and network-bound, keep the event loop responsive
        title, heights = await asyncio.to_thread(probe_heights, url)
    except Exception as e:
        logger.error(f"Format probe failed for {url}: {e}")
        raise HTTPException(
            status_code=400,
            detail="Couldn't read available qualities for this link.",
        )

    # bound the cache; drop the oldest entry when full
    if url not in format_cache and len(format_cache) >= FORMAT_CACHE_MAX:
        oldest = min(format_cache, key=lambda k: format_cache[k]["timestamp"])
        format_cache.pop(oldest, None)
    format_cache[url] = {"title": title, "heights": heights, "timestamp": time.time()}
    return {"title": title, "heights": heights}


# what the UI needs; internals like filepath stay server-side
PROGRESS_FIELDS = ("status", "progress", "filename", "speed", "eta", "error")


@app.post("/api/cancel/{task_id}")
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


@app.get("/api/progress/{task_id}")
async def get_progress(task_id: str):
    task = download_progress.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {k: task[k] for k in PROGRESS_FIELDS if k in task}


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')


@app.get("/api/download_file/{task_id}")
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
