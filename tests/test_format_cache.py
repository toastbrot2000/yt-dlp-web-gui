"""probe.py's result cache (TTL + bounded LRU-by-age). It fails silently when
broken, serving stale data or growing without bound."""

from app import probe
from app.probe import cache_formats, evict_expired_cache, get_cached_formats


def test_fresh_entry_is_returned():
    cache_formats("u", "Title", [1080, 720])
    assert get_cached_formats("u") == {"title": "Title", "heights": [1080, 720]}


def test_expired_entry_returns_none():
    cache_formats("u", "Title", [720])
    probe.format_cache["u"]["timestamp"] -= probe.FORMAT_CACHE_TTL + 1  # age past the TTL
    assert get_cached_formats("u") is None


def test_unknown_url_returns_none():
    assert get_cached_formats("never-seen") is None


def test_capacity_eviction_drops_the_oldest(monkeypatch):
    monkeypatch.setattr(probe, "FORMAT_CACHE_MAX", 2)

    # monotonic clock so the entries get distinct, increasing timestamps
    state = {"t": 0.0}

    def fake_time():
        state["t"] += 100.0
        return state["t"]

    monkeypatch.setattr(probe.time, "time", fake_time)
    cache_formats("a", "A", [])
    cache_formats("b", "B", [])
    cache_formats("c", "C", [])  # over capacity -> evicts the oldest, "a"
    assert set(probe.format_cache) == {"b", "c"}


def test_evict_expired_cache_removes_only_stale():
    now = 10_000.0
    cache_formats("fresh", "F", [])
    cache_formats("stale", "S", [])
    probe.format_cache["fresh"]["timestamp"] = now
    probe.format_cache["stale"]["timestamp"] = now - probe.FORMAT_CACHE_TTL - 1
    evict_expired_cache(now)
    assert "fresh" in probe.format_cache
    assert "stale" not in probe.format_cache
