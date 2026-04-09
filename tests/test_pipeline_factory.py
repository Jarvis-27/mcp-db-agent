"""Tests for PipelineFactory — caching, invalidation, LLM key fallback."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from src.auth.user_store import UserConfig
from src.core.pipeline_factory import NoLLMKeyAvailable, PipelineFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pool():
    return ThreadPoolExecutor(max_workers=2)


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.database_url = ""
    s.anthropic_api_key = "sk-ant-global"
    s.groq_api_key = "gsk-global"
    s.llm_provider = "anthropic"
    s.claude_model = "claude-sonnet-4-6"
    s.groq_model = "llama-3.3-70b-versatile"
    s.max_query_rows = 100
    s.query_timeout_seconds = 30
    s.max_self_correction_retries = 3
    s.schema_cache_ttl_seconds = 600
    s.allow_sqlite_user_dbs = True  # allow for tests
    s.environment = "development"
    s.extra_blocked_cidrs = ""
    s.sqlite_user_db_dir = "/tmp"
    s.auth_database_url = "sqlite:///./auth.db"
    return s


def _make_user(url: str = "sqlite:///./demo.db") -> UserConfig:
    return UserConfig(
        user_id="test-user-1",
        database_url=url,
        is_active=True,
    )


def _patch_build(factory):
    """Patch _build_components to return a mock without hitting a real DB."""
    mock_components = MagicMock()
    mock_components.engine = MagicMock()
    mock_components.inspector = MagicMock()
    factory._build_components = MagicMock(return_value=mock_components)
    return mock_components


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


async def test_same_url_returns_cached_pipeline(mock_settings, pool):
    factory = PipelineFactory(mock_settings, pool)
    _patch_build(factory)

    with patch("src.core.pipeline_factory.url_guard") as mock_guard:
        mock_guard.validate_database_url.return_value = MagicMock(drivername="sqlite")
        mock_guard.assert_url_still_safe = MagicMock(return_value=None)
        uc = _make_user()
        p1 = await factory.get(uc)
        p2 = await factory.get(uc)

    assert p1 is p2
    assert factory._build_components.call_count == 1


async def test_different_url_creates_new_pipeline(mock_settings, pool):
    factory = PipelineFactory(mock_settings, pool)
    _patch_build(factory)

    with patch("src.core.pipeline_factory.url_guard") as mock_guard:
        mock_guard.validate_database_url.return_value = MagicMock(drivername="sqlite")
        mock_guard.assert_url_still_safe = MagicMock(return_value=None)

        uc1 = _make_user("sqlite:///./db1.db")
        uc2 = _make_user("sqlite:///./db2.db")
        # Reset mock between calls to track each
        factory._build_components = MagicMock(
            side_effect=[MagicMock(engine=MagicMock(), inspector=MagicMock()),
                         MagicMock(engine=MagicMock(), inspector=MagicMock())]
        )
        p1 = await factory.get(uc1)
        p2 = await factory.get(uc2)

    assert p1 is not p2
    assert factory._build_components.call_count == 2


# ---------------------------------------------------------------------------
# Shutdown disposes all engines
# ---------------------------------------------------------------------------


async def test_shutdown_disposes_all_engines(mock_settings, pool):
    factory = PipelineFactory(mock_settings, pool)
    engine1 = MagicMock()
    engine2 = MagicMock()
    c1 = MagicMock(engine=engine1, inspector=MagicMock())
    c2 = MagicMock(engine=engine2, inspector=MagicMock())
    factory._cache[("url1",)] = c1
    factory._cache[("url2",)] = c2

    await factory.shutdown()

    engine1.dispose.assert_called_once()
    engine2.dispose.assert_called_once()
    assert len(factory._cache) == 0


# ---------------------------------------------------------------------------
# LLM key resolution (server-owned keys after multi-tenant migration)
# ---------------------------------------------------------------------------


def test_server_anthropic_key_used(mock_settings, pool):
    """After the multi-tenant migration, LLM keys come from server settings only."""
    factory = PipelineFactory(mock_settings, pool)
    us = factory._build_user_settings(_make_user())
    assert us.anthropic_api_key == "sk-ant-global"
    assert us.llm_provider == "anthropic"


def test_server_groq_key_used(mock_settings, pool):
    mock_settings.llm_provider = "groq"
    factory = PipelineFactory(mock_settings, pool)
    us = factory._build_user_settings(_make_user())
    assert us.groq_api_key == "gsk-global"
    assert us.llm_provider == "groq"


def test_no_llm_key_available_raises(mock_settings, pool):
    mock_settings.anthropic_api_key = ""
    factory = PipelineFactory(mock_settings, pool)
    with pytest.raises(NoLLMKeyAvailable):
        factory._build_user_settings(_make_user())


# ---------------------------------------------------------------------------
# stdio backward compat
# ---------------------------------------------------------------------------


def test_get_from_settings_raises_without_database_url(mock_settings, pool):
    mock_settings.database_url = ""
    factory = PipelineFactory(mock_settings, pool)
    with pytest.raises(RuntimeError, match="DATABASE_URL must be set"):
        factory.get_from_settings(mock_settings)


def test_get_from_settings_stdio_path_works(mock_settings, pool):
    """Regression: get_from_settings previously passed stale kwargs to UserConfig,
    raising TypeError: UserConfig.__init__() got an unexpected keyword argument 'llm_provider'.
    Pre-seed the cache so no real DB connection is attempted; the UserConfig
    construction (which was the crash site) runs before the cache check.
    """
    mock_settings.database_url = "sqlite:///./demo.db"
    factory = PipelineFactory(mock_settings, pool)

    expected = MagicMock()
    factory._cache[("sqlite:///./demo.db",)] = expected

    result = factory.get_from_settings(mock_settings)
    assert result is expected
