"""MCP servers that run inside the agent service, for agents whose agents.json mcp_url is "local:<name>".

They are reached in-process, so they need no deployment of their own. Each module's create_server() makes a
new server per connection, so a server can keep state for one delegation.
"""

from importlib import import_module

from mcp.server.mcpserver import MCPServer

SERVERS = {"research": "app.local_mcp.research"}


def local_server(name: str) -> MCPServer:
    if name not in SERVERS:
        raise ValueError(f"Unknown local MCP server {name!r}; known: {', '.join(SERVERS)}")
    return import_module(SERVERS[name]).create_server()
