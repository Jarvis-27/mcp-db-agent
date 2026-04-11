# Frontend Implementation Checklist

Date: 2026-04-11

This checklist is the dedicated frontend counterpart to [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md).

It is written for the product direction already frozen in the repo:

- Hosted multi-tenant MCP SaaS
- Public self-serve signup
- Authenticated customer web app
- Public pricing page
- Admin UI included in the same frontend surface
- SaaS-only web experience (not a UI for local stdio mode)

This document assumes the backend is completed first, or at least completed far enough that the frontend can be built against stable contracts.

Do not start frontend implementation until the required backend prerequisites for the corresponding phase are complete.

---

## Frontend Product Contract

The frontend must support three product surfaces:

1. **Public surface**
   - landing shell or pending homepage
   - pricing page
   - login entry points
   - signup flow
   - verification and login-link handling

2. **Customer authenticated app**
   - setup wizard
   - dashboard
   - usage and quota
   - API key management
   - database settings
   - client setup/config pages
   - billing pages
   - support/help pages

3. **Admin/support app**
   - tenant search
   - tenant detail view
   - support actions
   - query and setup inspection

The frontend is not a replacement for `/mcp`.
It is the product layer that lets a user reach first value without touching raw API endpoints.

---

## Recommended Frontend Placement

Create the frontend inside this repo at:

- `frontend/`

Recommended stack:

- Next.js
- TypeScript
- App Router
- Tailwind CSS
- component primitives via shadcn/ui or equivalent
- zod for client-side contract validation
- TanStack Query for async state and caching

Recommended deployment shape:

- separate frontend deployment from the Python app is acceptable later
- for v1, keep it in the same repo even if deployed separately

---

## Backend Prerequisite Gate

Before starting frontend implementation, validate backend readiness.

### Minimum backend phases that should be complete first

From `IMPLEMENTATION_CHECKLIST.md`:

- **Phase 3** — Plan Enforcement In MCP And API Surfaces
- **Phase 4** — Customer Setup Payloads And Client Config Generation
- **Phase 5** — enough API support to back the browser journey
- **Phase 6** — if billing pages are expected to be fully functional at launch
- **Phase 11** — if admin UI is expected to be fully functional at launch

### Frontend-critical backend capabilities that must exist before UI build begins

- stable owner-session auth flow
- stable onboarding status endpoint
- database submission endpoint
- API key create/list/revoke endpoints
- plan/quota-aware usage data
- setup config generation endpoint
- query history endpoint for the dashboard
- dashboard summary endpoint or equivalent contract
- admin data and support-action endpoints
- CORS/session/auth design frozen for browser usage

If these are not ready, finish backend contracts first. Do not paper over backend uncertainty in the frontend.

---

## Current Repo Map Relevant To Frontend

These are the main current backend files the frontend will depend on:

- `src/api/app.py`
  - owner-session flows
  - onboarding endpoints
  - API key endpoints
  - admin endpoints
- `src/api/schemas.py`
  - request/response contracts the frontend must consume
- `src/auth/onboarding.py`
  - onboarding state vocabulary and next-step meanings
- `src/auth/user_store.py`
  - tenant/account/plan/billing concepts reflected in UI
- `src/entitlements/*`
  - plan limits and warning semantics
- `IMPLEMENTATION_CHECKLIST.md`
  - backend implementation order and dependencies
- `PRODUCTION_READINESS_ROADMAP.md`
  - product behavior and launch flow

What is missing today:

- no `frontend/`
- no browser-oriented session model or BFF layer
- no customer dashboard endpoints defined as one stable summary contract
- no dedicated usage endpoint for quota UI
- no setup/config UI
- no admin UI
- no public pricing page

---

## Global Rules For Every Frontend Phase

- Every new page requires:
  - route definition
  - loading state
  - empty state when relevant
  - error state
  - mobile layout sanity check
  - accessibility review for keyboard and screen reader basics

- Every backend dependency must be consumed through:
  - a typed API client contract
  - runtime validation for critical payloads
  - central error handling

- Every authenticated route requires:
  - route guard behavior defined
  - redirect behavior defined
  - unauthorized state defined
  - expired-session recovery path defined

- Every mutation flow requires:
  - optimistic vs non-optimistic decision
  - success notification behavior
  - recoverable failure UI
  - duplicate-submit protection

- Every sensitive reveal flow requires:
  - explicit user confirmation if needed
  - single-reveal messaging where applicable
  - copy-to-clipboard UX
  - post-reveal warning text

