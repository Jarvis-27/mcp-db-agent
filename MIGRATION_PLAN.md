# Multi-Tenant Migration Plan: MCP Database Analytics Agent

## Context

The MCP Database Analytics Agent currently runs as a single-user local tool where one person edits `.env` to point at their database. The goal is to deploy it as a hosted service where multiple users can each register their own database, receive an API key, and connect any MCP client (Claude Desktop, Cursor, etc.) to the shared server — without touching `.env` or running their own instance.

**User decisions:**
- Open registration (anyone can register; lockable via `REGISTRATION_OPEN` env flag)
- SQLite for the auth database (zero-infra; swap to Postgres anytime via `AUTH_DATABASE_URL`)
- LLM key fallback: if user doesn't supply their own keys, use server's global keys from `.env`

---

## Root Problem

`src/server.py` lines 40–59 create module-level singletons tied to one database at import time:

```python
engine = create_engine(settings.database_url)   # single DB, global scope
inspector = SchemaInspector(engine)
generator = SQLGenerator(settings, inspector)
...
_cache: dict[str, tuple[str, float]] = {}        # shared across all callers
```

`src/config.py` requires `database_url`, `anthropic_api_key`, `groq_api_key`, `llm_provider` — all single-user fields — at startup.

---

## Target Architecture

```
HTTP Request (X-API-Key: mdbk_...)
  │
  ├── POST /api/v1/users/*  →  FastAPI registration app  →  UserStore (SQLite auth.db)
  │
  └── /mcp/*               →  ApiKeyMiddleware (ASGI)
                                 │  look up UserConfig from UserStore
                                 │  set user_config_var (ContextVar)
                                 ▼
                              FastMCP tools (server.py)
                                 │  _get_pipeline() reads ContextVar
                                 ▼
                              PipelineFactory.get(user_config)
                                 │  TTLCache keyed by database_url
                                 ▼
                              SchemaInspector / SQLGenerator / SQLValidator
                              SQLExecutor / SelfCorrector / ResultFormatter
                                 │
                                 └── QueryLog.log_query(..., user_id=user_id)
```

**Single entry point** (`src/app.py`): Starlette app that mounts FastAPI at `/api` and the authenticated FastMCP ASGI app at `/mcp`.

**stdio backward compatibility**: `uv run src/server.py` still works unchanged. The `_get_pipeline()` helper falls back to building a pipeline from global `settings` when no `user_config_var` is set (i.e., no middleware ran).

---

## Files to Create

### `src/auth/__init__.py` — empty

### `src/auth/crypto.py`
Thin wrapper around `cryptography.fernet.Fernet`.

```python
def encrypt(plaintext: str, key: str) -> str: ...
def decrypt(ciphertext: str, key: str) -> str: ...
```

Key is always `settings.credential_encryption_key`. Takes it as a parameter (not a global import) for testability.

### `src/auth/user_store.py`
SQLAlchemy `users` table + `UserStore` class.

**SQLAlchemy model `User`:**
| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | UUID4 string |
| `api_key_hash` | `String(64)` UNIQUE INDEX | SHA-256 of raw key |
| `database_url_enc` | `Text` | Fernet-encrypted |
| `llm_provider` | `String(20)` | `"claude"` or `"groq"` |
| `anthropic_api_key_enc` | `Text` nullable | Fernet-encrypted |
| `groq_api_key_enc` | `Text` nullable | Fernet-encrypted |
| `is_active` | `Boolean` | default True |
| `created_at` | `DateTime` | UTC |
| `updated_at` | `DateTime` | UTC |

**In-memory dataclass `UserConfig`** (never persisted, returned from store):
```python
@dataclass
class UserConfig:
    user_id: str
    database_url: str           # decrypted
    llm_provider: str
    anthropic_api_key: str | None   # decrypted, may be None
    groq_api_key: str | None        # decrypted, may be None
```

