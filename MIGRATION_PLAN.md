# Multi-Tenant Migration Plan: MCP Database Analytics Agent

> **Status:** production-ready plan, second revision. Validated for efficiency, reliability, security, and operability against the current code, the FastMCP/MCP-Python-SDK behaviour, and SQLAlchemy multi-tenant best practices.
>
> **No code in this repository has been changed yet.** This file is the spec.

---

## 1. Context

The MCP Database Analytics Agent currently runs as a single-user local tool: one operator edits `.env` to point at their database, then any MCP client (Claude Desktop, Cursor, VS Code Copilot) talks to the local stdio process.

The goal is to deploy it as a hosted service where **multiple users register their own database**, receive an API key, and connect any MCP client to a shared HTTP endpoint — without touching `.env` or running their own instance.

**Product decisions (locked in):**
- Open registration, lockable via `REGISTRATION_OPEN` env flag.
- SQLite for the auth database in dev; **Postgres required for any deployment with `--workers > 1`**. Swap is a config change (`AUTH_DATABASE_URL`).
- LLM-key fallback: if a user does not supply their own keys, the server's global keys are used (subject to per-user quota — see §6).
- Stdio mode (`uv run src/server.py`) must remain a working single-user path for local development.

---

## 2. Root Problem

`src/server.py:40-59` builds module-level singletons tied to one database at import time:

```python
engine = create_engine(settings.database_url)         # single DB, global scope
inspector = SchemaInspector(engine)
generator = SQLGenerator(settings, inspector)
...
_cache: dict[str, tuple[str, float]] = {}             # shared across all callers
```

`src/config.py:10-19` requires `database_url`, `anthropic_api_key`, `groq_api_key`, `llm_provider` — all single-user fields — at startup.

There is no auth, no user model, no per-request scoping, and no way to safely accept a database URL from an untrusted user.

---

## 3. Threat Model (read this before designing anything)

A hosted multi-tenant MCP server that accepts arbitrary database URLs from open registration faces a hostile environment. Every design decision below is a response to a specific threat in this list. **If a fix would weaken any of these, do not apply it.**

| # | Threat | Mitigation lives in |
|---|---|---|
| T1 | SSRF / arbitrary file read via user-supplied `database_url` (e.g. `sqlite:///./auth.db`, `postgresql://_@169.254.169.254/`) | `src/auth/url_guard.py` (§5.1) |
| T2 | RCE / file read via user DB privileges (`COPY ... FROM PROGRAM`, `pg_read_file`, `ATTACH DATABASE`, `load_extension`) | `src/core/sql_validator.py` extension (§6.5) |
| T3 | Cross-tenant data leak via shared `_cache`, ContextVar, or schema cache | request-scoped ContextVar with `try/finally` reset, per-user cache keys (§5.3, §6.1) |
| T4 | Cost abuse — burning the server's fallback LLM credits via spam | per-user quotas + rate limiting on `/v1/users/register` and `/mcp/*` (§5.4, §5.5) |
| T5 | Connection exhaustion — single tenant opens 1500 connections to user DBs | bounded per-engine pool, dispose-on-eviction (§6.2) |
| T6 | Credential disclosure at rest — auth.db dump leaks all tenant DB URLs and LLM keys | Fernet (rotatable via MultiFernet) + SHA-256 of api keys, never plaintext (§5.2) |
| T7 | Auth bypass / cross-tenant attribution loss in query history | non-nullable `user_id` in `query_history`, indexed; sentinel `__stdio__` for stdio mode (§6.4) |
| T8 | Prompt injection from user database content (sample values reach LLM prompt) | acknowledged, out of scope for this migration; tracked as future ticket |
| T9 | DNS rebinding — register a hostname that resolves public at register time, internal at connect time | url_guard re-validates IP at engine-build time inside `PipelineFactory.get()` (§5.1, §6.2) |
| T10 | Encryption-key compromise / rotation | `MultiFernet` with `CREDENTIAL_ENCRYPTION_KEYS=` (plural), documented rotation runbook (§5.2, §10) |

---

## 4. Target Architecture

```
                        HTTPS (terminated at reverse proxy)
                                │
                                ▼
                        uvicorn workers (N)
                                │
                                ▼
                  ┌──── Starlette parent app ────┐
                  │   lifespan = mcp_app.lifespan │
                  │     + AsyncExitStack (UserStore engine, PipelineFactory)
                  └──────────────────────────────┘
                        │                   │
                        │                   │
              Mount("/api", fastapi_app)    Mount("/mcp", mcp_app)
                        │                   │
                        │                   ▼
                        │       ApiKeyMiddleware (ASGI)
                        │           │ read X-API-Key OR Authorization: Bearer
                        │           │ TTL-LRU (60s) on sha256(key) → UserConfig
                        │           │ set user_config_var (ContextVar)
                        │           ▼
                        │       FastMCP(stateless_http=True, json_response=True)
                        │           │
                        │           ▼
                        │       _get_pipeline()          ← reads ContextVar
                        │           │
                        │           ▼
                        │       PipelineFactory.get(user_config)
                        │           │  TTLCache(maxsize=100, ttl=3600)
                        │           │  key = (database_url, llm_provider, key_prefix)
                        │           │  evict → engine.dispose()
                        │           ▼
                        │       SchemaInspector (TTL-cached schema string)
                        │       SQLGenerator | SQLValidator (hardened)
                        │       SQLExecutor (shared bounded ThreadPool)
                        │       SelfCorrector | ResultFormatter
                        │           │
                        │           └─→ QueryLog.log_query(..., user_id)
                        │
                        └─→ FastAPI registration / management endpoints
                                │
                                ▼
                            UserStore (auth DB: Postgres in prod, SQLite in dev)
```

**Key invariants:**
- **One ASGI lifespan**, on the parent Starlette app, composed via `AsyncExitStack` from FastMCP's lifespan + the UserStore engine + the PipelineFactory shutdown hook. Nested lifespans on mounted sub-apps are *not* invoked by Starlette — this is documented MCP-SDK behaviour and the #1 cause of "first /mcp request 500s".
- **`stateless_http=True, json_response=True`** on FastMCP — required for multi-tenant horizontal scale; eliminates per-session server state across workers.
- **`streamable_http_path="/"`** on FastMCP so mounting at `Mount("/mcp", mcp_app)` produces `/mcp/...` URLs and not `/mcp/mcp/...`.
- **stdio backward compatibility** preserved: `uv run src/server.py` still works because `_get_pipeline()` falls back to `_factory.get_from_settings(settings)` when no ContextVar is set. In that mode `settings.database_url` is required and the server fails loud at startup if missing.

---

## 5. Files to Create

### 5.1 `src/auth/url_guard.py` — **THE** security-critical module

Validates every user-supplied `database_url` before it ever reaches `create_engine()`. Runs at two points:

1. On `POST /v1/users/register` and `PUT /v1/users/me`.
2. Inside `PipelineFactory.get()` immediately before `create_engine()` (defense in depth, defeats DNS rebinding — T9).

