"""Environment-driven configuration and shared constants."""

import os
import sys

from dotenv import load_dotenv

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

# when frozen by PyInstaller, bundled assets live in sys._MEIPASS
BASE_DIR = os.getcwd()

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# optional CSP overrides for deployments that inject inline scripts
CSP_SCRIPT_SRC = os.getenv("CSP_SCRIPT_SRC", "'self'")

# drop the catch-all generic extractor so unsupported urls fail fast (no ssrf surface)
ALLOWED_EXTRACTORS = ['default', '-generic']
