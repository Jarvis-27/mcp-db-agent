"""Tests for /health/live (G1) and /health/ready (G2)."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.app import api_app
from src.auth.crypto import CredentialCipher
from src.auth.user_store import Base, UserStore
from src.core.heartbeat import HeartbeatMonitor


@pytest.fixture
def app_state():
    """Wire up enough api_app.state for the health endpoints to return 200."""
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

    api_app.state.user_store = store
    api_app.state.factory = MagicMock()
    api_app.state.executor_pool = pool
    api_app.state.heartbeat = heartbeat

    with patch("src.api.app.settings") as mock_settings:
        mock_settings.environment = "development"
        mock_settings.llm_provider = "anthropic"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.groq_api_key = ""
        yield {
            "engine": engine,
            "store": store,
            "pool": pool,
            "heartbeat": heartbeat,
            "settings": mock_settings,
        }

    pool.shutdown(wait=False, cancel_futures=True)
    Base.metadata.drop_all(engine)
    engine.dispose()
    # Remove the heartbeat reference so other test modules don't see it.
    try:
        del api_app.state.heartbeat
    except AttributeError:
        pass


@pytest.fixture
def client():
    return TestClient(api_app)


# ---------------------------------------------------------------------------
# G1 — /health/live
# ---------------------------------------------------------------------------


def test_live_returns_200_when_heartbeat_fresh(app_state, client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_live_returns_503_when_heartbeat_stale(app_state, client):
    """Force the heartbeat's last tick into the distant past — endpoint must 503."""
    app_state["heartbeat"]._last_tick -= 60  # 60 s in the past, well over stale_after
    resp = client.get("/health/live")
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["reason"] == "event_loop_stalled"
    assert body["detail"]["seconds_since_last_tick"] >= 60


def test_live_returns_503_when_heartbeat_missing(client):
    """If the lifespan never ran, no heartbeat → 503 immediately."""
    # Ensure the attribute is absent.
    if hasattr(api_app.state, "heartbeat"):
        del api_app.state.heartbeat
    resp = client.get("/health/live")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# G2 — /health/ready
# ---------------------------------------------------------------------------


def test_ready_returns_200_when_all_deps_ok(app_state, client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["auth_db"] == "ok"
    assert body["checks"]["cipher"] == "ok"
    assert body["checks"]["pipeline_factory"] == "ok"
    assert body["checks"]["executor_pool"] == "ok"
    assert body["checks"]["llm_provider"] == "ok"


def test_ready_returns_503_when_auth_db_fails(app_state, client):
    # Dispose engine so the connect() inside health_ready raises.
    app_state["engine"].dispose()
    # Also close the underlying connection.
    app_state["store"]._engine = MagicMock()
    app_state["store"]._engine.connect.side_effect = RuntimeError("connection refused")
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert checks["auth_db"].startswith("fail")


def test_ready_returns_503_when_factory_missing(app_state, client):
    api_app.state.factory = None
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert checks["pipeline_factory"].startswith("fail")


def test_ready_returns_503_when_executor_pool_shutdown(app_state, client):
    app_state["pool"].shutdown(wait=False, cancel_futures=True)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert checks["executor_pool"].startswith("fail")


def test_ready_returns_503_when_executor_pool_missing(app_state, client):
    api_app.state.executor_pool = None
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert checks["executor_pool"].startswith("fail")


def test_ready_returns_503_when_llm_key_missing(app_state, client):
    app_state["settings"].anthropic_api_key = ""
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert checks["llm_provider"].startswith("fail")


def test_ready_groq_provider_requires_groq_key(app_state, client):
    app_state["settings"].llm_provider = "groq"
    app_state["settings"].groq_api_key = ""
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    checks = resp.json()["detail"]["checks"]
    assert "GROQ" in checks["llm_provider"]
