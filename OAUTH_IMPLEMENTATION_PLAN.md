# OAuth Implementation Plan

## Scope

This document is the implementation reference for adding OAuth support to the hosted MCP deployment in this repository so it works with:

- ChatGPT
- OpenAI API MCP usage
- Claude MCP connector
- other OAuth-capable HTTPS MCP clients

This plan reflects the agreed architecture as of April 15, 2026.

## Final Decisions

- Use one shared MCP URL for all customers.
- Use Auth0 as the external identity provider.
- Use Auth0 Free for the first rollout.
- Use per-user sign-in.
- Allow all tenant members to use MCP tools.
- Protect all MCP tools with OAuth.
- Keep this app's database as the source of truth for tenant membership and database access.
- Keep API keys only as a secondary/manual auth path for non-OAuth clients.
- Treat the first Auth0 Free rollout as pilot-grade production.

## Target Architecture

### External shape

- Shared MCP endpoint:
  - `https://app.example.com/mcp`
- Frontend app:
  - existing public HTTPS frontend URL
- Auth issuer:
  - Auth0 tenant issuer URL, for example `https://your-tenant.us.auth0.com/`

### Authentication model

- OAuth 2.1 is the primary auth mechanism for hosted MCP.
- Clients authenticate users through Auth0.
- The MCP server validates the bearer token on every request.
- The MCP server resolves the authenticated user to a local tenant membership.
- Local tenant membership determines which tenant and database the request runs against.

### Authorization model

- All MCP tools require OAuth.
- Authorization is tenant-scoped through local membership lookup.
- A user may call tools only if:
  - the token is valid
  - the token audience matches the MCP resource
  - the token contains required scopes
  - the Auth0 subject is linked to a local tenant membership
  - the tenant is active and has an active database

## Why Local Membership Remains the Source of Truth

Auth0 Free is suitable for authentication, but Auth0 Organizations should not be treated as the core tenant model for this project because:

- Organizations availability varies by Auth0 plan.
- The SaaS tenant and member model already exists in this repository.
- The app already stores:
  - tenants
  - memberships
  - owner sessions
  - tenant databases
  - API keys
- Local membership lookup gives tighter control over:
  - tenant isolation
  - onboarding state
  - account status
  - database assignment
  - future billing/entitlements

Recommended mapping:

- Auth0 authenticates the user.
- Local DB decides what that user can access.

## Production Recommendation

### Recommended auth posture

- Primary: OAuth for all hosted user-facing MCP access.
- Secondary: API keys for manual HTTP clients, internal tooling, dev workflows, and non-OAuth environments.

### Why not API keys as primary auth

- ChatGPT's current MCP/App flow expects OAuth.
- OAuth provides per-user identity, revocation, consent, and auditability.
- API keys are not the right primary auth for a shared hosted MCP service exposed to end users.

## Known Constraints

### ChatGPT and MCP authorization requirements

The current OpenAI and MCP guidance requires the server to support:

- OAuth 2.1
- protected resource metadata
- `WWW-Authenticate` challenge responses
- PKCE
- dynamic client registration
- audience/resource validation

### Auth0 Free limitation

The main risk in this rollout is dynamic client registration hardening.

- ChatGPT currently expects DCR.
- Auth0 supports DCR.
- Auth0's stronger protections for DCR are limited compared with higher-tier setups.
- This is acceptable for the agreed pilot-grade production rollout.

## Existing Repo State

### Current auth path

The current hosted `/mcp` path is bearer-API-key authenticated, not OAuth authenticated.

Relevant files:

- [src/app.py](src/app.py)
- [src/auth/middleware.py](src/auth/middleware.py)
- [src/server.py](src/server.py)
- [src/setup/config_templates.py](src/setup/config_templates.py)
- [src/setup/service.py](src/setup/service.py)
- [src/auth/user_store.py](src/auth/user_store.py)
- [src/config.py](src/config.py)

### Current setup limitation

The setup payload generator explicitly marks ChatGPT as unsupported until OAuth exists.

## Recommended Libraries

### Keep

- `mcp`
  - use the existing FastMCP auth primitives already present in the installed SDK

### Add

- `PyJWT[crypto]`
  - for JWT verification against Auth0 JWKS
- `httpx`
  - move to runtime dependency if used by JWKS/discovery fetch logic at runtime

### Do not build

- do not build a custom OAuth authorization server in this repo

## High-Level Implementation Strategy

### Core idea

Use Auth0 as the issuer and FastMCP as the resource server surface.

Implementation flow:

