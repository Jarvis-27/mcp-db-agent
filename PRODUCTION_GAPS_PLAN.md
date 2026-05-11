# Production Gaps — Implementation Plan

Audit date: 2026-05-11
Branch audited: `master` @ `9e45a7a`
Companion doc: `PRODUCTION_READINESS_ROADMAP.md` (higher-level roadmap)

This document lists concrete production gaps where the implementation does not
yet stand behind the product's claims. Each item names the file, the claim, the
actual reality, and a fix direction. Items are ordered by recommended fix
order, not severity alone.

## How to use this doc

- Each item has a checkbox; tick it as you ship the fix.
- "Acceptance" describes what proves the gap is closed (usually a test).
- "Effort" is rough: S = under a day, M = 1–3 days, L = a week or more.
- Numbers (G1, G2, ...) are stable references; don't renumber after merging.

---

## Tier 1 — Launch blockers

### G1. `/health/live` is a stub — orchestrator cannot detect dead workers
- **File:** `src/api/app.py:1137-1139`
- **Claim:** "Health endpoints" listed under hosted-mode architecture in `CLAUDE.md`.
- **Reality:** Unconditional `{"status": "ok"}`. A worker with a stuck event
  loop, exhausted memory, or a deadlocked thread pool still reports healthy.
- **Fix direction:** Add an async heartbeat task that updates a timestamp on
  each event-loop tick; `/health/live` returns 503 when the timestamp is older
  than ~5 s. Keep it cheap — no DB calls.
- **Acceptance:** Unit test that monkey-patches the heartbeat to stale and
  asserts 503; smoke test under a deliberately blocked loop returns 503.
- **Effort:** S
- [ ] Done

### G2. `/health/ready` only checks the auth DB
- **File:** `src/api/app.py:1142-1151`
- **Claim:** "Readiness" implies the worker can actually serve requests.
- **Reality:** Pings the auth DB and returns ok. Does not verify the OAuth
  issuer (when `mcp_auth_mode != api_key_only`), the executor pool, the
  pipeline factory, or LLM provider configuration.
- **Fix direction:** Add lightweight, time-boxed (≤ 1 s each) checks per
  critical dependency. Surface the failing dependency in the 503 body.
- **Acceptance:** Test per dependency that simulates failure and asserts 503.
- **Effort:** M
- [ ] Done

### G3. FastAPI docs (`/docs`, `/redoc`, `/openapi.json`) exposed in production
- **File:** `src/api/app.py:94`
- **Claim:** Production-grade hosted API.
- **Reality:** No gate on `settings.environment`. Leaks every route shape,
  including admin/billing endpoints.
- **Fix direction:**
  ```python
  is_prod = settings.environment == "production"
  api_app = FastAPI(
      title="MCP Database Analytics - Account API",
      docs_url=None if is_prod else "/docs",
      redoc_url=None if is_prod else "/redoc",
      openapi_url=None if is_prod else "/openapi.json",
  )
  ```
- **Acceptance:** Test with `ENVIRONMENT=production` confirms 404 on all three;
  test with `development` confirms 200.
- **Effort:** S
- [ ] Done

### G4. SlowAPI runs in-memory by default — per-IP limits leak per worker
- **File:** `src/api/app.py:92`
- **Claim:** "Rate-limited by `slowapi`" in `CLAUDE.md` §api/app.py.
- **Reality:** No `storage_uri`. With N uvicorn workers, every bucket is
  per-process, so a `5/minute` signup limit becomes `5N/minute`.
- **Fix direction:** Configure a Redis-backed storage URI; require it when
  `ENVIRONMENT=production`. Fail closed on backend errors.
  ```python
  limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
  ```
- **Acceptance:** Integration test with 2 workers + shared Redis showing one
  global bucket; configuration validation rejects prod boot without `REDIS_URL`.
- **Effort:** M
- [ ] Done

### G5. MCP `ask_database` endpoint has no rate limit at all
- **File:** `src/server.py` (no limiter on tool calls) — limiter only attached
  to REST routes in `src/api/app.py`.
- **Claim:** "Per-user rate limits and fallback-LLM quotas limit cost abuse"
  (`CLAUDE.md` §security model).
- **Reality:** Only daily *quota* is enforced. An authenticated client can
  burst hundreds of `ask_database` calls per minute. Quota stops them at the
  daily cap; nothing stops the burst itself.
- **Fix direction:** Add a per-API-key sliding-window limiter (token bucket)
  applied inside the MCP middleware. Keyed by `user_id` (or hashed API key),
  not IP, so multiple clients of the same user are still throttled together.