```python
def validate_database_url(raw: str, *, allow_sqlite: bool) -> URL:
    """
    Returns a sanitised sqlalchemy.engine.url.URL or raises InvalidDatabaseURL.

    Hard rules:
      * Length <= 2048 chars; reject \\n, \\0, ;
      * make_url() must succeed
      * Scheme allow-list:
            postgresql, postgresql+psycopg2, mysql+pymysql
            (sqlite only when allow_sqlite=True; never in hosted prod)
      * For sqlite: path must be inside settings.sqlite_user_db_dir,
            no '..' segments, not equal to AUTH_DATABASE_URL or QUERY_LOG path.
      * For network DBs: resolve hostname to ALL its A/AAAA records via
            socket.getaddrinfo(); reject if ANY resolved IP is in:
                - 127.0.0.0/8, ::1
                - 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
                - 169.254.0.0/16 (link-local + cloud metadata)
                - fc00::/7 (ULA), fe80::/10 (link-local v6)
                - 0.0.0.0/8
                - any IP in settings.extra_blocked_cidrs
      * Strip query params: options, passfile, service, sslkey, sslcert,
            sslrootcert, krbsrvname, gsslib, host (anything that can
            redirect connection or read local files)
      * For postgresql in prod: require sslmode in {require, verify-ca, verify-full}
      * Return the sanitised URL
    """
```

**Companion function:**
```python
def assert_url_still_safe(url: URL) -> None:
    """Re-resolve hostname and re-check IP class. Called from PipelineFactory.get()."""
```

**Tests** (`tests/test_url_guard.py`) cover every threat in T1, T9.

### 5.2 `src/auth/crypto.py`

Thin wrapper around `cryptography.fernet.MultiFernet`. Plural keys enable rotation without re-encrypting at rest (see §10 runbook).

```python
class CredentialCipher:
    def __init__(self, keys: list[str]) -> None:
        # First key is the encryption key; all keys can decrypt.
        # Raises if keys is empty.
        self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])

    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str:
        # Raises CredentialDecryptError on failure (typed, not InvalidToken)
```

Constructed once at startup from `settings.credential_encryption_keys` (comma-separated). Injected into `UserStore`. Never imports `settings` itself — pure data in, data out.

### 5.3 `src/auth/user_store.py`

SQLAlchemy `users` table + `UserStore` class. **Migrations are managed by Alembic** (§5.7) — `Base.metadata.create_all` is *not* used for hosted deployments.

**SQLAlchemy model `User`:**

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | UUID4 string |
| `api_key_hash` | `String(64)` UNIQUE INDEX | SHA-256 hex of raw key |
| `database_url_enc` | `Text` NOT NULL | Fernet-encrypted (sanitised URL) |
| `llm_provider` | `String(20)` NOT NULL | `"anthropic"` or `"groq"` (matches existing code) |
| `anthropic_api_key_enc` | `Text` nullable | Fernet-encrypted |
| `groq_api_key_enc` | `Text` nullable | Fernet-encrypted |
| `is_active` | `Boolean` NOT NULL | default True |
| `created_at` | `DateTime(timezone=True)` NOT NULL | UTC, `datetime.now(UTC)` |
| `updated_at` | `DateTime(timezone=True)` NOT NULL | UTC, refreshed on update |
| `daily_query_count` | `Integer` NOT NULL | default 0, reset by `daily_quota_reset_at` |
| `daily_quota_reset_at` | `DateTime(timezone=True)` NOT NULL | UTC midnight rollover |

**In-memory dataclass `UserConfig`** — never persisted, returned from store, frozen:

```python
@dataclass(frozen=True)
class UserConfig:
    user_id: str
    database_url: str           # decrypted, already passed url_guard
    llm_provider: str
    anthropic_api_key: str | None   # decrypted; None if user did not supply
    groq_api_key: str | None        # decrypted; None if user did not supply
    is_active: bool
```

**`UserStore` methods:**

```python
def __init__(self, engine: Engine, cipher: CredentialCipher) -> None:
    # engine is injected; UserStore does NOT call create_all (Alembic handles schema)

def create_user(database_url, llm_provider, anthropic_api_key, groq_api_key) -> tuple[str, str]:
    """
    Returns (user_id, raw_api_key).
    raw_api_key format: 'mdbk_' + secrets.token_urlsafe(32)
    Stores SHA-256(raw_api_key) only.
    """

def get_user_by_api_key(raw_key: str) -> UserConfig | None:
    """Hash → DB lookup → decrypt → return UserConfig; None if missing or inactive."""

def get_user_by_id(user_id: str) -> UserConfig | None

def update_user(user_id, *, database_url=None, llm_provider=None,
                anthropic_api_key=None, groq_api_key=None) -> bool:
    """Partial update. Refreshes updated_at. Returns False if user missing."""

def rotate_api_key(user_id: str) -> str:
    """Generate a new raw key, replace api_key_hash, return raw key. Caller must
    invalidate any auth-key cache and any cached pipeline for this user."""

def deactivate_user(user_id: str) -> bool

def increment_daily_quota(user_id: str) -> int:
    """Atomic counter increment with daily reset; returns new count.
    Used by ask_database when the user is on the fallback LLM keys."""
```

**Critical:** every `database_url` written through `create_user`/`update_user` MUST go through `url_guard.validate_database_url()` first. The store rejects unsanitised input.

### 5.4 `src/auth/middleware.py`

Pure ASGI middleware (Starlette-compatible, FastMCP-version-agnostic). Houses the request-scoped ContextVar.

```python
user_config_var: ContextVar[UserConfig | None] = ContextVar("user_config", default=None)


class ApiKeyMiddleware:
    def __init__(self, app: ASGIApp, user_store: UserStore,
                 cache: TTLCache[str, UserConfig]) -> None:
        self._app = app
        self._user_store = user_store
        self._cache = cache  # keyed on sha256(key) — never raw

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        raw_key = _extract_api_key(scope["headers"])  # X-API-Key OR Authorization: Bearer mdbk_...
        if raw_key is None:
            await _send_401(send, "Missing API key")
            return

        cache_key = hashlib.sha256(raw_key.encode()).hexdigest()
        user_config = self._cache.get(cache_key)
        if user_config is None:
            user_config = self._user_store.get_user_by_api_key(raw_key)
            if user_config is None:
                await _send_401(send, "Invalid API key")
                return
            self._cache[cache_key] = user_config

        token = user_config_var.set(user_config)
        try:
            await self._app(scope, receive, send)
        finally:
            user_config_var.reset(token)   # exception-safe, always
```

**Why both header forms:** some MCP clients only support `Authorization: Bearer ...`. Accepting `X-API-Key` keeps curl examples cheap, accepting Bearer keeps clients happy.

**Why hash the cache key:** never hold raw API keys in process memory longer than the lookup itself.

**TTL on the cache:** 60 seconds. Short enough that `update_user`/`deactivate_user`/`rotate_api_key` propagate quickly without forcing cache invalidation across workers (which would require pub/sub). The store also exposes `invalidate_cached_key(sha256_hex)` for the same-worker case.

### 5.5 `src/api/__init__.py` — empty

### 5.6 `src/api/schemas.py`

Pydantic v2 request/response models. **All string fields are bounded.**

