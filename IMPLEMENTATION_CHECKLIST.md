# Implementation Checklist

Date: 2026-04-11

This checklist converts [PRODUCTION_READINESS_ROADMAP.md](./PRODUCTION_READINESS_ROADMAP.md) into an implementation sequence tied to the current repo layout.

It is written to be executed in order. Do not skip phase validation. If a phase fails validation, do not continue to the next one.

## Current Repo Map

These are the main places you will work in:

- `src/app.py`
  - Hosted Starlette entrypoint
  - app lifespan
  - `/api` and `/mcp` mounting
- `src/server.py`
  - MCP server entrypoint
  - tool registration
  - quota enforcement
  - query logging
- `src/api/app.py`
  - FastAPI management API
  - registration, onboarding, admin, API key endpoints
- `src/api/schemas.py`
  - request/response contracts
- `src/auth/onboarding.py`
  - onboarding state machine
- `src/auth/user_store.py`
  - tenant, membership, API key, active DB, quota persistence
- `src/auth/token_store.py`
  - verification/login tokens
- `src/auth/middleware.py`
  - MCP API key auth
- `src/auth/url_guard.py`
  - outbound DB safety
- `src/core/pipeline_factory.py`
  - tenant-scoped DB/LLM pipeline creation
- `src/core/query_log.py`
  - query history persistence
- `src/config.py`
  - global settings
- `src/email_sender.py`
  - email transport abstraction
- `alembic/versions/*`
  - schema history
- `tests/*`
  - current backend test suite

What is missing today:

- no customer-facing web app
- no billing module
- no plan/entitlement module
- no setup-config generation module
- no observability module
- no admin UI

Recommended new top-level additions:

- `frontend/`
  - customer-facing web app and admin UI
- `src/billing/`
  - Stripe integration, subscription state sync, entitlement updates
- `src/entitlements/`
  - plan definitions, quota decisions, account gating
- `src/observability/`
  - metrics, tracing, error-reporting wiring
- `src/setup/`
  - generated MCP client config payloads

If you do not want a separate frontend repo yet, keep `frontend/` inside this repo for v1.

## Global Rules For Every Phase

- Every schema change requires:
  - a new Alembic migration in `alembic/versions/`
  - test updates
  - README or product-doc updates if behavior changes
- Every new API behavior requires:
  - schema updates in `src/api/schemas.py`
  - endpoint updates in `src/api/app.py`
  - tests for success and failure cases
- Every MCP behavior change requires:
  - tests in `tests/test_quota_enforcement.py`, `tests/test_middleware.py`, `tests/test_tools.py`, or new MCP-focused tests
- Every phase ends with:
  - automated validation
  - manual validation
  - docs validation

Core validation commands for backend phases:

- `uv run pytest tests/ -m "not integration" -v`
- `uv run ruff check .`
- `uv run ruff format --check .`

When a phase introduces real external integrations, add staging validation in addition to unit tests.

## Phase 0: Freeze Product Contracts — COMPLETE (2026-04-11)

Goal: stop product ambiguity before refactoring code.

### Checklist

- [x] Freeze the v1 account lifecycle:
  - `register -> verify email -> connect database -> activate free tier -> issue/create API key -> show setup config -> use /mcp`
- [x] Freeze launch plans:
  - `free` — 25 ask_database/day, 1 API key, 1 active database
  - `pro` — 500 ask_database/day, 5 API keys
- [x] Freeze the primary quota unit:
  - `ask_database` requests/day
- [x] Freeze launch auth model:
  - owner email verification
  - owner login links
  - MCP API key auth (bearer)
  - OAuth 2.1 for remote MCP (launch requirement, not a fast follow)
- [x] Freeze launch database support:
  - PostgreSQL
  - MySQL
  - no SQLite in production
- [x] Freeze launch platform target:
  - VPS — GCP or DigitalOcean (static egress IP, no PaaS networking constraints)