- Every frontend phase ends with:
  - automated validation
  - manual validation
  - docs validation

Core validation commands for frontend phases:

- `pnpm install` or chosen package manager install command
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- `pnpm build`

If you choose a different package manager, freeze it once and use it consistently.

---

## Phase 0: Freeze Frontend Contracts And Architecture

Goal: remove ambiguity before any UI scaffolding starts.

### Decisions to freeze

- [ ] frontend framework
  - recommended: Next.js with App Router
- [ ] package manager
  - recommended: pnpm
- [ ] styling system
  - recommended: Tailwind + design tokens + reusable primitives
- [ ] data layer
  - recommended: TanStack Query + server actions only where it clearly helps
- [ ] validation strategy
  - recommended: zod for form validation and contract parsing
- [ ] auth model between browser and backend
  - recommended: frontend BFF session via secure HTTP-only cookie
- [ ] deployment model
  - same repo, frontend as separate build artifact if needed
- [ ] route grouping strategy
  - public routes
  - customer app routes
  - admin routes
- [ ] UI shell structure
  - separate shell for public pages
  - separate shell for customer app
  - separate shell or gated area for admin
- [ ] support for SaaS only
  - no UI work for local stdio mode

### Required outputs

- [ ] route map frozen
- [ ] page inventory frozen
- [ ] session/cookie strategy frozen
- [ ] backend API dependency map frozen
- [ ] state vocabulary aligned with backend:
  - onboarding status
  - account status
  - billing status
  - plan code
  - blockers
- [ ] role model frozen:
  - owner user flow
  - admin/support flow

### Recommended route inventory

#### Public
- [ ] `/`
- [ ] `/pricing`
- [ ] `/signup`
- [ ] `/login`
- [ ] `/auth/verify`
- [ ] `/auth/login`

#### Customer app
- [ ] `/app`
- [ ] `/app/setup/database`
- [ ] `/app/setup/api-key`
- [ ] `/app/setup/clients`
- [ ] `/app/dashboard`
- [ ] `/app/usage`
- [ ] `/app/api-keys`
- [ ] `/app/settings/database`
- [ ] `/app/billing`
- [ ] `/app/help`

#### Admin
- [ ] `/admin`
- [ ] `/admin/tenants`
- [ ] `/admin/tenants/[tenantId]`
- [ ] `/admin/tenants/[tenantId]/query-history`
- [ ] `/admin/tenants/[tenantId]/keys`
- [ ] `/admin/tenants/[tenantId]/setup`

### Validation

Automated:

- [ ] route inventory documented in frontend ADR or README
- [ ] backend dependency matrix documented

Manual:

- [ ] every launch-critical user task maps to exactly one page or flow
- [ ] every page has a clear owner, purpose, and backend dependency list

Do not continue until:

- frontend architecture is frozen
- browser auth/session approach is frozen
- page inventory is frozen

---

## Phase 1: Frontend Scaffold And Application Foundation

Goal: create a production-ready frontend foundation before building product pages.

### New top-level directory

- `frontend/`

### Recommended initial structure

- `frontend/app/`
- `frontend/components/`
- `frontend/features/`
- `frontend/lib/`
- `frontend/hooks/`
- `frontend/styles/`
- `frontend/public/`
- `frontend/tests/`
- `frontend/types/`

### Recommended detailed structure

- `frontend/app/(public)/`
- `frontend/app/(app)/`
- `frontend/app/(admin)/`
- `frontend/app/api/`
  - BFF endpoints or proxy handlers
- `frontend/components/ui/`
- `frontend/components/layout/`
- `frontend/components/feedback/`
- `frontend/features/auth/`
- `frontend/features/onboarding/`
- `frontend/features/dashboard/`
- `frontend/features/usage/`
- `frontend/features/api-keys/`
- `frontend/features/setup-config/`
- `frontend/features/billing/`
- `frontend/features/admin/`
- `frontend/lib/api/`
- `frontend/lib/auth/`
- `frontend/lib/contracts/`
- `frontend/lib/utils/`

### Checklist

- [ ] initialize Next.js app with TypeScript
- [ ] set up Tailwind
- [ ] add lint, typecheck, test, and build scripts
- [ ] establish design tokens
- [ ] create base layout primitives
- [ ] create app shell and public shell
- [ ] create typed API client layer
- [ ] create shared error model for API consumption
- [ ] create reusable form system
- [ ] create global toast/notification system
- [ ] create route guard utilities
- [ ] create loading and error boundaries
- [ ] set up env handling for backend API base URL
- [ ] define contract parsing for critical backend responses
- [ ] define admin-role gating hooks and helpers