- **Acceptance:** Concurrent-client test against one API key shows requests
  beyond the burst rate get a structured `rate_limited` error and the burst
  rate is configurable.
- **Effort:** M
- [ ] Done

### G6. Self-corrector retries with no backoff and no cost ceiling
- **File:** `src/core/self_corrector.py:38-77`
- **Claim:** "Max self-correction retries" controls cost (`CLAUDE.md`).
- **Reality:** Up to 3 LLM round-trips back-to-back per failed query, no
  backoff, no token budget, no differentiation between retryable
  (timeout / transient) and fatal (syntax / type) errors. Every failure pays
  the full retry tax.
- **Fix direction:**
  - Tag error categories at the executor layer.
  - Retry only on categories the LLM can plausibly fix
    (`UndefinedTable`, `UndefinedColumn`, type mismatch, ambiguous column).
  - Add a per-request token budget; abort early on cost exhaustion.
  - Add jittered backoff (e.g., 0.5 s, 1 s) between retries to absorb upstream
    throttling.
- **Acceptance:** Unit tests per error category proving retry vs. abort;
  cost-budget test that proves a request stops calling the LLM after N tokens.
- **Effort:** M
- [ ] Done

### G7. `MAX_QUERY_ROWS` is documented but unused
- **File:** `src/core/sql_validator.py:178` (hardcoded `LIMIT 100`).
- **Claim:** `MAX_QUERY_ROWS=100` is a tunable per `.env.example` and
  `CLAUDE.md`.
- **Reality:** Validator injects `LIMIT 100` regardless of the setting; any
  user-supplied `LIMIT > MAX_QUERY_ROWS` is not clamped either.
- **Fix direction:** Thread `settings.max_query_rows` into the validator;
  inject and *clamp*.
- **Acceptance:** Test that `LIMIT 9999` becomes `LIMIT {max_query_rows}` when
  the cap is lower, and that the auto-inject value follows the setting.
- **Effort:** S
- [ ] Done

### G8. SQL executor timeout cancels the future, not the database query
- **File:** `src/core/sql_executor.py`
- **Claim:** `QUERY_TIMEOUT_SECONDS` enforces query cost (`.env.example`).
- **Reality:** Thread-pool cancellation doesn't propagate to the DB driver.
  The Python coroutine returns; the underlying `SELECT` keeps running until
  the database kills it (which it may not). Under load this drains the pool.
- **Fix direction:** Set per-statement DB-side timeouts:
  - PostgreSQL: `SET LOCAL statement_timeout = ...` on the connection.
  - SQLite: `connection.set_progress_handler(...)` or rely on driver timeout.
  - MySQL: `MAX_EXECUTION_TIME(...)` hint or `max_execution_time` session var.
- **Acceptance:** Integration test that runs `SELECT pg_sleep(N)` with a
  shorter timeout and asserts the server kills it (server-side cancellation),
  not just the client coroutine.
- **Effort:** M
- [ ] Done

---

## Tier 2 — Pre-launch hardening

### G9. Schema cache never invalidates on DDL drift
- **File:** `src/core/schema_inspector.py` (TTL only, default 600 s).
- **Claim:** Schema introspection backs reliable SQL generation.
- **Reality:** If a customer's database adds a table or drops a column,
  generated SQL is wrong for up to 10 minutes. There's no error-driven bust.
- **Fix direction:** When the executor raises `UndefinedTable` /
  `UndefinedColumn`, call `SchemaInspector.refresh()` once and retry inside
  `SelfCorrector` *before* falling back to LLM repair.
- **Acceptance:** Integration test that drops a column mid-session and proves
  the next query refreshes the schema and succeeds without manual intervention.
- **Effort:** M
- [ ] Done

### G10. No graceful shutdown for in-flight queries
- **File:** `src/app.py` lifespan, `src/core/sql_executor.py`.
- **Claim:** Hosted multi-tenant service.
- **Reality:** SIGTERM tears down the thread pool without draining; clients
  receive connection reset mid-query. `query_history` rows never get a
  terminal state.
- **Fix direction:** In lifespan exit, set a "draining" flag (new requests
  return 503), wait up to N seconds for active futures, then call
  `executor.shutdown(wait=True)`. Mark interrupted queries as
  `status="interrupted"`.
- **Acceptance:** Test that issues a long-running query, sends shutdown,
  receives a structured error response *and* sees the matching
  `query_history` row marked interrupted.
- **Effort:** M
- [ ] Done

### G11. Defense-in-depth: system tables are only blocked by table-existence
- **File:** `src/core/sql_validator.py:160-167`
- **Claim:** "SQL is validated for dangerous functions and patterns" (§3).
- **Reality:** No explicit denylist for `pg_*`, `information_schema.*`,
  `mysql.*`, `sqlite_master`. Today, `SchemaInspector.get_table_names()`
  doesn't expose them so the existence check rejects them — but that's load-
  bearing on a single line of behavior in a different file.