### Repo impact

- [x] Updated `PRODUCTION_READINESS_ROADMAP.md`: frozen contract table, OAuth decision, VPS platform, answered all open questions

### Validation

**Product contract (one paragraph):**

A user registers with their email; a verification link is sent and upon clicking it they are guided to a setup flow where they connect a PostgreSQL or MySQL database; once the database passes a live connectivity check the tenant is automatically placed on the free plan (25 `ask_database` calls per day, 1 API key, 1 active database), the first API key is created in a controlled reveal step so the user can record it, and a setup page generates client-ready configuration for VS Code, Cursor, ChatGPT developer mode, and generic HTTP MCP — with OAuth 2.1 as the authentication standard for remote MCP access alongside bearer API keys; from that point the user queries their database through `/mcp`, receives quota warnings at 50%, 80%, and 100% of daily usage, and can self-serve upgrade to the pro plan (500 calls per day, 5 API keys) via Stripe Checkout; no human admin approval exists on this path, though admins retain the ability to suspend or close any account.

**Contradictory state identified (to be resolved in Phase 1):**

- `src/auth/onboarding.py:134` — `pending_db_connection` + `db_submitted` currently transitions to `PENDING_REVIEW`, which requires `admin_approved` to reach `ACTIVE`. This is directly contradicted by the frozen lifecycle. Phase 1 must remove `pending_review` from the self-serve path and make `db_submitted` transition directly to `ACTIVE`.

**Contract coverage check:**

- All future lifecycle decisions (activation gate, key issuance timing, quota enforcement, plan transitions, admin actions) can be answered from the frozen contract above with no ambiguity.

## Phase 1: Refactor States, Plans, And Entitlements — COMPLETE (2026-04-11)

Goal: make the data model match self-serve SaaS instead of manual review onboarding.

### Files changed

- [x] `src/auth/onboarding.py` — split into onboarding states + account states; `db_submitted` → `setup_complete`
- [x] `src/auth/user_store.py` — add `account_status` column, `activate_tenant()`, `set_account_status()`, plan limit in `create_api_key()`
- [x] `src/api/app.py` — `submit_database` calls `activate_tenant()`; admin endpoints operate on `account_status`
- [x] `src/api/schemas.py` — extended all responses with `account_status`, `plan_code`, `billing_status`
- [x] `alembic/versions/0005_phase1_split_account_states.py` — adds `account_status` column, data migration, fixes defaults

### New modules added

- [x] `src/entitlements/__init__.py`
- [x] `src/entitlements/plans.py` — `FREE_PLAN` (25/day, 1 key, 1 DB), `PRO_PLAN` (500/day, 5 keys, 2 DBs)
- [x] `src/entitlements/service.py` — `EntitlementService` with query/key/db quota checks and warning levels

### Checklist

- [x] `pending_review` removed from self-serve path — `db_submitted` goes directly to `setup_complete`
- [x] onboarding status and account status are distinct DB columns with distinct value sets
- [x] billing status and plan code have correct defaults (`free`)
- [x] `FREE_PLAN` and `PRO_PLAN` defined with frozen quotas from Phase 0
- [x] `create_api_key()` enforces plan-level API key cap
- [x] Admin suspend and close still work via `set_account_status()`
- [x] Existing tenant data migrated via `0005` migration (backward compatible downgrade included)

### Validation

Automated — 338 tests pass, lint clean:

- [x] `test_onboarding_state_machine.py` — `test_db_submitted_goes_to_setup_complete`, `test_db_submitted_never_goes_to_pending_review`
- [x] `test_registration_flow.py` — `test_happy_path_self_serve_activation`, `test_no_admin_approval_required_on_happy_path`
- [x] `test_user_store.py` — activate_tenant, set_account_status, plan limit enforcement
- [x] `test_admin_endpoints.py` — restricted/suspend/close via account_status; no manual approval on self-serve path
- [x] `test_entitlements.py` — plan definitions, quota checks, warning levels (new)

