from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from src import app as app_module


def _configure_oauth(monkeypatch) -> None:
    monkeypatch.setattr(app_module.settings, "mcp_resource_url", "https://mcp.example.com/mcp")
    monkeypatch.setattr(app_module.settings, "oauth_issuer_url", "https://auth.example.com/")
    monkeypatch.setattr(app_module.settings, "oauth_required_scopes", "mcp:access")


async def _unexpected_mcp_app(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 418, "headers": []})
    await send({"type": "http.response.body", "body": b"wrong app"})


def test_protected_resource_metadata_routes_include_chatgpt_alias(monkeypatch):
    _configure_oauth(monkeypatch)

    routes = app_module._build_protected_resource_routes()
    client = TestClient(
        Starlette(routes=[*routes, Mount("/mcp", app=_unexpected_mcp_app)])
    )

    response = client.get("/mcp/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "https://mcp.example.com/mcp",
        "authorization_servers": ["https://auth.example.com/"],
        "scopes_supported": ["mcp:access"],
        "bearer_methods_supported": ["header"],
    }


def test_protected_resource_metadata_routes_keep_standard_path(monkeypatch):
    _configure_oauth(monkeypatch)

    client = TestClient(Starlette(routes=app_module._build_protected_resource_routes()))

    response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json()["resource"] == "https://mcp.example.com/mcp"


def test_protected_resource_metadata_routes_include_root_alias(monkeypatch):
    _configure_oauth(monkeypatch)

    client = TestClient(Starlette(routes=app_module._build_protected_resource_routes()))

    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json()["authorization_servers"] == ["https://auth.example.com/"]


def test_chatgpt_auth_server_discovery_probe_redirects_to_issuer(monkeypatch):
    _configure_oauth(monkeypatch)

    client = TestClient(
        Starlette(routes=app_module._build_protected_resource_routes()),
        follow_redirects=False,
    )

    oauth_response = client.get("/mcp/.well-known/oauth-authorization-server")
    oidc_response = client.get("/mcp/.well-known/openid-configuration")

    assert oauth_response.status_code == 307
    assert oauth_response.headers["location"] == (
        "https://auth.example.com/.well-known/oauth-authorization-server"
    )
    assert oidc_response.status_code == 307
    assert oidc_response.headers["location"] == (
        "https://auth.example.com/.well-known/openid-configuration"
    )


def test_mcp_mount_path_middleware_avoids_post_redirect():
    async def mcp_root(_request):
        return PlainTextResponse("mcp-root")

    client = TestClient(
        Starlette(
            routes=[
                Mount(
                    "/mcp",
                    app=Starlette(routes=[Route("/", mcp_root, methods=["POST"])]),
                )
            ],
            middleware=[Middleware(app_module.MCPMountPathMiddleware)],
        ),
        follow_redirects=False,
    )

    response = client.post("/mcp")

    assert response.status_code == 200
    assert response.text == "mcp-root"
