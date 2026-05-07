"""Deployment smoke test for remote MCP OAuth discovery.

This script is intentionally non-interactive by default. It verifies the public
URLs that ChatGPT and Claude use before they can make an authenticated MCP call:

1. POST /mcp returns a 401 Bearer challenge, not a redirect or 404.
2. The challenge's resource_metadata URL is reachable and describes this MCP resource.
3. The ChatGPT-style /mcp/.well-known/oauth-protected-resource alias is reachable.
4. /mcp/.well-known OAuth/OIDC discovery redirects to the configured issuer.
5. The issuer publishes OAuth/OIDC metadata with the endpoints remote clients need.

If MCP_SMOKE_ACCESS_TOKEN or --access-token is supplied, it also verifies that an
authenticated client can initialize and list tools/resources.

Run:
    uv run python scripts/smoke_mcp_deployment.py

Common production run:
    uv run python scripts/smoke_mcp_deployment.py \
      --mcp-url https://mcp.prepme.space/mcp \
      --issuer-url https://YOUR_DOMAIN.auth0.com/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


_RESOURCE_METADATA_RE = re.compile(r'resource_metadata="([^"]+)"')
_DEFAULT_ENV_FILE = Path(__file__).parent.parent / ".env"
_JSONRPC_VERSION = "2.0"


class SmokeFailure(Exception):
    """Raised when a deployment smoke check fails."""


@dataclass(frozen=True)
class SmokeConfig:
    mcp_url: str
    issuer_url: str
    expected_resource: str
    expected_scopes: tuple[str, ...]
    timeout: float
    require_registration_endpoint: bool
    access_token: str = ""


class Reporter:
    def ok(self, name: str, detail: str = "") -> None:
        suffix = f" - {detail}" if detail else ""
        print(f"[OK] {name}{suffix}")

    def skip(self, name: str, detail: str = "") -> None:
        suffix = f" - {detail}" if detail else ""
        print(f"[SKIP] {name}{suffix}")


def _load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = _strip_env_value(value)
    return env


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if "#" in value and not (value.startswith('"') or value.startswith("'")):
        value = value.split("#", 1)[0].strip()
    return value.strip().strip('"').strip("'")


def _combined_env(env_file: Path) -> dict[str, str]:
    env = _load_env_file(env_file)
    env.update(os.environ)
    return env


def _split_scopes(raw: str) -> tuple[str, ...]:
    return tuple(scope for scope in raw.replace(",", " ").split() if scope)


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def _default_mcp_url(env: dict[str, str]) -> str:
    if env.get("MCP_RESOURCE_URL"):
        return env["MCP_RESOURCE_URL"]
    app_base_url = env.get("APP_BASE_URL", "http://localhost:8000")
    return f"{app_base_url.rstrip('/')}/mcp"


def _mounted_resource_metadata_url(mcp_url: str) -> str:
    return f"{_normalize_url(mcp_url)}/.well-known/oauth-protected-resource"


def _issuer_metadata_url(issuer_url: str, metadata_name: str) -> str:
    return f"{_normalize_url(issuer_url)}/.well-known/{metadata_name}"


def _fail(message: str) -> None:
    raise SmokeFailure(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _json_response(response: httpx.Response, *, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        _fail(f"{context} did not return JSON: {exc}; body={response.text[:300]!r}")

    _require(isinstance(payload, dict), f"{context} returned non-object JSON: {payload!r}")
    return payload


def _jsonrpc_payload(response: httpx.Response, *, context: str) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        return _json_response(response, context=context)

    for line in response.text.splitlines():
        if line.startswith("data:"):
            try:
                payload = json.loads(line.removeprefix("data:").strip())
            except json.JSONDecodeError as exc:
                _fail(f"{context} returned malformed SSE JSON: {exc}")
            _require(isinstance(payload, dict), f"{context} returned non-object SSE JSON")
            return payload
    _fail(f"{context} returned an SSE response without a data line")


def _extract_resource_metadata(www_authenticate: str) -> str:
    match = _RESOURCE_METADATA_RE.search(www_authenticate)
    _require(bool(match), f"WWW-Authenticate missing resource_metadata: {www_authenticate!r}")
    return match.group(1)


def _assert_resource_metadata(
    metadata: dict[str, Any],
    *,
    config: SmokeConfig,
    context: str,
) -> None:
    actual_resource = str(metadata.get("resource", ""))
    _require(
        _normalize_url(actual_resource) == _normalize_url(config.expected_resource),
        (
            f"{context} resource mismatch: expected {config.expected_resource!r}, "
            f"got {actual_resource!r}"
        ),
    )

    authorization_servers = metadata.get("authorization_servers")
    _require(
        isinstance(authorization_servers, list) and authorization_servers,
        f"{context} missing authorization_servers",
    )
    normalized_servers = {_normalize_url(str(server)) for server in authorization_servers}
    _require(
        _normalize_url(config.issuer_url) in normalized_servers,
        (
            f"{context} authorization_servers does not include {config.issuer_url!r}: "
            f"{authorization_servers!r}"
        ),
    )

    scopes_supported = metadata.get("scopes_supported") or []
    _require(isinstance(scopes_supported, list), f"{context} scopes_supported must be a list")
    missing_scopes = set(config.expected_scopes) - {str(scope) for scope in scopes_supported}
    _require(not missing_scopes, f"{context} missing scopes: {sorted(missing_scopes)}")

    bearer_methods = metadata.get("bearer_methods_supported") or []
    _require(
        "header" in bearer_methods,
        f"{context} bearer_methods_supported should include 'header': {bearer_methods!r}",
    )


def _check_metadata_url(
    client: httpx.Client,
    url: str,
    *,
    config: SmokeConfig,
    reporter: Reporter,
    label: str,
) -> dict[str, Any]:
    response = client.get(url)
    _require(response.status_code == 200, f"{label} returned {response.status_code}: {url}")
    metadata = _json_response(response, context=label)
    _assert_resource_metadata(metadata, config=config, context=label)
    reporter.ok(label, url)
    return metadata


def _assert_issuer_metadata(
    metadata: dict[str, Any],
    *,
    config: SmokeConfig,
    context: str,
) -> None:
    issuer = str(metadata.get("issuer", ""))
    _require(
        _normalize_url(issuer) == _normalize_url(config.issuer_url),
        f"{context} issuer mismatch: expected {config.issuer_url!r}, got {issuer!r}",
    )

    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        _require(metadata.get(field), f"{context} missing {field}")

    if config.require_registration_endpoint:
        _require(
            metadata.get("registration_endpoint"),
            f"{context} missing registration_endpoint; ChatGPT DCR setup may fail",
        )


def _check_issuer_metadata(
    client: httpx.Client,
    url: str,
    *,
    config: SmokeConfig,
    reporter: Reporter,
    label: str,
) -> dict[str, Any]:
    response = client.get(url)
    _require(response.status_code == 200, f"{label} returned {response.status_code}: {url}")
    metadata = _json_response(response, context=label)
    _assert_issuer_metadata(metadata, config=config, context=label)
    reporter.ok(label, url)
    return metadata


def _check_redirect_to_issuer_metadata(
    client: httpx.Client,
    metadata_name: str,
    *,
    config: SmokeConfig,
    reporter: Reporter,
) -> None:
    url = f"{_normalize_url(config.mcp_url)}/.well-known/{metadata_name}"
    expected_location = _issuer_metadata_url(config.issuer_url, metadata_name)

    response = client.get(url)
    if response.status_code == 200:
        metadata = _json_response(response, context=f"MCP {metadata_name}")
        _assert_issuer_metadata(metadata, config=config, context=f"MCP {metadata_name}")
        reporter.ok(f"MCP {metadata_name}", f"{url} returned metadata directly")
        return

    _require(
        response.status_code in {301, 302, 307, 308},
        f"MCP {metadata_name} returned {response.status_code}; expected redirect or metadata",
    )
    location = response.headers.get("location", "")
    _require(
        _normalize_url(location) == _normalize_url(expected_location),
        f"MCP {metadata_name} redirect mismatch: expected {expected_location!r}, got {location!r}",
    )
    reporter.ok(f"MCP {metadata_name} redirect", location)
    _check_issuer_metadata(
        client,
        location,
        config=config,
        reporter=reporter,
        label=f"Issuer {metadata_name}",
    )


def _post_jsonrpc(
    client: httpx.Client,
    config: SmokeConfig,
    *,
    method: str,
    request_id: int,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {config.access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    body: dict[str, Any] = {
        "jsonrpc": _JSONRPC_VERSION,
        "method": method,
        "id": request_id,
    }
    if params is not None:
        body["params"] = params

    response = client.post(config.mcp_url, headers=headers, json=body)
    _require(
        response.status_code == 200,
        f"Authenticated {method} returned {response.status_code}: {response.text[:500]}",
    )
    payload = _jsonrpc_payload(response, context=f"Authenticated {method}")
    _require("error" not in payload, f"Authenticated {method} returned JSON-RPC error: {payload}")
    return payload


def _check_tool_security(tool: dict[str, Any], expected_scopes: Sequence[str]) -> None:
    schemes = tool.get("securitySchemes") or (tool.get("_meta") or {}).get("securitySchemes") or []
    _require(isinstance(schemes, list) and schemes, f"tool {tool.get('name')} lacks securitySchemes")
    scheme_scopes = {
        str(scope)
        for scheme in schemes
        if isinstance(scheme, dict)
        for scope in scheme.get("scopes", [])
    }
    missing = set(expected_scopes) - scheme_scopes
    _require(not missing, f"tool {tool.get('name')} missing security scopes: {sorted(missing)}")


def run_smoke(
    config: SmokeConfig,
    *,
    client: httpx.Client | None = None,
    reporter: Reporter | None = None,
) -> None:
    reporter = reporter or Reporter()
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=config.timeout, follow_redirects=False)

    try:
        challenge = client.post(
            _normalize_url(config.mcp_url),
            headers={"Accept": "application/json, text/event-stream"},
        )
        _require(
            challenge.status_code == 401,
            f"POST /mcp should return 401 before auth; got {challenge.status_code}",
        )
        www_authenticate = challenge.headers.get("www-authenticate", "")
        _require(www_authenticate.lower().startswith("bearer"), "401 missing Bearer challenge")
        challenge_metadata_url = _extract_resource_metadata(www_authenticate)
        reporter.ok("Unauthenticated MCP challenge", challenge_metadata_url)

        _check_metadata_url(
            client,
            challenge_metadata_url,
            config=config,
            reporter=reporter,
            label="Challenge resource metadata",
        )
        _check_metadata_url(
            client,
            _mounted_resource_metadata_url(config.mcp_url),
            config=config,
            reporter=reporter,
            label="ChatGPT/Claude mounted resource metadata",
        )

        _check_redirect_to_issuer_metadata(
            client,
            "oauth-authorization-server",
            config=config,
            reporter=reporter,
        )
        _check_redirect_to_issuer_metadata(
            client,
            "openid-configuration",
            config=config,
            reporter=reporter,
        )

        if not config.access_token:
            reporter.skip(
                "Authenticated MCP list_tools/list_resources",
                "set MCP_SMOKE_ACCESS_TOKEN or pass --access-token",
            )
            return

        initialize = _post_jsonrpc(
            client,
            config,
            method="initialize",
            request_id=1,
            params={
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "deployment-smoke", "version": "0.1"},
            },
        )
        _require("result" in initialize, "initialize response missing result")
        reporter.ok("Authenticated initialize")

        tools_response = _post_jsonrpc(client, config, method="tools/list", request_id=2)
        tools = (tools_response.get("result") or {}).get("tools") or []
        _require(isinstance(tools, list) and tools, "tools/list returned no tools")
        if config.expected_scopes:
            for tool in tools:
                _require(isinstance(tool, dict), f"tools/list included non-object tool: {tool!r}")
                _check_tool_security(tool, config.expected_scopes)
        reporter.ok("Authenticated tools/list", f"{len(tools)} tools")

        resources_response = _post_jsonrpc(client, config, method="resources/list", request_id=3)
        resources = (resources_response.get("result") or {}).get("resources") or []
        _require(isinstance(resources, list), "resources/list returned non-list resources")
        reporter.ok("Authenticated resources/list", f"{len(resources)} resources")
    finally:
        if owns_client:
            client.close()


def _build_parser(env: dict[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke test deployed MCP OAuth discovery for ChatGPT and Claude."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=_DEFAULT_ENV_FILE,
        help="Path to an env file used for defaults.",
    )
    parser.add_argument(
        "--mcp-url",
        default=_default_mcp_url(env),
        help="Public MCP URL, e.g. https://mcp.example.com/mcp.",
    )
    parser.add_argument(
        "--issuer-url",
        default=env.get("OAUTH_ISSUER_URL", ""),
        help="OAuth issuer URL, e.g. https://YOUR_DOMAIN.auth0.com/.",
    )
    parser.add_argument(
        "--expected-resource",
        default=env.get("OAUTH_AUDIENCE") or env.get("MCP_RESOURCE_URL") or _default_mcp_url(env),
        help="Expected protected resource identifier. Defaults to OAUTH_AUDIENCE/MCP_RESOURCE_URL.",
    )
    parser.add_argument(
        "--expected-scopes",
        default=env.get("OAUTH_REQUIRED_SCOPES", "mcp:access"),
        help="Comma- or space-separated scopes expected in resource/tool metadata.",
    )
    parser.add_argument(
        "--access-token",
        default=env.get("MCP_SMOKE_ACCESS_TOKEN", ""),
        help="Optional OAuth access token for authenticated initialize/tools/list/resources/list.",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--no-require-registration-endpoint",
        action="store_true",
        help="Do not require issuer metadata to advertise registration_endpoint.",
    )
    return parser


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=_DEFAULT_ENV_FILE)
    pre_args, _ = pre_parser.parse_known_args(argv)
    env = _combined_env(pre_args.env_file)
    return _build_parser(env).parse_args(argv)


def _config_from_args(args: argparse.Namespace) -> SmokeConfig:
    mcp_url = _normalize_url(args.mcp_url)
    issuer_url = _normalize_url(args.issuer_url)
    expected_resource = _normalize_url(args.expected_resource)

    if not mcp_url:
        _fail("--mcp-url or MCP_RESOURCE_URL is required")
    if not issuer_url:
        _fail("--issuer-url or OAUTH_ISSUER_URL is required")
    if not expected_resource:
        _fail("--expected-resource, OAUTH_AUDIENCE, or MCP_RESOURCE_URL is required")

    return SmokeConfig(
        mcp_url=mcp_url,
        issuer_url=issuer_url,
        expected_resource=expected_resource,
        expected_scopes=_split_scopes(args.expected_scopes),
        timeout=args.timeout,
        require_registration_endpoint=not args.no_require_registration_endpoint,
        access_token=args.access_token.strip(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _config_from_args(args)

    print("MCP deployment smoke test")
    print(f"  MCP URL          : {config.mcp_url}")
    print(f"  Expected resource: {config.expected_resource}")
    print(f"  Issuer URL       : {config.issuer_url}")
    print(f"  Expected scopes  : {', '.join(config.expected_scopes) or '(none)'}")
    print()

    try:
        run_smoke(config)
    except SmokeFailure as exc:
        print(f"\n[FAIL] {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"\n[FAIL] HTTP error: {exc}", file=sys.stderr)
        return 1

    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
