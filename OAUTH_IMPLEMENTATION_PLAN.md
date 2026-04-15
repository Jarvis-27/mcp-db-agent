# OAuth Implementation Plan

## Scope

This document is the implementation reference for adding production-grade OAuth to the hosted MCP deployment in this repository.

It replaces the earlier tenant/member-oriented OAuth plan. The current codebase is a single-user account system, so this plan is written against the actual repository state as of April 15, 2026.

Goals:

- make the public `/mcp` endpoint work with OAuth-capable remote MCP clients
- support ChatGPT remote MCP connectivity
- support VS Code remote MCP connectivity
- support Cursor remote MCP connectivity
- support bearer-token-based MCP consumers such as Claude's MCP connector and OpenAI API remote MCP usage
- keep the existing web app auth flow stable during this project

Non-goals for this phase:

- replacing the current magic-link account login flow in the web app
- reintroducing tenant, membership, or organization concepts
- building a custom OAuth authorization server in this repository

## Final Decisions

- The product model remains single-user and account-scoped.
- The web app keeps its current passwordless email verification and login-link flow.
- OAuth is added to the hosted `/mcp` surface only.
- The MCP server acts as an OAuth 2.1 protected resource and validates bearer tokens on every request.
- The architecture should be standards-based and provider-agnostic at the core.
- Auth0 is the first concrete identity provider documented in this plan.
- Production target state for the public `/mcp` endpoint is `oauth_only`.
- Existing API-key support may remain temporarily for rollout and rollback, but it is not the target production posture for public MCP access.

## Current Repo State

### Product model

The repository is no longer multi-tenant.

Current core data model:

- `users`
- `user_sessions`
- `api_keys`
- one inlined active database per user

Relevant files:

- [src/auth/user_store.py](src/auth/user_store.py)
- [alembic/versions/0007_single_user_schema.py](alembic/versions/0007_single_user_schema.py)
- [SINGLE_USER_ACCOUNT_REFACTOR_PLAN.md](SINGLE_USER_ACCOUNT_REFACTOR_PLAN.md)

### Current auth model

The current app has two auth surfaces:

1. Web app and account APIs:
   - passwordless email verification
   - login-link session auth
   - session token required for `/api/v1/account/*`
2. Hosted `/mcp`:
   - bearer API-key auth only

Relevant files:

- [src/api/app.py](src/api/app.py)
- [src/app.py](src/app.py)
- [src/auth/middleware.py](src/auth/middleware.py)
- [src/setup/config_templates.py](src/setup/config_templates.py)

### Current MCP setup limitation

The setup payload generator correctly marks ChatGPT as unavailable until OAuth exists.

Relevant files:

- [src/setup/config_templates.py](src/setup/config_templates.py)
- [tests/test_setup_payloads.py](tests/test_setup_payloads.py)

### Current MCP SDK state

The pinned `mcp==1.26.0` package already includes resource-server auth primitives that this implementation should use rather than replacing:

- `AuthSettings`
- bearer token verification hooks
- `WWW-Authenticate` challenge handling
- protected resource metadata routes

This means the plan can build on the current package instead of assuming a custom MCP auth layer.

## Production Recommendation

### Recommended architecture

Production-grade for this codebase means:

- keep the current app login/session flow unchanged
- add OAuth only to `/mcp`
- make `/mcp` the OAuth-protected resource
- treat API keys as transitional or internal-only, not as the primary auth path for public remote MCP clients

### Why this is the recommended scope

Replacing the existing app login flow with Auth0 in the same project would create a second large auth migration:

- signup and verification flow changes
- session issuance changes
- frontend auth callback changes
- email delivery and onboarding changes

That work is not required to make remote MCP clients connect securely. The external requirement is that the MCP server implements the MCP authorization model correctly. The production-safe path is to isolate OAuth work to `/mcp` first.

### Target production posture

Recommended target:

- public `/mcp` runs in `oauth_only`
- account APIs continue to use the current session model
- API keys remain available only as a temporary migration aid, rollback tool, or internal path if explicitly retained

## Target Architecture

### External shape

- Public MCP endpoint:
  - `https://app.example.com/mcp`
- Existing frontend:
  - unchanged
- Existing account API:
  - unchanged
- Authorization server:
  - external IdP, first implementation documented with Auth0

### Authentication model

