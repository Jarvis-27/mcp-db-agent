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

## Phase 0: Freeze Product Contracts

Goal: stop product ambiguity before refactoring code.

### Checklist

- Freeze the v1 account lifecycle:
  - `register -> verify email -> connect database -> activate free tier -> issue/create API key -> show setup config -> use /mcp`
- Freeze launch plans:
  - `free`
  - `pro`
- Freeze the primary quota unit:
  - `ask_database` requests/day
- Freeze launch auth model:
  - owner email verification
  - owner login links
  - MCP API key auth
- Freeze launch database support:
  - PostgreSQL
  - MySQL
  - no SQLite in production
- Freeze launch platform target:
  - choose one of `Fly.io` or `Railway` before deployment work starts

### Repo impact

- Update [PRODUCTION_READINESS_ROADMAP.md](/C:/Users/Abhishek/Desktop/VsCode/mcp-db-agent/PRODUCTION_READINESS_ROADMAP.md:1) if any policy changes
- Update `README.md` later in the corresponding implementation phases

### Validation

- Write a one-paragraph product contract and confirm there are no remaining contradictory states such as mandatory `pending_review` on the default path
- Confirm all future implementation decisions can be answered from that contract

## Phase 1: Refactor States, Plans, And Entitlements

Goal: make the data model match self-serve SaaS instead of manual review onboarding.

### Files to change

- `src/auth/onboarding.py`
- `src/auth/user_store.py`
- `src/api/app.py`
- `src/api/schemas.py`
- `src/config.py`
- `alembic/versions/<new migration>.py`
- tests:
  - `tests/test_onboarding_state_machine.py`
  - `tests/test_registration_flow.py`
  - `tests/test_api_register.py`
  - `tests/test_api_me.py`
  - `tests/test_admin_endpoints.py`
  - `tests/test_user_store.py`

### New modules to add

- `src/entitlements/__init__.py`
- `src/entitlements/plans.py`
- `src/entitlements/service.py`
- `src/entitlements/schemas.py` if needed

### Checklist

- Replace the current default onboarding path so self-serve users do not land in mandatory `pending_review`
- Split concepts that are currently overloaded into distinct concerns:
  - onboarding status
  - account status
  - billing status
  - plan/entitlement state
- Add explicit plan representation
- Add explicit entitlement evaluation rules:
  - daily query cap
  - max API keys
  - max active databases
- Keep admin suspension/closure controls, but remove manual approval from the normal customer path
- Preserve backward-compatible support for existing tenants if you already have local data worth migrating

### Recommended implementation order

1. Redesign the target state model on paper first
2. Add migration
3. Update store methods in `src/auth/user_store.py`
4. Update state machine logic in `src/auth/onboarding.py`
5. Update API responses in `src/api/schemas.py`
6. Update API endpoint gating in `src/api/app.py`
7. Add entitlement service and wire it into API key issuance logic

### Validation

Automated:

- Extend `tests/test_onboarding_state_machine.py` to reflect the new lifecycle
- Update `tests/test_registration_flow.py` so the happy path no longer requires admin approval
- Add store-level tests for plan and entitlement lookup

Manual:

- Walk the happy path as plain English and verify it never depends on a human admin
- Confirm a tenant can still be suspended or closed by support/admin controls

Do not continue until:

- the happy path is self-serve
- existing tests pass after removal of `pending_review` from the normal path

## Phase 2: Self-Serve Activation Backend

Goal: make backend activation automatic after email verification and DB validation.

### Files to change

- `src/api/app.py`
- `src/api/schemas.py`
- `src/auth/user_store.py`
- `src/auth/token_store.py` if token lifecycle needs changes
- `src/config.py`
- tests:
  - `tests/test_registration_flow.py`
  - `tests/test_api_register.py`
  - `tests/test_api_me.py`
  - `tests/test_user_store.py`

### Checklist

- Keep `POST /v1/users/register`
- Keep email verification flow
- On successful verification:
  - create owner session
  - redirect or point the user toward setup
- On successful database submission:
  - validate URL
  - validate connectivity
  - persist encrypted credentials
  - activate tenant on free plan automatically
- Decide exactly when the first API key is created:
  - automatically on activation, or
  - one-click creation in setup flow

Recommended v1 choice:

- activate tenant automatically after DB validation
- let setup UI create the first key in a controlled step so the user sees and stores it

### Validation

Automated:

- add a single happy-path test that ends with an active tenant immediately after DB setup
- add failure tests for:
  - invalid verification token
  - invalid database URL
  - unreachable database
  - inactive tenant denied key creation

Manual:

- verify the lifecycle:
  - register
  - verify
  - submit DB
  - active
  - create key
- verify no admin step is needed

Do not continue until:

- activation is automatic
- there is a deterministic rule for first API key issuance

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
