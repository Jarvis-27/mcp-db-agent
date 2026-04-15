# MCP Database Analytics Agent

Hosted HTTP MCP server for querying a user-connected database in natural language.

The product model in this repo is now single-account and user-scoped:

`signup -> verify email -> connect database -> create API key -> use /mcp`

## What It Does

- Exposes MCP tools over HTTP at `/mcp`
- Uses API keys for MCP client authentication
- Stores one connected database per user account
- Generates SQL with the configured LLM, validates it, executes it, and returns structured results
- Tracks user-scoped quota usage, query history, and setup state

## Runtime Model

- Backend API: FastAPI/Starlette at `src.app:app`
- Frontend: Next.js app in `frontend/`
- Auth: passwordless email verification and login links
- MCP auth: user API keys
- Setup payloads: `POST /api/v1/account/setup-payloads`

Legacy tenant/admin/owner-session flows are removed from the supported product surface.

## Local Development

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

Open `http://localhost:3000`, sign up, complete setup, then connect an MCP client with:

- URL: `http://localhost:8000/mcp`
- Header: `Authorization: Bearer <api-key>` or `x-api-key: <api-key>`

## Important Environment Variables

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

See [.env.example](./.env.example) for the current full set.

## API Surface

### Auth

- `POST /api/v1/auth/signup`
- `GET /api/v1/auth/verify-email`
- `POST /api/v1/auth/request-login-link`
- `GET /api/v1/auth/exchange-login-link`
- `POST /api/v1/auth/logout`

### Account (session-authenticated)

All account routes use session token auth:

- `x-session-token: <session-token>`
- `Authorization: Bearer <session-token>`

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

### MCP

- `POST /mcp`
- Protected by user API keys

## Setup Payloads

`POST /api/v1/account/setup-payloads` returns client configuration material for VS Code, Cursor, generic HTTP MCP clients, and the current ChatGPT placeholder.

Example:

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
```

## Docker

Run the hosted HTTP stack:

```bash
docker compose up --build
```

The container image serves only the hosted HTTP runtime. The MCP endpoint remains `http://localhost:8000/mcp`.