1. A remote MCP client connects to `/mcp`.
2. If the request is unauthenticated, the server returns a proper `401` challenge with `WWW-Authenticate`.
3. The client discovers protected resource metadata from the MCP server.
4. The client discovers OAuth metadata from the authorization server.
5. The client performs OAuth authorization code + PKCE where supported.
6. The client sends `Authorization: Bearer <access-token>` to `/mcp`.
7. The MCP server validates the token and resolves it to exactly one local `User`.
8. The request is executed against that user's single connected database.

### Authorization model

The bearer token must pass all of the following checks:

- valid signature
- valid issuer
- valid audience or resource
- valid lifetime
- required scopes present
- OAuth identity linked to a local active user account
- local user account is `active`
- local user onboarding state is `setup_complete`
- local user has an active connected database

### Internal identity model

The internal execution path should still resolve to `UserConfig`, so the tool layer remains user-scoped and unaware of whether the caller arrived through:

- API key during transitional rollout
- OAuth bearer token in the final architecture

## What Changes and What Does Not

### Stays unchanged in this phase

- account signup
- email verification
- login-link flow
- session token auth for `/api/v1/account/*`
- account onboarding state machine
- one connected database per user
- user-scoped quota and query history model

### Changes in this phase

- `/mcp` gains OAuth resource-server behavior
- local users gain an OAuth identity linkage model
- setup payloads stop presenting ChatGPT as unavailable
- setup payloads become OAuth-aware for supported clients
- public MCP auth target shifts from API keys to OAuth

## Standards Requirements

The implementation should follow the MCP authorization model now expected by current clients and documentation:

- OAuth 2.1 protected resource behavior
- OAuth 2.0 Protected Resource Metadata
- `WWW-Authenticate` challenge responses
- PKCE with `S256`
- Resource Indicators (`resource` parameter)
- dynamic client registration where the client expects it

Operational meaning for this repository:

- the MCP server is the resource server
- the external IdP is the authorization server
- this repository should not implement its own general-purpose OAuth authorization server

## Provider Strategy

### Core design

The design should stay provider-agnostic at the architecture and code level:

- issuer URL
- OAuth discovery metadata
- JWKS
- audience or resource validation
- scopes
- subject linkage

The code should not be tightly named around Auth0 internals unless required by a specific setup helper.

### First provider

Auth0 is the first provider documented in this plan because:

- it can serve as the authorization server
- it publishes discovery metadata and JWKS
- it can support the MCP OAuth pattern required by ChatGPT and other clients

### What not to use from the old plan

Do not carry forward any tenant- or organization-based assumptions:

- no tenant membership lookup
- no Auth0 Organizations dependency
- no per-tenant authorization logic
- no member invite/link flow

This repository now authorizes exactly one local account per OAuth identity.

## Recommended Local Data Model Changes

### Current problem

The current local identity is email-based and session-based. There is no durable OAuth identity linkage on `users`.

### Recommended first rollout shape

Add OAuth linkage fields directly to `users`.

Recommended fields:

- `oauth_issuer`
- `oauth_subject`
- `oauth_email`
- `oauth_email_verified_at`
- `oauth_last_login_at`

Recommended constraints:

- unique index on `(oauth_issuer, oauth_subject)`
- searchable index on `oauth_email`

These fields should be nullable initially so the migration is backward-compatible.

### Why direct fields on `users`

For this codebase, direct linkage on `users` is the simplest production-ready design because:

- there is one account per user
- there is no membership layer anymore
- this avoids introducing a new identity-link table unless there is a real multi-provider requirement

If multi-provider login becomes a real product requirement later, this can be normalized into a dedicated identity-link table in a future migration.

## Recommended Linking Strategy

### Production-safe recommendation

Do not auto-link a local user purely from the first bearer token sent to `/mcp`.

Recommended flow:

1. User signs into the web app with the existing session flow.
2. User explicitly starts a "Connect MCP account" flow from the authenticated app.
3. The app completes one OAuth sign-in round-trip with the chosen provider.
4. The callback binds `(issuer, subject)` to the currently signed-in `users.id`.
5. Future `/mcp` bearer tokens resolve by subject, not by email.

### Why explicit linking is recommended

This is safer than blind first-login matching because it avoids:

- accidental linkage to the wrong account
- ambiguous email-based linking
- linking from an unauthenticated `/mcp` request with no app session context

### Email usage