1. Client connects to `/mcp`.
2. If unauthenticated, server returns proper auth challenge and metadata.
3. Client completes OAuth with Auth0.
4. Client sends bearer token on every MCP request.
5. Server verifies the token.
6. Server resolves Auth0 user identity to a local tenant membership.
7. Existing pipeline logic runs using the resolved tenant database configuration.

## Detailed Repo Work Plan

## 1. Add OAuth configuration

File:

- [src/config.py](src/config.py)

Add settings for:

- `AUTH_MODE`
  - values: `hybrid`, `oauth_only`, `api_key_only`
- `MCP_RESOURCE_URL`
  - canonical shared MCP URL, for example `https://app.example.com/mcp`
- `AUTH0_ISSUER`
  - Auth0 issuer base URL
- `AUTH0_AUDIENCE`
  - should match the configured MCP API audience
- `AUTH0_JWKS_URL`
  - optional override
- `AUTH0_REQUIRED_SCOPES`
  - comma-separated scopes
- optional cache/timeout settings:
  - `AUTH0_JWKS_CACHE_SECONDS`
  - `AUTH0_HTTP_TIMEOUT_SECONDS`

Recommended defaults:

- `AUTH_MODE=hybrid` for first rollout
- `AUTH0_REQUIRED_SCOPES=mcp:access`

## 2. Extend tenant membership model for OAuth identity linkage

File:

- [src/auth/user_store.py](src/auth/user_store.py)

Add fields to `TenantMembership`:

- `auth_provider`
  - for now expected value: `auth0`
- `auth_subject`
  - Auth0 user subject from token `sub`
- optional `last_login_at`

Add constraints/indexing:

- unique index on `(auth_provider, auth_subject)`
- searchable index on `auth_subject`

These fields must be nullable initially for backward compatibility.

## 3. Add Alembic migration

Folder:

- [alembic/versions](alembic/versions)

Add a migration that:

- adds new columns to `tenant_memberships`
- creates the unique index
- preserves existing data
- is safe to run on existing environments

No destructive backfill assumptions.

## 4. Add OAuth token verification module

Create a new module, recommended:

- `src/auth/oauth_verifier.py`

Responsibilities:

- fetch JWKS from Auth0
- cache JWKS
- verify JWT signature
- verify `iss`
- verify `aud`
- verify `exp`
- verify `nbf` if present
- verify required scopes
- extract `sub`
- return a normalized auth context for downstream user lookup

Recommended approach:

- use `PyJWT[crypto]`
- use `PyJWKClient` or equivalent JWKS lookup flow
- cache keys and tolerate key rotation

The verifier must reject:

- missing bearer token
- malformed token
- invalid signature
- wrong issuer
- wrong audience
- expired token
- insufficient scopes

## 5. Add OAuth identity resolution module

Create a new module, recommended:

- `src/auth/oauth_identity.py`

Responsibilities:

- take verified token claims
- resolve `sub` to local `TenantMembership`
- fetch tenant
- fetch active database
- construct the same internal request-scoped user configuration used by existing tool execution

Output should align with current `UserConfig` expectations so the tool layer does not need to know whether the caller used:

- API key auth
- OAuth auth

Failure cases:

- user not linked to any membership
- tenant inactive
- setup incomplete
- no active database

## 6. Replace API-key-only MCP wrapping with FastMCP auth support

File:

- [src/app.py](src/app.py)

Current state:

- `/mcp` is mounted with a custom API-key wrapper

Target state:

- use FastMCP auth support with:
  - `auth=AuthSettings(...)`
  - `token_verifier=<oauth verifier>`

Required behavior:

- publish protected resource metadata
- return proper `401` and `WWW-Authenticate` challenge
- advertise the canonical MCP resource URL
- validate bearer tokens on every request

Keep hybrid support:

- in `hybrid` mode, preserve API-key auth path for manual and legacy clients
- in `oauth_only` mode, reject API-key-only MCP access

Design note:

- REST management APIs may continue using current owner-session and API-key logic
- this plan is focused on hosted MCP auth

## 7. Unify request-scoped identity handling

Files:

- [src/server.py](src/server.py)
- [src/auth/middleware.py](src/auth/middleware.py)

Goal:

- both API-key auth and OAuth auth should resolve to the same internal request context model

Recommended direction:

- keep `UserConfig` as the canonical internal auth object
- ensure OAuth requests populate the same fields needed by:
  - pipeline factory
  - query log
  - entitlements
  - quota enforcement

`src.server` should not care whether auth came from:

- API key
- OAuth bearer token

## 8. Add member management APIs

This is required because the selected product model is:

- per-user sign-in
- all tenant members can use MCP tools

Current repo state is owner-centric. A usable OAuth rollout needs member lifecycle support.

