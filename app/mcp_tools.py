"""Bridge between the MCP travel-research server and LangChain tools.

Starts the MCP server as a subprocess (stdio transport) and converts
its tools into LangChain ``StructuredTool`` objects so they can be
used alongside the existing deterministic tools.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from langchain_core.tools import StructuredTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LOGGER = logging.getLogger(__name__)

_SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["-m", "app.mcp_server"],
)


async def _call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Spawn the MCP server, call a single tool, return the result."""
    async with stdio_client(_SERVER_PARAMS) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            # result.content is a list of TextContent / ImageContent objects
            for block in result.content:
                if hasattr(block, "text"):
                    try:
                        return json.loads(block.text)
                    except json.JSONDecodeError:
                        return {"raw": block.text}
            return {"raw": str(result.content)}


def _sync_call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Synchronous wrapper around the async MCP tool call."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _call_mcp_tool(tool_name, arguments)).result()
    return asyncio.run(_call_mcp_tool(tool_name, arguments))


def _make_travel_advisory_tool() -> StructuredTool:
    def get_travel_advisory(destination: str) -> dict[str, Any]:
        """Get travel advisory for a destination: visa requirements, safety level,
        currency, timezone, emergency numbers, and local transport tips.
        Call this tool to research practical travel information before planning."""
        return _sync_call_mcp_tool("get_travel_advisory", {"destination": destination})

    return StructuredTool.from_function(
        func=get_travel_advisory,
        name="get_travel_advisory",
        description=(
            "Get travel advisory for a destination via MCP: visa requirements, "
            "safety, currency, timezone, emergency numbers, transport tips."
        ),
    )


def _make_local_phrases_tool() -> StructuredTool:
    def get_local_phrases(destination: str) -> dict[str, Any]:
        """Get useful local phrases for a destination: hello, thank you, please,
        excuse me, and other essential travel phrases in the local language.
        Call this to include cultural tips in the travel plan."""
        return _sync_call_mcp_tool("get_local_phrases", {"destination": destination})

    return StructuredTool.from_function(
        func=get_local_phrases,
        name="get_local_phrases",
        description=(
            "Get useful local phrases for a destination via MCP: greetings, "
            "thank you, help, and other travel phrases in the local language."
        ),
    )


def load_mcp_travel_tools() -> list[StructuredTool]:
    """Return LangChain tools backed by the MCP travel-research server."""
    tools = [_make_travel_advisory_tool(), _make_local_phrases_tool()]
    LOGGER.info("Loaded %d MCP travel-research tools", len(tools))
    return tools