### Validation

Automated:

- [ ] `pnpm lint`
- [ ] `pnpm typecheck`
- [ ] `pnpm test`
- [ ] `pnpm build`

Manual:

- [ ] shells render correctly with placeholder routes
- [ ] route groups are cleanly separated
- [ ] no page contains direct hardcoded backend fetch logic without shared client helpers

Do not continue until:

- the frontend foundation is stable
- shared client and shell patterns are in place

---

## Phase 2: Public Marketing Surface And Pricing Page

Goal: build the public-facing entry surface for the SaaS.

### Pages to build

- `/(public)/page`
- `/(public)/pricing/page`
- optional:
  - waitlist or contact CTA blocks
  - support/help teaser

### Checklist

- [ ] create a minimal but production-quality public homepage
- [ ] communicate the product clearly:
  - what it is
  - who it is for
  - supported databases
  - supported MCP clients
- [ ] add pricing page for:
  - free plan
  - pro plan
- [ ] show launch pricing clearly aligned with backend plan definitions
- [ ] show CTA paths:
  - signup
  - login
- [ ] add FAQ blocks for common setup concerns:
  - do I need to host anything?
  - what DBs are supported?
  - is my data safe?
  - what clients are supported?
- [ ] add lightweight trust/status messaging without overpromising unsupported features
- [ ] ensure pricing content aligns with repo roadmap and frozen quotas

### Validation

Automated:

- [ ] visual regression or snapshot coverage for core public sections
- [ ] content sanity tests if using CMS-like config objects

Manual:

- [ ] free/pro quotas match backend entitlements exactly
- [ ] public claims do not advertise features that backend does not yet support
- [ ] mobile layout is readable and conversion path is obvious

Do not continue until:

- the public entry point is clear
- pricing matches product reality

---

## Phase 3: Auth Entry Points And Browser Session Architecture

Goal: make browser authentication coherent and safe.

### Backend dependencies

- owner login-link flow
- verification flow
- stable owner-session issuance behavior
- frontend-compatible redirect/callback semantics

### Recommended auth approach

Do not expose raw backend owner-session tokens directly to the browser app logic.
Use the frontend as a BFF layer:

- frontend route handlers receive verification/login tokens
- frontend exchanges them with backend
- frontend stores secure HTTP-only session cookie
- frontend server-side code calls backend with owner-session header

### Pages and handlers to build

- `/signup`
- `/login`
- `/auth/verify`
- `/auth/login`
- optional route handlers under `frontend/app/api/auth/*`

### Checklist

- [ ] build signup form
- [ ] build login form requesting login link
- [ ] build verification callback flow
- [ ] build login-link callback flow
- [ ] store browser session in secure HTTP-only cookie
- [ ] implement logout flow
- [ ] implement expired-session handling
- [ ] define post-auth redirect logic based on onboarding/account state
- [ ] implement route guards for:
  - anonymous-only routes
  - authenticated app routes
  - admin routes
- [ ] handle blocked states clearly:
  - suspended
  - restricted
  - closed

### UX requirements

- [ ] verification success page should not dump raw JSON
- [ ] login callback should recover gracefully on invalid or expired tokens
- [ ] signup/login success should explain next steps in plain language
- [ ] user should always know whether they need to verify email, connect DB, create key, or contact support

### Validation

Automated:

- [ ] route-guard tests
- [ ] cookie/session utility tests
- [ ] invalid/expired token flow tests

Manual:

- [ ] signup → verification → authenticated redirect works from browser
- [ ] login-link flow works from browser
- [ ] logout clears session and protected routes redirect properly

Do not continue until:

- browser auth works end to end
- session handling is stable

---

## Phase 4: Onboarding Wizard

Goal: build the full self-serve setup path in the browser.

### Pages to build

- `/app/setup/database`
- `/app/setup/api-key`
- `/app/setup/clients`

### Wizard flow

- owner arrives after verification or login
- onboarding status is loaded
- if DB not connected → go to database step
- after successful DB connection → go to API key step
- after first key creation → go to client config/setup step
- after setup completion → route to dashboard

### Checklist

- [ ] build onboarding state loader and redirect logic
- [ ] build database connection form
- [ ] include DB connection guidance:
  - PostgreSQL format
  - MySQL format
  - security/TLS reminders
