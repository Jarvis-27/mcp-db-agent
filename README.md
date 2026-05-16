# PlainQuery

**Ask your database questions in plain English.** PlainQuery connects any PostgreSQL or SQLite database to Claude, Cursor, or VS Code — and answers with real, structured data instead of guesses.

[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.github.Jarvis--27%2Fmcp--db--agent-3b82f6)](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Jarvis-27/mcp-db-agent)
[![CI](https://github.com/Jarvis-27/mcp-db-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Jarvis-27/mcp-db-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-3b82f6)

<!-- TODO: add a demo GIF here. Record a 20-30s clip: open Claude Desktop, ask "What were our top 5 products by revenue last quarter?", show the answer. Save it to docs/demo.gif and uncomment the line below. -->
<!-- ![PlainQuery demo](docs/demo.gif) -->

> _Demo GIF coming soon — see [Add a demo](#add-a-demo) for what to record._

---

## What it does

You connect a database once. Then, from any MCP client, you ask questions like:

> _"How many orders did we ship in March?"_
> _"Which 5 customers spent the most last year?"_
> _"What's the average order value by month?"_

PlainQuery introspects your schema, generates SQL with an LLM, **validates it for safety**, runs it, and returns structured JSON. If a query fails, it reads the error and **retries automatically**.

## Why PlainQuery

- **Natural language, real answers** — no SQL required; results come from your actual data, not a hallucination.
- **Read-only and safe by design** — every query is checked before it runs: writes (`INSERT`/`UPDATE`/`DELETE`/DDL) are blocked, dangerous functions and patterns are scanned out, and a `LIMIT` is injected automatically.
- **Self-correcting** — when a generated query errors, the agent feeds the error back to the LLM and retries (up to a configurable limit).
- **Schema-aware** — automatically introspects and caches your schema, so questions map to the right tables and columns.
- **Works with any MCP client** — Claude Desktop, Cursor, VS Code Copilot, or anything that speaks MCP.
- **Secure multi-tenant hosting** — database URLs and LLM keys are Fernet-encrypted at rest; user-supplied connection strings are SSRF-guarded; every request is tenant-scoped.
- **Hosted or self-hosted** — use the managed service, or run the whole stack yourself with Docker.
- **Bring your own LLM** — Anthropic Claude or Groq.

## How it works

```
Your question
   → Schema introspection      (reads tables/columns, cached)
   → SQL generation            (schema + question → LLM → SQL)
   → Safety validation         (blocks writes, scans dangerous patterns, injects LIMIT)
   → Execution                 (runs read-only, with a timeout)
   → Self-correction retry     (on error: feed it back to the LLM, fix, re-run)
   → Structured JSON result
```

---

## Quick start

### Option 1 — Use the hosted service (no install)

1. Sign up at **`https://plainquery.in`** and verify your email.
2. Connect your PostgreSQL database and create an API key.
3. Add the server to your MCP client (see [Connect your MCP client](#connect-your-mcp-client)).

That's it — start asking questions.

### Option 2 — Run it yourself

See [Self-hosting & local development](#self-hosting--local-development) below.

## Connect your MCP client

PlainQuery is published on the [official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Jarvis-27/mcp-db-agent) as `io.github.Jarvis-27/mcp-db-agent`, so registry-aware clients can discover it directly.

To configure a client manually, point it at the MCP endpoint and pass your API key:

```json
{
  "mcpServers": {
    "plainquery": {
      "url": "https://plainquery.in/mcp",
      "headers": { "X-API-Key": "mdbk_your_key_here" }
    }
  }
}
```

The backend can also generate ready-to-paste config for VS Code, Cursor, and generic HTTP clients — call `POST /api/v1/account/setup-payloads` (see [Setup payloads](#setup-payloads)). MCP clients can authenticate with an OAuth 2.1 bearer token or an API key, depending on `MCP_AUTH_MODE`.

---

## Self-hosting & local development

### Prerequisites

- Python 3.12+
- `uv`
- Node.js 20+ and `pnpm` for the frontend
- At least one LLM API key (`ANTHROPIC_API_KEY` or `GROQ_API_KEY`)

### Backend

```bash
uv sync
cp .env.example .env
```

Edit `.env` with at least:

- `CREDENTIAL_ENCRYPTION_KEYS`
- `REGISTRATION_OPEN=true`
- one LLM provider key plus `LLM_PROVIDER`

Run the backend:

```bash
uv run uvicorn src.app:app --reload --host 0.0.0.0 --port 8000
```

The backend mounts:

- REST API at `http://localhost:8000/api`
- MCP endpoint at `http://localhost:8000/mcp`

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Open `http://localhost:3000`, sign up, complete setup, link your OAuth identity via account settings, then connect an MCP client at `http://localhost:8000/mcp`. The client will complete the OAuth flow automatically, or you can use an API key in `api_key_only` / `hybrid` mode.

### Runtime model

- Backend API: FastAPI/Starlette at `src.app:app`
- Frontend: Next.js app in `frontend/`
- Auth: passwordless email verification and login links
- MCP auth: OAuth 2.1 bearer tokens (`oauth_only`), API keys (`api_key_only`), or both (`hybrid`) — set via `MCP_AUTH_MODE`
- Setup payloads: `POST /api/v1/account/setup-payloads`
- Billing: Stripe Checkout, Customer Portal, and webhook-confirmed Free/Pro entitlements

The product model is single-account and user-scoped:
`signup → verify email → connect database → link OAuth identity → use /mcp → upgrade with Stripe`

## Security

- User-supplied database URLs are validated against SSRF, path traversal, private IPs, and DNS rebinding before any connection attempt.
- Database URLs and LLM keys are Fernet-encrypted at rest, with support for key rotation.
- Generated SQL is validated before execution: single-statement guard, forbidden-function scan, dangerous-pattern scan, write/DDL block, table-existence check, and automatic `LIMIT` injection.
- Per-request context scoping prevents cross-tenant data leaks.
- Per-user rate limits and fallback-LLM quotas limit cost abuse.

## Important environment variables

| Variable | Description |
|---|---|
| `AUTH_DATABASE_URL` | Auth/account database used by the hosted product |
| `CREDENTIAL_ENCRYPTION_KEYS` | Encrypts stored database URLs and other secrets |
| `REGISTRATION_OPEN` | Enables or disables public signup |
| `ANTHROPIC_API_KEY` / `GROQ_API_KEY` | LLM credentials for SQL generation |
| `LLM_PROVIDER` | Active provider name |
| `APP_BASE_URL` | Base URL used in setup payloads |
| `FRONTEND_BASE_URL` | Base URL used in email links |
| `ALLOW_SQLITE_USER_DBS` | Dev-only escape hatch for user-supplied SQLite databases |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Stripe API and webhook credentials |
| `STRIPE_PRO_PRICE_ID` | Stripe Price ID that maps to the Pro plan |
| `STRIPE_CHECKOUT_SUCCESS_URL` / `STRIPE_CHECKOUT_CANCEL_URL` | Optional Checkout redirect overrides |
| `STRIPE_CUSTOMER_PORTAL_RETURN_URL` | Optional Customer Portal return URL override |

See [.env.example](./.env.example) for the current full set.

## API surface

### Auth

- `POST /api/v1/auth/signup`
- `GET /api/v1/auth/verify-email`
- `POST /api/v1/auth/request-login-link`
- `GET /api/v1/auth/exchange-login-link`
- `POST /api/v1/auth/logout`

### Account (session-authenticated)

All account routes use session token auth (`x-session-token: <session-token>` or `Authorization: Bearer <session-token>`):

- `GET /api/v1/account`
- `GET /api/v1/account/status`
- `PUT /api/v1/account/database`
- `GET /api/v1/account/api-keys`
- `POST /api/v1/account/api-keys`
- `DELETE /api/v1/account/api-keys/{id}`
- `POST /api/v1/account/api-keys/{id}/rotate`
- `POST /api/v1/account/setup-payloads`
- `GET /api/v1/account/dashboard`
- `GET /api/v1/account/usage/recent`

### Billing

- `GET /api/v1/account/billing`
- `POST /api/v1/account/billing/checkout-session`
- `POST /api/v1/account/billing/portal-session`
- `POST /api/v1/billing/webhook`

Stripe webhooks are the source of truth for plan transitions. Checkout or
subscription activation moves a user to `plan_code=pro`; canceled, unpaid, or
past-due states restrict paid entitlements without deleting database setup.

### OAuth MCP account linking (session-authenticated)

- `GET /api/v1/account/mcp-oauth/status`
- `POST /api/v1/account/mcp-oauth/start`
- `GET /api/v1/account/mcp-oauth/callback`
- `DELETE /api/v1/account/mcp-oauth/link`

### MCP

- `POST /mcp`
- Auth: OAuth 2.1 bearer token, API key, or both — controlled by `MCP_AUTH_MODE`

## Setup payloads

`POST /api/v1/account/setup-payloads` returns client configuration material for VS Code, Cursor, generic HTTP MCP clients, and the current ChatGPT placeholder.

```bash
curl -X POST http://localhost:8000/api/v1/account/setup-payloads \
  -H "Authorization: Bearer <session-token>" \
  -H "Content-Type: application/json" \
  -d '{"raw_api_key":"mdbk_..."}'
```

The backend never stores raw API keys after creation. A raw key is only embedded in setup payloads when you explicitly send it in the request.

## Tests

```bash
uv run pytest tests/ -m "not integration"
uv run pytest tests/ -m integration
uv run ruff check .
uv run mypy src --ignore-missing-imports
```

## Deployment smoke test

After each hosted deploy, verify the public MCP OAuth discovery surface:

```bash
uv run python scripts/smoke_mcp_deployment.py \
  --mcp-url https://mcp.example.com/mcp \
  --issuer-url https://YOUR_DOMAIN.auth0.com/
```

The smoke test checks the unauthenticated `/mcp` challenge, protected resource
metadata, ChatGPT/Claude well-known discovery routes, and issuer metadata. To
also verify authenticated MCP `initialize`, `tools/list`, and `resources/list`,
pass a linked user's access token with `--access-token` or
`MCP_SMOKE_ACCESS_TOKEN`.

## Docker

Run the hosted HTTP stack:

```bash
docker compose up --build
```

The container image serves only the hosted HTTP runtime. The MCP endpoint remains `http://localhost:8000/mcp`.

---

## Add a demo

A short demo GIF at the top of this README is the single biggest conversion lever for a launch. To record one:

1. Open Claude Desktop (or Cursor) connected to PlainQuery against the demo database.
2. Ask 2-3 questions that show range — a count, a ranking, an aggregation by month.
3. Record ~20-30 seconds, export as a GIF, save to `docs/demo.gif`.
4. Uncomment the image line near the top of this file.

## License

[MIT](./LICENSE) © 2026 PlainQuery
