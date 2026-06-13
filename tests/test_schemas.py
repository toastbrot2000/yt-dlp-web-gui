"""DownloadRequest.quality validation: the guard that stops anything but a sane
height (or "best") from reaching yt-dlp's format selector."""

import pytest
from pydantic import ValidationError

from app.schemas import DownloadRequest


def make(**kw):
    return DownloadRequest(**{"url": "https://x/watch?v=a", "format_type": "mp4", **kw})


@pytest.mark.parametrize("quality", ["best", "144", "1080", "4320"])
def test_accepts_valid_quality(quality):
    assert make(quality=quality).quality == quality


@pytest.mark.parametrize("quality", ["143", "4321", "1080p", "best; ls", "bestaudio", ""])
def test_rejects_bad_quality(quality):
    with pytest.raises(ValidationError):
        make(quality=quality)


def test_rejects_unknown_format_type():
    with pytest.raises(ValidationError):
        make(format_type="mkv")


def test_quality_defaults_to_best():
    assert make().quality == "best"