Manual verification:

- Happy path in plain English: register → verify email → submit DB → account activates automatically on free plan (no admin step) → create API key → use /mcp ✓
- Tenant can still be suspended via `POST /v1/admin/tenants/{id}/suspend` ✓
- Tenant can still be closed via `POST /v1/admin/tenants/{id}/close` ✓
- `PENDING_REVIEW` exists only as an admin-triggered risk hold, not as the default path ✓

## Phase 2: Self-Serve Activation Backend — COMPLETE (2026-04-11)

Goal: make backend activation automatic after email verification and DB validation.

### Files changed

- [x] `src/api/app.py` — `submit_database` validates URL, runs live connectivity check, calls `activate_tenant()` (done in Phase 1); `create_api_key` endpoint rejects pre-activation tenants with 409
- [x] `tests/test_registration_flow.py` — added 5 failure tests covering all Phase 2 validation requirements

### First API key timing decision

**Decision:** one-click creation in setup flow (not automatic on activation).

Rationale: the user must see and store the raw key exactly once; auto-issuing it silently would mean the key is logged or lost. The setup UI presents a reveal step after activation where the user explicitly creates the first key via `POST /v1/api-keys` with their owner session.

### Checklist

- [x] `POST /v1/users/register` — unchanged
- [x] Email verification flow — unchanged; `GET /v1/onboarding/verify-email` issues owner session on success
- [x] On successful verification: owner session issued; user directed to database setup
- [x] On successful database submission: URL validated → live connectivity check → credentials encrypted and stored → tenant activated on free plan automatically
- [x] First API key timing: one-click creation in setup flow (deterministic rule documented above)

### Validation

Automated — 343 tests pass, lint clean:

- [x] `test_happy_path_self_serve_activation` — active tenant immediately after DB setup (no admin step)
- [x] `test_invalid_verification_token_returns_400` — bogus token → 400
- [x] `test_already_used_verification_token_returns_400` — reuse same token → 400
- [x] `test_invalid_database_url_returns_400` — sqlite URL rejected → 400
- [x] `test_unreachable_database_returns_400` — connect failure → 400
- [x] `test_inactive_tenant_cannot_create_api_key` — pre-activation key creation → 409

Manual verification:

- register → verify → submit DB → account_status=active, status=setup_complete, plan_code=free (automatic, no admin step) ✓
- bogus/expired/reused tokens all return 400 ✓
- inactive tenant cannot issue an API key ✓

## Phase 3: Plan Enforcement In MCP And API Surfaces

Goal: move from a single hardcoded quota into plan-driven enforcement.

### Files to change

- `src/server.py`
- `src/auth/middleware.py`
- `src/auth/user_store.py`
- `src/core/query_log.py`
- `src/config.py`
- `src/entitlements/service.py`
- tests:
  - `tests/test_quota_enforcement.py`
  - `tests/test_middleware.py`
  - `tests/test_query_history.py`
  - add `tests/test_entitlements.py`

### Checklist

- Replace or wrap `settings.ask_database_quota_per_day` with tenant-specific plan resolution
- Enforce entitlements at these points:
  - `ask_database`
  - API key creation
  - API key rotation if you want plan-level limits
  - active database count
- Keep quota checks before cold-path DB pipeline resolution
- Return structured over-limit responses
- Record quota and plan context in logs where appropriate

### Validation

Automated:

- free tenant at quota boundary succeeds exactly at limit and fails above it
- paid tenant receives the correct higher limit
- cache hits do not count against quota
- suspended tenant cannot use MCP
- API key creation is capped by plan

Manual:

- inspect API and MCP error responses and ensure they are user-comprehensible

Do not continue until:

- entitlements are evaluated server-side
- there are no plan decisions hardcoded only in UI or docs

## Phase 4: Customer Setup Payloads And Client Config Generation

Goal: make setup a product feature, not a docs exercise.

