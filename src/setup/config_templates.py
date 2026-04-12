"""Client-specific setup payload rendering."""

import json

from src.setup.schemas import ClientSetupPayload


_SERVER_LABEL = "mcp-db-agent"


def _json_snippet(payload: object) -> str:
    return json.dumps(payload, indent=2)


def _bearer_value(raw_api_key: str | None, placeholder: str) -> str:
    return f"Bearer {raw_api_key}" if raw_api_key else f"Bearer {placeholder}"


def build_vs_code_payload(mcp_url: str, raw_api_key: str | None) -> ClientSetupPayload:
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


def build_cursor_payload(mcp_url: str, raw_api_key: str | None) -> ClientSetupPayload:
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


def build_chatgpt_payload(mcp_url: str) -> ClientSetupPayload:
    return ClientSetupPayload(
        client_id="chatgpt_developer_mode",
        display_name="ChatGPT developer mode",
        status="unsupported_until_oauth",
        auth_method="oauth_2_1_required",
        config_path_hint="ChatGPT developer mode custom connector configuration",
        snippet_format="text/plain",
        snippet="",
        api_key_handling="Do not paste a bearer API key here. ChatGPT app connectivity requires OAuth.",
        instructions=(
            "Keep using VS Code, Cursor, or a generic HTTP MCP client for now.",
            "Enable OAuth 2.1 support before offering a connectable ChatGPT config.",
        ),
        availability_reason=(
            f"ChatGPT remote MCP app connections should use OAuth. This deployment only exposes "
            f"bearer API-key auth at {mcp_url} today."
        ),
    )


def build_generic_http_payload(mcp_url: str, raw_api_key: str | None) -> ClientSetupPayload:
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
