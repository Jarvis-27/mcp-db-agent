# SaaS Identity And Production Plan

Date: 2026-04-10

## Goal

Turn this project from "public self-register and immediately get an API key" into a SaaS where:

- a human account is verified before any API key is issued
- new tenants start on very low quotas
- onboarding, billing, abuse controls, and production operations are explicit

This plan is written against the current codebase, where:

- `POST /api/v1/users/register` is public
- `registration_open` defaults to `True`
- registration currently creates a tenant and returns an API key immediately
- the app is exposed directly on port `8000`

## Recommendation Summary

Use a managed identity provider for human users, keep your own internal tenant and API key system, and move API key issuance behind a verified onboarding workflow.

Recommended stack:

- Human auth: Auth0 Universal Login
- Anti-bot: Cloudflare Turnstile on signup and sensitive forms
- Billing and proof-of-intent: Stripe Billing Checkout + Stripe webhooks
- Optional stronger identity proof for risky customers: Stripe Identity
- Edge protection: Cloudflare WAF + Cloudflare rate limiting rules
- Observability: OpenTelemetry for FastAPI and SQLAlchemy
- Feature rollout and kill switches: OpenFeature

## What "Verified Identity" Should Mean

Do not treat "email verified" as sufficient identity proof on its own. Auth0 explicitly notes that email verification proves access to the mailbox, not that the user is who they claim to be.

Define assurance levels:

- `email_verified`
  - User completed Auth0 email verification.
- `account_verified`
  - Email verified
  - Turnstile passed during signup
  - Paid subscription or approved free trial exists
  - Owner completed MFA or passkey enrollment
- `high_trust`
  - `account_verified`
  - Optional: government ID / selfie check via Stripe Identity
  - Optional: manual review for high-risk or high-spend tenants

Practical SaaS default:

- Do not issue any API key until the tenant reaches `account_verified`.
- Reserve `high_trust` for enterprise, high-quota, or abuse-sensitive use cases.

## Target Architecture

### 1. Separate Human Identity From API Keys

Keep these concerns separate:

- Human login/session
  - Auth0 handles sign-up, login, email verification, MFA, passwordless or passkey flows.
- SaaS tenant state
  - Your app stores tenant, membership, billing, trust level, quotas, database connection state, and API keys.
- Machine access
  - Your app issues hashed, scoped API keys only after onboarding completes.

This is the right split for a SaaS. Do not let Auth0-issued user tokens double as the long-lived machine credential for MCP clients.

### 2. Close Public API-Key Registration

Replace the current flow:

- `POST /api/v1/users/register` -> returns `api_key`

With this flow:

1. User signs up through a web app using Auth0.
2. Auth0 verifies email.
3. App creates an internal tenant in `pending_verification`.
4. User completes billing or an approved free-trial step.
5. User completes MFA or passkey enrollment.
6. User submits database connection details.
7. App validates and tests the database connection.
8. App issues the first API key through an authenticated tenant-owner action.

### 3. Add Explicit Onboarding States

Add a tenant onboarding state machine:

- `pending_email_verification`
- `pending_billing`
- `pending_mfa`
- `pending_db_connection`
- `pending_review`
- `active`
- `suspended`
- `closed`

Do not let MCP access or API key issuance happen unless tenant state is `active`.

## Recommended Vendor And Library Choices

### Auth0

Use Auth0 for:

- Universal Login
- email verification
- MFA / WebAuthn
- attack protection
- Organizations if you want B2B workspaces

Why:

- It gives you email verification, MFA, attack protection, and org concepts without building auth flows yourself.
- It integrates cleanly with a Python/FastAPI backend through JWT verification.

What to use from Auth0:

- Universal Login
- email verification
- MFA with WebAuthn preferred for owners/admins
- Attack Protection: Bot Detection, Suspicious IP Throttling, Brute-Force Protection
- Organizations if you want one workspace per customer company

### Cloudflare Turnstile

Use Turnstile on:

- signup
- login if abuse becomes high
- "create trial"
- "issue API key"
- "rotate API key"

Important implementation note:

- Turnstile requires server-side token validation. Do not trust the browser token alone.

### Stripe Billing

Use Stripe Checkout + subscriptions for:

- proof of payment method / proof of intent
- free trial with explicit customer record
- recurring billing
- plan-to-quota mapping

Use Stripe webhooks for:

- `checkout.session.completed`
- `invoice.paid`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Treat webhooks as the source of truth for entitlement changes.

### Stripe Identity

Optional, not default.

Use only if you need stronger assurance than:

- verified email
- payment instrument
- MFA

Good triggers for Stripe Identity:

- unusually high requested quotas
- high fraud signals
- enterprise plans with elevated risk
- abuse incidents

### OpenTelemetry

Instrument:

- FastAPI / ASGI request traces
- SQLAlchemy database spans
- outbound calls to Stripe/Auth0/LLM providers as trace spans

### OpenFeature

Use feature flags for:

- `public_signup_enabled`
- `issue_api_keys_enabled`
- `trial_plan_enabled`
- `signup_requires_payment_method`
- `signup_requires_mfa`
- `stripe_identity_required`

This gives you safe rollout and emergency kill switches without redeploying.

## Proposed Product Flow

### Signup And Onboarding

1. User lands on marketing/app site.
2. Signup form is protected by Turnstile.
3. User creates account with Auth0 Universal Login.
4. Auth0 email verification completes.
5. Backend creates or upserts internal tenant and owner membership.
6. User starts a trial or paid plan through Stripe Checkout.
7. Stripe webhook marks tenant billing state as `trialing` or `active`.
8. User is required to enroll MFA or passkey before API key issuance.
9. User submits `database_url`.
10. Backend validates URL, does dry-run connectivity, and stores encrypted connection details.
11. Tenant reaches `active`.
12. Owner can create the first API key.

### API Key Issuance Rules

Only allow API key creation when:

- Auth0 user is authenticated
- email is verified
- MFA or passkey enrollment is complete
- tenant billing status is acceptable
- tenant status is `active`
- tenant is not suspended or under review

Optional extra rules:

- block disposable email domains
- require business email for self-serve teams above a certain quota
- require manual review for high-risk geographies or suspicious signals

## Changes Required In This Codebase

### Immediate Policy Changes

1. Set `REGISTRATION_OPEN=false` in production immediately.
2. Change the code default for `registration_open` from `True` to `False`.
3. Fail startup in `staging` and `production` unless `REGISTRATION_OPEN` is explicitly set.
4. Stop issuing API keys directly from the public register endpoint.

### API Surface Changes

Deprecate:

- `POST /api/v1/users/register` as a public anonymous endpoint

Replace with authenticated tenant-owner flows:

- `POST /api/v1/onboarding/database`
  - submit and validate DB connection after account verification
- `GET /api/v1/onboarding/status`
  - return onboarding state and blockers
- `POST /api/v1/api-keys`
  - create a new API key
- `GET /api/v1/api-keys`
  - list key metadata only
- `DELETE /api/v1/api-keys/{id}`
  - revoke a key
- `POST /api/v1/billing/webhooks/stripe`
  - webhook receiver
- `POST /api/v1/auth/sync`
  - optional endpoint to sync Auth0 subject and tenant membership

Keep:

- `GET/PUT/DELETE /v1/users/me`
- `POST /v1/users/me/rotate-key`

But eventually migrate these to tenant-aware key management endpoints.

### Data Model Additions

Add tables roughly like:

- `tenants`
  - `id`
  - `name`
  - `status`
  - `trust_level`
  - `billing_customer_id`
  - `billing_subscription_id`
  - `billing_status`
  - `plan_code`
  - `quota_profile_id`
  - `created_at`
  - `suspended_at`
- `tenant_memberships`
  - `tenant_id`
  - `auth_subject`
  - `email`
  - `role`
  - `email_verified_at`
  - `mfa_verified_at`
- `api_keys`
  - `id`
  - `tenant_id`
  - `name`
  - `prefix`
  - `key_hash`
  - `scope`
  - `created_by`
  - `last_used_at`
  - `revoked_at`