**`UserStore` methods:**
```python
def __init__(self, auth_database_url: str, encryption_key: str) -> None
    # creates engine, runs create_all

def create_user(database_url, llm_provider, anthropic_api_key, groq_api_key) -> tuple[str, str]
    # returns (user_id, raw_api_key)
    # raw_api_key format: "mdbk_" + base64url(32 random bytes)
    # stores SHA-256(raw_api_key) only

def get_user_by_api_key(raw_key: str) -> UserConfig | None
    # hash → DB lookup → decrypt → return UserConfig; None if missing/inactive

def get_user_by_id(user_id: str) -> UserConfig | None

def update_user(user_id, database_url, llm_provider, anthropic_api_key, groq_api_key) -> bool

def deactivate_user(user_id: str) -> bool
```

### `src/auth/middleware.py`
Pure ASGI middleware (Starlette-compatible, not FastMCP-specific). Works regardless of FastMCP version.

```python
user_config_var: ContextVar[UserConfig | None] = ContextVar("user_config", default=None)

class ApiKeyMiddleware:
    def __init__(self, app: ASGIApp, user_store: UserStore) -> None

    async def __call__(self, scope, receive, send) -> None:
        # Only applies to http/websocket scopes
        # Reads b"x-api-key" from scope["headers"]
        # Missing key → 401 JSON response, no forwarding
        # Invalid key → 401 JSON response, no forwarding
        # Valid key → set user_config_var ContextVar, forward to app, reset on exit
```

Tool handlers in `server.py` call `user_config_var.get()` directly — no signature changes needed.

### `src/api/__init__.py` — empty

### `src/api/schemas.py`
Pydantic request/response models:
```python
class RegisterRequest(BaseModel):
    database_url: str
    llm_provider: str = "claude"   # validated: "claude" | "groq"
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None

class RegisterResponse(BaseModel):
    user_id: str
    api_key: str   # shown ONCE, never again

class UserMetaResponse(BaseModel):
    user_id: str
    llm_provider: str
    has_anthropic_key: bool
    has_groq_key: bool
    created_at: str

class UpdateRequest(BaseModel):
    database_url: str | None = None
    llm_provider: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
```

### `src/api/app.py`
FastAPI app. `_user_store` is a module-level variable set by `src/app.py` at startup (injected, not created here).

**Endpoints:**
| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/users/register` | none (open) | Register → returns `{user_id, api_key}` |
| `GET` | `/v1/users/me` | X-API-Key | Return user metadata (no secrets) |
| `PUT` | `/v1/users/me` | X-API-Key | Update database_url / API keys |
| `DELETE` | `/v1/users/me` | X-API-Key | Deactivate account |
| `GET` | `/health` | none | `{"status": "ok"}` |

`require_api_key` FastAPI dependency: reads `X-API-Key` header, looks up user, returns `user_id` (raises `HTTPException(401)` on failure).

### `src/core/pipeline_factory.py`
Caches pipeline components by database_url.

```python
@dataclass
class PipelineComponents:
    inspector: SchemaInspector
    generator: SQLGenerator
    validator: SQLValidator
    executor: SQLExecutor
    corrector: SelfCorrector
    formatter: ResultFormatter
    dialect: str

class PipelineFactory:
    def __init__(self) -> None:
        # TTLCache(maxsize=100, ttl=3600), threading.Lock

    def get(self, user_config: UserConfig) -> PipelineComponents:
        # Cache key: (database_url, llm_provider, anthropic_key_prefix, groq_key_prefix)
        # LLM key fallback: user's key if set, else settings.anthropic_api_key / settings.groq_api_key
        # Builds UserSettings adapter, creates engine, instantiates all components

    def get_from_settings(self, s: Settings) -> PipelineComponents:
        # Backward compat path for stdio/single-user mode
        # Builds a UserConfig from s.database_url, s.llm_provider, etc., then calls get()
```

**`UserSettings` adapter** (defined in this file):
```python
@dataclass
class UserSettings:
    """Satisfies the attribute interface expected by SQLGenerator, SQLExecutor, SelfCorrector."""
    llm_provider: str
    anthropic_api_key: str
    groq_api_key: str
    claude_model: str          # from global settings
    groq_model: str            # from global settings
    max_query_rows: int        # from global settings
    query_timeout_seconds: int # from global settings
    max_self_correction_retries: int  # from global settings
