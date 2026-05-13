"""Acceptance tests for G10 — graceful shutdown for in-flight queries."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, QueryHistory, UserStore
from src.core.drain import DrainState
from src.core.heartbeat import HeartbeatMonitor
from src.core.query_log import QueryLog
from src.middleware.drain_guard import DrainGuardMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_cache() -> dict:
    return {}


def _make_quota_snapshot(plan_code: str = "free", daily_count: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        user_id="test-user-id",
        plan_code=plan_code,
        daily_count=daily_count,
        daily_quota_reset_at=datetime.now(UTC) + timedelta(hours=1),
    )


# ---------------------------------------------------------------------------
# DrainGuardMiddleware
# ---------------------------------------------------------------------------


def _build_drain_test_app(drain_state: DrainState) -> Starlette:
    async def ok_endpoint(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[
            Route("/api/v1/users/me", ok_endpoint),
            Route("/api/health/live", ok_endpoint),
            Route("/api/health/ready", ok_endpoint),
            Route("/mcp/", ok_endpoint),
        ],
        middleware=[Middleware(DrainGuardMiddleware, drain_state=drain_state)],
    )


def test_middleware_refuses_non_health_when_draining():
    drain_state = DrainState()
    drain_state.begin_drain()
    client = TestClient(_build_drain_test_app(drain_state))

    resp = client.get("/api/v1/users/me")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "Service is shutting down"
    assert body["code"] == "service_draining"
    assert body["retry_after_seconds"] == 30
    assert resp.headers.get("retry-after") == "30"


def test_middleware_refuses_mcp_when_draining():
    drain_state = DrainState()
    drain_state.begin_drain()
    client = TestClient(_build_drain_test_app(drain_state))

    resp = client.get("/mcp/")

    assert resp.status_code == 503
    assert resp.json()["code"] == "service_draining"


def test_middleware_lets_health_through_when_draining():
    drain_state = DrainState()
    drain_state.begin_drain()
    client = TestClient(_build_drain_test_app(drain_state))

    live = client.get("/api/health/live")
    ready = client.get("/api/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 200


def test_middleware_passes_through_normally_when_not_draining():
    drain_state = DrainState()
    client = TestClient(_build_drain_test_app(drain_state))

    resp = client.get("/api/v1/users/me")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /health/ready integration
# ---------------------------------------------------------------------------


@pytest.fixture
def ready_app_state():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    store = UserStore(engine, cipher)
    pool = ThreadPoolExecutor(max_workers=2)
    heartbeat = HeartbeatMonitor()
    drain_state = DrainState()

    api_app.state.user_store = store
    api_app.state.factory = MagicMock()
    api_app.state.executor_pool = pool
    api_app.state.heartbeat = heartbeat
    api_app.state.drain_state = drain_state

    with patch("src.api.app.settings") as mock_settings:
        mock_settings.environment = "development"
        mock_settings.llm_provider = "anthropic"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.groq_api_key = ""
        yield {"drain_state": drain_state}

    pool.shutdown(wait=False, cancel_futures=True)
    Base.metadata.drop_all(engine)
    engine.dispose()
    for attr in ("heartbeat", "drain_state"):
        try:
            delattr(api_app.state, attr)
        except AttributeError:
            pass


def test_health_ready_passes_when_not_draining(ready_app_state):
    client = TestClient(api_app)
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"]["draining"] == "ok"


def test_health_ready_fails_when_draining(ready_app_state):
    ready_app_state["drain_state"].begin_drain()
    client = TestClient(api_app)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert checks["draining"] == "fail: draining"


# ---------------------------------------------------------------------------
# ask_database drain handling
# ---------------------------------------------------------------------------


async def test_ask_database_returns_structured_envelope_during_drain():
    import src.server as server

    drain_state = DrainState()
    drain_state.begin_drain()

    query_log = MagicMock()
    with (
        patch.object(server, "_drain_state", drain_state),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result_text = await server.ask_database("Anything?")

    result = json.loads(result_text)
    assert result["error"] == "Service is shutting down"
    assert result["code"] == "service_draining"
    assert result["retry_after_seconds"] == 30
    # Drain envelope short-circuits before any pipeline / quota work, so no
    # query_history row should be written.
    query_log.log_query.assert_not_called()


async def test_ask_database_logs_interrupted_row_on_cancellation():
    """Acceptance criterion: cancelled in-flight request → query_history row with error_code."""
    import src.server as server

    # Wire a real in-memory query_log so we can read the row back.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = CredentialCipher([Fernet.generate_key().decode()])
    UserStore(engine, cipher)  # initialise schema bindings
    query_log = QueryLog(engine=engine)

    # Pipeline whose execute_with_correction blocks forever — we will cancel
    # the asyncio task wrapping ask_database to simulate the lifespan tearing
    # down a slow query.
    pipeline = MagicMock()
    pipeline.dialect = "sqlite"

    async def _block_forever(*_args, **_kwargs):
        await asyncio.sleep(60)

    pipeline.corrector = MagicMock()
    pipeline.corrector.execute_with_correction = AsyncMock(side_effect=_block_forever)

    user_store = MagicMock()
    user_store.consume_daily_query_quota.return_value = _make_quota_snapshot()

    with (
        patch.object(server, "_drain_state", DrainState()),  # not draining yet
        patch.object(server, "_user_store", user_store),
        patch.object(server, "_get_pipeline", AsyncMock(return_value=pipeline)),
        patch("src.server._current_user_id", return_value="test-user-id"),
        patch("src.server._current_api_key_id", return_value=None),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
        patch.object(server, "_mcp_limiter", None),
    ):
        task = asyncio.create_task(server.ask_database("slow question"))
        # Yield to let the task progress past _get_pipeline into the await.
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # Read the query_history row that the CancelledError handler wrote.
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        rows = session.query(QueryHistory).all()

    assert len(rows) == 1
    row = rows[0]
    assert row.success is False
    assert row.error_code == "shutdown_interrupted"
    assert row.error == "query cancelled by server shutdown"
    assert row.user_id == "test-user-id"
    assert row.question == "slow question"

    engine.dispose()


# ---------------------------------------------------------------------------
# DrainState behaviour
# ---------------------------------------------------------------------------


async def test_drain_state_wait_returns_zero_when_idle():
    state = DrainState()
    assert await state.wait_for_in_flight(0.1) == 0


async def test_drain_state_wait_for_in_flight_honours_timeout():
    state = DrainState()

    async def _slow():
        await asyncio.sleep(5)

    task = asyncio.create_task(_slow())
    state.register(task)
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        remaining = await state.wait_for_in_flight(0.2)
        elapsed = loop.time() - start
        assert remaining == 1
        assert elapsed < 1.0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state.unregister(task)


async def test_drain_state_cancel_remaining_runs_finally_blocks():
    """cancel_remaining must await briefly so CancelledError handlers can complete."""
    state = DrainState()
    flag = {"ran": False}

    async def _handler():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            flag["ran"] = True
            raise

    task = asyncio.create_task(_handler())
    state.register(task)
    await asyncio.sleep(0.01)  # let the task start

    await state.cancel_remaining(settle_seconds=1.0)

    assert task.done()
    assert flag["ran"] is True
    state.unregister(task)


async def test_drain_state_completes_naturally_when_tasks_finish_in_time():
    state = DrainState()

    async def _fast():
        await asyncio.sleep(0.05)

    task = asyncio.create_task(_fast())
    state.register(task)
    remaining = await state.wait_for_in_flight(1.0)
    assert remaining == 0
    assert task.done()
    state.unregister(task)