Recommended additions in [src/api/app.py](src/api/app.py) and [src/api/schemas.py](src/api/schemas.py):

- invite member by email
- list members
- remove member
- view membership linkage status
- optionally resend invite/link instructions

Minimum pilot behavior:

1. Owner invites member by email.
2. A local membership record is created.
3. Member signs in through Auth0.
4. On first successful authenticated app flow, that Auth0 subject is linked to the pending membership.

Possible matching strategies:

- safest initial strategy:
  - match Auth0 email to an invited membership email
  - require exact email match
- after match:
  - set `auth_provider=auth0`
  - set `auth_subject=<sub>`

Avoid automatic tenant creation from OAuth login.

## 9. Update setup payload generation

Files:

- [src/setup/config_templates.py](src/setup/config_templates.py)
- [src/setup/service.py](src/setup/service.py)

Required changes:

- ChatGPT should no longer be marked unsupported
- setup payloads should explain OAuth-based connection
- Claude setup should document OAuth bearer token usage instead of only raw API keys
- generic HTTP payload should explain:
  - OAuth path
  - API-key fallback path if `AUTH_MODE=hybrid`

The setup UX should clearly distinguish:

- user-facing OAuth clients
- manual header-based API-key clients

## 10. Update docs and environment examples

Files:

- [README.md](README.md)
- [.env.example](.env.example)

Add:

- Auth0 configuration instructions
- MCP resource URL guidance
- shared URL architecture explanation
- local membership linkage explanation
- supported-client matrix
- rollout limitations for Auth0 Free pilot

## 11. Add tests

Test areas:

- protected resource metadata route
- `401` challenge with `WWW-Authenticate`
- token verification success
- token verification failure cases
- scope failure
- Auth0 subject to membership resolution
- tenant isolation
- hybrid mode compatibility
- setup payload correctness

Recommended test files:

- new tests under `tests/auth/`
- setup-related tests under `tests/setup/`
- API tests for member management under `tests/api/`

## Auth0 Configuration Plan

## 1. Create Auth0 tenant

Use Auth0 Free for initial rollout.

## 2. Create frontend application

Purpose:

- user sign-in for the frontend
- support Authorization Code + PKCE

## 3. Create an Auth0 API for the MCP resource

This API represents the MCP server as the protected resource.

Set:

- identifier / audience:
  - recommended to match the canonical MCP resource URL
  - example: `https://app.example.com/mcp`

Define scopes:

- `mcp:access`

Optional future scopes:

- `mcp:read`
- `mcp:admin`

For the current design, one shared scope is enough.

## 4. Enable DCR

This is required for ChatGPT compatibility under current MCP/OpenAI guidance.

Security note:

- this is the main pilot risk on Auth0 Free
- monitor and restrict as much as possible within free-plan limits

## 5. Configure redirect URIs

Need:

- frontend app callback URL
- any logout URLs required by frontend
- ChatGPT connector/app redirect URI shown during ChatGPT setup

## 6. Issuer and discovery

Your Auth0 issuer will be the auth server metadata source.

Example issuer:

- `https://your-tenant.us.auth0.com/`

Clients will discover:

- `/.well-known/oauth-authorization-server`
- or OIDC discovery endpoint as supported

## OAuth Flow to Support

### ChatGPT / OpenAI app flow

1. ChatGPT calls MCP without valid token.
2. MCP server returns `401` with `WWW-Authenticate`.
3. ChatGPT fetches protected resource metadata.
4. Metadata points to Auth0 issuer.
5. ChatGPT performs DCR.
6. ChatGPT performs Authorization Code + PKCE.
7. ChatGPT receives token for the MCP resource.
8. ChatGPT calls `/mcp` with `Authorization: Bearer <token>`.
9. Server verifies token and resolves tenant membership.

### Claude MCP connector flow

Claude's connector supports OAuth bearer tokens for authenticated servers.

Operationally:

- bearer token must be valid for the MCP resource
- server must validate it on every request

### Generic OAuth-capable MCP clients

They should work with the same protected resource metadata and bearer-token validation model.

## Internal Data Model Changes

### Existing model to keep

- `Tenant`
- `TenantMembership`
- `TenantDatabase`
- `OwnerSession`
- `ApiKey`

### New linkage fields

On `TenantMembership`:

- `auth_provider`
- `auth_subject`
- optional `last_login_at`

### Optional future additions

Not required for the first rollout, but may be useful later:

- `invite_status`
- `invited_at`
- `joined_at`
- `role`
- `auth_email_verified_at`

## Error Handling Requirements

### MCP HTTP auth errors

When auth is missing or invalid:

- return `401 Unauthorized`
- include `WWW-Authenticate`
- include protected resource metadata URL

