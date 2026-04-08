"""PipelineFactory — creates and caches per-user pipeline component sets."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cachetools import TTLCache
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL

from src.auth import url_guard
from src.auth.user_store import UserConfig
from src.config import Settings
from src.core.result_formatter import ResultFormatter
from src.core.schema_inspector import SchemaInspector
from src.core.self_corrector import SelfCorrector
from src.core.sql_executor import SQLExecutor
from src.core.sql_generator import SQLGenerator
from src.core.sql_validator import SQLValidator

log = logging.getLogger(__name__)


class NoLLMKeyAvailable(Exception):
    """Raised when neither the user nor the server has a key for the requested LLM provider."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            f"No API key available for provider '{provider}'. "
            "Supply your own key via PUT /v1/users/me."
        )


@dataclass(frozen=True)
class UserSettings:
    """Satisfies the attribute interface expected by SQLGenerator, SQLExecutor,
    and SelfCorrector. Decouples them from the global Settings so they can be
    constructed per-request without leaking config across users.
    """

    llm_provider: str
    anthropic_api_key: str
    groq_api_key: str
    claude_model: str
    groq_model: str
    max_query_rows: int
    query_timeout_seconds: int
    max_self_correction_retries: int


@dataclass(frozen=True)
class PipelineComponents:
    inspector: SchemaInspector
    generator: SQLGenerator
    validator: SQLValidator
    executor: SQLExecutor
    corrector: SelfCorrector
    formatter: ResultFormatter
    dialect: str
    engine: object  # sqlalchemy.engine.Engine — typed as object to avoid circular imports


class _DisposingTTLCache(TTLCache):
    """TTLCache that disposes the SQLAlchemy engine when an entry is evicted."""

    def popitem(self):
        key, value = super().popitem()
        try:
            value.engine.dispose()
        except Exception as exc:
            log.warning("engine_dispose_failed", extra={"err": str(exc)})
        return key, value


