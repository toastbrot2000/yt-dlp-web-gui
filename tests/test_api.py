"""Request handling through the app, with no network.

TestClient is built without a `with` block on purpose: that skips the lifespan,
so the cleanup loop never starts. The one path that would hit the network (a
real download) runs with run_download patched out, so these cover the wiring,
not yt-dlp.
"""

import time

from fastapi.testclient import TestClient

from app import downloads
from app.main import app

client = TestClient(app)


def test_empty_url_is_rejected():
    r = client.post("/api/download", json={"url": "  ", "format_type": "mp4"})
    assert r.status_code == 400


def test_pure_playlist_is_rejected():
    r = client.post("/api/download", json={
        "url": "https://www.youtube.com/playlist?list=PL1", "format_type": "mp4"})
    assert r.status_code == 400
    assert "laylist" in r.json()["detail"]


def test_out_of_range_quality_is_422():
    r = client.post("/api/download", json={
        "url": "https://www.youtube.com/watch?v=a", "format_type": "mp4", "quality": "9999"})
    assert r.status_code == 422


def test_download_publishes_queued_task_before_scheduling(monkeypatch):
    monkeypatch.setattr("app.routes.run_download", lambda *a, **k: None)  # no real download
    r = client.post("/api/download", json={
        "url": "https://www.youtube.com/watch?v=abc", "format_type": "mp4"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    # the entry must exist as "queued" so the first progress poll can't 404
    assert downloads.download_progress[task_id]["status"] == "queued"
    assert "notice" not in r.json()


def test_video_in_playlist_returns_notice(monkeypatch):
    monkeypatch.setattr("app.routes.run_download", lambda *a, **k: None)
    r = client.post("/api/download", json={
        "url": "https://www.youtube.com/watch?v=abc&list=PL1", "format_type": "mp4"})
    assert r.status_code == 200
    assert "notice" in r.json()


def test_progress_404_for_unknown_task():
    assert client.get("/api/progress/nope").status_code == 404


def test_cancel_404_for_unknown_task():
    assert client.post("/api/cancel/nope").status_code == 404


def test_cancel_queued_task_marks_cancelled_immediately():
    downloads.download_progress["q"] = {"status": "queued", "progress": 0, "timestamp": time.time()}
    r = client.post("/api/cancel/q")
    assert r.status_code == 200
    assert downloads.download_progress["q"]["status"] == "cancelled"
    assert downloads.cancel_events["q"].is_set()


def test_cancel_active_task_enters_cancelling():
    downloads.download_progress["d"] = {"status": "downloading", "progress": 40, "timestamp": time.time()}
    r = client.post("/api/cancel/d")
    assert r.status_code == 200
    assert downloads.download_progress["d"]["status"] == "cancelling"
    assert downloads.cancel_events["d"].is_set()


def test_cannot_cancel_finished_task():
    downloads.download_progress["f"] = {"status": "finished", "progress": 100, "timestamp": time.time()}
    assert client.post("/api/cancel/f").status_code == 400


def test_progress_hides_internal_fields():
    downloads.download_progress["x"] = {
        "status": "downloading",
        "progress": 12,
        "filepath": "/srv/secret/path/file.mp4",  # server-only, must not leak
        "_completed_bytes": 999,
    }
    body = client.get("/api/progress/x").json()
    assert body["status"] == "downloading"
    assert "filepath" not in body
    assert "_completed_bytes" not in body
