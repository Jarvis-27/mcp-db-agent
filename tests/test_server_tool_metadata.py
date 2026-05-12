from src import server
from src.config import Settings


async def test_apps_tool_metadata_includes_oauth_security_schemes(monkeypatch):
    monkeypatch.setattr(Settings, "mcp_oauth_enabled", lambda self: True)
    monkeypatch.setattr(Settings, "oauth_required_scopes_list", lambda self: ["mcp:access"])

    tools = await server._list_tools_with_app_metadata()

    assert tools
    for tool in tools:
        payload = tool.model_dump(by_alias=True, exclude_none=True, mode="json")
        assert payload["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp:access"]}]
        assert payload["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp:access"]}]
        assert payload["annotations"]["readOnlyHint"] is True
        assert payload["title"]