```python
LLMProvider = Literal["anthropic", "groq"]   # matches existing src/config.py and sql_generator.py

class RegisterRequest(BaseModel):
    database_url: str = Field(..., min_length=1, max_length=2048)
    llm_provider: LLMProvider = "anthropic"
    anthropic_api_key: str | None = Field(default=None, max_length=512)
    groq_api_key: str | None = Field(default=None, max_length=512)

class RegisterResponse(BaseModel):
    user_id: str
    api_key: str   # 'mdbk_...' — shown ONCE, never again
    warning: str = "Store this key now. We cannot show it to you again."

class UserMetaResponse(BaseModel):
    user_id: str
    llm_provider: LLMProvider
    has_anthropic_key: bool
    has_groq_key: bool
    is_active: bool
    created_at: str   # ISO 8601 UTC
    daily_query_count: int

class UpdateRequest(BaseModel):
    database_url: str | None = Field(default=None, max_length=2048)
    llm_provider: LLMProvider | None = None
    anthropic_api_key: str | None = Field(default=None, max_length=512)
    groq_api_key: str | None = Field(default=None, max_length=512)

class RotateKeyResponse(BaseModel):
    api_key: str   # new key, shown ONCE
```

### 5.7 `src/api/app.py`

FastAPI app. The `UserStore` is read from `request.app.state.user_store` (set by `src/app.py` at startup) — module-level injection is avoided so the test client can mount its own state cleanly.

**Endpoints:**

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/users/register` | none (open, rate-limited 5/min/IP) | Register → returns `{user_id, api_key}`. **Performs dry-run connect** to the supplied DB URL with a 5 s timeout to fail fast on bad credentials. |
| `GET` | `/v1/users/me` | X-API-Key / Bearer | Return user metadata (no secrets). |
| `PUT` | `/v1/users/me` | X-API-Key / Bearer | Update database_url / API keys. Re-runs `url_guard`, dry-run connect, and `PipelineFactory.invalidate(user_id)`. |
| `POST` | `/v1/users/me/rotate-key` | X-API-Key / Bearer | Issue a new API key, invalidate old. |
| `DELETE` | `/v1/users/me` | X-API-Key / Bearer | Deactivate; `PipelineFactory.invalidate(user_id)`; cache invalidation. |
| `GET` | `/health/live` | none | Process up. Returns `{"status":"ok"}`. |
| `GET` | `/health/ready` | none | Process up + auth DB reachable + cipher initialised. Returns 503 on failure. |

**Rate limiting:** `slowapi`, configured globally on `register` (5/min/IP) and on `rotate-key` (10/hour/user). Limits are env-tunable.

**Dependency `require_api_key`:** reads `X-API-Key` header (or `Authorization: Bearer`), looks up user via the same auth-key cache used by the MCP middleware, returns the `UserConfig`. Raises `HTTPException(401)` on failure.

**Error responses are bounded** — we never echo back the supplied database_url or API key in any 4xx body, to avoid log poisoning.

### 5.8 `src/core/pipeline_factory.py`

Caches pipeline components keyed by user config. Replaces the module-level singletons in the current `src/server.py`.

```python
@dataclass(frozen=True)
class PipelineComponents:
    inspector: SchemaInspector
    generator: SQLGenerator
    validator: SQLValidator
    executor: SQLExecutor
    corrector: SelfCorrector
    formatter: ResultFormatter
    dialect: str
    engine: Engine        # held so eviction can dispose


class _DisposingTTLCache(TTLCache):
    """TTLCache that calls engine.dispose() when an entry is evicted."""
    def popitem(self):
        key, value = super().popitem()
        try:
            value.engine.dispose()
        except Exception as exc:
            log.warning("engine_dispose_failed", extra={"fields": {"err": str(exc)}})
        return key, value


class PipelineFactory:
    def __init__(self, settings: Settings, executor_pool: ThreadPoolExecutor) -> None:
        self._settings = settings
        self._executor_pool = executor_pool
        self._cache: _DisposingTTLCache = _DisposingTTLCache(maxsize=100, ttl=3600)
        self._lock = asyncio.Lock()
        self._per_key_locks: dict[tuple, asyncio.Lock] = {}

    async def get(self, user_config: UserConfig) -> PipelineComponents:
        cache_key = self._build_key(user_config)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Per-key lock so concurrent first-hits for the same user
        # only build one Engine.
        async with self._lock:
            key_lock = self._per_key_locks.setdefault(cache_key, asyncio.Lock())
        async with key_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

            # Defense in depth: re-validate URL right before binding.
            url = url_guard.validate_database_url(
                user_config.database_url,
                allow_sqlite=self._settings.allow_sqlite_user_dbs,
            )
            url_guard.assert_url_still_safe(url)

            # Build engine OFF the event loop — pool warmup + dry connect block.
            components = await asyncio.to_thread(self._build_components, url, user_config)
            self._cache[cache_key] = components
            return components

    def _build_key(self, uc: UserConfig) -> tuple[str, str, str, str]:
        # Key prefix only — never the full key — and only the first 8 chars
        # so two users sharing the same DB URL but different keys cache separately.
        return (
            uc.database_url,
            uc.llm_provider,
            (uc.anthropic_api_key or "")[:8],
            (uc.groq_api_key or "")[:8],
        )

    def _build_components(self, url: URL, uc: UserConfig) -> PipelineComponents:
        engine = create_engine(
            url,
            pool_size=2,
            max_overflow=3,
            pool_timeout=10,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args=self._connect_args_for(url),
        )
        # Dry-run: fail fast at first call rather than at first query
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        inspector = SchemaInspector(engine)
        user_settings = self._build_user_settings(uc)
        generator = SQLGenerator(user_settings, inspector)
        validator = SQLValidator(inspector)
        executor = SQLExecutor(engine, user_settings, self._executor_pool)
        corrector = SelfCorrector(generator, validator, executor, user_settings)
        formatter = ResultFormatter()
        dialect = "postgresql" if url.drivername.startswith("postgresql") else \
                  "mysql" if url.drivername.startswith("mysql") else "sqlite"
        return PipelineComponents(inspector, generator, validator, executor,
                                   corrector, formatter, dialect, engine)

    def _build_user_settings(self, uc: UserConfig) -> "UserSettings":
        # LLM key fallback — empty string is treated as "not set".
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
        """Drop every cache entry whose UserConfig.user_id matches.
        Called from PUT/DELETE /v1/users/me and POST /v1/users/me/rotate-key."""
        async with self._lock:
            for key in [k for k, v in self._cache.items() if v_user_id_matches(k, user_id)]:
                components = self._cache.pop(key)
                components.engine.dispose()

    async def shutdown(self) -> None:
        """Dispose every cached engine. Called from app lifespan shutdown."""
        async with self._lock:
            for components in list(self._cache.values()):
                components.engine.dispose()
            self._cache.clear()

    def get_from_settings(self, s: Settings) -> PipelineComponents:
        """Stdio backward-compat path."""
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
        # Sync path — stdio mode is single-threaded.
        return asyncio.get_event_loop().run_until_complete(self.get(synthetic))
```

**`UserSettings` adapter** (defined in this file):

```python
@dataclass(frozen=True)
class UserSettings:
    """Satisfies the attribute interface expected by SQLGenerator,
    SQLExecutor, SelfCorrector. Decouples them from the global Settings
    so they can be constructed per-request without leaking config across users.
    """
    llm_provider: str
    anthropic_api_key: str
    groq_api_key: str
    claude_model: str
    groq_model: str
    max_query_rows: int
    query_timeout_seconds: int
    max_self_correction_retries: int
