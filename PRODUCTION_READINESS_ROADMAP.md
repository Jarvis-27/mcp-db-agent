# Production Readiness Roadmap

Date: 2026-04-11

## Scope

This roadmap is for the product you chose:

- Hosted multi-tenant MCP SaaS
- Public self-serve signup
- Individual users first
- Email verification is sufficient for v1
- Free tier with limited usage, then paid monthly subscriptions
- Supported customer databases: PostgreSQL and MySQL
- Customer DB credentials stored encrypted in the app's auth database
- Primary user experience: sign up, verify email, connect database, receive usable MCP config, connect client, query database

This document is intentionally product- and implementation-oriented. It avoids code and focuses on the end-to-end system you need to ship.

## Executive Summary

Your biggest gap is no longer the MCP query engine. The core MCP server and tenant/auth foundations already exist. The biggest gap is that the product flow is still halfway between:

- a local developer tool
- and a self-serve SaaS

Today, the hosted path still reflects a manually approved onboarding model:

`register -> verify email -> submit database -> pending_review -> admin approve -> create API key -> use /mcp`

That is not the flow you want to launch.

Your production target should be:

`register -> verify email -> connect database -> automatic activation on free plan -> issue API key -> show client-ready MCP config -> user connects their MCP client -> query database -> upgrade to paid when free quota is exhausted`

The roadmap below is organized around making that target real, safe, and operable.

## Product Definition You Should Freeze First

These are the decisions I recommend you treat as fixed for v1.

### Product shape

- The product is a hosted remote MCP server, not primarily a local stdio tool.
- `stdio` remains supported only for development, demos, and local smoke testing.
- `/mcp` over Streamable HTTP becomes the primary product surface.
- `/api` becomes the onboarding, billing, and account-management surface.

### Activation policy

- Email verification is enough to create a free-tier tenant in v1.
- Manual admin approval should not be on the happy path.
- Admin actions should remain available for support, abuse response, suspension, and account closure.

### Database connection policy

- Customers must connect a PostgreSQL or MySQL database before they can use the product meaningfully.
- API keys should be issued only after:
  - email verification succeeds
  - database connectivity check succeeds
  - tenant is placed on a valid entitlement plan

This prevents you from creating lots of active API keys for users who never complete setup.

### Billing policy

- Free tier should be low-friction and not require payment details up front.
- Paid monthly subscription unlocks higher quotas and support once the user has validated product value.
- Stripe should be the billing source of truth.

### Client support policy

- Your product promise is "works with major MCP clients", but your rollout should use support tiers:
  - Tier 1 at launch: VS Code, Cursor, ChatGPT developer mode, generic HTTP MCP clients
  - Tier 2 after launch hardening: any client whose remote auth or config UX is less stable

This matters because remote MCP auth expectations differ by client, and some modern clients are converging on OAuth for remote HTTP MCP.

## Current Repo State vs Target Product

### What already exists

- Hosted ASGI app with `/api` and `/mcp`
- Tenant-backed auth database model
- Email verification and owner-session flows
- API key issuance and rotation
- MCP API key middleware
- Query quota counter
- Multi-tenant pipeline construction
- URL validation and SSRF defenses
- Core `ask_database` flow with safety validation, execution, retries, caching, and query logging

### What is still product-incomplete

- Mandatory manual approval is still in the hosted happy path
- No real customer-facing setup UI
- No billing integration
- No generated client-ready setup experience
- No production-grade email provider integration beyond SMTP/logging
- No production observability stack
- No deployment opinion for stable outbound DB connectivity
- MySQL is not fully production-complete in packaging and validation

## The Architectural Direction I Recommend

Keep one deployable application for v1, but separate concerns clearly inside it.

### Application surfaces

- `Web/API app`
  - signup
  - verification
  - database setup
  - billing
  - owner account management
  - API key management
  - generated client setup pages
  - admin/support UI
- `MCP endpoint`
  - `/mcp`
  - read-only data tooling
  - tenant-scoped auth and quota enforcement

### Data systems

- `Primary app database`
  - PostgreSQL only
  - stores tenants, memberships, sessions, billing state, encrypted customer DB credentials, API keys, usage counters, audit events, query history
- `Customer databases`
  - external PostgreSQL or MySQL instances
  - never mixed with your own app database

### Recommended runtime pattern for v1

- One web service
- One managed PostgreSQL database for your app
- Optional Redis later if you need shared rate limits, session coordination, or job queueing across replicas

