from __future__ import annotations

import sys

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import a2a_pb2 as a2a
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from holdline.config import HOST, authorization_ok, configure_logging, url
from holdline.executors import HoldlineExecutor

SPECS = {
    "policy": {
        "skill_id": "hold-policy",
        "name": "Hold policy specialist",
        "description": "Check the hold window and excluded categories. Does not release stock.",
        "example": "Review hold policy for HL-2201",
    },
    "shipment": {
        "skill_id": "hold-shipment",
        "name": "Shipment evidence specialist",
        "description": "Read shipment documents, damage, and receipt state from MCP. Does not release stock.",
        "example": "Check shipment evidence for HL-2201",
    },
    "disposition": {
        "skill_id": "hold-disposition",
        "name": "Disposition specialist",
        "description": "Turn policy and shipment findings into one disposition. Does not release stock.",
        "example": "Write a disposition for HL-2201",
    },
}


class BearerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "GET" and (path == "/health" or path.startswith("/.well-known/")):
            return await call_next(request)
        if not authorization_ok(request.headers.get("authorization")):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def _security(card: a2a.AgentCard) -> None:
    scheme_fields = a2a.HTTPAuthSecurityScheme.DESCRIPTOR.fields_by_name
    kwargs = {"scheme": "bearer"}
    if "bearer_format" in scheme_fields:
        kwargs["bearer_format"] = "opaque"
    if "description" in scheme_fields:
        kwargs["description"] = "Holdline service bearer token"
    scheme = a2a.SecurityScheme(http_auth_security_scheme=a2a.HTTPAuthSecurityScheme(**kwargs))
    card.security_schemes["holdlineBearer"].CopyFrom(scheme)
    requirement = a2a.SecurityRequirement()
    requirement.schemes["holdlineBearer"].list.append("")
    card.security_requirements.append(requirement)


def agent_card(role: str) -> a2a.AgentCard:
    spec = SPECS[role]
    card = a2a.AgentCard(
        name=spec["name"],
        description=spec["description"],
        version="1.0.0",
        supported_interfaces=[
            a2a.AgentInterface(
                url=url(role) + "/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=a2a.AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            a2a.AgentSkill(
                id=spec["skill_id"],
                name=spec["name"],
                description=spec["description"],
                tags=[role, "holdline"],
                examples=[spec["example"]],
            )
        ],
    )
    _security(card)
    return card


def build_app(role: str) -> Starlette:
    if role not in SPECS:
        raise SystemExit("Usage: python -m specialists.server policy|shipment|disposition")
    card = agent_card(role)
    handler = DefaultRequestHandler(
        agent_executor=HoldlineExecutor(role),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    async def health(_request):
        from holdline.config import token
        from holdline.evidence import corpus_rules, shipments, skill

        try:
            token()
            corpus_rules()
            shipments()
            skill()
        except Exception:
            return JSONResponse({"service": role, "ready": False}, status_code=503)
        return JSONResponse({"service": role, "ready": True})

    starlette_app = Starlette(
        routes=[
            Route("/health", health),
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/"),
        ]
    )
    starlette_app.add_middleware(BearerMiddleware)
    return starlette_app


def main() -> None:
    configure_logging()
    role = sys.argv[1] if len(sys.argv) > 1 else ""
    application = build_app(role)
    from holdline.config import PORTS

    uvicorn.run(application, host=HOST, port=PORTS[role], log_level="warning")


if __name__ == "__main__":
    main()
