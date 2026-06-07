import os
import uuid
import logging
import asyncio
import time
import urllib.parse
from typing import Dict, Any, Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# delete downloaded files and task entries older than 1 hour
async def cleanup_loop():
    while True:
        try:
            now = time.time()
            for filename in os.listdir(DOWNLOAD_DIR):
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(filepath):
                    if now - os.path.getmtime(filepath) > 3600:
                        os.remove(filepath)
                        logger.info(f"Cleanup: Deleted stale file {filename}")

            stale_tasks = []
            for tid, data in download_progress.items():
                if data.get("timestamp") and now - data["timestamp"] > 3600:
                    stale_tasks.append(tid)
            
            for tid in stale_tasks:
                del download_progress[tid]
                logger.info(f"Cleanup: Pruned stale task {tid}")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(cleanup_loop())
    yield

app = FastAPI(title="yt-dlp Web GUI", lifespan=lifespan)

def cleanup_file(path: str, task_id: str = None):
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Deleted temporary file: {path}")
    except Exception as e:
        logger.error(f"Error deleting file {path}: {e}")
    
    if task_id and task_id in download_progress:
        del download_progress[task_id]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

STATIC_DIR = os.path.join(os.getcwd(), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

download_progress: Dict[str, Dict[str, Any]] = {}

# cache probed formats so repeated polls for a url don't re-hit the source site
FORMAT_CACHE_TTL = 600
format_cache: Dict[str, Dict[str, Any]] = {}

# drop the catch-all generic extractor so unsupported urls fail fast (no ssrf surface)
ALLOWED_EXTRACTORS = ['default', '-generic']


class DownloadRequest(BaseModel):
    url: str
    format_type: str  # mp4 or mp3
    quality: str = "best"  # best, 2160, 1440, 1080, 720, 480


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
    if "youtu.be" in host and path.strip("/"):
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
    if d['status'] == 'downloading':
        # prefer byte counts over percent_str, which can be unreliable
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        
        if total:
            progress_val = (downloaded / total) * 100
        else:
            try:
                p = d.get('_percent_str', '0%').replace('%', '').strip()
                progress_val = float(p)
            except Exception:
                progress_val = 0

        download_progress[task_id].update({
            "status": "downloading",
            "progress": progress_val,
            "filename": os.path.basename(d.get('filename', 'Unknown')),
            "speed": d.get('_speed_str', 'N/A'),
            "eta": d.get('_eta_str', 'N/A')
        })
    elif d['status'] == 'finished':
        # download done, post-processing may still run
        download_progress[task_id].update({
            "status": "processing",
            "progress": 100,
            "filename": os.path.basename(d.get('filename', 'Unknown')),
            "filepath": d.get('filename')
        })
        logger.info(f"Task {task_id} download finished, now processing.")


def run_download(task_id: str, url: str, format_type: str, quality: str = "best"):
    logger.info(f"Starting download for {url} as {format_type} ({quality}) (Task ID: {task_id})")
    
    def postprocessor_hook(d):
        if d['status'] == 'finished':
            info = d.get('info_dict')
            if info:
                download_progress[task_id].update({
                    "status": "processing",
                    "progress": 100,
                    "filename": info.get('filename', 'Unknown'),
                    "filepath": info.get('filepath') or info.get('filename')
                })

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: progress_hook(d, task_id)],
        'postprocessor_hooks': [postprocessor_hook],
        'quiet': True,
        'no_warnings': True,
        # single video only, even if the url carries a playlist/mix
        'noplaylist': True,
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
            # cap at target height like 2160, 1440, 1080, 720, 480
            ydl_opts.update({
                'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
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

    try:
        download_progress[task_id] = {
            "status": "starting", 
            "progress": 0,
            "timestamp": time.time()
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            # deduce filepath if the hooks missed it
            if task_id in download_progress:
                task = download_progress[task_id]
                if not task.get('filepath'):
                    if 'requested_downloads' in info:
                        filepath = info['requested_downloads'][0].get('filepath')
                    else:
                        filepath = ydl.prepare_filename(info)

                    # account for the mp3 extension swap from post-processing
                    if format_type == 'mp3' and filepath and not filepath.endswith('.mp3'):
                        filepath = os.path.splitext(filepath)[0] + '.mp3'

                    task['filepath'] = filepath
                    task['filename'] = os.path.basename(filepath) if filepath else 'Unknown'

        # mark finished only after the context manager exits, once post-processing is done
        if task_id in download_progress:
            download_progress[task_id].update({
                "status": "finished",
                "progress": 100,
                "timestamp": time.time()
            })

    except Exception as e:
        logger.error(f"Error downloading {url}: {str(e)}")
        download_progress[task_id] = {
            "status": "error",
            "progress": 0,
            "error": str(e),
            "timestamp": time.time()
        }

@app.post("/api/download")
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    has_video, is_playlist = inspect_url(request.url)

    # a pure playlist/mix with no single video to fall back to isn't supported yet
    if is_playlist and not has_video:
        raise HTTPException(
            status_code=400,
            detail="Playlists and mixes aren't supported yet. Please paste a link to a single video.",
        )

    task_id = str(uuid.uuid4())
    background_tasks.add_task(run_download, task_id, request.url, request.format_type, request.quality)

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

    format_cache[url] = {"title": title, "heights": heights, "timestamp": time.time()}
    return {"title": title, "heights": heights}


@app.get("/api/progress/{task_id}")
async def get_progress(task_id: str):
    if task_id not in download_progress:
        raise HTTPException(status_code=404, detail="Task not found")
    return download_progress[task_id]

@app.get("/")
async def read_index():
    from fastapi.responses import FileResponse
    return FileResponse('static/index.html')

@app.get("/api/download_file/{task_id}")
async def download_file(task_id: str, background_tasks: BackgroundTasks):
    
    if task_id not in download_progress:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = download_progress[task_id]
    if task.get("status") != "finished" or not task.get("filepath"):
        raise HTTPException(status_code=400, detail="File not ready or failed")
    
    file_path = task["filepath"]
    filename = os.path.basename(file_path)

    # url-encode the filename for the content-disposition header (rfc 5987)
    encoded_filename = urllib.parse.quote(filename)

    # clean up the file after the response is sent
    background_tasks.add_task(cleanup_file, file_path, task_id)

    return FileResponse(
        file_path, 
        media_type='application/octet-stream', 
        headers={
            "Content-Disposition": f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