- `tenant_databases`
  - `tenant_id`
  - `database_url_enc`
  - `validation_status`
  - `last_validation_at`
  - `last_validation_error`
- `quota_profiles`
  - `code`
  - `daily_queries`
  - `rpm`
  - `max_concurrent_queries`
  - `max_api_keys`
  - `max_databases`
- `webhook_events`
  - `provider`
  - `provider_event_id`
  - `received_at`
  - `processed_at`
  - `status`
- `audit_log`
  - actor
  - tenant
  - action
  - request_id
  - outcome

### Auth Changes

For the management API:

- verify Auth0 JWTs using JWKS
- map Auth0 subject (`sub`) to internal user membership
- authorize tenant-owner-only actions for billing, database config, and API key issuance

For the MCP API:

- keep API-key auth for machine access
- move from "user" semantics to "tenant + key" semantics
- support scoped keys
  - read-only MCP access
  - admin key management
  - billing management should not use API keys

## Quota Design

Start new accounts very small. Make upgrades explicit.

### Suggested Default Quotas

`new_trial`

- `ask_database`: 25 per day
- 5 requests per minute
- 1 concurrent query
- 1 API key
- 1 registered database
- max query timeout: 15 seconds
- max rows returned: 50

`verified_paid_starter`

- `ask_database`: 200 per day
- 20 requests per minute
- 2 concurrent queries
- 3 API keys
- 1 registered database
- max query timeout: 30 seconds
- max rows returned: 100

`growth`

- `ask_database`: 1,000 per day
- 60 requests per minute
- 5 concurrent queries
- 10 API keys
- 3 registered databases

`enterprise`

- negotiated
- may require higher trust level or manual review

### Abuse Controls

Quota checks should happen before:

- LLM calls
- cold-path database connection creation
- expensive schema introspection

Also add:

- separate limits for key issuance and key rotation
- per-tenant concurrency caps
- per-tenant DB connection caps
- hard suspension switch for abuse, chargeback, or legal hold

## Production Steps Beyond Identity

### 1. Edge And Network Hardening

- Put the app behind a reverse proxy or CDN edge.
- Do not expose Uvicorn directly to the Internet.
- Restrict trusted proxy IPs. Do not use `forwarded_allow_ips="*"`.
- Add Cloudflare WAF managed rules.
- Add Cloudflare rate limiting rules for:
  - signup
  - login
  - password reset
  - API key issuance
  - API key rotation
  - MCP endpoint

### 2. Replace In-Memory / Per-Process Abuse Controls

Your current `slowapi` setup is not enough as the primary control for a horizontally scaled SaaS.

Do this:

- keep app-level limits as a secondary control
- enforce primary rate limiting at the edge
- use durable quota counters in Postgres or Redis for tenant-level quotas

### 3. Fix Product-Security Gaps Already Identified In This Repo

Before public launch, complete these fixes:

- enforce a strict read-only SQL allowlist, not a blacklist
- keep using sanitized database URLs everywhere
- ensure real DB-side query cancellation / statement timeout
- turn sample-value-to-LLM behavior into an explicit product setting
- verify all hosted production paths have green tests and type checks

### 4. Secret Management

- Move secrets out of `.env` for production.
- Store Auth0, Stripe, database, and encryption secrets in a real secret manager.
- Rotate:
  - `CREDENTIAL_ENCRYPTION_KEYS`
  - webhook signing secrets
  - any server-side API credentials
- Keep API keys hashed only. Never store raw API keys after issuance.

### 5. Webhook Safety

For Stripe and any future providers:

- verify signatures
- make handlers idempotent
- store webhook event IDs and reject duplicates
- return `2xx` quickly, then do heavy work asynchronously
- build replay tooling for failed webhook processing

### 6. Audit And Compliance Readiness

Log and retain:

- signup and verification attempts
- API key creation, rotation, revocation
- billing entitlement changes
- database credential updates
- admin actions
- tenant suspension and reactivation

Make logs immutable enough for incident review.

### 7. Observability

Add:

