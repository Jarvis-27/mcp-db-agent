"""Verify the parent Starlette app's CORS policy (G12).

The wildcard `allow_methods=["*"]` / `allow_headers=["*"]` combination with
`allow_credentials=True` violates the CORS spec. These tests pin the explicit
method/header constants and exercise an actual preflight + simple request
against a minimal Starlette app wired with the same middleware config.

A minimal Starlette app is used (rather than the imported `app`) because the
parent `app` captures `settings.cors_allow_origins` at import time, and the
default in tests is an empty list — which would short-circuit CORS handling.
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.app import CORS_ALLOW_HEADERS, CORS_ALLOW_METHODS, CORS_EXPOSE_HEADERS


def _build_test_app() -> Starlette:
    async def _ok(_request):
        return PlainTextResponse("ok")

    return Starlette(
        routes=[Route("/", _ok, methods=["GET", "POST"])],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["https://example.com"],
                allow_credentials=True,
                allow_methods=CORS_ALLOW_METHODS,
                allow_headers=CORS_ALLOW_HEADERS,
                expose_headers=CORS_EXPOSE_HEADERS,
            ),
        ],
    )


def test_no_wildcard_methods_or_headers():
    assert "*" not in CORS_ALLOW_METHODS
    assert "*" not in CORS_ALLOW_HEADERS
    assert set(CORS_ALLOW_METHODS) >= {"GET", "POST", "PUT", "DELETE", "OPTIONS"}
    assert set(CORS_ALLOW_HEADERS) >= {
        "Content-Type",
        "Authorization",
        "X-API-Key",
        "X-Session-Token",
        "X-Request-ID",
    }


def test_preflight_returns_explicit_methods_and_headers():
    client = TestClient(_build_test_app())
    response = client.options(
        "/",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key, Content-Type",
        },
    )

    assert response.status_code == 200

    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin == "https://example.com"

    allow_credentials = response.headers.get("access-control-allow-credentials")
    assert allow_credentials == "true"

    allow_methods = response.headers.get("access-control-allow-methods", "")
    assert allow_methods != "*"
    returned_methods = {m.strip() for m in allow_methods.split(",")}
    assert {"GET", "POST", "PUT", "DELETE", "OPTIONS"} <= returned_methods

    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert allow_headers != "*"
    returned_headers = {h.strip().lower() for h in allow_headers.split(",")}
    assert {
        "content-type",
        "authorization",
        "x-api-key",
        "x-session-token",
        "x-request-id",
    } <= returned_headers


def test_actual_request_exposes_request_id():
    """X-Request-ID is set on every response by RequestIDMiddleware; CORS must
    expose it so cross-origin JS can read it for tracing."""
    client = TestClient(_build_test_app())
    response = client.get("/", headers={"Origin": "https://example.com"})

    assert response.status_code == 200

    expose_headers = response.headers.get("access-control-expose-headers", "")
    returned = {h.strip().lower() for h in expose_headers.split(",")}
    assert "x-request-id" in returned