- [ ] support clear validation errors for DB submission failures
- [ ] decide whether DB connection test is inline or submit-based
- [ ] show activation success state when free plan is activated
- [ ] build first API key creation page
- [ ] implement one-time reveal UX for API key
- [ ] add copy-to-clipboard affordances
- [ ] add explicit warning that the raw key is only shown once
- [ ] build client setup handoff page after first key creation
- [ ] handle re-entry if the user refreshes mid-wizard
- [ ] handle partial progress states cleanly

### UX requirements

- [ ] wizard must feel deterministic, not like a pile of forms
- [ ] every step must explain why it exists
- [ ] all blockers should map to backend state cleanly
- [ ] setup must never require Postman or manual API inspection

### Validation

Automated:

- [ ] onboarding state transition tests
- [ ] form validation tests
- [ ] first API key reveal flow tests

Manual:

- [ ] new user can complete setup from browser only
- [ ] bad DB credentials show actionable errors
- [ ] refresh during setup preserves or safely reconstructs progress

Do not continue until:

- the browser setup path reaches first value cleanly

---

## Phase 5: Client Setup And Generated Configuration Pages

Goal: turn setup into a product feature instead of a docs scavenger hunt.

### Backend dependencies

- setup payload endpoint
- client-specific generated config payloads
- quota summary data
- auth guidance from backend

### Pages to build

- `/app/setup/clients`
- optional nested tabs or subroutes:
  - Cursor
  - VS Code
  - ChatGPT developer mode
  - generic HTTP MCP

### Checklist

- [ ] create client setup overview page
- [ ] create client-specific config views
- [ ] display:
  - endpoint URL
  - auth method
  - copy-paste config
  - example prompts
  - quota summary
- [ ] add copy button UX for every generated snippet
- [ ] add warnings when a client requires a specific auth flow or limitation
- [ ] ensure raw secrets are only displayed when backend explicitly returns them
- [ ] provide reconnect path if the user revokes and recreates a key later
- [ ] make setup pages accessible again from dashboard, not just during onboarding

### Validation

Automated:

- [ ] contract parsing tests for setup payloads
- [ ] snapshot or component tests for config rendering

Manual:

- [ ] configs are copy-paste usable
- [ ] content matches actual backend auth behavior
- [ ] one supported client can be configured from the generated setup page alone

Do not continue until:

- client setup from the UI works without external docs

---

## Phase 6: Customer Dashboard, Usage, And Query Visibility

Goal: make the product state visible and understandable after setup.

### Backend dependencies

- dashboard summary endpoint or equivalent
- usage/quota endpoint
- recent query history endpoint
- account, billing, and plan status available in stable shape

### Pages to build

- `/app/dashboard`
- `/app/usage`

### Dashboard content

- account status
- onboarding status
- plan
- billing state
- active database summary
- API key count
- daily usage
- quota remaining
- recent queries
- next recommended action

### Checklist

- [ ] build dashboard summary cards
- [ ] build usage overview section
- [ ] build quota warning presentation
- [ ] build recent query history table or list
- [ ] show recent query success/failure indicators
- [ ] show empty state when no queries exist yet
- [ ] display meaningful next step based on state:
  - create first key
  - connect a client
  - upgrade plan
  - reconnect DB
- [ ] build separate usage page if dashboard density gets too high
- [ ] clearly distinguish account issues from billing issues from onboarding issues

### Validation

Automated:

- [ ] dashboard rendering tests for multiple backend states
- [ ] usage display tests for warning thresholds
- [ ] query history rendering tests

Manual:

- [ ] free-tier user can understand remaining quota instantly
- [ ] failure states do not require log inspection to understand at a product level

Do not continue until:

- the dashboard explains the account state clearly in one screen

---

## Phase 7: API Key Management And Database Settings

Goal: make core account operations self-serve.

### Pages to build

- `/app/api-keys`
- `/app/settings/database`

### Checklist

- [ ] build API key list page
- [ ] show key metadata:
  - name
  - prefix
  - scopes
  - created at
  - last used at
  - revoked at
- [ ] build create API key flow
- [ ] build revoke API key flow
- [ ] if rotation is supported in the intended UX, build rotate flow or clearly defer it
- [ ] handle plan-limit failure states cleanly
- [ ] build database settings page
- [ ] show active DB metadata without leaking secrets
- [ ] build update DB connection flow
- [ ] show validation errors on update
- [ ] communicate impact of DB credential changes

