"""Minimal MCP client: discover and exercise the blog MCP server by hand.

Run with the blog API and MCP server up:  python scripts/try_mcp_client.py
"""

import asyncio

from mcp.client.client import Client

MCP_URL = "http://127.0.0.1:8101/mcp"


async def main():
    async with Client(MCP_URL) as client:
        tools = await client.list_tools()
        print("TOOLS:", [t.name for t in tools.tools])
        print("create_post schema:", tools.tools[[t.name for t in tools.tools].index("create_post")].input_schema)

        res = await client.call_tool(
            "create_post", {"title": "Hello MCP", "content": "First post via **MCP**.", "author": "sachin"}
        )
        print("create_post ->", res.structured_content or res.content)

        res = await client.call_tool("list_posts", {})
        print("list_posts ->", res.structured_content or res.content)

        res = await client.call_tool("get_post", {"post_id": 999999})
        print("get_post(999999) isError:", res.is_error, res.content[0].text)

        resources = await client.list_resources()
        print("RESOURCES:", [str(r.uri) for r in resources.resources])
        templates = await client.list_resource_templates()
        print("TEMPLATES:", [t.uri_template for t in templates.resource_templates])

        prompts = await client.list_prompts()
        print("PROMPTS:", [p.name for p in prompts.prompts])


asyncio.run(main())