```

**No changes** are required to `sql_generator.py`, `sql_executor.py`, or `self_corrector.py` beyond `SQLExecutor` accepting an injected `ThreadPoolExecutor` (see §6.3) — they only read named attributes, and `UserSettings` provides all of them.

### 5.9 `src/app.py` — combined ASGI entry point

Single source of truth for the hosted deployment. Stdio mode does not use this file.

```python
async def lifespan(app: Starlette):
    # 1. Build cipher (fails loud if no encryption key)
    cipher = CredentialCipher(settings.credential_encryption_keys_list())

    # 2. Build auth-DB engine
    auth_engine = create_engine(settings.auth_database_url, pool_pre_ping=True)
    if settings.auth_database_url.startswith("sqlite"):
        _enable_sqlite_wal(auth_engine)

    # 3. Build UserStore
    user_store = UserStore(auth_engine, cipher)

    # 4. Build query-key cache, query log, factory
    auth_key_cache = TTLCache(maxsize=10_000, ttl=60)
    executor_pool = ThreadPoolExecutor(max_workers=settings.query_pool_size,
                                        thread_name_prefix="sql-exec")
    query_log = QueryLog(engine=auth_engine)   # share auth DB by default; see §6.4
    factory = PipelineFactory(settings, executor_pool)

    # 5. Stash on app.state for the FastAPI app
    api_app.state.user_store = user_store
    api_app.state.auth_key_cache = auth_key_cache
    api_app.state.factory = factory

    # 6. Stash for the FastMCP tool layer (server.py reads these via getattr)
    server_module = importlib.import_module("src.server")
    server_module._factory = factory
    server_module._query_log = query_log

    # 7. Compose with FastMCP's lifespan
    async with mcp_app.router.lifespan_context(app):
        try:
            yield
        finally:
            await factory.shutdown()
            executor_pool.shutdown(wait=False, cancel_futures=True)
            auth_engine.dispose()


# Build the FastMCP instance with the production flags
import src.server as server_module
mcp = server_module.build_mcp(
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",   # so Mount("/mcp", ...) gives /mcp/...
)
mcp_app = mcp.streamable_http_app()

# Build FastAPI app
api_app = build_api_app()      # see src/api/app.py

# Wrap mcp_app with API key middleware
authed_mcp_app = ApiKeyMiddleware(
    mcp_app,
    user_store=...,             # bound at lifespan startup via app.state
    cache=...,
)

# Parent Starlette app — note lifespan is at this level
app = Starlette(
    lifespan=lifespan,
    routes=[
        Mount("/api", app=api_app),
        Mount("/mcp", app=authed_mcp_app),
    ],
    middleware=[
        Middleware(RequestIDMiddleware),                # adds request_id ContextVar
        Middleware(BodySizeLimitMiddleware,
                   max_bytes=settings.max_request_bytes),
        Middleware(CORSMiddleware,
                   allow_origins=settings.cors_allow_origins,
                   allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["*"]),
    ],
)