```

No changes to `sql_generator.py`, `sql_executor.py`, or `self_corrector.py` — they only read named attributes, and `UserSettings` provides all of them.

### `src/app.py`
Combined ASGI entry point for multi-tenant deployment.

```python
# 1. Build UserStore singleton
# 2. Inject _user_store into src.api.app module (before it's used)
# 3. Import src.server to trigger @mcp.tool / @mcp.resource decorators
# 4. Get FastMCP's Starlette ASGI app via mcp.streamable_http_app()
# 5. Wrap it with ApiKeyMiddleware
# 6. Mount:  /api  → FastAPI app,  /mcp  → authenticated FastMCP app
# 7. if __name__ == "__main__": uvicorn.run(...)
```

---

## Files to Modify

### `src/config.py`
- Make `database_url`, `anthropic_api_key`, `groq_api_key`, `llm_provider` **optional with `""` defaults** (they're now per-user; still work in `.env` for stdio mode)
- Add `auth_database_url: str = "sqlite:///./auth.db"`
- Add `credential_encryption_key: str = ""`
- Add `port: int = 8000`
- Add `registration_open: bool = True`

### `src/server.py`
**Remove** lines 40–52 (global engine + all singleton component construction).

**Add at module level:**
```python
from src.auth.middleware import user_config_var
from src.core.pipeline_factory import PipelineFactory

_factory = PipelineFactory()
_query_log = QueryLog()

def _get_pipeline() -> PipelineComponents:
    user_config = user_config_var.get()
    if user_config is not None:
        return _factory.get(user_config)
    return _factory.get_from_settings(settings)  # stdio fallback