Email may still be used as a one-time safety check during explicit linking, but it should not be the primary runtime identity key. Runtime resolution should use:

- `issuer`
- `sub`

## Recommended Libraries

### Keep using

- `mcp`
  - use FastMCP auth support already present in the installed package

### Add or promote to runtime dependency

- `PyJWT[crypto]`
  - JWT validation against JWKS
- `httpx`
  - runtime fetches for discovery and JWKS if not already available at runtime

### Do not build

- do not build a custom OAuth authorization server in this repository
- do not build a custom MCP auth transport when FastMCP already supports the needed resource-server pieces

## Detailed Repo Work Plan

## 1. Add MCP OAuth configuration

File:

- [src/config.py](src/config.py)

Add settings for the MCP OAuth surface, recommended names:

- `MCP_AUTH_MODE`
  - values: `api_key_only`, `hybrid`, `oauth_only`
- `MCP_RESOURCE_URL`
  - canonical public URL for `/mcp`
- `OAUTH_ISSUER_URL`
  - provider issuer URL
- `OAUTH_AUDIENCE`
  - expected audience or resource value
- `OAUTH_JWKS_URL`
  - optional override
- `OAUTH_REQUIRED_SCOPES`
  - comma-separated required scopes
- `OAUTH_HTTP_TIMEOUT_SECONDS`
- `OAUTH_JWKS_CACHE_SECONDS`

Recommended posture:

- staging rollout may use `MCP_AUTH_MODE=hybrid`
- production target should be `MCP_AUTH_MODE=oauth_only`

## 2. Add OAuth linkage fields to `users`

File:

- [src/auth/user_store.py](src/auth/user_store.py)

Add nullable columns for:

- `oauth_issuer`
- `oauth_subject`
- `oauth_email`
- `oauth_email_verified_at`
- `oauth_last_login_at`

Add store methods for:

- loading a user by `(issuer, subject)`
- linking a user to `(issuer, subject)`
- updating last OAuth login timestamps

## 3. Add Alembic migration

Folder:

- [alembic/versions](alembic/versions)

Add a migration that:

- extends `users`
- creates the unique index on `(oauth_issuer, oauth_subject)`
- preserves existing users
- assumes no destructive backfill

## 4. Add OAuth token verification module

Create:

- `src/auth/oauth_verifier.py`

Responsibilities:

- fetch provider discovery metadata if needed
- fetch JWKS
- cache JWKS
- verify JWT signature
- verify `iss`
- verify `aud` or resource
- verify `exp`
- verify `nbf` if present
- verify required scopes
- extract normalized identity claims

Return a normalized auth context containing at least:

- issuer
- subject
- email if present
- scopes
- token expiry

Reject:

- missing bearer token
- malformed token
- invalid signature
- wrong issuer
- wrong audience or resource
- expired or not-yet-valid token
- insufficient scopes

## 5. Add OAuth identity resolution module

Create:

- `src/auth/oauth_identity.py`

Responsibilities:

- take verified token claims
- resolve `(issuer, subject)` to a local `User`
- verify local account status and onboarding status
- verify a connected database exists
- return the same internal `UserConfig` shape used by the tool execution path

Failure cases:

- no linked user
- user suspended or closed
- setup incomplete
- no active database

## 6. Add explicit account-linking flow

Recommended files:

- [src/api/app.py](src/api/app.py)
- [src/api/schemas.py](src/api/schemas.py)
- frontend authenticated setup/account pages as needed

Add a small authenticated flow that lets the currently signed-in user bind their local account to the OAuth identity used for MCP.

This flow should:

- require an existing session-authenticated app user
- start provider sign-in
- receive callback
- validate returned identity
- bind `(issuer, subject)` to the current `users.id`

Do not make the first `/mcp` request perform automatic account creation or ambiguous account linking.

## 7. Replace API-key-only MCP wrapping with FastMCP auth support

Files:

- [src/server.py](src/server.py)
- [src/app.py](src/app.py)

Current state:

- `/mcp` is wrapped by custom API-key middleware

Target state:

- build the FastMCP app with `auth=AuthSettings(...)`
- provide a `token_verifier`
- let FastMCP expose protected resource metadata routes
- let FastMCP emit proper `WWW-Authenticate` challenge behavior

Recommended implementation approach:

- instantiate the FastMCP server with OAuth auth settings when MCP auth mode includes OAuth
- make `MCP_RESOURCE_URL` the canonical `resource_server_url`
- use FastMCP middleware and route generation instead of continuing the custom wrapper as the long-term path

