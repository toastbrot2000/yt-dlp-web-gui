import os
import uuid
import threading
import logging
from typing import Dict, Any

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="yt-dlp Web GUI")

# CORS (optional for local dev but good practice)
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
# task_id -> { "status": "downloading"|"finished"|"error", "progress": int, "filename": str, "error": str }
download_progress: Dict[str, Dict[str, Any]] = {}

class DownloadRequest(BaseModel):
    url: str
    format_type: str  # "mp4" or "mp3"

def progress_hook(d, task_id):
    if d['status'] == 'downloading':
        try:
            p = d.get('_percent_str', '0%').replace('%', '')
            progress_val = float(p)
        except Exception:
            progress_val = 0
            
        download_progress[task_id].update({
            "status": "downloading",
            "progress": progress_val,
            "filename": d.get('filename', 'Unknown'),
            "speed": d.get('_speed_str', 'N/A'),
            "eta": d.get('_eta_str', 'N/A')
        })
    elif d['status'] == 'finished':
        download_progress[task_id].update({
            "status": "finished",
            "progress": 100,
            "filename": d.get('filename', 'Unknown'),
            # Capture the absolute path of the downloaded file
            "filepath": d.get('filename')
        })

def run_download(task_id: str, url: str, format_type: str):
    logger.info(f"Starting download for {url} as {format_type} (Task ID: {task_id})")
    
    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: progress_hook(d, task_id)],
        'quiet': True,
        'no_warnings': True,
    }

    if format_type == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:  # mp4
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
        })

    try:
        download_progress[task_id] = {"status": "starting", "progress": 0}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Ensure it's marked as finished if hook didn't catch it
        if download_progress[task_id]["status"] != "finished":
             download_progress[task_id]["status"] = "finished"
             download_progress[task_id]["progress"] = 100

        logger.info(f"Download finished for {task_id}")

    except Exception as e:
        logger.error(f"Error downloading {url}: {str(e)}")
        download_progress[task_id] = {
            "status": "error",
            "progress": 0,
            "error": str(e)
        }

@app.post("/api/download")
async def start_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    background_tasks.add_task(run_download, task_id, request.url, request.format_type)
    return {"task_id": task_id}

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
async def download_file(task_id: str):
    from fastapi.responses import FileResponse
    
    if task_id not in download_progress:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = download_progress[task_id]
    if task.get("status") != "finished" or not task.get("filepath"):
        raise HTTPException(status_code=400, detail="File not ready or failed")
    
    filename = os.path.basename(task["filepath"])
    return FileResponse(
        task["filepath"], 
        media_type='application/octet-stream', 
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