if __name__ == "__main__":
    # In prod we run via `uvicorn src.app:app --workers 4 --proxy-headers ...`.
    # This block is for `python src/app.py` quickstart only.
    import uvicorn
    uvicorn.run(
        "src.app:app",
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
```

**Why this shape:**
- `lifespan` lives on the **parent** Starlette app and composes FastMCP's lifespan via `mcp_app.router.lifespan_context(app)`. Without this, the streamable HTTP session manager never starts and `/mcp/*` 500s.
- `streamable_http_path="/"` prevents the `/mcp/mcp/...` double-prefix bug.
- All middlewares — request ID, body size cap, CORS — live on the parent app so both `/api` and `/mcp` get them.
- Engines and the thread pool are torn down in shutdown.

### 5.10 `src/middleware/request_id.py`

Tiny ASGI middleware: read `X-Request-ID` if present (sanitised), otherwise mint a UUID4. Set a `request_id_var: ContextVar[str]`. The JSON logger reads it and adds it to every line. Critical for debugging multi-tenant traffic.

### 5.11 `src/middleware/body_size.py`

Reject any request with `Content-Length` over `settings.max_request_bytes` (default 65536). Defends against memory abuse on `POST /v1/users/register`.

### 5.12 `alembic/` + `alembic.ini` — migrations from day one

We adopt Alembic immediately so the auth and query-log schemas can evolve without data loss. The plan ships with one initial migration:

- `alembic/versions/0001_initial.py` — creates `users` and `query_history` tables exactly as specified in §5.3 and §6.4.
- `alembic.ini` configured to read `AUTH_DATABASE_URL` from environment (not hard-coded).
- A startup hook in `src/app.py` lifespan **logs a warning** (not an error) if `alembic_version` is missing or behind head, and refuses to start in production mode (`settings.environment == "production"`). Dev mode auto-runs `alembic upgrade head`.

---

## 6. Files to Modify

### 6.1 `src/config.py`

Make all single-user fields optional with empty defaults; add the multi-tenant settings. Validate at use-site, fail fast in HTTP mode.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE))

    # ── Single-user / stdio mode (now optional) ────────────────────────
    database_url: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = ""
    claude_model: str = "claude-sonnet-4-6"
    groq_model: str = "llama-3.3-70b-versatile"
    max_query_rows: int = 100
    query_timeout_seconds: int = 30
    max_self_correction_retries: int = 3
    transport: str = "stdio"

    # ── Multi-tenant / hosted mode ─────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    auth_database_url: str = "sqlite:///./auth.db"
    credential_encryption_keys: str = ""   # comma-separated; first is the encryption key
    registration_open: bool = True
    allow_sqlite_user_dbs: bool = False    # NEVER true in prod
    sqlite_user_db_dir: str = "/var/lib/mcp-db-agent/user-dbs"
    extra_blocked_cidrs: str = ""          # comma-separated; e.g. "10.20.30.0/24,..."
    port: int = 8000
    cors_allow_origins: list[str] = []     # empty = closed
    max_request_bytes: int = 65536
    query_pool_size: int = 64              # ThreadPoolExecutor for SQLExecutor
    register_rate_limit: str = "5/minute"
    ask_database_quota_per_day: int = 200  # only enforced when on fallback LLM keys
    schema_cache_ttl_seconds: int = 600

    @field_validator("credential_encryption_keys")
    @classmethod
    def _check_keys(cls, v: str, info) -> str:
        if not v and info.data.get("environment") != "development":
            raise ValueError(
                "CREDENTIAL_ENCRYPTION_KEYS is required in non-development mode. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet;"
                " print(Fernet.generate_key().decode())\""
            )
        return v

    def credential_encryption_keys_list(self) -> list[str]:
        return [k.strip() for k in self.credential_encryption_keys.split(",") if k.strip()]
```

### 6.2 `src/server.py`

**Remove** lines 40–52 (global engine + all singleton component construction). **Remove** the module-level `dialect` line.

**Add** at module level:

```python
from src.auth.middleware import user_config_var
from src.core.pipeline_factory import PipelineFactory, NoLLMKeyAvailable
from cachetools import TTLCache

# These are populated by src/app.py lifespan startup. In stdio mode they are
# created lazily inside _get_pipeline().
_factory: PipelineFactory | None = None
_query_log: QueryLog | None = None

# Bounded LRU+TTL — multi-tenant safe.
_cache: TTLCache[tuple[str, str], tuple[str, float]] = TTLCache(maxsize=1000, ttl=3600)
CACHE_TTL = 3600


def build_mcp(*, stateless_http: bool = True,
              json_response: bool = True,
              streamable_http_path: str = "/") -> FastMCP:
    """Construct the FastMCP instance with the requested HTTP flags.
    Called by src/app.py for hosted mode and by __main__ for stdio mode."""
    return FastMCP(
        "Database Analytics Agent",
        host="0.0.0.0",
        port=settings.port,
        stateless_http=stateless_http,
        json_response=json_response,
        streamable_http_path=streamable_http_path,
    )


mcp = build_mcp(stateless_http=False, json_response=False, streamable_http_path="/mcp")


async def _get_pipeline() -> PipelineComponents:
    global _factory
    user_config = user_config_var.get()
    if _factory is None:
        # Stdio fallback path: build a factory the first time.
        _factory = PipelineFactory(settings, ThreadPoolExecutor(max_workers=8))
    if user_config is not None:
        return await _factory.get(user_config)
    return _factory.get_from_settings(settings)


def _current_user_id() -> str:
    uc = user_config_var.get()
    return uc.user_id if uc is not None else "__stdio__"
```

**Modify each tool/resource handler** to call `_get_pipeline()`:

```python
@mcp.resource("schema://overview")
async def schema_overview() -> str:
    pipeline = await _get_pipeline()
    return get_schema_overview(pipeline.inspector)

@mcp.tool()
async def list_tables() -> str:
    pipeline = await _get_pipeline()
    return _list_tables(pipeline.inspector)

@mcp.tool()
async def describe_schema(table_name: str) -> str:
    pipeline = await _get_pipeline()
    return _describe_schema(table_name, pipeline.inspector)

@mcp.tool()
async def get_sample_data(table_name: str, limit: int = 5) -> str:
    pipeline = await _get_pipeline()
    return _get_sample_data(table_name, pipeline.inspector, limit)

@mcp.tool()
async def ask_database(question: str) -> str:
    pipeline = await _get_pipeline()
    user_id = _current_user_id()

    cache_key = (user_id, question.lower().strip())
    now = time.monotonic()

    # Cache hit
    if cache_key in _cache:
        cached_result, cached_at = _cache[cache_key]
        if now - cached_at < CACHE_TTL:
            payload = json.loads(cached_result)
            payload["cached"] = True
            return json.dumps(payload, indent=2)

    # LLM-quota enforcement on fallback path
    uc = user_config_var.get()
    on_fallback = uc is not None and (
        (uc.llm_provider == "anthropic" and not uc.anthropic_api_key) or
        (uc.llm_provider == "groq" and not uc.groq_api_key)
    )
    if on_fallback:
        used = await asyncio.to_thread(_factory._user_store.increment_daily_quota, user_id)
        if used > settings.ask_database_quota_per_day:
            return formatter.format_error(
                "Daily fallback quota exceeded. Provide your own LLM key via PUT /v1/users/me.",
                "", []
            )

    start = time.monotonic()
    result = await pipeline.corrector.execute_with_correction(question, pipeline.dialect)
    duration_ms = int((time.monotonic() - start) * 1000)

    if result["success"]:
        formatted = pipeline.formatter.format(result["sql"], result["data"], result["attempts"])
        _query_log.log_query(
            question=question, sql=result["sql"], success=True,
            row_count=len(result["data"]), attempts=result["attempts"],
            duration_ms=duration_ms, error=None, user_id=user_id,
        )
        _cache[cache_key] = (formatted, time.monotonic())
        return formatted

    # ... error path identical to today, plus user_id=user_id in log_query call ...

@mcp.tool()
async def query_history(limit: int = 10) -> str:
    user_id = _current_user_id()
    return json.dumps(_query_log.get_recent_queries(limit, user_id=user_id), indent=2)
```

**Important:** the `schema_context_length = len(generator.get_schema_context())` line in current `server.py:168` is **removed**. It triggers the full schema scan a second time per question; we already cache the schema string inside `SchemaInspector` (§6.5) but eliminating the dead computation is simpler and free.

**`if __name__ == "__main__"`** block stays — stdio path is unchanged. It still calls `mcp.run(transport="stdio")` after the HTTP-mode lazy init.

### 6.3 `src/core/sql_executor.py`

Accept an injected `ThreadPoolExecutor` instead of using the default. Critical so registration endpoints don't share a thread pool with long-running user queries.

```python
class SQLExecutor:
    def __init__(self, engine: Engine, settings, pool: ThreadPoolExecutor) -> None:
        self._engine = engine
        self._timeout = settings.query_timeout_seconds
        self._pool = pool

    async def execute(self, sql: str) -> list[dict[str, object]]:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(self._pool, partial(self._run_query, sql)),
            timeout=float(self._timeout),
        )

    # _run_query is unchanged
```

`PipelineFactory` constructs every `SQLExecutor` with the same shared pool (`settings.query_pool_size`, default 64).

### 6.4 `src/core/query_log.py`

**Targeted changes:**

1. Constructor accepts an injected `Engine` so we can share the auth DB or use a separate one without re-opening files.
2. `user_id` column is **non-nullable** with no default; every call site must pass it. Stdio mode passes `"__stdio__"`.
3. Composite index `(user_id, id desc)` for fast history queries at scale.
4. Switch `datetime.utcnow()` (deprecated in 3.12) to `datetime.now(datetime.UTC)`.
5. If the engine is SQLite, enable WAL on `connect` via `event.listens_for(engine, "connect")`:
   ```python
   def _enable_wal(dbapi_conn, _):
       cur = dbapi_conn.cursor()
       cur.execute("PRAGMA journal_mode=WAL")
       cur.execute("PRAGMA busy_timeout=5000")
       cur.execute("PRAGMA synchronous=NORMAL")
       cur.close()
   ```
6. `get_recent_queries(limit, user_id)` requires a non-empty `user_id`; raises `ValueError` if missing.
7. Schema is owned by Alembic — `_Base.metadata.create_all` is removed; `__init__` only stores the engine.

### 6.5 `src/core/schema_inspector.py`

Add a TTL cache around `get_full_schema()` (the most expensive method, called on every `ask_database` invocation):

```python
class SchemaInspector:
    def __init__(self, engine: Engine, cache_ttl_seconds: int = 600) -> None:
        self._engine = engine
        self._inspector = inspect(engine)
        self._schema_cache: tuple[str, float] | None = None
        self._cache_ttl = cache_ttl_seconds

    def get_full_schema(self) -> str:
        if self._schema_cache is not None:
            text, ts = self._schema_cache
            if time.monotonic() - ts < self._cache_ttl:
                return text

        text = self._build_full_schema()
        self._schema_cache = (text, time.monotonic())
        return text

    def refresh(self) -> None:
        """Bust the schema cache. Called from PipelineFactory.invalidate()
        and from a new MCP tool `refresh_schema` (optional)."""
        self._schema_cache = None
        self._inspector = inspect(self._engine)

    # _build_full_schema is the existing get_full_schema body
```

`PipelineFactory.invalidate(user_id)` calls `inspector.refresh()` on every dropped entry before `engine.dispose()`.

### 6.6 `src/core/sql_validator.py` — security hardening

Add the dangerous-keyword block list and single-statement enforcement.

```python
_FORBIDDEN_FUNCTIONS = {
    # PostgreSQL file/network/RCE
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "pg_stat_file", "lo_import", "lo_export",
    "dblink", "dblink_connect",
    # SQLite
    "load_extension",
}

_FORBIDDEN_STATEMENT_PATTERNS = [
    re.compile(r"\bCOPY\b.*\bFROM\s+PROGRAM\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bCOPY\b.*\bTO\s+PROGRAM\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bATTACH\s+DATABASE\b", re.IGNORECASE),
    re.compile(r"\bDETACH\s+DATABASE\b", re.IGNORECASE),
    re.compile(r"\bSELECT\b.*\bINTO\s+\w", re.IGNORECASE | re.DOTALL),  # SELECT INTO new_table
    re.compile(r"\bPRAGMA\b\s+writable_schema", re.IGNORECASE),
    re.compile(r"\bLOAD_FILE\s*\(", re.IGNORECASE),                       # MySQL
    re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE),                     # MySQL
    re.compile(r"\bINTO\s+DUMPFILE\b", re.IGNORECASE),                    # MySQL
]
```

`SQLValidator.validate()` adds, after the existing checks:

1. **Single statement only** — `len([s for s in sqlparse.parse(sql) if s.tokens]) == 1`. Multi-statement strings are rejected.
2. **Forbidden function scan** — for each forbidden function name, regex `\bname\s*\(` (case-insensitive). Reject on match.
3. **Forbidden pattern scan** — every regex in `_FORBIDDEN_STATEMENT_PATTERNS`. Reject on match.

These run **before** the existing DML/DDL token check so the most dangerous patterns are caught first.

### 6.7 `pyproject.toml`

Add to `[project] dependencies`:

```toml
"fastapi>=0.115.0",
"uvicorn[standard]>=0.34.0",
"python-multipart>=0.0.20",
"cachetools>=5.5.0",
"cryptography>=44.0.0",
"slowapi>=0.1.9",
"alembic>=1.14.0",
```

Add to `[dependency-groups] dev`:

```toml
"httpx>=0.28.0",     # for FastAPI TestClient
"pytest-mock>=3.14.0",
"pip-audit>=2.7.0",
"mypy>=1.13.0",
```

Bump `[tool.ruff] target-version` from `"py311"` to `"py312"` to match `requires-python = ">=3.12"`.

### 6.8 `.env.example`

```env
# ── Mode ────────────────────────────────────────────────────────────
ENVIRONMENT=development                # development|staging|production
TRANSPORT=stdio                        # stdio|streamable-http (HTTP uses src/app.py)

# ── Single-user / stdio mode (only needed when TRANSPORT=stdio) ─────
DATABASE_URL=
ANTHROPIC_API_KEY=
GROQ_API_KEY=
LLM_PROVIDER=anthropic
CLAUDE_MODEL=claude-sonnet-4-6
GROQ_MODEL=llama-3.3-70b-versatile
MAX_QUERY_ROWS=100
QUERY_TIMEOUT_SECONDS=30
MAX_SELF_CORRECTION_RETRIES=3

# ── Hosted multi-tenant mode (src/app.py) ───────────────────────────
AUTH_DATABASE_URL=sqlite:///./auth.db
# Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Plural — comma-separated list, first is the encryption key, others are decryption-only.
# Required in staging and production.
CREDENTIAL_ENCRYPTION_KEYS=

REGISTRATION_OPEN=true
ALLOW_SQLITE_USER_DBS=false            # NEVER true outside dev
SQLITE_USER_DB_DIR=/var/lib/mcp-db-agent/user-dbs
EXTRA_BLOCKED_CIDRS=                   # e.g. 10.20.30.0/24,2001:db8::/32

PORT=8000
CORS_ALLOW_ORIGINS=                    # comma-separated; empty = closed
MAX_REQUEST_BYTES=65536
QUERY_POOL_SIZE=64
REGISTER_RATE_LIMIT=5/minute
ASK_DATABASE_QUOTA_PER_DAY=200         # only enforced on fallback LLM keys
SCHEMA_CACHE_TTL_SECONDS=600
```

### 6.9 `Dockerfile`

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Non-root user
RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Persist auth DB and user-supplied SQLite DBs (dev only) on a volume
RUN mkdir -p /var/lib/mcp-db-agent/user-dbs && chown -R app:app /app /var/lib/mcp-db-agent
USER app

EXPOSE 8000

ENV ENVIRONMENT=production
ENV TRANSPORT=streamable-http

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3).status==200 else 1)"

# Production: 4 workers, proxy headers (for X-Forwarded-* from a reverse proxy)
CMD ["uv", "run", "uvicorn", "src.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

# For stdio single-user mode: docker run -e TRANSPORT=stdio --entrypoint "uv run src/server.py" ...
```

### 6.10 `docker-compose.yml`

Provision a real Postgres for the auth DB (multi-worker safe by default). Move the demo ecommerce DB to `docker-compose.demo.yml`.

```yaml
services:
  auth-db:
    image: postgres:16
    environment:
      POSTGRES_USER: mcp_auth
      POSTGRES_PASSWORD_FILE: /run/secrets/auth_db_password
      POSTGRES_DB: mcp_auth
    volumes:
      - auth-db-data:/var/lib/postgresql/data
    secrets:
      - auth_db_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mcp_auth -d mcp_auth"]
      interval: 5s
      timeout: 5s
      retries: 5

  mcp-server:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      ENVIRONMENT: production
      AUTH_DATABASE_URL: postgresql://mcp_auth:${AUTH_DB_PASSWORD}@auth-db:5432/mcp_auth
      CREDENTIAL_ENCRYPTION_KEYS: ${CREDENTIAL_ENCRYPTION_KEYS}
    depends_on:
      auth-db:
        condition: service_healthy

volumes:
  auth-db-data:

secrets:
  auth_db_password:
    file: ./secrets/auth_db_password.txt
```

### 6.11 `docker-compose.demo.yml` — new

Lifts the original ecommerce Postgres demo into its own compose so contributors can `docker compose -f docker-compose.demo.yml up` to seed a target database for testing the MCP server against.

---

## 7. Implementation Order

Each step's imports are satisfied by the previous step. **Do not parallelise** — earlier steps catch design bugs cheap.

| # | Step | Why this position |
|---|---|---|
| 1 | `pyproject.toml` — add deps → `uv sync` | Everything else needs them |
| 2 | `src/config.py` — new fields, validators | Foundation; standalone |
| 3 | `src/auth/url_guard.py` (T1, T9) + `tests/test_url_guard.py` | **Security floor — write tests first** |
| 4 | `src/auth/crypto.py` (MultiFernet) + `tests/test_crypto.py` | Standalone |
| 5 | Alembic init + `alembic/versions/0001_initial.py` (auth + query_log tables) | Schema before any store code |
| 6 | `src/auth/user_store.py` + `tests/test_user_store.py` | Depends on crypto + url_guard + Alembic |
| 7 | `src/core/sql_validator.py` — add forbidden function/pattern checks (T2) + tests | Security floor; isolated change |
| 8 | `src/core/schema_inspector.py` — TTL cache + refresh() | Standalone |
| 9 | `src/core/sql_executor.py` — accept injected ThreadPoolExecutor | Standalone |
| 10 | `src/core/query_log.py` — non-nullable user_id, injected engine, WAL hook | Depends on Alembic schema |
| 11 | `src/core/pipeline_factory.py` (+ UserSettings adapter) + tests | Depends on 3, 6, 8, 9 |
| 12 | `src/auth/middleware.py` + tests | Depends on user_store + auth-key cache |
| 13 | `src/middleware/request_id.py`, `src/middleware/body_size.py` | Standalone |
| 14 | `src/api/schemas.py` | Standalone |
| 15 | `src/api/app.py` + tests (slowapi rate limiting, dry-run connect) | Depends on user_store, schemas, url_guard, pipeline_factory |
| 16 | `src/server.py` — refactor to use `_get_pipeline()` and `build_mcp()` | Depends on pipeline_factory + middleware |
| 17 | `src/app.py` — combined entry point with proper lifespan composition | Depends on everything |
| 18 | `Dockerfile` + `docker-compose.yml` + `docker-compose.demo.yml` + `.env.example` | Last; deployment surface |
| 19 | CI updates (`.github/workflows/ci.yml`) — add `mypy`, `pip-audit`, `alembic check` | After everything compiles |
| 20 | `CLAUDE.md` + README updates (architecture, MCP client connection examples) | Documentation last |

---

## 8. Migration Notes

| What | Impact | Resolution |
|---|---|---|
| `settings.database_url` etc. now default to `""` | Existing single-user `.env` still works (field present → used) | None for users; the validator in `_get_pipeline()` raises a clear error if both `.env` and ContextVar are empty |
| Alembic added | First-run dev needs `alembic upgrade head` | `src/app.py` lifespan auto-runs migrations in `ENVIRONMENT=development`. Production refuses to start if `alembic_version` < head — operators run migrations explicitly (audited) |
| `query_log.db` schema gains non-nullable `user_id` | Existing dev DB schema mismatch | Initial Alembic migration handles this. For pre-Alembic dev DBs: `python -m src.scripts.migrate_query_log` (one-shot, idempotent, populates legacy rows with `__legacy__`) |
| `_QueryHistory.user_id` is `NOT NULL` | Any caller forgetting to pass `user_id` raises | This is intentional — fail loud beats silent cross-tenant leak |
| `docker-compose.yml` loses ecommerce `db` service | Demo setup moves | Use `docker-compose.demo.yml` |
| `src/server.py` no longer has `engine`, `inspector`, etc. at module scope | Tests that imported these globals break | Existing tests construct components directly — verified during plan validation |
| `_cache` key type changes from `str` to `tuple[str, str]` and gains TTL eviction | Cache misses on restart and on TTL expiry | Acceptable; in-memory only, per worker |
| `SQLExecutor` constructor adds `pool` argument | Existing tests construct SQLExecutor without a pool | Update tests to pass a small `ThreadPoolExecutor(max_workers=2)`. Backward-compat shim is intentionally **not** added — explicit pool ownership is the point |
| `mcp.run(transport="stdio")` still works | None | The stdio path constructs `mcp` with `stateless_http=False` because stdio doesn't use HTTP at all |
| Deprecated `datetime.utcnow()` removed from `query_log.py` | None — pure improvement | Tests assert UTC tz-aware timestamps |

---

## 9. Verification

### 9.1 New unit tests (created alongside the feature they test)

| Test file | Coverage |
|---|---|
| `test_url_guard.py` | All blocked schemes; RFC1918/loopback/link-local IPs; `169.254.169.254`; SQLite path traversal; `\n` and `;` injection; query-param stripping; DNS-rebinding (mock `getaddrinfo` to return public then private) |
| `test_crypto.py` | Encrypt→decrypt round-trip; wrong key raises `CredentialDecryptError`; MultiFernet rotation (encrypted with key1, decryptable after adding key2 first) |
| `test_user_store.py` | `create_user` returns `mdbk_…` of correct length; `get_user_by_api_key` returns correct UserConfig; wrong key returns None; deactivated returns None; `update_user` partial update; `rotate_api_key` invalidates old; `increment_daily_quota` rolls over at UTC midnight |
| `test_sql_validator_dangerous.py` | `pg_read_file`, `pg_ls_dir`, `lo_import`, `dblink`; `COPY ... TO PROGRAM`; `ATTACH DATABASE`; `load_extension`; `SELECT INTO new_table`; `LOAD_FILE`; `INTO OUTFILE`; multi-statement string; comment-injection (`/* */`) |
| `test_pipeline_factory.py` | Same database_url returns cached pipeline; different URL → new; concurrent first-hits build only one engine; `invalidate(user_id)` disposes engine; `shutdown()` disposes all; LLM key fallback; `NoLLMKeyAvailable` when both user and global empty |
| `test_pipeline_factory_eviction.py` | Forced eviction calls `engine.dispose()` |
| `test_middleware.py` | Missing key → 401; `X-API-Key` accepted; `Authorization: Bearer` accepted; invalid key → 401; valid key → ContextVar set; **exception inside inner app still resets ContextVar**; auth-key cache hit avoids store lookup |
| `test_middleware_concurrency.py` | 50 concurrent requests with different keys, each tool handler reads `user_config_var` and asserts it matches its own request |
| `test_schema_inspector_cache.py` | First call hits DB; second call within TTL does not; `refresh()` busts cache |
| `test_api_register.py` | `POST /v1/users/register` 201; rate limit triggers at 6th request; oversize body 413; bad URL 400 from url_guard; **dry-run connect failure 400 with no leaked details** |
| `test_api_me.py` | `GET /v1/users/me` 200; `PUT` updates and invalidates pipeline; `DELETE` deactivates; `POST /me/rotate-key` issues new key, old key 401 |
| `test_app_lifespan.py` | Startup builds factory, store, cipher; shutdown disposes engines; missing `CREDENTIAL_ENCRYPTION_KEYS` in production raises at startup |
| `test_app_routing.py` | `/api/health/live` 200; `/api/health/ready` 200 when DB up, 503 when DB down; mounted MCP route serves at `/mcp/...` (not `/mcp/mcp/...`) |
| `test_stdio_mode_refuses_empty_url.py` | `_get_pipeline()` with empty `settings.database_url` raises `RuntimeError` with the documented message |
| `test_query_log_user_scoping.py` | Two users log queries; `get_recent_queries(user_id=A)` returns only A's; passing empty `user_id` raises `ValueError` |
| `test_concurrent_users_e2e.py` | 10 simulated users × 5 concurrent `ask_database` calls each; correct `user_id` stamping in `query_log` for every row; no cross-leak |

### 9.2 Existing-test backward compatibility

Existing tests (`test_sql_validator.py`, `test_sql_executor.py`, `test_schema_inspector.py`, `test_result_formatter.py`, `test_self_corrector.py`, `test_tools.py`, `test_integration.py`) must pass unchanged after the migration. The only test that needs an update is anything that constructs `SQLExecutor` directly — it now requires a `ThreadPoolExecutor` argument.

```bash
uv run pytest -m "not integration"          # full unit suite, no LLM calls
uv run pytest -m integration                # LLM round-trips; needs API keys
```

### 9.3 End-to-end multi-tenant smoke (Verification step 3)

```bash
# Start the hosted server (note: uvicorn directly, NOT `python src/app.py`)
docker compose up --build -d
sleep 5

# Health
curl -fsS http://localhost:8000/api/health/live
curl -fsS http://localhost:8000/api/health/ready

# Register a tenant pointing at a hosted Postgres demo (NOT a local sqlite path)
USER1=$(curl -fsS -X POST http://localhost:8000/api/v1/users/register \
    -H "Content-Type: application/json" \
    -d '{"database_url": "postgresql://demo:demo@demo-host:5432/ecommerce", "llm_provider": "groq"}')
KEY1=$(echo "$USER1" | jq -r .api_key)

# SSRF defense: this MUST 400
curl -i -X POST http://localhost:8000/api/v1/users/register \
    -H "Content-Type: application/json" \
    -d '{"database_url": "sqlite:////app/auth.db"}'   # expect 400 InvalidDatabaseURL
curl -i -X POST http://localhost:8000/api/v1/users/register \
    -H "Content-Type: application/json" \
    -d '{"database_url": "postgresql://x@169.254.169.254/y"}'   # expect 400

# MCP tool call via the streamable HTTP transport.
# Note: streamable HTTP requires Accept: text/event-stream OR json_response=True returning JSON.
curl -fsS -X POST http://localhost:8000/mcp/ \
    -H "X-API-Key: $KEY1" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_tables","arguments":{}}}'

# Verify query history is scoped
curl -fsS -X POST http://localhost:8000/mcp/ \
    -H "X-API-Key: $KEY1" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"query_history","arguments":{"limit":5}}}'

