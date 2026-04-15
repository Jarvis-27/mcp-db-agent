"""Client-specific setup payload rendering."""

import json

from src.setup.schemas import ClientSetupPayload


_SERVER_LABEL = "mcp-db-agent"


def _json_snippet(payload: object) -> str:
    return json.dumps(payload, indent=2)


def _bearer_value(raw_api_key: str | None, placeholder: str) -> str:
    return f"Bearer {raw_api_key}" if raw_api_key else f"Bearer {placeholder}"


def build_vs_code_payload(
    mcp_url: str,
    raw_api_key: str | None,
    *,
    oauth_configured: bool = False,
    api_keys_enabled: bool = True,
) -> ClientSetupPayload:
    if oauth_configured:
        config: dict[str, object] = {
            "servers": {
                _SERVER_LABEL: {
                    "type": "http",
                    "url": mcp_url,
                }
            }
        }
        api_key_handling = (
            "VS Code will discover the authorization server from the MCP resource "
            "metadata and prompt you to sign in with OAuth."
        )
        if api_keys_enabled:
            api_key_handling += " API keys remain available as a rollout fallback."
        return ClientSetupPayload(
            client_id="vs_code",
            display_name="VS Code",
            status="ready",
            auth_method="oauth_2_1",
            config_path_hint=".vscode/mcp.json or your VS Code user MCP config",
            snippet_format="application/json",
            snippet=_json_snippet(config),
            api_key_handling=api_key_handling,
            instructions=(
                "Open your VS Code MCP configuration file.",
                "Paste this server entry and save the file.",
                "Start the server in VS Code and complete the OAuth sign-in prompt.",
            ),
        )

    headers = {"Authorization": _bearer_value(raw_api_key, "${input:mcpDbAgentApiKey}")}
    config: dict[str, object] = {
        "servers": {
            _SERVER_LABEL: {
                "type": "http",
                "url": mcp_url,
                "headers": headers,
            }
        }
    }
    api_key_handling = (
        "The raw API key is embedded in this snippet."
        if raw_api_key
        else "VS Code will prompt once for the API key using an input variable."
    )
    if raw_api_key is None:
        config["inputs"] = [
            {
                "type": "promptString",
                "id": "mcpDbAgentApiKey",
                "description": "MCP DB Agent API key",
                "password": True,
            }
        ]
    return ClientSetupPayload(
        client_id="vs_code",
        display_name="VS Code",
        status="ready",
        auth_method="bearer_api_key",
        config_path_hint=".vscode/mcp.json or your VS Code user MCP config",
        snippet_format="application/json",
        snippet=_json_snippet(config),
        api_key_handling=api_key_handling,
        instructions=(
            "Open your VS Code MCP configuration file.",
            "Paste this server entry and save the file.",
            "Start the server in VS Code and verify list_tables works.",
        ),
    )

def build_cursor_payload(
    mcp_url: str,
    raw_api_key: str | None,
    *,
    oauth_configured: bool = False,
    api_keys_enabled: bool = True,
) -> ClientSetupPayload:
    if oauth_configured:
        config = {
            "mcpServers": {
                _SERVER_LABEL: {
                    "url": mcp_url,
                }
            }
        }
        api_key_handling = (
            "Cursor supports OAuth for remote HTTP and SSE MCP servers and will "
            "prompt you to authorize."
        )
        if api_keys_enabled:
            api_key_handling += " API keys remain available as a rollout fallback."
        return ClientSetupPayload(
            client_id="cursor",
            display_name="Cursor",
            status="ready",
            auth_method="oauth_2_1",
            config_path_hint=".cursor/mcp.json or ~/.cursor/mcp.json",
            snippet_format="application/json",
            snippet=_json_snippet(config),
            api_key_handling=api_key_handling,
            instructions=(
                "Create or update .cursor/mcp.json.",
                "Paste this remote MCP server entry.",
                "Reload Cursor and complete the OAuth prompt when it appears.",
            ),
        )

    config = {
        "mcpServers": {
            _SERVER_LABEL: {
                "url": mcp_url,
                "headers": {
                    "Authorization": _bearer_value(raw_api_key, "${env:MCP_DB_AGENT_API_KEY}")
                },
            }
        }
    }
    api_key_handling = (
        "The raw API key is embedded in this snippet."
        if raw_api_key
        else "Set MCP_DB_AGENT_API_KEY in your environment before starting Cursor."
    )
    return ClientSetupPayload(
        client_id="cursor",
        display_name="Cursor",
        status="ready",
        auth_method="bearer_api_key",
        config_path_hint=".cursor/mcp.json or ~/.cursor/mcp.json",
        snippet_format="application/json",
        snippet=_json_snippet(config),
        api_key_handling=api_key_handling,
        instructions=(
            "Create or update .cursor/mcp.json.",
            "If you keep the environment placeholder, set MCP_DB_AGENT_API_KEY first.",
            "Reload Cursor and confirm the server connects.",
        ),
    )