Do not introduce extra infrastructure too early if a single service can carry the first production release.

## The Core Product Flow You Should Implement

This should become your single golden path.

### 1. Signup

- User enters email
- Service creates tenant in a pre-activation state
- Verification email is sent

### 2. Email verification

- User clicks verification link
- Tenant owner session is created
- User lands in a setup flow, not a raw API response flow

### 3. Database connection setup

- User enters database URL
- Service validates scheme, hostname, and TLS requirements
- Service performs a dry-run connectivity test
- Service stores the credential encrypted

### 4. Free-tier activation

- If email is verified and DB validation passes, tenant becomes active on free plan automatically
- The product provisions:
  - plan
  - daily quota
  - usage counters
  - default active database
  - first API key or one-click API key creation in setup UI

### 5. Client setup page

- User sees:
  - MCP endpoint URL
  - API key
  - client-specific config blocks
  - "test your connection" instructions
  - quota information

### 6. Usage

- User connects Claude/Cursor/VS Code/ChatGPT/generic client
- User queries their own database via `/mcp`
- Usage counts against tenant entitlements

### 7. Upgrade path

- When free quota is near exhaustion or exhausted:
  - show upgrade prompts in dashboard
  - send email nudges
  - disable additional `ask_database` calls when hard limit is reached
  - leave account and config intact for later conversion

## Recommended Domain Model Changes

The current data model is close, but it still mixes onboarding and activation concerns. For SaaS, split them more clearly.

### Keep onboarding state narrow

Use onboarding state only for setup progression:

- `pending_email_verification`
- `pending_db_connection`
- `setup_complete`

Remove `pending_review` from the normal self-serve path. Keep support-driven review as a separate risk or support flag, not as the default onboarding state.

### Add separate account state

Use account state for whether a tenant is allowed to use the product:

- `active`
- `restricted`
- `suspended`
- `closed`

### Add separate billing state

Use billing state for entitlement decisions:

- `free`
- `trialing`
- `active_paid`
- `past_due`
- `canceled`

This separation avoids trying to represent everything through one status field.

### Add plan and entitlement data

You need an explicit plan model, even if you start with only two plans.

Recommended entities:

- `plans`
- `tenant_subscriptions`
- `tenant_entitlements`
- `usage_events` or `usage_counters`
- `audit_events`

### Recommended plan structure for v1

Keep it simple:

- `free`
  - 1 active database
  - 1 API key
  - low daily `ask_database` cap
  - low result/history retention if needed
- `pro`
  - higher daily cap
  - more API keys
  - better support
  - optional higher timeout / larger result limits later

Do not over-design multiple plans before you have pricing signal.

## Quota And Entitlement Recommendations

You asked for guidance here. My recommendation is:

### Meter the expensive thing

Count `ask_database` as the primary billable/limited unit because it triggers:

- LLM usage
- SQL generation/correction
- DB execution
- logging
- result formatting

Do not make `list_tables` or `describe_schema` your primary monetization unit. They matter for abuse control, but they are not your core cost driver in the same way.

### Use a two-layer quota model

Layer 1: product quota

- per-tenant daily `ask_database` hard cap
- determined by plan

Layer 2: abuse-control limits

- per-IP signup rate limit
- per-IP and per-API-key request burst limits
- per-tenant concurrent query limits

### Recommended initial quotas

Use these as a starting point, then adjust once you observe cost and conversion.

- `free`
  - 25 `ask_database` requests per day
  - 1 API key
  - 1 active database
- `pro`
  - 500 `ask_database` requests per day
  - 5 API keys
  - 2 active databases only if you really need it

If your LLM cost is high, start lower, not higher. You can always loosen quotas later. It is much harder to take quota away after launch.

### Add warnings before hard failure

- Warn at 50%, 80%, and 100% of daily quota
- Return a structured quota response from MCP calls
- Make upgrade action obvious from the dashboard

### Keep entitlements server-side only

- Do not trust client-side plan metadata
- Every MCP request should resolve entitlements server-side

## Identity And Authentication Roadmap

### v1 recommendation

Stay with your own email verification and owner session flow for now, because you explicitly want to delay Auth0.

That is acceptable for v1 if you keep the scope narrow:

- owner login by emailed link
- email verification required
- no team members yet
- no broad delegated permissions model yet

### What must change in the current model

