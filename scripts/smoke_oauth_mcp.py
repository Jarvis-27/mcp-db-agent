"""OAuth smoke test: get a real user access token and make an MCP tool call.

Run:
    uv run scripts/smoke_oauth_mcp.py

Before running:
    1. Add http://localhost:9999/callback to Auth0's Allowed Callback URLs
       (Applications → your Regular Web App → Settings → Allowed Callback URLs)
    2. Make sure your .env has OAUTH_ISSUER_URL, OAUTH_AUDIENCE, OAUTH_CLIENT_ID set.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Load settings from .env
# ---------------------------------------------------------------------------

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update(os.environ)
    return env

env = _load_env()

ISSUER        = env.get("OAUTH_ISSUER_URL", "").rstrip("/")
CLIENT_ID     = env.get("OAUTH_CLIENT_ID", "")
CLIENT_SECRET = env.get("OAUTH_CLIENT_SECRET", "")
AUDIENCE      = env.get("OAUTH_AUDIENCE", "")
MCP_URL       = env.get("MCP_RESOURCE_URL", "http://localhost:8000/mcp").rstrip("/") + "/"

CALLBACK_PORT = 9999
REDIRECT_URI  = f"http://localhost:{CALLBACK_PORT}/callback"

# ---------------------------------------------------------------------------
# Validate config
# ---------------------------------------------------------------------------

missing = [k for k, v in {"OAUTH_ISSUER_URL": ISSUER, "OAUTH_CLIENT_ID": CLIENT_ID, "OAUTH_AUDIENCE": AUDIENCE}.items() if not v]
if missing:
    raise SystemExit(f"Missing required .env values: {', '.join(missing)}")

# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
code_challenge = (
    base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
    .rstrip(b"=")
    .decode()
)

# ---------------------------------------------------------------------------
# Local callback server
# ---------------------------------------------------------------------------

_result: dict[str, str | None] = {"code": None, "error": None}
_done = threading.Event()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        _result["code"] = params.get("code")
        _result["error"] = params.get("error_description") or params.get("error")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "Authorization complete — return to your terminal." if _result["code"] else f"Error: {_result['error']}"
        self.wfile.write(f"<h2>{msg}</h2>".encode())
        _done.set()

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
threading.Thread(target=server.handle_request, daemon=True).start()

# ---------------------------------------------------------------------------
# Step 1: open browser for auth code + PKCE
# ---------------------------------------------------------------------------

auth_params = {
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "scope": "openid email mcp:access",
    "audience": AUDIENCE,
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
    "prompt": "consent",  # force fresh grant so new scopes are included
}
auth_url = f"{ISSUER}/authorize?{urllib.parse.urlencode(auth_params)}"

print(f"\nOpening browser for OAuth login...")
print(f"Auth URL:\n  {auth_url}\n")
webbrowser.open(auth_url)

print("Waiting for Auth0 callback (120s timeout)...")
if not _done.wait(timeout=120):
    raise SystemExit("Timed out waiting for Auth0 callback.")

if _result["error"]:
    raise SystemExit(f"Auth0 returned an error: {_result['error']}")

code = _result["code"]
print(f"Got authorization code: {code[:12]}...\n")

# ---------------------------------------------------------------------------
# Step 2: exchange code for tokens
# ---------------------------------------------------------------------------

token_payload: dict = {
    "grant_type": "authorization_code",
    "client_id": CLIENT_ID,
    "code": code,
    "redirect_uri": REDIRECT_URI,
    "code_verifier": code_verifier,
}
if CLIENT_SECRET:
    token_payload["client_secret"] = CLIENT_SECRET

resp = httpx.post(f"{ISSUER}/oauth/token", data=token_payload, timeout=15)
resp.raise_for_status()
token_data = resp.json()

access_token = token_data.get("access_token", "")
if not access_token:
    raise SystemExit(f"No access_token in response: {token_data}")

print(f"Access token: {access_token[:40]}...\n")

# Decode payload without verification just to show what Auth0 put in the token
import base64 as _b64, json as _json
_parts = access_token.split(".")
if len(_parts) == 3:
    _pad = _parts[1] + "=" * (-len(_parts[1]) % 4)
    _claims = _json.loads(_b64.urlsafe_b64decode(_pad))
    print(f"Token scopes : {_claims.get('scope', '(none)')}")
    print(f"Token aud    : {_claims.get('aud')}")
    print(f"Token sub    : {_claims.get('sub', '')[:30]}...\n")

# ---------------------------------------------------------------------------
# Step 3: initialize MCP session
# ---------------------------------------------------------------------------

headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

init_resp = httpx.post(
    MCP_URL,
    headers=headers,
    json={
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "smoke-test", "version": "0.1"},
        },
        "id": 0,
    },
    timeout=15,
)

print(f"MCP initialize ({init_resp.status_code}):")
if init_resp.status_code != 200:
    raise SystemExit(f"Init failed:\n{init_resp.text}")
print(json.dumps(init_resp.json(), indent=2))

# ---------------------------------------------------------------------------
# Step 4: call ask_database
# ---------------------------------------------------------------------------

print("\nCalling ask_database...\n")

tool_resp = httpx.post(
    MCP_URL,
    headers=headers,
    json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "ask_database",
            "arguments": {"question": "How many users are there?"},
        },
        "id": 1,
    },
    timeout=60,
)

print(f"ask_database ({tool_resp.status_code}):")
print(json.dumps(tool_resp.json(), indent=2))
