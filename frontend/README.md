# MCP Database Agent - Frontend

Customer-facing Next.js 16 web application for the MCP Database Analytics Agent.

## Tech Stack

- **Next.js 16** (App Router, Server Components, Server Actions)
- **TypeScript**
- **Tailwind CSS**
- **shadcn/ui**
- **pnpm**

## Local Development

### Prerequisites

- Node.js 20+
- pnpm (`npm install -g pnpm`)
- Backend running at `http://localhost:8000` (see root README)

### Setup

```bash
cp .env.local.example .env.local
pnpm install
pnpm dev
```

Open `http://localhost:3000`.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BACKEND_API_URL` | `http://localhost:8000` | Backend base URL (server-side only) |

## Commands

```bash
pnpm dev          # start dev server
pnpm build        # production build
pnpm start        # serve production build
pnpm lint         # eslint
pnpm typecheck    # tsc --noEmit
```

## Application Flow

```text
/signup           -> register email
/auth/verify      -> exchange email token -> set session cookie
/setup/status     -> view gated or blocked account states
/setup/database   -> submit database URL
/setup/api-key    -> create first API key (one-time reveal)
/api-keys         -> manage keys after setup or recover from missing-key state
/setup/clients    -> copy MCP client config
```

## Auth Model

Session is stored in an HTTP-only `mdb_session` cookie set by Server Actions and Server Components. The raw token is never exposed to client-side JavaScript. All authenticated requests to the backend inject the cookie value via the `x-owner-session` header (server-side only).
