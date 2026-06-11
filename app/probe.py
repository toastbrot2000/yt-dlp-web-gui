"""URL inspection and format probing, with a small in-memory result cache."""

import time
import urllib.parse
from typing import Any, Dict

import yt_dlp

from app.config import ALLOWED_EXTRACTORS

# cache probed formats so repeated polls for a url don't re-hit the source site
FORMAT_CACHE_TTL = 600
FORMAT_CACHE_MAX = 256
format_cache: Dict[str, Dict[str, Any]] = {}


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


def get_cached_formats(url: str):
    """returns the cached probe result for url, or None when absent or expired."""
    cached = format_cache.get(url)
    if cached and time.time() - cached["timestamp"] < FORMAT_CACHE_TTL:
        return {"title": cached["title"], "heights": cached["heights"]}
    return None


def cache_formats(url: str, title: str, heights):
    # bound the cache; drop the oldest entry when full
    if url not in format_cache and len(format_cache) >= FORMAT_CACHE_MAX:
        oldest = min(format_cache, key=lambda k: format_cache[k]["timestamp"])
        format_cache.pop(oldest, None)
    format_cache[url] = {"title": title, "heights": heights, "timestamp": time.time()}


def evict_expired_cache(now: float):
    for url, entry in list(format_cache.items()):
        if now - entry["timestamp"] > FORMAT_CACHE_TTL:
            format_cache.pop(url, None)