- **Fix direction:** Add an explicit denylist applied regardless of inspector
  results.
  ```python
  _FORBIDDEN_SCHEMAS = {"pg_catalog", "information_schema", "mysql", "sys", "performance_schema"}
  _FORBIDDEN_TABLES  = {"sqlite_master", "sqlite_sequence", "sqlite_temp_master"}
  ```
- **Acceptance:** Regression tests for each engine asserting the SELECT is
  rejected even if a future inspector change were to surface system tables.
- **Effort:** S
- [ ] Done

### G12. CORS uses wildcard methods + headers with `allow_credentials=True`
- **File:** `src/app.py:489-495`
- **Claim:** "CORS configured" (§config).
- **Reality:** `allow_methods=["*"]` and `allow_headers=["*"]` combined with
  `allow_credentials=True` violates the CORS spec when any non-empty origin
  list is configured. Browsers may reject it; if they don't, the policy is
  broader than needed.
- **Fix direction:** Enumerate methods and headers explicitly:
  ```python
  allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
  allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Session-Token"],
  ```
- **Acceptance:** Test of a preflight request from an allowed origin returns
  the explicit method/header set, not `*`.
- **Effort:** S
- [ ] Done

### G13. No CI workflow
- **File:** missing `.github/workflows/`.
- **Claim:** README documents `uv run pytest`, ruff, mypy.
- **Reality:** Nothing runs on PR or push. Security-critical tests
  (`test_url_guard`, `test_sql_validator`, `test_crypto`) exist but are not
  gated.
- **Fix direction:** Add `ci.yml` with jobs:
  1. lint: `uv run ruff check . && uv run ruff format --check .`
  2. types: `uv run mypy src --ignore-missing-imports`
  3. unit: `uv run pytest -m "not integration"`
  4. integration (separate job, service container for Postgres).
- **Acceptance:** PR shows all four checks; failing any blocks merge.
- **Effort:** M
- [ ] Done

### G14. Encryption-key retirement is not implemented
- **File:** `src/auth/crypto.py`
- **Claim:** "Supports key rotation via comma-separated
  `CREDENTIAL_ENCRYPTION_KEYS`" (`CLAUDE.md` §crypto.py).
- **Reality:** Adding a new primary key works; *retiring* an old key is
  unsafe because existing ciphertexts still depend on it. There is no
  re-encryption pass.
- **Fix direction:** Add `scripts/rotate_encryption_keys.py` that walks the
  `users` table, decrypts every credential with the multi-key, re-encrypts
  with the *primary* key, writes back inside a single transaction per row.
  Document the retire procedure.
- **Acceptance:** Test that runs the script after rotating keys and proves
  the old key can be removed without losing decryptability.
- **Effort:** M
- [ ] Done

### G15. Quota wording — "daily" reset is anchored to user activity, not midnight
- **File:** `src/auth/user_store.py:266-267, 944-968`
- **Claim:** Daily quota implies a calendar-day cadence.
- **Reality:** The atomic SQL is correct (no race) but the reset window is
  set to "next midnight after the first consume", so each user's "day" floats
  relative to wall-clock. UX-misleading but not a correctness bug.
- **Fix direction:** Pick one of:
  - Align all resets to a fixed UTC midnight (cron job or scheduled task).
  - Document the floating-window behavior in the API response (`reset_at` is
    already returned; surface it in user-facing copy too).
- **Acceptance:** Either the scheduled job is in place and tested, or the
  pricing/docs page explicitly references the floating reset window.
- **Effort:** S (docs) / M (cron)
- [ ] Done

---

## Tier 3 — Operational maturity

### G16. No observability beyond structured logs
- **Claim:** Hosted, paid product.
- **Reality:** No Prometheus, no OpenTelemetry, no per-user cost tracking
  beyond log lines. You will fly blind on latency, LLM cost, error rates,
  and cache effectiveness.
- **Fix direction:** OpenTelemetry instrumentation:
  - FastAPI auto-instrumentation for HTTP spans.
  - SQLAlchemy instrumentation for DB spans.
  - Manual spans around `SQLGenerator.generate` and `SelfCorrector` retries
    with token counts as attributes.
  - OTLP exporter; pick a backend (Honeycomb / Grafana Tempo / Datadog).
- **Acceptance:** A trace for one `ask_database` request shows the HTTP
  span, the schema-introspect span, the LLM span (with token counts), the
  SQL execution span, and the corrector retries (if any).
- **Effort:** L
- [ ] Done

