from __future__ import annotations

import json

import httpx2
from mcp import Client as MCPClient
from mcp.client.streamable_http import streamable_http_client

from holdline.config import token, url


async def get_shipment(shipment_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token()}"}
    timeout = httpx2.Timeout(8.0, connect=3.0)
    async with httpx2.AsyncClient(headers=headers, timeout=timeout, trust_env=False) as http:
        transport = streamable_http_client(url("mcp") + "/mcp", http_client=http)
        async with MCPClient(transport, read_timeout_seconds=8) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            if "get_shipment" not in names:
                raise RuntimeError("get_shipment is not advertised")
            result = await client.call_tool("get_shipment", {"shipment_id": shipment_id})
            if result.is_error:
                raise RuntimeError("shipment evidence tool failed")
            if result.structured_content:
                return result.structured_content
            text = "".join(
                block.text for block in result.content if getattr(block, "type", "") == "text"
            )
            return json.loads(text)
