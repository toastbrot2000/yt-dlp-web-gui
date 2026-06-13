"""run_download must bail before building a YoutubeDL when a task is cancelled
while still queued, so these run with no network and no yt-dlp call."""

import threading

from app import downloads
from app.downloads import run_download


def test_already_cancelled_task_is_left_untouched():
    downloads.download_progress["t"] = {"status": "cancelled", "progress": 0}
    run_download("t", "https://example.com/watch?v=a", "mp4", "best")
    assert downloads.download_progress["t"]["status"] == "cancelled"


def test_cancel_event_set_while_queued_finalises_as_cancelled():
    downloads.download_progress["t"] = {"status": "queued", "progress": 0}
    event = threading.Event()
    event.set()
    downloads.cancel_events["t"] = event
    run_download("t", "https://example.com/watch?v=a", "mp4", "best")
    assert downloads.download_progress["t"]["status"] == "cancelled"
    assert "t" not in downloads.cancel_events  # event consumed, no stale flag left