### New modules to add

- `src/setup/__init__.py`
- `src/setup/config_templates.py`
- `src/setup/service.py`
- `src/setup/schemas.py`

### Files to change

- `src/api/app.py`
- `src/api/schemas.py`
- tests:
  - add `tests/test_setup_payloads.py`
  - extend `tests/test_api_me.py` or add a dedicated setup endpoint test file

### Frontend surface to add

- `frontend/`
  - customer dashboard
  - setup page
  - API key reveal flow
  - client-specific config pages

If you do not want to start frontend implementation immediately, still build the backend payloads now.

### Checklist

- Add an authenticated endpoint that returns setup data for the current tenant
- Generate client-ready configuration payloads for:
  - VS Code
  - Cursor
  - ChatGPT developer mode
  - generic HTTP MCP
- Include:
  - endpoint URL
  - auth method
  - API key handling instructions
  - sample prompts
  - quota summary
- Decide whether you also emit copy-paste snippets or downloadable config files

### Validation

Automated:

- verify generated configs are tenant-scoped
- verify no secret other than the explicitly returned raw API key is leaked
- verify a revoked key is not still embedded in new setup payloads

Manual:

- test each generated config in staging with a real client where possible
- confirm the setup payload matches actual `/mcp` auth requirements

Do not continue until:

- one supported client can be connected from generated setup material alone

## Phase 5: Frontend Application

Goal: add the missing customer-facing product surface.

### New top-level directory

- `frontend/`

Recommended initial pages:

- signup
- verification success
- database connect
- dashboard
- API keys
- usage/quota
- billing
- setup/config
- support/help

### Backend files impacted

- `src/api/app.py`
- `src/api/schemas.py`
- CORS settings in `src/config.py`
- email links in `src/email_sender.py`

### Checklist

- Choose frontend framework and hosting model
- Build owner-session based auth flow for web pages
- Build the setup wizard:
  - verify state
  - collect DB URL
  - run connection test
  - activate free tier
  - create first API key
  - show generated config
- Build dashboard summary:
  - account state
  - billing state
  - connected DB
  - remaining quota
  - recent queries

### Validation

Automated:

- frontend route guards
- setup wizard state transitions
- API contract tests against backend schemas

Manual:

- run a full new-user setup without touching Postman or raw API routes
- confirm all critical product actions are available from UI

Do not continue until:

- a new user can complete the entire setup from the browser

## Phase 6: Billing Integration

Goal: add free-to-paid conversion and billing-backed entitlements.

### New modules to add

- `src/billing/__init__.py`
- `src/billing/stripe_client.py`
- `src/billing/service.py`
- `src/billing/webhooks.py`
- `src/billing/models.py` if you split persistence models

### Files to change

- `src/api/app.py`
- `src/api/schemas.py`
- `src/auth/user_store.py`
- `src/config.py`
- `alembic/versions/<billing migration>.py`
- tests:
  - add `tests/test_billing_webhooks.py`
  - add `tests/test_billing_checkout.py`
  - add `tests/test_entitlement_transitions.py`

### Checklist

- Add Stripe customer mapping per tenant
- Add subscription records per tenant
- Add endpoint to create Checkout session
- Add endpoint to create Customer Portal session
- Add webhook endpoint
- Map Stripe events to internal billing state changes
- On paid activation:
  - upgrade plan
  - recalculate entitlements
- On payment failure/cancellation:
  - downgrade or restrict paid entitlements
  - keep account metadata intact

### Validation

Automated:

- webhook signature validation
- webhook idempotency
- trial/free -> paid transition
- paid -> past_due transition
- paid -> canceled transition

Manual:

- run Stripe test-mode flow end to end in staging
- verify entitlements update immediately after webhook processing

Do not continue until:

- billing state is driven by Stripe webhook truth, not by optimistic frontend assumptions

## Phase 7: MySQL Production Support