- request tracing
- database spans
- outbound provider spans
- structured JSON logs
- request IDs propagated everywhere
- dashboards for:
  - signup funnel
  - onboarding drop-offs
  - quota denials
  - query latency
  - DB connectivity failures
  - LLM cost by tenant

### 8. Backups And Disaster Recovery

- use managed Postgres for auth/billing/tenant state
- enable automated backups and point-in-time recovery
- test restore of:
  - auth DB
  - webhook event state
  - audit log storage
- document RPO and RTO

### 9. CI/CD And Security Gates

Require before deploy:

- unit + integration tests
- type checks
- lint
- dependency vulnerability scan
- migration check
- smoke test of hosted startup
- smoke test of signup-disabled production config

### 10. Data Governance

Decide and document:

- whether schema sample values are sent to external LLMs
- where logs are stored
- how long tenant credentials are retained
- whether deleted tenants trigger credential shredding
- what regions you support for data residency

## Rollout Plan

### Phase 0: Immediate Risk Reduction

Target: 1 to 2 days

- set `REGISTRATION_OPEN=false` in production
- close direct public registration
- stop direct port exposure where possible
- restrict proxy trust
- add edge rate limits

### Phase 1: Identity And Billing Foundation

Target: 1 to 2 weeks

- integrate Auth0 for human auth
- add verified email requirement
- add Stripe Checkout and webhooks
- add tenant + membership tables
- add onboarding state machine

### Phase 2: Controlled API Key Issuance

Target: 1 week

- replace anonymous register endpoint
- add authenticated key issuance
- add quota profiles
- add low default quotas
- add audit logging for key lifecycle

### Phase 3: Operational Hardening

Target: 1 to 2 weeks

- add OpenTelemetry
- add webhook idempotency storage
- add suspension tooling
- add support/admin dashboard basics
- add incident runbooks

### Phase 4: Higher Assurance And Enterprise

Target: later

- Auth0 Organizations
- domain verification
- SAML/SCIM
- Stripe Identity or manual review for high-risk tenants
- enterprise quota approval workflow

## Concrete Product Decisions I Recommend

If this were my SaaS, I would ship with these defaults:

- public signup allowed only through a web app, not the API
- email verification required
- MFA or passkey required before first API key
- Stripe Checkout trial or paid plan required before first API key
- no anonymous API key issuance at all
- default trial quota: 25 queries/day, 1 key, 1 database
- all high-quota requests require manual approval
- all sensitive endpoints protected at the edge and in-app

## Source Notes

The recommendations above are based on your current repository architecture plus current official documentation:

- Auth0 Verify Emails: https://auth0.com/docs/manage-users/user-accounts/verify-emails
- Auth0 MFA: https://auth0.com/docs/secure/multi-factor-authentication
- Auth0 Attack Protection: https://auth0.com/docs/secure/attack-protection
- Auth0 Organizations: https://auth0.com/docs/manage-users/organizations
- Cloudflare Turnstile: https://developers.cloudflare.com/turnstile/get-started/
- Cloudflare Rate Limiting Rules: https://developers.cloudflare.com/waf/rate-limiting-rules/
- Cloudflare Managed Rules: https://developers.cloudflare.com/waf/managed-rules/
- Stripe Subscriptions Overview: https://docs.stripe.com/billing/subscriptions/overview
- Stripe Webhooks: https://docs.stripe.com/webhooks
- Stripe Idempotent Requests: https://docs.stripe.com/api/idempotent_requests
- Stripe Identity: https://docs.stripe.com/identity
- OpenTelemetry Languages: https://opentelemetry.io/docs/languages/
- OpenTelemetry Python Zero-Code Instrumentation: https://opentelemetry.io/docs/zero-code/python/
- OpenTelemetry FastAPI Instrumentation: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
- OpenTelemetry SQLAlchemy Instrumentation: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/sqlalchemy/sqlalchemy.html
- OpenFeature Introduction: https://openfeature.dev/docs/reference/intro
- OpenFeature Python SDK: https://openfeature.dev/docs/reference/sdks/server/python/
