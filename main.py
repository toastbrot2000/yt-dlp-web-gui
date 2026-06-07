import os
import uuid
import logging
import asyncio
import time
import urllib.parse
from typing import Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cleanup task: Delete files older than 1 hour
async def cleanup_loop():
    while True:
        try:
            now = time.time()
            for filename in os.listdir(DOWNLOAD_DIR):
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(filepath):
                    # If file is older than 1 hour
                    if now - os.path.getmtime(filepath) > 3600:
                        os.remove(filepath)
                        logger.info(f"Cleanup: Deleted stale file {filename}")
            
            # Also cleanup stale task progress entries (older than 1 hour)
            stale_tasks = []
            for tid, data in download_progress.items():
                if data.get("timestamp") and now - data["timestamp"] > 3600:
                    stale_tasks.append(tid)
            
            for tid in stale_tasks:
                del download_progress[tid]
                logger.info(f"Cleanup: Pruned stale task {tid}")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        
        await asyncio.sleep(600) # Run every 10 minutes

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start cleanup loop
    asyncio.create_task(cleanup_loop())
    yield
    # Shutdown: Cleanup (optional)

app = FastAPI(title="yt-dlp Web GUI", lifespan=lifespan)

# Helper to remove file after download
def cleanup_file(path: str, task_id: str = None):
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Deleted temporary file: {path}")
    except Exception as e:
        logger.error(f"Error deleting file {path}: {e}")
    
    if task_id and task_id in download_progress:
        del download_progress[task_id]

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create downloads directory
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Create static directory if it doesn't exist
STATIC_DIR = os.path.join(os.getcwd(), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Store active downloads progress
download_progress: Dict[str, Dict[str, Any]] = {}

# Cache of probed formats so repeated polls for the same URL don't hit the
# source site again (cuts latency and bot-detection/rate-limit exposure).
# url -> { "heights": list[int], "title": str, "timestamp": float }
FORMAT_CACHE_TTL = 600  # seconds
format_cache: Dict[str, Dict[str, Any]] = {}

# Restrict yt-dlp to sites with a dedicated extractor. Dropping the catch-all
# "generic" extractor means an unsupported URL fails instantly instead of the
# server fetching and scraping the arbitrary page (an SSRF surface + slow miss).
ALLOWED_EXTRACTORS = ['default', '-generic']


class DownloadRequest(BaseModel):
    url: str
    format_type: str  # "mp4" or "mp3"
    quality: str = "best" # "best", "2160", "1440", "1080", "720", "480"


class FormatsRequest(BaseModel):
    url: str


def inspect_url(url: str):
    """Inspect a URL for single-video vs. playlist/mix context.

    Returns (has_video, is_playlist_context):
      has_video           - the URL points at a specific video we can grab on its own
      is_playlist_context - the URL also carries a playlist or mix (list= / /playlist)
    """
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
    except Exception:
        # If we can't parse it, don't block — let yt-dlp decide.
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
    """Extract metadata for a URL (no download) and return available video heights.

    Returns (title, heights) where heights is a sorted-descending list of the
    distinct vertical resolutions the source offers. Raises on extraction error.
    """
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        # Bound the probe so a slow/unresponsive host can't tie up a worker.
        'socket_timeout': 8,
        'allowed_extractors': ALLOWED_EXTRACTORS,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # A playlist/mix URL yields entries; probe the first concrete video.
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
        # Use total_bytes or downloaded_bytes for more accurate percentage if percent_str is unreliable
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
        # Download is done, but post-processing might start
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
        # Only the single video, even if the URL carries a playlist/mix context.
        'noplaylist': True,
        # Supported sites only — no arbitrary page fetching (see ALLOWED_EXTRACTORS).
        'allowed_extractors': ALLOWED_EXTRACTORS,
    }

    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            # Grab the thumbnail so EmbedThumbnail can use it as cover art.
            'writethumbnail': True,
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                },
                # Write title/artist/date/etc. that yt-dlp scraped into the file's
                # tags. 'artist' falls back through uploader automatically.
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                # Embed the thumbnail as ID3 cover art (runs after extraction).
                {'key': 'EmbedThumbnail'},
            ],
        })
    else:  # mp4
        # result into an mp4 container regardless of source codec.
        if quality == "best":
            ydl_opts.update({
                'format': 'bestvideo+bestaudio/best',
            })
        else:
            # target height like 2160, 1440, 1080, 720, 480
            ydl_opts.update({
                'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            })
        ydl_opts.update({
            'merge_output_format': 'mp4',
            # Grab the thumbnail so EmbedThumbnail can set the MP4 cover atom.
            'writethumbnail': True,
            'postprocessors': [
                # Write title/artist/date/etc. into the container tags.
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                # Embed the thumbnail into the MP4 'covr' atom.
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
            
            # Final check to ensure we have the filepath
            if task_id in download_progress:
                task = download_progress[task_id]
                if not task.get('filepath'):
                    # Try to deduce filepath if hook missed it
                    if 'requested_downloads' in info:
                        filepath = info['requested_downloads'][0].get('filepath')
                    else:
                        filepath = ydl.prepare_filename(info)
                    
                    # Handle post-processing extension changes
                    if format_type == 'mp3' and filepath and not filepath.endswith('.mp3'):
                        filepath = os.path.splitext(filepath)[0] + '.mp3'
                        
                    task['filepath'] = filepath
                    task['filename'] = os.path.basename(filepath) if filepath else 'Unknown'

        # Set final status to finished ONLY after the context manager exits (all post-processing done)
        if task_id in download_progress:
            download_progress[task_id].update({
                "status": "finished",
                "progress": 100,
                "timestamp": time.time() # Update timestamp so it survives 1 more hour
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

    # A pure playlist/mix (no single video to fall back to) isn't supported yet.
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

    # Serve from cache when fresh to avoid re-probing the source.
    cached = format_cache.get(url)
    if cached and time.time() - cached["timestamp"] < FORMAT_CACHE_TTL:
        return {"title": cached["title"], "heights": cached["heights"]}

    try:
        # Extraction is blocking/network-bound; keep the event loop responsive.
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
    
    # URL-encode the filename for the Content-Disposition header (RFC 5987)
    encoded_filename = urllib.parse.quote(filename)
    
    # Schedule cleanup after response is sent
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