Goal: make MySQL an actual supported product path, not a partial one.

### Files to change

- `pyproject.toml`
- `src/auth/url_guard.py`
- `src/core/pipeline_factory.py`
- `src/core/sql_generator.py`
- `src/core/sql_validator.py`
- `README.md`
- tests:
  - `tests/test_url_guard.py`
  - `tests/test_pipeline_factory.py`
  - add MySQL integration coverage

### Checklist

- Add explicit runtime dependency support for your chosen MySQL driver
- Document supported connection URL formats
- Review URL guard rules for MySQL TLS requirements
- Verify SQL dialect prompts and validation assumptions work for MySQL
- Add integration tests against a real MySQL service in CI or staging

### Validation

Automated:

- MySQL URL validation tests
- MySQL pipeline construction tests
- MySQL query execution integration tests

Manual:

- connect a real MySQL database in staging and run the full setup path

Do not continue until:

- you can successfully onboard and query both PostgreSQL and MySQL in staging

## Phase 8: Security And Abuse Controls

Goal: harden the open-signup SaaS path.

### Files to change

- `src/auth/url_guard.py`
- `src/api/app.py`
- `src/auth/user_store.py`
- `src/config.py`
- `src/auth/middleware.py`
- tests:
  - `tests/test_url_guard.py`
  - `tests/test_middleware.py`
  - add abuse/rate-limit coverage

### New modules to add

- `src/security/__init__.py` if you want a dedicated home
- `src/security/risk_service.py`
- `src/security/audit.py`

### Checklist

- Add bot protection to signup
- Add resend-email throttling
- Add owner login-link throttling
- Add API key creation/rotation throttling
- Add support/risk flags on tenants
- Add audit event recording for:
  - email verification
  - login-link use
  - DB credential update
  - API key create/revoke/rotate
  - billing state changes
  - suspension/closure
- Enforce TLS expectations for supported DB engines
- Finalize blocked CIDR policy

### Validation

Automated:

- blocked-IP and hostname tests
- risk-flag gating tests
- rate-limit tests where practical
- audit event persistence tests

Manual:

- verify signup abuse controls in staging
- verify a suspended tenant cannot use API or MCP routes

Do not continue until:

- you can explain how a malicious public user is rate-limited, blocked, suspended, and audited

## Phase 9: Email Delivery

Goal: move from dev logging/basic SMTP assumptions to production email delivery.

### Files to change

- `src/email_sender.py`
- `src/config.py`
- `src/api/app.py`
- tests:
  - add `tests/test_email_sender.py`
  - extend registration flow tests if behavior changes

### Checklist

- Keep the email abstraction
- Add a production transport choice:
  - transactional email API provider preferred
  - SMTP optional fallback
- Add operational email templates for:
  - verification
  - owner login
  - quota warnings
  - payment failure
  - DB connection broken

### Validation

Automated:

- template rendering tests
- transport selection tests
- failure-path tests

Manual:

- send real emails in staging and verify links, TTL expectations, and deliverability

Do not continue until:

- verification and login-link emails are dependable in staging

## Phase 10: Observability

Goal: make the service diagnosable in production.

### New modules to add

- `src/observability/__init__.py`
- `src/observability/tracing.py`
- `src/observability/metrics.py`
- `src/observability/errors.py`

### Files to change

- `src/app.py`
- `src/server.py`
- `src/core/logger.py`
- `src/config.py`
- potentially `src/api/app.py`, `src/core/pipeline_factory.py`, `src/email_sender.py`

### Checklist

- Add OpenTelemetry setup
- Add tracing for:
  - HTTP requests
  - MCP requests
  - outbound LLM calls
  - auth DB queries
  - Stripe calls
  - email calls
- Add metrics for:
  - signup funnel
  - activation funnel
  - MCP usage
  - error counts
  - webhook failures
  - quota exhaustion
- Add error reporting and alerts

### Validation

Automated:

- instrumentation wiring tests where practical
- configuration tests for enabled/disabled observability providers

Manual:

- verify traces appear in staging
- verify a forced error emits an alert
- verify logs contain request ID and tenant ID without leaking secrets

Do not continue until:

- you can answer "what failed for this tenant?" from logs and observability tooling

## Phase 11: Admin UI And Support Tooling

Goal: make support operations possible without shell/database access.

### Frontend additions

- admin pages inside `frontend/`

### Backend files to change

- `src/api/app.py`
- `src/api/schemas.py`
- `src/auth/user_store.py`
- tests:
  - `tests/test_admin_endpoints.py`
  - add admin search/support tests

### Checklist

- Add tenant search
- Show:
  - tenant identity
  - account/billing/onboarding state
  - API keys
  - active DB metadata
  - recent query history
  - recent errors
  - quota usage
- Add support actions:
  - suspend
  - close
  - revoke key
  - inspect setup state

### Validation

Automated:

- admin authorization tests
- support action tests

Manual:

- resolve a simulated support ticket using only the admin UI

Do not continue until:

- normal support workflows do not require direct database edits

## Phase 12: Deployment, Staging, And Runbooks

Goal: make the system deployable and recoverable.

### Files to change

- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `README.md`
- add platform-specific deploy descriptors if needed

### New docs to add

- `docs/deployment.md`
- `docs/staging-checklist.md`
- `docs/runbooks.md`
- `docs/incident-response.md`

### Checklist

- Choose the platform
- Stand up staging
- Stand up production
- Provision managed PostgreSQL for app data
- Configure secrets
- Configure backups
- Configure health checks
- Configure deploy pipeline
- Configure rollback procedure

### Validation

Manual:

- deploy staging from scratch
- restore from backup in a test environment
- execute rollback at least once
- verify outbound DB connectivity from the chosen platform

Do not continue until:

- staging mirrors production closely enough to catch integration issues

## Phase 13: Final Launch Validation

Goal: prove the product works as a SaaS, not just as a codebase.

### End-to-end checklist

- new user signs up
- verification email arrives
- user verifies email
- user lands on setup flow
- user connects PostgreSQL
- user activates free tier
- user creates first API key
- user receives client-ready config
- user connects one tier-1 MCP client
- user runs a successful `ask_database`
- user hits quota warning
- user upgrades through Stripe
- entitlements increase
- user continues querying

Repeat the same for MySQL before launch if MySQL is advertised on the landing page.

### Validation

Automated:

- full staging smoke suite

Manual:

- run the entire launch journey yourself on staging
- have one external tester complete the journey without internal guidance

Do not launch until:

- the external tester can complete onboarding and first value without engineering intervention

## Definition Of Done By Area

### Backend onboarding is done when

- manual approval is off the default path
- DB validation auto-activates the free tier
- tests reflect the new lifecycle

### Billing is done when

- Stripe webhooks drive subscription truth
- entitlements update automatically

### MCP readiness is done when

- quotas are plan-aware
- tenant gating is enforced server-side
- generated client setup matches actual auth behavior

### Security is done when

- open signup has abuse protection
- outbound DB safety is enforced
- audit trails exist

### Product UX is done when

- the browser flow covers signup through first successful MCP use

### Ops is done when

- staging exists
- alerts work
- backups are proven
- support can operate through tools, not raw DB access

## Suggested Working Order Inside The Repo

Use this sequence for the least thrash:

1. `src/auth/onboarding.py`
2. `src/auth/user_store.py`
3. `alembic/versions/*`
4. `src/api/schemas.py`
5. `src/api/app.py`
6. `src/entitlements/*`
7. `src/server.py`
8. `tests/*`
9. `src/setup/*`
10. `frontend/*`
11. `src/billing/*`
12. `src/security/*`
13. `src/observability/*`
14. deployment/docs updates

This order keeps your domain model stable before you build UI or deployment assumptions on top of it.