# Rotate key, verify old key 401
NEW=$(curl -fsS -X POST http://localhost:8000/api/v1/users/me/rotate-key -H "X-API-Key: $KEY1")
NEWKEY=$(echo "$NEW" | jq -r .api_key)
curl -i -X POST http://localhost:8000/mcp/ -H "X-API-Key: $KEY1" \
     -H "Content-Type: application/json" -H "Accept: application/json" \
     -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_tables","arguments":{}}}'   # expect 401
curl -fsS -X POST http://localhost:8000/mcp/ -H "X-API-Key: $NEWKEY" \
     -H "Content-Type: application/json" -H "Accept: application/json" \
     -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_tables","arguments":{}}}'   # expect 200
```

### 9.4 Stdio backward compatibility

```bash
# Set DATABASE_URL in .env, then:
uv run src/server.py
# Connect from Claude Desktop as today; the server uses the .env config and runs single-tenant.
```

### 9.5 CI gating

`.github/workflows/ci.yml` adds:

```yaml
- run: uv run ruff check .
- run: uv run mypy src
- run: uv run pytest -m "not integration"
- run: uv run pip-audit                     # CVE scan
- run: uv run alembic check                 # detects unapplied migrations vs models
```

---

## 10. Operational runbook (production)

### 10.1 First deploy
1. Generate `CREDENTIAL_ENCRYPTION_KEYS`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Store in your secret manager. Set `CREDENTIAL_ENCRYPTION_KEYS=<key>` in the environment of every worker.
2. Provision a Postgres for the auth DB. Set `AUTH_DATABASE_URL`.
3. `alembic upgrade head` against the auth DB. (CI gates this; production never auto-migrates.)
4. Launch behind a reverse proxy that terminates TLS (nginx, Caddy, ALB). Pass `X-Forwarded-*` headers; uvicorn runs with `--proxy-headers --forwarded-allow-ips='*'`.
5. Smoke-test §9.3.

### 10.2 Encryption-key rotation
1. Generate a new key, **prepend** it to `CREDENTIAL_ENCRYPTION_KEYS`:
   `CREDENTIAL_ENCRYPTION_KEYS=<new>,<old>`
2. Rolling-restart workers. New writes use `<new>`; old ciphertexts still decrypt via `<old>`.
3. (Optional, lazy) Run `python -m src.scripts.rotate_credentials` which reads every row, decrypts (using either key), re-encrypts with `<new>`, and writes back.
4. After all rows are re-encrypted, drop `<old>`:
   `CREDENTIAL_ENCRYPTION_KEYS=<new>`
5. Rolling-restart workers.

### 10.3 Schema migration
1. `git pull` the new code. Test in staging.
2. `alembic upgrade head` against production auth DB.
3. Rolling-restart workers. New code reads new schema; old code is gone.
4. Roll back: `alembic downgrade -1`. Every migration MUST have a working `downgrade()`.

### 10.4 Suspected user abuse
1. `UPDATE users SET is_active=false WHERE id=...` (or call `DELETE /v1/users/me` as admin).
2. Worker auth-key cache TTL is 60 s — within a minute the user is fully cut off across all workers.
3. To cut them off immediately, restart the workers (deactivation hits the DB but cached `UserConfig` lingers up to 60 s).

### 10.5 Disaster recovery
- Auth DB: standard Postgres backup/restore.
- Encryption key: stored in your secret manager. **Without it the auth DB is useless** — every credential is undecryptable. Back it up at least as carefully as the database itself.

---

## 11. Out of scope (tracked as future work)

- **Prompt injection from user database content into the LLM prompt** (T8). Real risk, inherited from the existing single-tenant design. Mitigation requires structured tool-use mode and content escaping. Tracked separately.
- **Per-tenant cache coherence across workers**. Each worker has its own auth-key cache and pipeline cache; deactivation has up to 60 s of staleness on other workers. Acceptable for v1; future fix is Redis-backed cache or a shared event bus.
- **Browser MCP clients** — CORS is closed by default. When/if a browser client lands, set `cors_allow_origins` explicitly.
- **OpenTelemetry tracing** — current logging covers `request_id` and `user_id` correlation. OTel spans are a follow-up.
- **Per-user budget tracking in dollars** — current quota is request count, not token cost. Token-cost accounting is a follow-up.
- **Fine-grained RBAC inside a tenant** — the model is one user = one DB. Multi-database-per-user, sharing, and roles are future work.

---

## 12. Sources consulted during plan validation

- [HTTP Deployment — FastMCP](https://gofastmcp.com/deployment/http) — lifespan composition, mount paths, stateless_http.
- [How to mount streamable HTTP app to an existing Starlette app · python-sdk #673](https://github.com/modelcontextprotocol/python-sdk/issues/673) — confirms parent-app lifespan requirement.
- [Mounting a Streamable HTTP MCP endpoint on existing FastAPI app does not work · python-sdk #1367](https://github.com/modelcontextprotocol/python-sdk/issues/1367) — confirms `streamable_http_path` workaround.
- [Misleading docs: `mcp.http_app()` returns Starlette with no lifespan attribute · jlowin/fastmcp #510](https://github.com/jlowin/fastmcp/issues/510) — confirms nested lifespan failure.
- [sse_app() ignores mount prefix · python-sdk #412](https://github.com/modelcontextprotocol/python-sdk/issues/412) — confirms double-prefix bug.
- [SQLAlchemy connection pool tuning discussion #10697](https://github.com/sqlalchemy/sqlalchemy/discussions/10697) — pool sizing math used in §6.2.
- [SQLAlchemy 2.0 Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html) — `pool_pre_ping`, `pool_recycle`, `dispose()` semantics.