```

**Modify each tool/resource handler** to call `_get_pipeline()` at the top:
- `schema_overview()`: `pipeline = _get_pipeline(); return get_schema_overview(pipeline.inspector)`
- `list_tables()`: `pipeline = _get_pipeline(); return _list_tables(pipeline.inspector)`
- `describe_schema(table_name)`: `pipeline = _get_pipeline(); return _describe_schema(table_name, pipeline.inspector)`
- `get_sample_data(table_name, limit)`: `pipeline = _get_pipeline(); return _get_sample_data(table_name, pipeline.inspector, limit)`
- `ask_database(question)`: get pipeline, use `pipeline.corrector`, `pipeline.formatter`, `pipeline.dialect`; change `generator.get_schema_context()` to `pipeline.generator.get_schema_context()`
- `query_history(limit)`: read user_id from ContextVar, filter log by user_id

**Update `_cache` key** from `str` to `tuple[str, str]` → `(user_id, question.lower().strip())` where `user_id = user_config.user_id if user_config else ""`

**Update `query_log.log_query()` calls** to pass `user_id=user_id`.

**Keep** `mcp = FastMCP(...)` and `if __name__ == "__main__"` entry point unchanged.

### `src/core/query_log.py`
Two targeted changes only:

1. Add column to `_QueryHistory`:
   ```python
   user_id = Column(String(36), nullable=False, default="", index=True)
   ```

2. Update method signatures (backward-compat defaults preserved):
   ```python
   def log_query(self, ..., user_id: str = "") -> None
   def get_recent_queries(self, limit: int = 10, user_id: str = "") -> list[dict]:
       # add .filter(_QueryHistory.user_id == user_id) when user_id is non-empty
   ```

### `pyproject.toml`
Add to `[project] dependencies`:
```
"fastapi>=0.115.0",
"uvicorn[standard]>=0.34.0",
"python-multipart>=0.0.20",
"cachetools>=5.5.0",
"cryptography>=44.0.0",
```

### `.env.example`
Add:
```
AUTH_DATABASE_URL=sqlite:///./auth.db
CREDENTIAL_ENCRYPTION_KEY=          # generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
REGISTRATION_OPEN=true
PORT=8000
```

Mark `DATABASE_URL`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `LLM_PROVIDER` as optional (only needed for single-user stdio mode).

### `Dockerfile`
- Change `CMD` from `uv run src/server.py` to `uv run src/app.py`
- Add env vars: `AUTH_DATABASE_URL`, `CREDENTIAL_ENCRYPTION_KEY`, `PORT`
- Keep `ENV TRANSPORT=streamable-http`
- Add comment: "For stdio single-user mode, override CMD with: uv run src/server.py"

### `docker-compose.yml`
- **Remove** the `db` (ecommerce Postgres) service from the main compose — users bring their own DBs
- **Keep** the `mcp-server` service; add `AUTH_DATABASE_URL` and `CREDENTIAL_ENCRYPTION_KEY` env vars
- Move the demo ecommerce Postgres to a new `docker-compose.demo.yml` for local development

---

## Implementation Order

Execute in this order (each step's imports are satisfied before the next):

1. `pyproject.toml` — add deps → `uv sync`
2. `src/auth/crypto.py`
3. `src/auth/user_store.py` (depends on crypto.py)
4. `src/config.py` (standalone)
5. `src/core/query_log.py` (add user_id, backward-compat defaults)
6. `src/core/pipeline_factory.py` (depends on config.py + all core modules)
7. `src/auth/middleware.py` (depends on user_store.py)
8. `src/api/schemas.py` (standalone Pydantic models)
9. `src/api/app.py` (depends on user_store.py, schemas.py, config.py)
10. `src/server.py` — modify (depends on pipeline_factory.py, middleware.py)
11. `src/app.py` — new combined entry point (depends on everything)
12. `Dockerfile` + `docker-compose.yml` + `.env.example`

---

## Migration Notes

| What | Impact | Resolution |
|---|---|---|
| `settings.database_url` etc. now default to `""` | Existing `.env` still works (field present → used) | None needed |
| `query_log.db` has no `user_id` column | Existing dev DB schema mismatch | Delete `query_log.db` and let it recreate, or run: `ALTER TABLE query_history ADD COLUMN user_id TEXT NOT NULL DEFAULT ''` |
| `docker-compose.yml` loses ecommerce `db` service | Demo setup breaks | Use new `docker-compose.demo.yml` for local demo |
| `src/server.py` no longer has `engine`, `inspector`, etc. at module scope | Any test that imports these globals breaks | Tests use components directly — not affected |
| `_cache` key type changes from `str` to `tuple[str, str]` | Cache misses on restart | Acceptable; it's in-memory only |

---

## Verification

**Step 1 — Unit tests (add to `tests/`):**
- `test_crypto.py`: encrypt→decrypt round-trip; wrong key raises `ValueError`
- `test_user_store.py`: create_user returns `mdbk_...` key; get_user_by_api_key returns correct UserConfig; wrong key returns None; deactivated user returns None
- `test_pipeline_factory.py`: same database_url returns cached pipeline; different URL creates new one
- `test_middleware.py`: missing key → 401; invalid key → 401; valid key → ContextVar set correctly
- `test_api.py` (FastAPI TestClient): `POST /api/v1/users/register` → 201 + api_key; `GET /api/v1/users/me` with valid key → 200; with invalid key → 401; `DELETE /api/v1/users/me` deactivates

**Step 2 — Backward compat (existing tests unchanged):**
```bash
uv run pytest tests/test_sql_validator.py tests/test_sql_executor.py tests/test_schema_inspector.py tests/test_result_formatter.py tests/test_self_corrector.py
```

**Step 3 — End-to-end multi-tenant flow:**
```bash
# Start the server
uv run src/app.py

# Register a user pointing at the demo SQLite DB
curl -X POST http://localhost:8000/api/v1/users/register \
  -H "Content-Type: application/json" \
  -d '{"database_url": "sqlite:///./demo.db", "llm_provider": "groq"}'
# → {"user_id": "...", "api_key": "mdbk_..."}

# Call an MCP tool via HTTP
curl -X POST http://localhost:8000/mcp \
  -H "X-API-Key: mdbk_..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_tables","arguments":{}}}'

# Verify query history is scoped to this user
curl -X POST http://localhost:8000/mcp \
  -H "X-API-Key: mdbk_..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"query_history","arguments":{"limit":5}}}'
```

**Step 4 — Docker:**
```bash
docker compose up --build
curl http://localhost:8000/api/health
```