### G17. Request ID not propagated into LLM/SQL paths
- **File:** `RequestIDMiddleware` exists (`src/app.py:498`), but `SQLGenerator`
  and `SQLExecutor` don't pull from the request ContextVar.
- **Claim:** Structured logging.
- **Reality:** No way to follow one HTTP request through to its LLM call and
  its `query_history` row.
- **Fix direction:** Add a ContextVar-based request-id getter; include it in
  every log line and in the `query_history.request_id` column.
- **Acceptance:** Grepping logs by request ID yields the full trace; the
  `query_history` row matches.
- **Effort:** S
- [ ] Done

### G18. No backup / disaster-recovery documentation or scripts
- **Claim:** Storing third-party database credentials at rest.
- **Reality:** Nothing in repo describes auth-DB backup cadence, key escrow
  for `CREDENTIAL_ENCRYPTION_KEYS`, restore drills, or RTO/RPO targets.
- **Fix direction:**
  - Add `docs/operations/backup-and-restore.md` with concrete commands.
  - Add `scripts/restore_auth_db.sh` that operators can run.
  - Document key escrow: where the encryption key is stored (and where it
    isn't), who has access, and how to recover it.
- **Acceptance:** Monthly restore drill on a non-prod copy succeeds inside
  the stated RTO.
- **Effort:** M

### G19. No email-verification gate on registration
- **Claim:** Multi-tenant SaaS positioning (free plans, paid plans).
- **Reality:** Signup issues an API key immediately. Throwaway emails can
  burn the free plan.
- **Fix direction:** Issue API key only after verification, or restrict
  `ask_database` quota until verification completes. (Tie to existing
  email-sending stack: `Resend` integration is already present per recent
  commits.)
- **Acceptance:** Signup test asserts no usable API key is returned until
  the verification link is clicked.
- **Effort:** M
- [ ] Done

### G20. Sub-app exception handler uses a type-ignore
- **File:** `src/api/app.py:96`
  ```python
  api_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
  ```
- **Claim:** N/A — code smell only.
- **Reality:** Type-ignored slowapi handler integrations have broken across
  past versions. Worth a regression test.
- **Fix direction:** Replace the ignore with a typed adapter; add a test that
  asserts `429` is actually returned by the mounted sub-app.
- **Acceptance:** Test exercises rate limit and asserts 429 body shape.
- **Effort:** S
- [ ] Done

### G21. `_extract_table_names` is a FROM/JOIN regex
- **File:** `src/core/sql_validator.py:199-210`
- **Claim:** Table-existence check covers all referenced tables.
- **Reality:** Misses constructs like `MERGE INTO x` or `TABLE x`. Today this
  doesn't matter because DML is blocked, but the load-bearing assumption is
  brittle. Combined with G11, this is the second weak point in the
  defense-in-depth chain.
- **Fix direction:** Walk `sqlparse` tokens to extract identifiers; deprecate
  the regex.
- **Acceptance:** Add a property-based or fixture-based test corpus including
  CTEs, subqueries, schema-qualified tables, lateral joins.
- **Effort:** M
- [ ] Done

---

## Recommended ordering

Bundle by file blast radius. Each bundle is a separate PR.

1. **PR-1 (Health + docs):** G1, G2, G3.
2. **PR-2 (Rate limiting):** G4, G5.
3. **PR-3 (Cost protection):** G6, G7, G8.
4. **PR-4 (Schema and shutdown):** G9, G10.
5. **PR-5 (Validator hardening):** G11, G21.
6. **PR-6 (Ops):** G12, G13, G17, G20.
7. **PR-7 (Crypto + quota docs):** G14, G15.
8. **PR-8 (Email verification):** G19.
9. **PR-9 (Observability):** G16.
10. **PR-10 (DR):** G18.

## Out of scope for this plan

- Anything covered by `PRODUCTION_READINESS_ROADMAP.md` (higher-level
  positioning), unless this doc explicitly references it.
- Refactors not driven by a specific gap above.
- New product features.

## Notes on findings *not* included

The following were considered and rejected as not-actually-gaps after
verification against the code:

- **"SQL validator misses block comments"** — `_first_sql_keyword` strips
  both `--` and `/* */` correctly (`sql_validator.py:192-194`).
- **"Quota update has a TOCTOU race"** — the UPDATE in
  `consume_daily_query_quota` is atomic at the DB level
  (`user_store.py:949-968`); concurrent calls serialize on the row lock.
- **"UNION SELECT bypasses the SELECT allowlist"** — UNION is technically
  allowed, but any system-table reference (`pg_user`, etc.) is rejected by
  the table-existence check. G11 hardens this further as defense in depth.
