"""Verify that FastAPI's docs/redoc/openapi URLs are gated by ENVIRONMENT (G3).

Tests exercise the ``_build_api_app`` helper directly under each environment
value so they do not need to reload the module — that would invalidate the
shared ``api_app`` singleton other test files cache at import time.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import _build_api_app
from src.config import settings


@pytest.fixture
def production_env(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    return settings


@pytest.fixture
def development_env(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    return settings


@pytest.fixture
def staging_env(monkeypatch):
    monkeypatch.setattr(settings, "environment", "staging")
    return settings


def test_docs_404_in_production(production_env):
    app = _build_api_app()
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_200_in_development(development_env):
    app = _build_api_app()
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"

    client = TestClient(app)
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_docs_visible_in_staging(staging_env):
    """Staging is not 'production'; docs remain visible for QA."""
    app = _build_api_app()
    assert app.docs_url == "/docs"
    client = TestClient(app)
    assert client.get("/openapi.json").status_code == 200
