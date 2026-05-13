"""Unit tests for the per-user MCP burst limiter (G5)."""

import asyncio
import time

import pytest

from src.auth.rate_limiter import PerUserSlidingWindow


async def test_allows_up_to_capacity():
    limiter = PerUserSlidingWindow(capacity=3, window_seconds=60.0)
    results = [await limiter.acquire("u1") for _ in range(3)]
    assert all(allowed for allowed, _ in results)
    assert all(retry == 0.0 for _, retry in results)


async def test_rejects_beyond_capacity():
    limiter = PerUserSlidingWindow(capacity=2, window_seconds=60.0)
    await limiter.acquire("u1")
    await limiter.acquire("u1")
    allowed, retry_after = await limiter.acquire("u1")
    assert allowed is False
    assert retry_after > 0


async def test_buckets_are_per_user():
    limiter = PerUserSlidingWindow(capacity=1, window_seconds=60.0)
    a, _ = await limiter.acquire("alice")
    b, _ = await limiter.acquire("bob")
    a2, _ = await limiter.acquire("alice")
    assert a is True
    assert b is True
    assert a2 is False  # alice's bucket is full; bob's is not consumed by alice


async def test_window_slides_after_time_passes(monkeypatch):
    """Timestamps falling outside the window must be dropped."""
    limiter = PerUserSlidingWindow(capacity=2, window_seconds=1.0)

    base = [1000.0]

    def fake_monotonic() -> float:
        return base[0]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    # Fill the bucket at t=1000.
    assert (await limiter.acquire("u"))[0] is True
    assert (await limiter.acquire("u"))[0] is True
    assert (await limiter.acquire("u"))[0] is False

    # Jump 2 seconds — past the 1-second window. Old timestamps fall off.
    base[0] = 1002.0
    assert (await limiter.acquire("u"))[0] is True


async def test_concurrent_calls_one_key_throttled():
    """Acceptance test (G5): N+1 concurrent calls against one key → exactly capacity succeed."""
    capacity = 10
    limiter = PerUserSlidingWindow(capacity=capacity, window_seconds=60.0)

    results = await asyncio.gather(*(limiter.acquire("same-user") for _ in range(capacity + 5)))
    allowed_count = sum(1 for allowed, _ in results if allowed)
    rejected_count = sum(1 for allowed, _ in results if not allowed)
    assert allowed_count == capacity
    assert rejected_count == 5


def test_invalid_capacity_rejected():
    with pytest.raises(ValueError):
        PerUserSlidingWindow(capacity=0, window_seconds=60.0)


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        PerUserSlidingWindow(capacity=1, window_seconds=0)


def test_capacity_and_window_exposed():
    limiter = PerUserSlidingWindow(capacity=42, window_seconds=15.5)
    assert limiter.capacity == 42
    assert limiter.window_seconds == 15.5


async def test_burst_capacity_configurable():
    """Acceptance test (G5): burst capacity must be plumbed from the configured value."""
    settings_value = 7
    limiter = PerUserSlidingWindow(capacity=settings_value, window_seconds=60.0)
    for _ in range(settings_value):
        allowed, _ = await limiter.acquire("u")
        assert allowed
    allowed, _ = await limiter.acquire("u")
    assert allowed is False
