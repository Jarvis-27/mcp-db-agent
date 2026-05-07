from __future__ import annotations

import json

import httpx
import pytest

from scripts.smoke_mcp_deployment import SmokeConfig, SmokeFailure, run_smoke


def _config(*, access_token: str = "") -> SmokeConfig:
    return SmokeConfig(
        mcp_url="https://mcp.example.com/mcp",
        issuer_url="https://auth.example.com",
        expected_resource="https://mcp.example.com/mcp",
        expected_scopes=("mcp:access",),
        timeout=5,
        require_registration_endpoint=True,
        access_token=access_token,
    )


def _json_response(status: int, payload: dict, headers: dict[str, str] | None = None):
    return httpx.Response(
        status,
        json=payload,
        headers=headers or {"content-type": "application/json"},
    )


def _issuer_metadata():
    return {
        "issuer": "https://auth.example.com/",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/oauth/token",
        "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
        "registration_endpoint": "https://auth.example.com/oidc/register",
    }


def _resource_metadata():
    return {
        "resource": "https://mcp.example.com/mcp",
        "authorization_servers": ["https://auth.example.com/"],
        "scopes_supported": ["mcp:access"],
        "bearer_methods_supported": ["header"],
    }


def _discovery_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == "https://mcp.example.com/mcp":
            return httpx.Response(
                401,
                json={"error": "invalid_token"},
                headers={
                    "www-authenticate": (
                        'Bearer error="invalid_token", '
                        'resource_metadata="https://mcp.example.com/mcp/.well-known/'
                        'oauth-protected-resource"'
                    )
                },
            )
        if (
            request.method == "GET"
            and url == "https://mcp.example.com/mcp/.well-known/oauth-protected-resource"
        ):
            return _json_response(200, _resource_metadata())
        if (
            request.method == "GET"
            and url
            in {
                "https://mcp.example.com/mcp/.well-known/oauth-authorization-server",
                "https://mcp.example.com/mcp/.well-known/openid-configuration",
            }
        ):
            metadata_name = url.rsplit("/", 1)[-1]
            return httpx.Response(
                307,
                headers={"location": f"https://auth.example.com/.well-known/{metadata_name}"},
            )
        if (
            request.method == "GET"
            and url
            in {
                "https://auth.example.com/.well-known/oauth-authorization-server",
                "https://auth.example.com/.well-known/openid-configuration",
            }
        ):
            return _json_response(200, _issuer_metadata())
        return httpx.Response(404, text=f"unhandled {request.method} {url}")

    return httpx.MockTransport(handler)


def test_discovery_smoke_passes_without_access_token():
    client = httpx.Client(transport=_discovery_transport(), follow_redirects=False)

    run_smoke(_config(), client=client)


def test_discovery_smoke_fails_when_challenge_metadata_is_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == "https://mcp.example.com/mcp":
            return httpx.Response(
                401,
                json={"error": "invalid_token"},
                headers={
                    "www-authenticate": (
                        'Bearer error="invalid_token", '
                        'resource_metadata="https://mcp.example.com/.well-known/'
                        'oauth-protected-resource/mcp"'
                    )
                },
            )
        if (
            request.method == "GET"
            and url == "https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
        ):
            return httpx.Response(404, text="not found")
        return _json_response(200, _resource_metadata())

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    with pytest.raises(SmokeFailure, match="Challenge resource metadata returned 404"):
        run_smoke(_config(), client=client)


def test_authenticated_smoke_checks_tools_and_resources():
    discovery = _discovery_transport()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.headers.get("authorization") == "Bearer token":
            payload = json.loads(request.content)
            method = payload["method"]
            if method == "initialize":
                return _json_response(200, {"jsonrpc": "2.0", "id": 1, "result": {}})
            if method == "tools/list":
                return _json_response(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "tools": [
                                {
                                    "name": "list_tables",
                                    "inputSchema": {"type": "object"},
                                    "securitySchemes": [
                                        {"type": "oauth2", "scopes": ["mcp:access"]}
                                    ],
                                    "_meta": {
                                        "securitySchemes": [
                                            {"type": "oauth2", "scopes": ["mcp:access"]}
                                        ]
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "resources/list":
                return _json_response(
                    200,
                    {"jsonrpc": "2.0", "id": 3, "result": {"resources": []}},
                )
        return discovery.handle_request(request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    run_smoke(_config(access_token="token"), client=client)