## 8. Unify internal request-scoped identity

Files:

- [src/auth/middleware.py](src/auth/middleware.py)
- [src/server.py](src/server.py)

Goal:

- both transitional API-key auth and final OAuth auth resolve to the same internal `UserConfig`

The MCP tools should remain user-scoped and should not care whether the caller authenticated with:

- an API key during rollout
- an OAuth access token in target state

## 9. Update setup payload generation

Files:

- [src/setup/service.py](src/setup/service.py)
- [src/setup/config_templates.py](src/setup/config_templates.py)
- tests under [tests/test_setup_payloads.py](tests/test_setup_payloads.py)

Required changes:

- ChatGPT should no longer be marked unsupported once OAuth is live
- VS Code payloads should describe OAuth-capable connection setup
- Cursor payloads should describe OAuth-capable connection setup
- generic HTTP payloads should clearly distinguish:
  - OAuth-capable clients
  - unsupported non-OAuth clients on the production public endpoint

Important nuance:

- ChatGPT and VS Code can drive OAuth against a compliant MCP server
- Cursor documents OAuth support for remote SSE and Streamable HTTP MCP servers
- Claude's MCP connector and OpenAI API remote MCP usage can consume bearer access tokens, but the calling application obtains and refreshes those tokens

That means setup UX should stop assuming a raw API key is the universal answer.

## 10. Reposition existing API-key features

Files:

- [src/api/app.py](src/api/app.py)
- [src/setup/service.py](src/setup/service.py)
- frontend API-key screens and copy
- [README.md](README.md)

Recommended target posture:

- keep API-key management temporarily if needed for rollout
- stop presenting API keys as the preferred public MCP setup path
- document them as transitional, internal, or rollback-only if they remain enabled

If production is truly `oauth_only`, customer-facing setup payloads for public `/mcp` should not embed raw API keys as the primary path.

## 11. Update docs and environment examples

Files:

- [README.md](README.md)
- [.env.example](.env.example)

Document:

- current app auth stays as-is
- `/mcp` becomes OAuth-protected
- canonical resource URL requirements
- explicit account-linking step
- Auth0 first-provider setup
- supported client matrix
- transitional API-key policy if retained during rollout

## 12. Add tests

Recommended test areas:

- protected resource metadata route
- `401` responses with correct `WWW-Authenticate`
- token verification success and failure cases
- wrong issuer rejection
- wrong audience or resource rejection
- scope rejection
- subject-to-user resolution
- suspended and setup-incomplete user rejection
- explicit link flow
- `hybrid` compatibility during rollout
- `oauth_only` behavior in target state
- setup payload correctness

Recommended locations:

- new tests under `tests/auth/`
- API tests under `tests/api/`
- setup payload tests under `tests/setup/` or the existing setup test files

## Auth0 First-Provider Plan

This section is implementation-specific to the first provider. The core architecture above should remain generic.

## 1. Create Auth0 tenant

Use an Auth0 tenant that will act as the authorization server for the MCP resource.

## 2. Create an Auth0 application for the account-linking flow

Purpose:

- explicit "Connect MCP account" flow from the signed-in web app
- authorization code + PKCE

This is only for linking the local app account to the OAuth identity. It does not replace the app's main login system in this phase.

## 3. Create an Auth0 API for the MCP resource

This API represents the protected resource:

- recommended identifier: the canonical MCP resource URL
- example: `https://app.example.com/mcp`

Define scopes, for example:

- `mcp:access`

## 4. Configure discovery, JWKS, and audience

The implementation will validate tokens using:

- issuer
- JWKS
- audience or resource matching the MCP resource

## 5. Configure dynamic client registration posture

Current client expectations still make DCR relevant for some MCP clients, especially ChatGPT.

For Auth0, verify:

- registration endpoint exposure
- allowed redirect URI policy
- PKCE support
- resource parameter handling

## 6. Configure allowed redirect URIs

At minimum:

- the account-linking callback URL in your web app
- the ChatGPT connector redirect URI shown during setup
- any provider-specific localhost or VS Code redirect URIs required by supported clients during their OAuth flow

## Rollout Strategy

### Recommended rollout phases

## Phase 1: foundation

- config surface
- `users` schema extension
- Alembic migration
- token verifier
- identity resolution

