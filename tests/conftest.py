"""Shared fixtures: reset the process-global task and cache dicts around each test."""

import pytest

from app import downloads, probe


@pytest.fixture(autouse=True)
def reset_shared_state():
    def clear():
        downloads.download_progress.clear()
        downloads.cancel_events.clear()
        probe.format_cache.clear()

    clear()
    yield
    clear()