### UX requirements

- [ ] dangerous actions should require deliberate confirmation where appropriate
- [ ] API key creation and reveal should be clear but fast
- [ ] database update flow should explain reconnect expectations

### Validation

Automated:

- [ ] API key mutation tests
- [ ] plan-limit UI state tests
- [ ] DB settings form tests

Manual:

- [ ] user can self-manage keys without raw API usage
- [ ] DB update path is understandable and safe

Do not continue until:

- core self-serve account management is complete

---

## Phase 8: Billing Pages And Upgrade UX

Goal: support free-to-paid conversion in the frontend.

### Backend dependencies

- Stripe checkout session endpoint
- customer portal endpoint
- billing state truth from webhook-backed backend
- plan and entitlement summary endpoint

### Pages to build

- `/app/billing`
- upgrade CTA surfaces on dashboard and usage pages

### Checklist

- [ ] build billing overview page
- [ ] show current plan
- [ ] show billing state
- [ ] show plan comparison for upgrade
- [ ] build upgrade CTA to Checkout
- [ ] build manage billing CTA to Customer Portal
- [ ] show payment or billing failure states clearly
- [ ] surface entitlement changes after upgrade or downgrade
- [ ] handle free-plan exhausted state with upgrade prompts
- [ ] avoid optimistic entitlement assumptions that race ahead of Stripe webhook truth

### Validation

Automated:

- [ ] billing UI state tests
- [ ] upgrade CTA and redirect tests
- [ ] webhook-reflected state rendering tests

Manual:

- [ ] free user can discover upgrade path naturally
- [ ] paid user can reach billing management without confusion
- [ ] billing states shown in UI match backend truth

Do not continue until:

- upgrade and billing management are clear from the frontend

---

## Phase 9: Admin UI And Support Workflows

Goal: make support operations possible without shell access or raw database inspection.

### Backend dependencies

- admin auth model defined
- tenant search/list endpoints
- tenant detail endpoints
- support actions:
  - suspend
  - close
  - approve or clear restrictions if applicable
  - revoke key
- query history and setup inspection endpoints

### Pages to build

- `/admin`
- `/admin/tenants`
- `/admin/tenants/[tenantId]`
- related tenant detail sections or tabs

### Tenant detail should show

- tenant identity
- owner email
- account status
- onboarding status
- billing status
- plan code
- active database metadata
- API keys
- recent queries
- recent setup state
- quota usage
- support blockers or risk flags if backend exposes them

### Checklist

- [ ] build admin login/gating flow
- [ ] build tenant list/search page
- [ ] build tenant detail page
- [ ] build account state badges and action controls
- [ ] build support action buttons:
  - suspend
  - close
  - approve if relevant
  - revoke API key
- [ ] build recent query history view for tenant
- [ ] build setup-state inspection view
- [ ] build empty/error states for missing tenants or failed loads
- [ ] record mutation confirmations and success/failure messaging clearly
- [ ] keep admin navigation visually distinct from customer navigation

### Validation

Automated:

- [ ] admin route protection tests
- [ ] tenant search/render tests
- [ ] support action tests with mocked backend responses

Manual:

- [ ] support operator can resolve a basic ticket from UI alone
- [ ] admin actions are clearly dangerous and not easy to misfire

Do not continue until:

- common support tasks are possible from the admin UI alone

---

## Phase 10: Error Handling, Accessibility, UX Hardening, And Polish

Goal: make the frontend trustworthy, understandable, and resilient.

### Checklist

- [ ] add app-wide error boundaries
- [ ] add graceful offline and transient-failure messaging where appropriate
- [ ] standardize empty states
- [ ] standardize success and failure toasts
- [ ] ensure keyboard accessibility for forms, modals, menus, and tables
- [ ] ensure color contrast is acceptable
- [ ] ensure loading states do not cause layout thrash
- [ ] ensure dangerous actions are visually distinct
- [ ] ensure copy-to-clipboard interactions provide feedback
- [ ] ensure all sensitive pages avoid accidental secret persistence in client state
- [ ] audit for localStorage/sessionStorage misuse with secrets
- [ ] verify mobile behavior across core flows
- [ ] verify responsive behavior for dashboard and admin data views

### Validation

Automated:

- [ ] accessibility checks where feasible
- [ ] smoke tests for all critical routes

Manual:

- [ ] keyboard-only pass on key flows
- [ ] mobile pass on key flows
- [ ] error recovery pass on key flows