## Phase 2: account linking

- explicit authenticated link flow
- callback handling
- local subject binding

## Phase 3: MCP auth wiring

- FastMCP auth settings
- protected resource metadata
- `WWW-Authenticate`
- request-context unification

## Phase 4: setup UX and docs

- setup payload changes
- frontend copy changes
- README and `.env.example` updates

## Phase 5: transitional rollout

- run `hybrid` in non-production if needed
- validate rollback path
- verify client compatibility

## Phase 6: production cutover

- switch public `/mcp` to `oauth_only`
- remove public-facing API-key setup guidance
- keep API-key support only if explicitly needed for rollback or internal usage

## Client Support Matrix to Plan Against

### ChatGPT

Target support:

- full OAuth-driven remote MCP connection

Requirements to satisfy:

- protected resource metadata
- `WWW-Authenticate`
- authorization server discovery
- DCR
- PKCE `S256`
- resource parameter support

### VS Code

Target support:

- OAuth-driven remote MCP connection

Planning note:

- current VS Code documentation explicitly supports OAuth for MCP servers and documents DCR-first behavior with fallback handling

### Cursor

Target support:

- OAuth-driven remote MCP connection for remote SSE and Streamable HTTP MCP servers

Planning note:

- current Cursor docs state OAuth support for remote HTTP/SSE MCP servers

### Claude MCP connector

Target support:

- bearer access token supplied by the caller after completing OAuth externally

Planning note:

- Claude's connector accepts an `authorization_token`
- the API consumer owns token acquisition and refresh

### OpenAI API remote MCP usage

Target support:

- bearer access token supplied by the caller when using remote MCP through the API

Planning note:

- current OpenAI remote MCP docs say the caller may need to pass an OAuth authorization token depending on the server

## Security Checklist

- validate JWT signature against JWKS
- validate issuer exactly
- validate audience or resource exactly
- validate expiration and `nbf`
- validate required scopes
- never trust unsigned token claims
- never resolve users from headers, query params, or email alone at request time
- resolve the local user from verified `(issuer, subject)`
- require explicit local account linking
- ensure all MCP execution remains user-scoped
- log auth failures without logging raw tokens
- cache JWKS safely
- handle key rotation
- keep `MCP_RESOURCE_URL` canonical and stable
- require HTTPS in production

## Open Questions to Resolve During Implementation

- whether the account-linking callback should live in the backend, frontend, or both
- exact UI placement for the "Connect MCP account" flow in the authenticated app
- whether API-key issuance should be fully hidden once production `/mcp` is `oauth_only`
- whether a future phase should replace the app's current login flow with provider-based login as a separate project

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
- optional frontend auth-linking files
- new tests under `tests/`

## Acceptance Criteria

OAuth support is complete when all of the following are true:

- `/mcp` exposes valid OAuth protected resource metadata
- unauthenticated `/mcp` requests produce correct `401` responses with `WWW-Authenticate`
- valid provider-issued bearer tokens are accepted only when minted for this MCP resource
- OAuth identities resolve to exactly one linked local `User`
- unlinked, inactive, suspended, closed, or setup-incomplete users are rejected cleanly
- MCP execution still resolves to the same user-scoped `UserConfig`
- ChatGPT can connect through OAuth
- VS Code can connect through OAuth
- Cursor can connect through OAuth
- Claude and OpenAI API remote MCP usage can call the server with valid access tokens obtained externally
- production public `/mcp` can run in `oauth_only`

## Sources

External references used for this plan:

- OpenAI Apps SDK authentication:
  - https://developers.openai.com/apps-sdk/build/auth
- OpenAI remote MCP guide:
  - https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- MCP authorization specification:
  - https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- Claude MCP connector:
  - https://platform.claude.com/docs/en/agents-and-tools/mcp-connector
- VS Code MCP developer guide:
  - https://code.visualstudio.com/api/extension-guides/mcp
- Cursor MCP documentation:
  - https://docs.cursor.com/en/context/mcp

Local repository references used for this plan:

- [src/auth/user_store.py](src/auth/user_store.py)
- [src/api/app.py](src/api/app.py)
- [src/app.py](src/app.py)
- [src/auth/middleware.py](src/auth/middleware.py)
- [src/setup/config_templates.py](src/setup/config_templates.py)
- [alembic/versions/0007_single_user_schema.py](alembic/versions/0007_single_user_schema.py)
