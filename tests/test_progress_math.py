"""progress_hook's byte math: the trickiest logic here, and it reads yt-dlp's
hook-dict contract that the nightly bump can quietly change."""

import threading

import pytest
from yt_dlp.utils import DownloadCancelled

from app import downloads
from app.downloads import progress_hook


def make_task(task_id="t1"):
    downloads.download_progress[task_id] = {"status": "starting", "progress": 0}
    return downloads.download_progress[task_id]


def test_progress_within_single_stream():
    task = make_task()
    progress_hook({"status": "downloading", "downloaded_bytes": 250, "total_bytes": 1000}, "t1")
    assert task["progress"] == 25.0
    assert task["status"] == "downloading"
    assert task["_prev_downloaded"] == 250


def test_progress_never_regresses_when_total_grows():
    task = make_task()
    progress_hook({"status": "downloading", "downloaded_bytes": 250, "total_bytes": 1000}, "t1")
    # a bigger total later reports a lower raw %; the bar must not walk backwards
    progress_hook({"status": "downloading", "downloaded_bytes": 300, "total_bytes": 2000}, "t1")
    assert task["progress"] == 25.0


def test_progress_carries_across_fragment_boundary():
    task = make_task()
    progress_hook({"status": "downloading", "downloaded_bytes": 800, "total_bytes_estimate": 1000}, "t1")
    assert task["progress"] == 80.0
    # audio stream starts and downloaded_bytes resets; the 800 must be banked, not lost
    progress_hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200}, "t1")
    assert task["_completed_bytes"] == 800
    assert task["progress"] == 85.0  # (800 + 50) / (800 + 200)


def test_finished_banks_remaining_bytes_and_moves_to_processing():
    task = make_task()
    progress_hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 500}, "t1")
    progress_hook({"status": "finished"}, "t1")
    assert task["_completed_bytes"] == 500
    assert task["_prev_downloaded"] == 0
    assert task["status"] == "processing"


def test_progress_caps_at_100():
    task = make_task()
    progress_hook({"status": "downloading", "downloaded_bytes": 1100, "total_bytes": 1000}, "t1")
    assert task["progress"] == 100.0


def test_hook_raises_when_cancelled():
    make_task()
    event = threading.Event()
    event.set()
    downloads.cancel_events["t1"] = event
    with pytest.raises(DownloadCancelled):
        progress_hook({"status": "downloading", "downloaded_bytes": 1}, "t1")


def test_hook_is_noop_when_task_already_gone():
    # raising here would abort an already-orphaned download thread
    progress_hook({"status": "downloading", "downloaded_bytes": 1}, "missing")