Do not continue until:

- the app feels production-grade, not prototype-grade

---

## Phase 11: Frontend Integration Validation Against Real Backend

Goal: verify the frontend works against the real backend contracts, not just mocks.

### Checklist

- [ ] connect frontend to staging backend
- [ ] validate auth callbacks end to end
- [ ] validate onboarding wizard against real DB validation errors
- [ ] validate API key flows against real backend behavior
- [ ] validate setup/config pages against real generated payloads
- [ ] validate dashboard and usage pages against real quota values
- [ ] validate billing pages against staging billing state if available
- [ ] validate admin pages against staging admin flows
- [ ] verify no route depends on undocumented backend payload shape

### Recommended test journeys

- [ ] new user signs up and verifies email
- [ ] new user connects DB
- [ ] new user creates first API key
- [ ] new user copies client config and reaches first value
- [ ] existing user logs in via login link
- [ ] free user sees usage and upgrade prompts
- [ ] admin searches tenant and performs support action

### Validation

Automated:

- [ ] end-to-end tests for critical journeys
- [ ] contract smoke suite against staging

Manual:

- [ ] run the full browser journey without touching raw API routes
- [ ] have at least one flow tested with fresh eyes, not just by the implementer

Do not continue until:

- the frontend works end to end against the real backend

---

## Phase 12: Launch Readiness For Frontend

Goal: ensure the frontend is deployable, operable, and aligned with the product promise.

### Checklist

- [ ] production env variables documented
- [ ] build and deploy pipeline defined
- [ ] error monitoring for frontend configured
- [ ] analytics strategy defined if desired
- [ ] caching strategy for public pages defined
- [ ] SEO basics for public pages handled
- [ ] legal/footer/status links handled if required
- [ ] support/help content reviewed
- [ ] pricing and plan copy reviewed against backend truth
- [ ] admin access policy reviewed
- [ ] no placeholder content remains on launch-critical routes

### Validation

Automated:

- [ ] production build succeeds cleanly
- [ ] deploy preview checks pass

Manual:

- [ ] public pages are presentable
- [ ] authenticated app is coherent
- [ ] admin UI is intentionally gated

Do not launch until:

- public, customer, and admin surfaces all meet minimum quality bar

---

## Definition Of Done By Area

### Public product surface is done when

- pricing is live
- signup and login entry points are clear
- public claims match actual product behavior

### Customer onboarding is done when

- a new user can complete setup in the browser
- first API key can be created and captured safely
- client setup can be completed from generated config pages

### Customer app is done when

- dashboard explains account state clearly
- usage and quota are visible
- API keys and DB settings are self-serve
- billing entry points are understandable

### Admin UI is done when

- support can find tenants
- support can inspect state
- support can take core actions without shell access

### Frontend architecture is done when

- typed API access is centralized
- route guards are stable
- no core flows depend on ad hoc fetch logic

### UX polish is done when

- loading, empty, and error states are consistent
- secrets are handled carefully
- accessibility basics are met

---

## Suggested Working Order Inside The Frontend

Use this sequence for the least thrash:

1. `frontend/` scaffold and tooling
2. shared layouts and API client
3. public pages
4. auth callbacks and session handling
5. onboarding wizard
6. setup/config pages
7. dashboard and usage
8. API keys and DB settings
9. billing pages
10. admin UI
11. UX hardening and accessibility
12. staging integration and end-to-end validation

This order keeps the session/auth foundation stable before feature pages pile on top of it.

---

## Frontend-To-Backend Dependency Map

### Backend Phase 3 enables

- quota-aware usage UI
- plan-aware gating and messaging

### Backend Phase 4 enables

- client setup/config pages
- setup payload rendering

### Backend Phase 5 enables

- customer dashboard and complete setup journey

### Backend Phase 6 enables

- billing pages and upgrade UX

### Backend Phase 11 enables

- admin UI and support workflows

If backend contracts change after frontend work begins, update this checklist and the typed client contracts immediately.

---

## Final Recommendation

Build the frontend only after the backend contracts are genuinely stable enough to support it.

The highest-leverage frontend sequence is:

1. freeze frontend contracts
2. scaffold the app properly
3. build browser auth/session correctly
4. build the onboarding wizard first
5. build setup/config pages second
6. build dashboard and self-serve surfaces next
7. add admin UI and billing after the core customer path is solid

If the onboarding flow is excellent, the product will feel real.
If onboarding is weak, no amount of dashboard polish will save it.