- owner sessions should back the setup dashboard
- API keys should authenticate MCP access
- owner-session auth should never be used directly for `/mcp`

### What you should add later

Auth0 becomes a v1.1 or v2 concern when you need:

- stronger login assurance
- MFA
- account recovery
- multi-user workspaces
- SSO
- OAuth-based MCP auth compatibility

Auth0's own docs explicitly note that verified email is not strong identity proof by itself. That is fine for your v1 product decision, but it should remain a conscious limitation, not an accidental one.

## Billing Roadmap

Stripe is the right choice for this product.

### Recommended billing architecture

Use:

- Stripe Checkout for subscription purchase
- Stripe Customer Portal for self-serve plan and billing management
- Stripe webhooks as the source of truth for subscription status

### Why this is the right v1 approach

- minimal custom billing UI
- fast to launch
- operationally mature
- easy transition from free to paid
- customer self-service is already handled

### Billing states to support at launch

- `free`
- `trialing` if you decide to offer a paid trial
- `active_paid`
- `past_due`
- `canceled`

### Stripe events you should treat as authoritative

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.trial_will_end` if you use trials

### Billing policy recommendation

For your first launch:

- allow free plan without card
- upgrade via Stripe Checkout when quota pressure appears
- use Customer Portal for self-serve billing changes

### Access control recommendation

Billing should affect entitlements, not destroy setup.

When payment fails or subscription is canceled:

- reduce or suspend paid entitlements
- keep account metadata
- keep generated setup information
- do not erase customer DB configuration

This makes reactivation much easier.

## MCP Authentication Strategy

This is a crucial product decision because you said you want support across major MCP clients.

### The current repo

Right now, your hosted `/mcp` path is API-key protected with `X-API-Key` or `Authorization: Bearer`.

That is enough for some clients and for direct integrations, but it is not the complete long-term answer for broad remote MCP compatibility.

### The emerging standard

Modern remote MCP clients are converging on:

- Streamable HTTP
- OAuth for authenticated remote servers

This matters because:

- Cursor documents OAuth for remote SSE and Streamable HTTP MCP
- ChatGPT developer mode supports OAuth and no-auth for remote MCP
- the MCP specification recommends OAuth-based authorization for HTTP transports

### Recommendation

Treat API keys as your v1 credential for your own dashboard and for clients that can directly send bearer tokens.

But if "all major clients" is a launch requirement, plan OAuth support early instead of bolting it on later.

### Practical rollout recommendation

Phase A:

- launch with bearer API keys where supported
- generate client-specific config templates
- make setup page the primary UX

Phase B:

- add OAuth 2.1 support for remote MCP
- keep API keys for service-to-service and owner-level automation

### Design principle

Do not design the setup UI around one auth scheme only. Build it so the account can expose:

- API key auth
- OAuth auth
- client-specific instructions per transport/auth combination

## Client Setup Experience Roadmap

This is one of the highest leverage product features you can build.

### The setup page must generate

- endpoint URL
- auth method
- raw API key or OAuth connect action
- client-specific config for:
  - VS Code
  - Cursor
  - ChatGPT developer mode
  - generic remote MCP client

### What the page should also include

- test connection step
- example prompts
- quota and plan details
- last successful query timestamp
- active database summary

### Why this matters

Most self-serve SaaS users will not abandon because SQL is hard. They will abandon because integration friction is high.

Your setup page is part of the product, not an afterthought.

## Database Connectivity And Safety Roadmap

This is one of the most sensitive parts of the system because your service connects outward to arbitrary customer databases.

### What the repo already does well

- scheme allowlist
- hostname resolution
- blocked private and metadata ranges
- DNS rebinding defense via re-resolution
- SQLite disallowed by default in hosted mode

### What you should add before production

#### 1. Require TLS for both supported engines

Current code enforces PostgreSQL SSL mode in non-development mode. Extend that discipline to MySQL as well.

Recommended production policy:

- PostgreSQL: require secure SSL mode
- MySQL: require TLS parameters and verify your chosen driver behavior

#### 2. Complete MySQL production support

The repo already recognizes MySQL URLs and dialect handling in parts of the code, but packaging and production support are not yet complete enough to market confidently.

You need:

- explicit MySQL dependency support in the app package set
- integration tests against a real MySQL service
- docs that clearly state supported MySQL versions/drivers
- dialect-specific query and schema validation review

#### 3. Tighten network policy

Recommended production policy:

- allow only PostgreSQL and MySQL connection schemes
- deny SQLite completely in production
- keep private, loopback, link-local, and metadata IP blocks
- add any provider-specific internal ranges you discover to extra blocked CIDRs

#### 4. Add connection lifecycle controls

- connection test on setup
- connection test on credential update
- periodic health check for active database configuration
- clear customer-facing error when their DB credentials become invalid

#### 5. Make outbound IP strategy explicit

Many customer databases are behind IP allowlists. Your hosting platform choice must account for that.

If you do not solve this early, onboarding will break for otherwise valid customers.

## Security Roadmap

This should be treated as launch scope, not "later."

### Minimum production rules

- no SQLite in production
- no customer DB connections to private or local address space
- TLS required for customer DB connections
- encrypted customer credentials at rest
- rotation-capable encryption keys
- short-lived owner sessions
- hashed API keys only
- structured audit logs for account actions

### Abuse controls

Because signup is public, add:

- IP-based signup rate limiting
- email resend throttling
- owner login-link throttling
- API key creation/rotation throttling
- per-tenant MCP request burst control

### Add a support/risk flag system

Instead of default manual approval, add optional risk controls:

- `manual_review_required`
- `high_risk`
- `billing_hold`
- `abuse_hold`

Then keep self-serve open by default, but retain the ability to stop specific tenants.

### Recommendation on bot protection

Even if you defer Auth0, I recommend adding CAPTCHA or Turnstile on public signup before launch. Open signup plus LLM-backed queries is otherwise an easy abuse target.

## Email Delivery Roadmap

You said SMTP is part of your baseline, but I recommend not relying solely on direct SMTP for production.

### Why

- transactional email APIs are usually easier to operate
- Railway specifically documents SMTP restrictions on lower plans and recommends transactional email providers over HTTPS APIs
- email delivery analytics, retries, and reputation management are much better with dedicated providers

### Recommendation

Keep your email abstraction, but support:

- Resend, Postmark, or Mailgun via HTTPS API
- SMTP only as a fallback or alternate transport

### Required production emails

- email verification
- owner login link
- quota warnings
- payment failed
- upgrade nudges
- database connection broken

## Admin And Support Surface

Even if onboarding is self-serve, you still need an internal control plane.

### v1 admin UI needs

- search tenant by email or tenant ID
- see onboarding state, billing state, and account state
- see active database metadata
- revoke or rotate API keys
- suspend or close tenant
- inspect recent query history
- inspect recent errors and quota usage

### Why this matters

Without this, every support issue becomes a database query or direct production intervention.

## Observability And Operations Roadmap

You asked for:

- SMTP or equivalent email delivery
- admin UI
- metrics
- tracing
- error alerts

The right way to do this is with OpenTelemetry-first instrumentation.

### Recommendation

Instrument the service with OpenTelemetry and export OTLP data to a managed backend.

Good v1 path:

- OpenTelemetry in app
- OTLP exporter
- one managed observability backend for traces, metrics, and logs if possible
- optionally separate exception tracking if you prefer a specialized tool

### What to instrument

- FastAPI/Starlette requests
- MCP tool calls
- SQLAlchemy calls for your auth DB
- outbound customer DB connections where possible
- outbound LLM requests
- Stripe API calls
- email provider calls

### Minimum metrics you should have

- signup attempts and success rate
- email verification completion rate
- database connection test success rate
- free-to-paid conversion rate
- MCP request count by tenant and tool
- `ask_database` latency
- self-correction retry count
- quota exhaustion count
- LLM provider failure rate
- Stripe webhook failure rate
- owner login-link success rate

### Minimum alerts you should have

- app unavailable
- auth DB unavailable
- error rate spike
- webhook failures
- email delivery failures
- unusual signup spike
- unusual quota burn spike
- sustained external DB connection failures

### Logging requirements

- keep structured logs
- add tenant ID and request ID to every relevant event
- never log raw DB credentials or raw API keys

## Deployment Platform Recommendation

Your candidate platforms are:

- VPS
- Render
- Fly.io
- Railway

### The real decision criterion

For this product, the most important infrastructure question is not "which platform is easiest?"

It is:

- how reliable is outbound connectivity to arbitrary customer databases?
- can customers allowlist your outbound IPs?
- how quickly can you operate backups, health checks, and secrets?

### Platform recommendation

If customer DB IP allowlisting is likely to matter early, prefer Fly.io first.

Why:

- official support for egress IP allocation
- strong fit for Dockerized apps
- good control over networking

If speed of shipping matters more than network rigor, Railway is a strong second choice.

Why:

- very fast path to deploy a FastAPI app
- static outbound IPs available on Pro
- simple operational model

Important caveat:

- Railway docs note static outbound IPs may be shared
- Railway also recommends transactional email over HTTPS APIs, with SMTP constraints on lower plans

Render is also workable, but it is weaker if customers need dedicated allowlistable outbound IPs.

Why:

- outbound traffic uses region-specific shared ranges
- dedicated static outbound IP generally requires extra measures such as QuotaGuard

### My recommendation

Choose one of these:

1. `Fly.io` if networking and allowlisting are important from day one
2. `Railway` if speed to first production is more important and you can tolerate some networking constraints

I would not start on a plain VPS unless you explicitly want to own more of the ops burden yourself.

## Production Infrastructure Minimum

Before launch, you should have:

- 1 production web service
- 1 staging web service
- 1 production managed PostgreSQL database for app/auth data
- 1 staging managed PostgreSQL database
- secrets management in the platform
- automated deploys from main/release branch
- health checks
- daily backups and restore procedure

Optional but valuable:

- Redis for distributed rate limiting and caching
- background job worker for non-request-bound tasks

## Background Jobs You Should Plan For

You can launch without a big job system, but these tasks will quickly want async execution:

- email sending retries
- Stripe webhook retry handling
- periodic quota resets if you move away from lazy reset logic
- database health checks
- stale session cleanup
- analytics rollups

If you stay single-service initially, keep the architecture job-ready so you can add a worker later without a rewrite.

## Product UX Roadmap

Do not treat the product as "API first only." For this SaaS, the web UX is critical.

### The minimum user-facing pages

- signup
- verify email success
- connect database
- setup complete
- dashboard
- usage and quota
- billing
- API keys
- generated client configs
- support/help

### The dashboard should answer these questions immediately

- Is my account active?
- Is my database connected?
- What is my MCP endpoint?
- What is my API key or auth method?
- How much quota do I have left today?
- How do I connect my chosen client?
- Why is my connection failing if something is broken?

## Repo-Level Changes You Should Make Early

These changes are foundational and should happen before broader product work.

### 1. Reposition the product in documentation

- make hosted SaaS the primary README path
- keep stdio/local mode as developer-only documentation
- add a hosted quickstart

### 2. Refactor the state model

- remove `pending_review` from the standard self-serve critical path
- split onboarding, billing, and account states

### 3. Finish MySQL support

- add missing dependency support
- add integration tests
- update docs

### 4. Make plan/entitlement checks first-class

- not just query quota
- also API key limits, DB limits, and feature flags

### 5. Make `/mcp` product-ready

- auth
- quotas
- billing-aware gating
- client-ready setup guidance

## Recommended Implementation Order

If you want the shortest path to a real production launch, build in this order.

### Phase 1: Reframe the current backend for self-serve SaaS

- freeze product states and plan model
- remove manual approval from happy path
- define free and paid entitlements
- define billing and account states
- define automatic activation rules

Exit criteria:

- you can describe the lifecycle in one sentence without exceptions

### Phase 2: Finish the core self-serve onboarding path

- signup
- email verification
- owner session
- database connection UI and backend flow
- automatic free-tier activation
- API key issuance at the right moment

Exit criteria:

- a user can become active without human intervention

### Phase 3: Build the setup dashboard and generated client config flow

- dashboard
- API keys page
- generated client configs
- test-connection guidance
- usage/quota display

Exit criteria:

- a non-technical user can connect one supported client with no manual doc reading

### Phase 4: Add billing

- Stripe Checkout
- webhooks
- Customer Portal
- plan transitions
- quota changes on billing state change

Exit criteria:

- free user can upgrade to paid and see entitlements update automatically

### Phase 5: Security hardening

- TLS enforcement
- abuse controls
- bot protection
- audit logging
- support risk flags
- production secret rotation procedures

Exit criteria:

- you have a written abuse and incident response policy for common events

### Phase 6: Observability and admin operations

- OpenTelemetry
- dashboards
- alerts
- admin UI
- support tooling

Exit criteria:

- you can diagnose signup, billing, email, DB, and MCP failures without direct DB shell access

### Phase 7: Deployment and staging

- choose platform
- provision staging and production
- backups
- health checks
- deploy workflow
- rollback procedure

Exit criteria:

- staging mirrors production shape

### Phase 8: Launch hardening

- end-to-end smoke tests
- billing tests
- DB connection matrix tests
- client setup validation
- runbooks

Exit criteria:

- one new user can complete the full path end to end with no internal intervention

## Testing Strategy Roadmap

You should expand testing around the product edges, not only the SQL engine.

### Add automated tests for

- signup to activation happy path
- free quota exhaustion
- billing upgrade and downgrade
- webhook idempotency
- email verification token lifecycle
- owner login link lifecycle
- API key creation and revocation
- PostgreSQL connectivity validation
- MySQL connectivity validation
- MCP auth rejection and acceptance paths
- suspended account behavior
- client setup payload generation

### Add staging smoke tests for

- real email delivery
- real Stripe test mode
- real PostgreSQL target
- real MySQL target
- remote MCP request flow

## Launch Criteria

Do not call the product production-ready until all of these are true.

- self-serve user can activate without manual approval
- free quota is enforced cleanly
- paid plan upgrade works through Stripe
- database setup works for PostgreSQL and MySQL
- generated setup instructions work for your tier-1 clients
- you can suspend abusive tenants
- backups and restore are proven
- alerts are live
- admin UI exists
- staging environment exists
- docs match actual behavior

## Open Questions You Still Need To Answer

These do not block planning, but they do need product decisions before implementation is complete.

### 1. Should free tier require a connected database before API key issuance?

I recommend yes.

### 2. Will free tier require a card after a period of time?

I recommend no for the initial launch. Let usage pressure drive upgrade instead.

### 3. Is OAuth for remote MCP a launch requirement or a fast follow?

If "all major clients" is literal for launch, treat it as launch scope.

### 4. What exact daily quota and monthly price will you launch with?

You need this before implementing Stripe products and plan entitlements.

### 5. Which single hosting platform will you commit to first?

Do not build platform-specific assumptions for three providers at once.

## Final Recommendation

If you want the highest-probability path to a real launch, do this:

1. Convert the hosted backend from manual-review onboarding to true self-serve activation.
2. Make the setup dashboard and generated client configs a first-class product feature.
3. Add Stripe billing with free-to-paid plan transitions.
4. Harden outbound database connectivity, MySQL support, and security controls.
5. Choose a hosting platform based primarily on outbound IP strategy, not just developer convenience.
6. Ship with a narrow but polished support tier for remote MCP clients.

That sequence gets you to a real SaaS.

## References

These sources were used to verify current ecosystem recommendations and platform/client behavior.

- MCP transports: https://modelcontextprotocol.io/legacy/concepts/transports
- MCP authorization extensions overview: https://modelcontextprotocol.io/extensions/auth/overview
- ChatGPT developer mode and remote MCP support: https://platform.openai.com/docs/developer-mode
- OpenAI remote MCP guide: https://platform.openai.com/docs/guides/tools-remote-mcp
- Cursor MCP docs: https://docs.cursor.com/context/model-context-protocol
- VS Code MCP docs: https://code.visualstudio.com/docs/copilot/customization/mcp-servers
- Auth0 verified email usage guidance: https://auth0.com/docs/manage-users/user-accounts/user-profiles/verified-email-usage
- Auth0 MFA docs: https://auth0.com/docs/mfa/guides/customize-mfa-universal-login
- Stripe customer portal: https://docs.stripe.com/billing/subscriptions/integrating-customer-portal
- Stripe subscription webhooks: https://docs.stripe.com/billing/subscriptions/webhooks
- Stripe limiting one subscription and customer-portal redirect pattern: https://docs.stripe.com/payments/checkout/limit-subscriptions
- OpenTelemetry Python auto-instrumentation example: https://opentelemetry.io/docs/zero-code/python/example/
- Render FastAPI production deployment best practices: https://render.com/articles/fastapi-production-deployment-best-practices
- Render Postgres backups: https://render.com/docs/postgresql-backups
- Fly.io egress IP docs: https://fly.io/docs/flyctl/machine-egress-ip-allocate/
- Railway FastAPI deployment: https://docs.railway.com/guides/fastapi
- Railway static outbound IPs: https://docs.railway.com/networking/static-outbound-ips
- Railway outbound networking and SMTP guidance: https://docs.railway.com/networking/outbound-networking