def build_chatgpt_payload(mcp_url: str, *, oauth_configured: bool = False) -> ClientSetupPayload:
    """Build the ChatGPT client payload.

    When *oauth_configured* is True (the server has OAuth 2.1 enabled), ChatGPT
    is listed as ``ready`` because it can drive the full OAuth authorization-code
    flow against a compliant MCP server.

    When *oauth_configured* is False, ChatGPT remains ``unsupported_until_oauth``
    because API-key-only auth is insufficient for ChatGPT's remote MCP connector.
    """
    if not oauth_configured:
        return ClientSetupPayload(
            client_id="chatgpt_developer_mode",
            display_name="ChatGPT developer mode",
            status="unsupported_until_oauth",
            auth_method="oauth_2_1_required",
            config_path_hint="ChatGPT developer mode custom connector configuration",
            snippet_format="text/plain",
            snippet="",
            api_key_handling=(
                "Do not paste a bearer API key here. "
                "ChatGPT app connectivity requires OAuth."
            ),
            instructions=(
                "Keep using VS Code, Cursor, or a generic HTTP MCP client for now.",
                "Enable OAuth 2.1 support before offering a connectable ChatGPT config.",
            ),
            availability_reason=(
                f"ChatGPT remote MCP app connections require OAuth. "
                f"This deployment only exposes bearer API-key auth at {mcp_url} today."
            ),
        )

    # OAuth is configured: provide the connection snippet
    config = {
        "connector_type": "mcp",
        "url": mcp_url,
        "auth": {
            "type": "oauth",
            "note": (
                "ChatGPT will discover the authorization server via the protected "
                "resource metadata at /.well-known/oauth-protected-resource and "
                "complete the OAuth 2.1 PKCE flow automatically."
            ),
        },
    }
    return ClientSetupPayload(
        client_id="chatgpt_developer_mode",
        display_name="ChatGPT developer mode",
        status="ready",
        auth_method="oauth_2_1",
        config_path_hint="ChatGPT developer mode custom connector configuration",
        snippet_format="application/json",
        snippet=_json_snippet(config),
        api_key_handling=(
            "ChatGPT will obtain an OAuth access token automatically. "
            "No API key is needed."
        ),
        instructions=(
            "In ChatGPT developer mode, add a custom connector.",
            f"Set the MCP server URL to: {mcp_url}",
            "ChatGPT will complete the OAuth flow and prompt you to authorize.",
            "Verify the connection by asking: 'List the tables in my database.'",
        ),
    )


def build_generic_http_payload(
    mcp_url: str,
    raw_api_key: str | None,
    *,
    oauth_configured: bool = False,
    api_keys_enabled: bool = True,
) -> ClientSetupPayload:
    if oauth_configured:
        config = {
            "transport": "streamable-http",
            "url": mcp_url,
            "headers": {
                "Authorization": "Bearer <oauth-access-token>",
            },
        }
        auth_copy = (
            "Your caller must obtain and refresh an OAuth access token externally, "
            "then send it as a bearer token on MCP requests."
        )
        if api_keys_enabled:
            auth_copy += " API keys remain available during rollout, but OAuth is preferred."
        return ClientSetupPayload(
            client_id="generic_http",
            display_name="Generic HTTP MCP",
            status="ready",
            auth_method="caller_supplied_bearer_token",
            config_path_hint="Any MCP client or integration that accepts an HTTP URL and bearer token",
            snippet_format="application/json",
            snippet=_json_snippet(config),
            api_key_handling=auth_copy,
            instructions=(
                "Point your client at the generated /mcp URL.",
                "Acquire an OAuth access token for this MCP resource in your application.",
                "Send Authorization: Bearer <oauth-access-token> on requests.",
            ),
        )

    config = {
        "transport": "streamable-http",
        "url": mcp_url,
        "headers": {"Authorization": _bearer_value(raw_api_key, "<paste-api-key-here>")},
    }
    api_key_handling = (
        "The raw API key is embedded in this snippet."
        if raw_api_key
        else "Replace <paste-api-key-here> with an active API key before use."
    )
    return ClientSetupPayload(
        client_id="generic_http",
        display_name="Generic HTTP MCP",
        status="ready",
        auth_method="bearer_api_key",
        config_path_hint="Any MCP client or integration that accepts an HTTP URL and headers",
        snippet_format="application/json",
        snippet=_json_snippet(config),
        api_key_handling=api_key_handling,
        instructions=(
            "Point your client at the generated /mcp URL.",
            "Send Authorization: Bearer <api-key> on requests.",
            "Verify the client can call list_tables or describe_schema.",
        ),
    )
