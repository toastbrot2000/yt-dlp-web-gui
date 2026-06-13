"""inspect_url classifies a link from the string alone; it drives the
endpoints' playlist 400 and the video-in-playlist notice."""

import pytest

from app.probe import inspect_url


@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", (True, False)),
    ("https://youtu.be/dQw4w9WgXcQ", (True, False)),
    ("https://www.youtube.com/shorts/abc123", (True, False)),
    ("https://www.youtube.com/embed/abc123", (True, False)),
    ("https://www.youtube.com/playlist?list=PL123", (False, True)),    # pure playlist -> rejected
    ("https://www.youtube.com/watch?v=abc&list=PL123", (True, True)),  # video in a playlist -> warn
    ("https://youtu.be/", (False, False)),
    ("not even a url", (False, False)),  # unparseable -> defer to yt-dlp
    ("", (False, False)),
])
def test_inspect_url(url, expected):
    assert inspect_url(url) == expected