When scopes are insufficient:

- return `403 Forbidden` or the appropriate challenge behavior supported by FastMCP

### User-resolution failures

Examples:

- token valid but no linked membership
- linked user belongs to no active tenant
- tenant setup incomplete
- tenant has no active database

These must fail cleanly and not leak tenant information.

## Backward Compatibility

### First rollout mode

Recommended:

- `AUTH_MODE=hybrid`

Meaning:

- OAuth works for ChatGPT, OpenAI MCP, Claude, and future user-facing clients
- API keys still work for manual clients and internal testing

### Future direction

After the pilot stabilizes:

- consider moving hosted `/mcp` to `oauth_only`
- retain API keys only for management APIs or internal service paths if desired

## Security Checklist

- validate JWT signature against JWKS
- validate issuer exactly
- validate audience exactly
- validate expiration
- validate scopes
- never trust token claims without signature verification
- do not resolve tenant from user-supplied headers or query params
- resolve tenant only from verified identity plus local membership
- ensure all MCP requests stay tenant-isolated
- log auth failures without logging raw tokens
- cache JWKS safely
- handle JWKS rotation
- ensure canonical resource URL is stable and consistent

## Rollout Plan

## Phase 1: foundation

- config settings
- membership schema changes
- Alembic migration
- JWT verifier

## Phase 2: MCP auth wiring

- FastMCP auth integration
- metadata publication
- challenge responses
- request-scoped identity unification

## Phase 3: membership enablement

- invite/list/remove member APIs
- first-login subject linkage flow

## Phase 4: setup UX and docs

- setup payload changes
- README changes
- `.env.example` changes

## Phase 5: validation

- automated tests
- manual validation with:
  - MCP Inspector
  - ChatGPT
  - OpenAI API MCP usage
  - Claude MCP connector

## Recommended File Change List

Likely files to edit:

- [src/config.py](src/config.py)
- [src/app.py](src/app.py)
- [src/server.py](src/server.py)
- [src/auth/user_store.py](src/auth/user_store.py)
- [src/auth/middleware.py](src/auth/middleware.py)
- [src/api/app.py](src/api/app.py)
- [src/api/schemas.py](src/api/schemas.py)
- [src/setup/service.py](src/setup/service.py)
- [src/setup/config_templates.py](src/setup/config_templates.py)
- [README.md](README.md)
- [.env.example](.env.example)
- `alembic/versions/<new_migration>.py`
- `src/auth/oauth_verifier.py`
- `src/auth/oauth_identity.py`
- new test files under `tests/`

## Open Questions to Resolve During Implementation

- whether pinned `mcp==1.26.0` is sufficient for the exact tool-level auth metadata ChatGPT expects, or whether a stable v1.x upgrade is needed
- exact member invite/link UX in the frontend
- whether email-match linking is enough for the first rollout or if explicit invite acceptance is needed
- whether OAuth should eventually replace API-key auth entirely on `/mcp`

## Execution Order

Recommended order of implementation:

1. schema changes for membership linkage
2. config surface
3. JWT verifier
4. OAuth identity resolution
5. FastMCP auth wiring on `/mcp`
6. hybrid auth compatibility
7. member management APIs
8. setup payload updates
9. docs
10. tests

## Acceptance Criteria

OAuth support is complete when all of the following are true:

- `/mcp` exposes valid MCP/OAuth auth discovery metadata
- unauthenticated requests produce correct auth challenges
- Auth0-issued bearer tokens are accepted only when valid for this MCP resource
- authenticated users are mapped to the correct local tenant membership
- all tenant members can use MCP tools
- tenant isolation holds across requests
- ChatGPT can connect through OAuth
- OpenAI API MCP usage can connect through OAuth
- Claude MCP connector can connect with OAuth bearer tokens
- API-key fallback still works in hybrid mode

## Sources

- OpenAI MCP guide:
  - https://developers.openai.com/api/docs/mcp
- OpenAI Apps SDK auth:
  - https://developers.openai.com/apps-sdk/build/auth
- MCP authorization specification:
  - https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- Anthropic MCP connector:
  - https://platform.claude.com/docs/en/agents-and-tools/mcp-connector
- Auth0 MCP overview:
  - https://auth0.com/ai/docs/mcp/intro/overview
- Auth0 MCP client registration guide:
  - https://auth0.com/ai/docs/mcp/guides/registering-your-mcp-client-application
- Auth0 Organizations docs:
  - https://auth0.com/docs/organizations
- Auth0 pricing:
  - https://auth0.com/pricing
- PyJWT docs:
  - https://pyjwt.readthedocs.io/
