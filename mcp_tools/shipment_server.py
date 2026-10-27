from __future__ import annotations

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from holdline.config import HOST, PORTS, authorization_ok, configure_logging
from holdline.evidence import known_shipment, shipment_record

mcp = MCPServer("holdline-shipments")


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    from holdline.config import token
    from holdline.evidence import shipments

    try:
        token()
        shipments()
    except Exception:
        return JSONResponse({"service": "mcp", "ok": False}, status_code=503)
    return JSONResponse({"service": "mcp", "ok": True})


@mcp.tool()
def get_shipment(shipment_id: str) -> dict:
    """Return the synthetic receiving record for one shipment id."""
    if not known_shipment(shipment_id):
        raise ValueError("unknown shipment")
    return shipment_record(shipment_id)


class BearerASGI:
    """Require the Holdline bearer token on everything except GET /health.

    Plain ASGI, not BaseHTTPMiddleware, so streamed MCP responses pass through untouched.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["method"] == "GET" and scope["path"] == "/health":
            return await self.app(scope, receive, send)
        header = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                header = value.decode("latin-1")
                break
        if not authorization_ok(header):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def build_app():
    inner = mcp.streamable_http_app(stateless_http=True, json_response=True, host=HOST)
    return BearerASGI(inner)


if __name__ == "__main__":
    configure_logging()
    uvicorn.run(build_app(), host=HOST, port=PORTS["mcp"], log_level="info")
