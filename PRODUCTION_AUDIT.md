# Production Audit

Date: 2026-04-09

This note captures the current production-readiness findings from a code audit of the repository, including `CLAUDE.md`, implementation paths, deployment defaults, and the local quality gates.

## Critical Findings

### 1. SQL validation is not production-safe yet

The SQL safety layer in `src/core/sql_validator.py` uses a blacklist instead of a strict read-only allowlist.

Observed issue:
- Non-`SELECT` statements such as `COPY`, `CALL`, `VACUUM`, and `SET ROLE` currently pass validation and then execute through `src/core/sql_executor.py`.

Impact:
- If the connected DB role has elevated privileges, this can become file read/write, side effects, or privilege abuse.

Verified examples accepted by the validator:
- `COPY users TO '/tmp/out.csv'`
- `COPY users FROM '/etc/passwd'`
- `COPY (SELECT * FROM users) TO '/tmp/out.csv'`
- `CALL dangerous_procedure()`
- `VACUUM`
- `SET ROLE postgres`

Required fix:
- Replace the blacklist approach with a read-only allowlist.
- Enforce top-level `SELECT` or explicitly approved read-only query forms only.
- Add tests for all currently accepted dangerous statements.

### 2. Sanitized database URLs are not actually used

`src/auth/url_guard.py` returns a sanitized URL and strips dangerous query params like:
- `host`
- `service`
- `passfile`
- `sslkey`
- `options`

Observed issue:
- `src/api/app.py` validates but then continues using the raw `body.database_url` for `_dry_run_connect()` and persistence.
- `src/auth/user_store.py` revalidates but also persists the raw input.

Impact:
- The SSRF / local-file protection is weakened exactly where the app first touches user-supplied connection strings.

Required fix:
- Persist and connect using the sanitized URL returned by `validate_database_url()`.
- Do not reuse the unsanitized input after validation.
- Add tests proving stripped params cannot survive registration or update flows.

### 3. `ask_database` quota is defined but not enforced

Relevant code:
- `src/config.py`
- `src/auth/user_store.py`
- `src/server.py`

Observed issue:
- `ask_database_quota_per_day` exists in config.
- `increment_daily_quota()` exists in `UserStore`.
- The hosted MCP path never enforces the quota before LLM or DB work.

Impact:
- Any valid API key can trigger unlimited LLM calls and expensive database queries.

Required fix:
- Enforce quota in the hosted `ask_database` path before generation/execution.
- Return a clear quota error when exceeded.
- Add tests for quota increment, reset, and denial behavior.

### 4. Query timeout does not cancel database work

Observed issue:
- `src/core/sql_executor.py` uses `asyncio.wait_for(...)` around thread-pool work.
- This only times out the awaiter; it does not stop the query still running inside the worker thread.

Impact:
- Long-running queries can continue consuming DB resources and thread-pool slots after timeout.
- This can degrade service or become a denial-of-service path.

Required fix:
- Use database-native statement timeouts where supported.
- Ensure timeout policy actually interrupts work at the DB layer.
- Revisit `query_pool_size` and engine pool sizing under load.

### 5. Forwarded proxy headers are trusted from anywhere

Relevant files:
- `src/app.py`
- `Dockerfile`
- `docker-compose.yml`

Observed issue:
- `forwarded_allow_ips="*"` is enabled.
- The compose setup also publishes port `8000` directly.
- Rate limiting uses client IP via `slowapi`.

Impact:
- If the app is reachable directly, spoofed forwarded headers can poison client-IP-based controls and logs.

Required fix:
- Restrict trusted forwarded IPs to the actual reverse proxy.
- Do not expose the app directly unless proxy trust is disabled.
- Document the required network topology for production.

## High-Priority Findings

### 6. Live sample data is sent to external LLMs

Observed issue:
- `src/core/schema_inspector.py` includes sampled string values in schema context.
- `src/core/sql_generator.py` and `src/core/self_corrector.py` send that context to Anthropic/Groq.

Impact:
- Real data samples, not just schema metadata, are sent off-box to third-party LLM providers.

Required fix:
- Make this an explicit product/security decision before production.
- Either remove samples from prompts, redact them, or gate the behavior by configuration.
- Document data egress clearly.

### 7. Stdio mode is currently broken

Observed issue:
- `src/core/pipeline_factory.py` constructs `UserConfig` with fields that no longer exist on the dataclass in `src/auth/user_store.py`.

Verified behavior:
- Running the stdio construction path raises:
  `TypeError: UserConfig.__init__() got an unexpected keyword argument 'llm_provider'`

Impact:
- A documented deployment mode does not currently work.

Required fix:
- Either restore stdio compatibility or remove/document the unsupported mode.
- Add a direct test for the stdio bootstrap path.

## Release Process / Regression Gaps

### 8. Tests and types are out of sync with the implementation

Observed issue:
- `ruff` passes.
- Unit tests fail heavily.
- `mypy` reports many type errors.
- Several tests still expect older per-user LLM fields and behaviors that no longer match the live code.

Examples of drift:
- `tests/test_user_store.py`
- `tests/test_api_me.py`
- `tests/test_api_register.py`
- `tests/test_pipeline_factory.py`
- `tests/test_middleware.py`

Impact:
- The repo does not currently have a reliable regression gate.
- CI passing in principle is less meaningful when tests no longer represent the real product.

Required fix:
- Decide the canonical product behavior first.
- Update implementation and tests together.
- Do not ship until non-integration tests and type checks are green.

## Validation Performed

Local checks run during the audit:
- `uv run ruff check .` -> passed
- `uv run pytest tests/ -m "not integration" -v` -> 35 failed, 20 errors
- `uv run mypy src --ignore-missing-imports` -> 50 errors

Note:
- A local `UV_CACHE_DIR` override was needed because the default `uv` cache path in this environment was broken.

## Minimum Before Production

The following must be fixed before public deployment:

1. Replace blacklist SQL validation with a strict read-only allowlist.
2. Use sanitized database URLs for connection and persistence.
3. Enforce hosted `ask_database` quotas.
4. Implement real DB-side query timeout/cancellation.
5. Fix forwarded-header trust and deployment exposure defaults.
6. Make prompt data exposure an explicit, documented decision.
7. Fix or remove broken stdio mode.
8. Restore trustworthy test and type-check coverage.