class PipelineFactory:
    def __init__(self, settings: Settings, executor_pool: ThreadPoolExecutor) -> None:
        self._settings = settings
        self._executor_pool = executor_pool
        self._cache: _DisposingTTLCache = _DisposingTTLCache(maxsize=100, ttl=3600)
        self._lock = asyncio.Lock()
        self._per_key_locks: dict[tuple, asyncio.Lock] = {}

    async def get(self, user_config: UserConfig) -> PipelineComponents:
        """Return cached pipeline for user_config, building one if needed."""
        cache_key = self._build_key(user_config)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Per-key lock prevents multiple concurrent first-hits from building
        # multiple engines for the same user configuration.
        async with self._lock:
            key_lock = self._per_key_locks.setdefault(cache_key, asyncio.Lock())
        async with key_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

            # Defense in depth: re-validate URL right before binding (T9)
            validated_url = url_guard.validate_database_url(
                user_config.database_url,
                allow_sqlite=self._settings.allow_sqlite_user_dbs,
            )
            url_guard.assert_url_still_safe(validated_url)

            # Build engine off the event loop — pool warmup + dry connect block
            components = await asyncio.to_thread(
                self._build_components, validated_url, user_config
            )
            self._cache[cache_key] = components
            return components

    def _build_key(self, uc: UserConfig) -> tuple[str, str, str, str]:
        # Use key prefix only (first 8 chars) so two users sharing a DB URL but
        # different keys cache separately without storing full keys in memory.
        return (
            uc.database_url,
            uc.llm_provider,
            (uc.anthropic_api_key or "")[:8],
            (uc.groq_api_key or "")[:8],
        )

    def _build_components(self, validated_url: URL, uc: UserConfig) -> PipelineComponents:
        engine = create_engine(
            validated_url,
            pool_size=2,
            max_overflow=3,
            pool_timeout=10,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args=self._connect_args_for(validated_url),
        )
        # Dry-run connect — fail fast at build time rather than at first query
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        inspector = SchemaInspector(
            engine, cache_ttl_seconds=self._settings.schema_cache_ttl_seconds
        )
        user_settings = self._build_user_settings(uc)
        generator = SQLGenerator(user_settings, inspector)
        validator = SQLValidator(inspector)
        executor = SQLExecutor(engine, user_settings, self._executor_pool)
        corrector = SelfCorrector(generator, validator, executor, user_settings)
        formatter = ResultFormatter()

        drivername = validated_url.drivername
        if drivername.startswith("postgresql"):
            dialect = "postgresql"
        elif drivername.startswith("mysql"):
            dialect = "mysql"
        else:
            dialect = "sqlite"

        return PipelineComponents(
            inspector=inspector,
            generator=generator,
            validator=validator,
            executor=executor,
            corrector=corrector,
            formatter=formatter,
            dialect=dialect,
            engine=engine,
        )

    def _connect_args_for(self, url: URL) -> dict:
        if url.drivername.startswith("postgresql"):
            return {"connect_timeout": 10}
        return {}

    def _build_user_settings(self, uc: UserConfig) -> UserSettings:
        anthropic = uc.anthropic_api_key or self._settings.anthropic_api_key or ""
        groq = uc.groq_api_key or self._settings.groq_api_key or ""
        if uc.llm_provider == "anthropic" and not anthropic:
            raise NoLLMKeyAvailable("anthropic")
        if uc.llm_provider == "groq" and not groq:
            raise NoLLMKeyAvailable("groq")
        return UserSettings(
            llm_provider=uc.llm_provider,
            anthropic_api_key=anthropic,
            groq_api_key=groq,
            claude_model=self._settings.claude_model,
            groq_model=self._settings.groq_model,
            max_query_rows=self._settings.max_query_rows,
            query_timeout_seconds=self._settings.query_timeout_seconds,
            max_self_correction_retries=self._settings.max_self_correction_retries,
        )

    async def invalidate(self, user_id: str) -> None:
        """Drop every cache entry whose PipelineComponents belongs to user_id.

        Called from PUT/DELETE /v1/users/me and POST /v1/users/me/rotate-key.
        Note: the cache key doesn't include user_id directly, so we must check
        by rebuilding and comparing — or we clear all entries for safety.
        In practice, invalidation is infrequent and clearing the full cache is
        acceptable.
        """
        async with self._lock:
            for key in list(self._cache.keys()):
                components = self._cache.pop(key)
                components.inspector.refresh()
                try:
                    components.engine.dispose()
                except Exception as exc:
                    log.warning("engine_dispose_on_invalidate_failed", extra={"err": str(exc)})

    async def shutdown(self) -> None:
        """Dispose every cached engine. Called from app lifespan shutdown."""
        async with self._lock:
            for components in list(self._cache.values()):
                try:
                    components.engine.dispose()
                except Exception as exc:
                    log.warning("engine_dispose_on_shutdown_failed", extra={"err": str(exc)})
            self._cache.clear()

    def get_from_settings(self, s: Settings) -> PipelineComponents:
        """Synchronous stdio backward-compat path.

        Builds and caches a pipeline keyed on the global settings database_url.
        Raises RuntimeError if DATABASE_URL is not set.
        """
        if not s.database_url:
            raise RuntimeError(
                "DATABASE_URL must be set for stdio mode. "
                "Set it in .env, or run the HTTP server via `uv run uvicorn src.app:app`."
            )
        synthetic = UserConfig(
            user_id="__stdio__",
            database_url=s.database_url,
            llm_provider=s.llm_provider or "anthropic",
            anthropic_api_key=s.anthropic_api_key or None,
            groq_api_key=s.groq_api_key or None,
            is_active=True,
        )

        # For stdio mode we skip the URL guard (localhost is fine in dev)
        # and build components synchronously.
        cache_key = self._build_key(synthetic)
        if cache_key in self._cache:
            return self._cache[cache_key]

        from sqlalchemy import create_engine

        engine = create_engine(s.database_url)
        inspector = SchemaInspector(engine, cache_ttl_seconds=s.schema_cache_ttl_seconds)
        user_settings = UserSettings(
            llm_provider=s.llm_provider or "anthropic",
            anthropic_api_key=s.anthropic_api_key or "",
            groq_api_key=s.groq_api_key or "",
            claude_model=s.claude_model,
            groq_model=s.groq_model,
            max_query_rows=s.max_query_rows,
            query_timeout_seconds=s.query_timeout_seconds,
            max_self_correction_retries=s.max_self_correction_retries,
        )
        generator = SQLGenerator(user_settings, inspector)
        validator = SQLValidator(inspector)
        executor = SQLExecutor(engine, user_settings, self._executor_pool)
        corrector = SelfCorrector(generator, validator, executor, user_settings)
        formatter = ResultFormatter()
        dialect = "postgresql" if s.database_url.startswith("postgresql") else "sqlite"
        components = PipelineComponents(
            inspector=inspector,
            generator=generator,
            validator=validator,
            executor=executor,
            corrector=corrector,
            formatter=formatter,
            dialect=dialect,
            engine=engine,
        )
        self._cache[cache_key] = components
        return components
