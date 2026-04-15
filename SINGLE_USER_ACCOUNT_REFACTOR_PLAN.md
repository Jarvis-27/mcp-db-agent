# Single-User Account Refactor Plan

## Summary
- Convert the hosted product from a tenant-plus-membership model to a true single-user account model.
- Keep the current self-serve flow shape: `signup -> email verification -> connect database -> create API key -> use /mcp`.
- Keep passwordless magic-link auth, free/pro plans, and API-key auth for remote MCP clients.
- Remove tenant, membership, owner-session, admin, and stdio-specific concepts from the hosted product.
- Ship this as a breaking release with a one-time data migration and atomic backend/frontend cutover.

## Core Implementation Changes
- Replace the current account model with one canonical `users` table that owns identity, onboarding state, account state, billing state, quota counters, and the single connected database.
- Collapse `tenants` + `tenant_memberships` + active `tenant_databases` into `users`.
- Inline the active database onto `users` with fields for encrypted URL, validation status, last validation time, and last validation error.
- Rename `owner_sessions` to `user_sessions` and key them directly by `user_id`.
- Update `verification_tokens` to reference `user_id` instead of `membership_id`.
- Update `api_keys` to reference `user_id` instead of `tenant_id` and remove `created_by_membership_id`.
- Update `query_history` to use `user_id` instead of `tenant_id`.
- Keep `account_status`, but reduce the supported product states to `active`, `suspended`, and `closed`.
- Remove `restricted`, `pending_review`, tenant search, tenant approval, and all admin-only workflows from code, tests, config, and docs.
- Keep exactly one connected database per user; reconnecting replaces the current database and invalidates user-scoped caches/pipelines.
- Keep free/pro entitlements, but evaluate them per user rather than per tenant.
- Remove hosted/stdio duality from the product codepath; hosted HTTP becomes the only supported mode.

## Backend and Data Model
- Refactor the persistence layer so `UserStore` becomes the real primary abstraction rather than a tenant-backed compatibility wrapper.
- Remove membership-oriented methods such as `create_tenant_with_owner`, `get_owner_membership_*`, and `issue_owner_session`; replace them with direct user/account methods.
- Keep `UserConfig.user_id` as the canonical machine-auth identifier and remove tenant aliases from the auth context.
- Simplify onboarding state handling to the self-serve path only: `pending_email_verification`, `pending_db_connection`, `setup_complete`.
- Remove the optional organization/tenant name concept from signup and persistence.
- Keep email globally unique across all users and use it as the sole login identifier.
- Remove `ADMIN_API_KEY` validation and related settings from runtime configuration.
- Remove stdio-only settings and branches such as `database_url`, `transport`, `__stdio__`, and local query-log fallback behavior.

## Public API, Types, and UI Contract
- Rename signup to `POST /v1/auth/signup` and remove `tenant_name` from the request body.
- Keep `GET /v1/auth/verify-email`, `POST /v1/auth/request-login-link`, `GET /v1/auth/exchange-login-link`, and `POST /v1/auth/logout`, but rename payload fields from `owner_session_token` to `session_token`.
- Move current-account operations under `/v1/account/*`.
- Use these account endpoints: `GET /v1/account`, `GET /v1/account/status`, `PUT /v1/account/database`, `GET /v1/account/api-keys`, `POST /v1/account/api-keys`, `DELETE /v1/account/api-keys/{id}`, `POST /v1/account/api-keys/{id}/rotate`, `POST /v1/account/setup-payloads`, `GET /v1/account/dashboard`, `GET /v1/account/usage/recent`.
- Remove legacy `/v1/users/register`, `/v1/users/me`, `/v1/users/me/rotate-key`, and all `/v1/admin/*` routes rather than keeping shims.
- Rename all API response fields and TS types from `tenant_id` to `user_id`.
- Keep customer-facing UI copy as “account,” but use `user` in backend schemas, API payloads, and internal code.
- Remove organization-name inputs and any tenant wording from signup, status pages, emails, setup screens, and API key screens.
- Keep the current visible browser route structure unless a route is admin-only; update copy and payload handling in place.
- Update email templates so verification and login links refer to account sign-in, not tenant owner sessions.

## MCP and Runtime Behavior
- Keep `/mcp` protected by API keys for this phase.
- Rename internal MCP scoping, cache keys, log fields, and query history filters from tenant-based to user-based.
- Ensure pipeline invalidation remains scoped to the user when the connected database or API keys change.
- Preserve quota enforcement and query logging behavior exactly, but keyed on `user_id`.
- Keep machine auth behavior unchanged for clients except for renamed metadata fields in any management APIs.

## Migration and Cutover
- Implement one Alembic migration that creates the new user-centric shape and migrates data in the same release.
- Make the migration fail fast if any tenant has zero owners, more than one owner, or any non-owner memberships; those cases require manual cleanup before cutover.
- Copy each tenant owner email and verification timestamp into the new `users` row.
- Copy the active tenant database into the user row; ignore inactive historical database rows.
- Rewrite foreign keys in sessions, verification tokens, API keys, and query history from tenant/membership references to direct `user_id` references.
- Add a unique index on `users.email` and user-scoped indexes replacing all tenant-scoped indexes.
- Run the release in a maintenance window and deploy backend plus frontend atomically; do not support mixed old/new clients.
- After successful cutover, delete dead compatibility code, obsolete migrations helpers, tenant/admin docs, and admin/frontend checklist items tied to tenants.

## Test Plan
- Add migration tests that start from the current tenant schema and assert correct collapse into the new user schema.
- Cover the full happy path: signup, verify email, session issuance, database connect, API key creation, setup payload generation, and MCP usage.
- Cover duplicate-email signup, expired token, reused token, invalid login link, and logged-out session behavior.
- Cover suspended and closed accounts being denied for account routes and MCP access.
- Cover reconnecting the single database and verifying cache invalidation plus continued MCP correctness.
- Cover API key create, list, revoke, rotate, and quota-limit enforcement under free and pro plans.
- Cover query-history, dashboard, and quota responses returning `user_id` semantics only.
- Update frontend tests for signup/login/setup flow, removed organization field, renamed payload fields, and removed admin/tenant states.
- Add negative tests that removed routes and removed types are no longer present.

## Assumptions and Defaults
- Magic-link email auth remains the only end-user sign-in method in this phase.
- Free and pro plans remain unchanged except for moving scope from tenant to user.
- Exactly one connected database is supported per user account.
- No admin console or admin API is included in this refactor.
- Hosted HTTP is the only supported runtime after this change; stdio mode is removed from scope.
- No new auth or framework library is required; reuse the current FastAPI, Starlette, SQLAlchemy, Alembic, and Next.js stack.
