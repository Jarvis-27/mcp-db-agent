# Pre-Deployment Verification Notes

Date: 2026-04-09

This document records the issues found while running the repository verification matrix before server deployment testing.

## Verified Current State

- Full repository test suite passes:
  - `283 passed`
- Hosted multi-tenant startup smoke passed in both development and production-style settings.
- Single-user startup smoke passed in both development and production-style settings.
- The current configured online PostgreSQL URL is reachable with SSL and succeeds on a read-only `SELECT 1` when connected without PostgreSQL startup `options`.

## Resolved Issue 1: Bundled integration tests were unreliable

### Status

Resolved in the current working tree.

### Reason

The integration fixture creates an in-memory SQLite database with:

- `create_engine("sqlite:///:memory:")`

The SQL executor runs queries in a thread pool and opens a fresh connection when executing SQL. With in-memory SQLite, each connection gets its own isolated database. That means:

- the fixture creates tables and data on one connection
- the executor runs queries on another connection
- the executor sees no tables and returns errors such as `no such table: customers`

Once that first execution fails, the self-correction loop may generate multi-statement SQL, which is then correctly rejected by the validator. That makes all five integration tests fail even though the LLM provider path is reachable.

### Fix

Change the integration fixture to use a shared SQLite setup instead of `sqlite:///:memory:`.

Safe options:

1. Preferred: use a shared in-process SQLite engine with `StaticPool`

```python
from sqlalchemy.pool import StaticPool

e = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

2. Acceptable: use a temporary file-backed SQLite database

This avoids per-connection isolation and is also safe for threaded execution.

### Deployment Impact

This issue no longer blocks release verification. The integration suite now provides a meaningful signal again.

## Resolved Issue 2: Part of the non-integration suite depended on local demo database state

### Status

Resolved in the current working tree.

### Reason

These tests use the process-global app settings rather than constructing their own isolated test database. They implicitly depend on:

- `DATABASE_URL` being set
- that URL pointing to the expected demo schema
- the local demo schema having already been seeded

That makes the suite environment-sensitive and risky for CI or pre-deploy validation.

### Fix

Make these tests self-contained.

Safe options:

1. Best fix:
   - stop reading `settings.database_url` in these tests
   - create a dedicated test database fixture inside the test file
   - seed only the tables and rows the test needs

2. Minimum fix:
   - explicitly override `DATABASE_URL` inside the tests to a temporary local SQLite file
   - seed that database in test setup

Do not rely on the operator's `.env` for these tests.

### Deployment Impact

This issue no longer blocks release verification. The test suite is now self-contained enough to run safely.

## New Blocking Issue: Online PostgreSQL pooler compatibility

### Problem

The repository test suite passes, but a real smoke test against the configured online PostgreSQL database fails when the application uses the hosted pipeline path.

### Reason

`src/core/pipeline_factory.py` injects PostgreSQL startup `options` via:

- `options=-c statement_timeout=...`

That works for many PostgreSQL deployments, but the currently configured Neon pooled endpoint rejects it with:

- `unsupported startup parameter in options: statement_timeout`

The same database URL succeeds immediately when connected with only:

- `connect_timeout=10`

and no startup `options`.

This means:

- the remote database itself is reachable
- SSL is configured correctly
- credentials are valid
- the current application connection strategy is the incompatible part

### Fix

Do not send `statement_timeout` as a PostgreSQL startup option for pooled providers like Neon pooler.

Safer alternatives:

1. Preferred:
   - keep `connect_timeout` in `connect_args`
   - remove startup `options`
   - set `statement_timeout` after connect, per checked-out connection

2. Acceptable:
   - detect incompatible pooled endpoints and skip startup `options` for those URLs

The first option is safer because it preserves timeout behavior without depending on provider-specific startup-parameter support.

### Deployment Impact

This is a real runtime blocker for online PostgreSQL deployments that use a pooler endpoint like the current one. The suite is green, but the deployed server will still fail to connect until this is fixed.

## Deployment Requirements Confirmed During Smoke Checks

These are not failures, but they must remain true when deploying the hosted server:

- `CREDENTIAL_ENCRYPTION_KEYS` must be set for non-development environments
- the auth database must be migrated to Alembic head before production startup
- hosted mode should use `src.app`
- single-user mode should use `src/server.py`

## Recommended Action Before Server Testing

1. Update PostgreSQL timeout handling in `src/core/pipeline_factory.py` so pooled online providers are supported.
2. Re-run the full suite:
   - `uv run pytest tests/ -v`
3. Re-run a real read-only smoke against the actual online `DATABASE_URL`.
4. Only after the remote smoke passes should this build be treated as deployable for server testing.

## Bottom Line

The test suite is now green, but the online PostgreSQL path is not yet deployment-safe for the current pooled Neon-style connection. The remaining blocker is runtime connection compatibility, not test reliability.
