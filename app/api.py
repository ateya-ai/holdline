from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from holdline.config import (
    async_enabled,
    authorization_ok,
    configure_logging,
    log_event,
    token,
    url,
)
from holdline.contracts import CaseIn, DependencyUnavailable, ReviewConflict
from holdline.evidence import corpus_rules, known_shipment, shipments
from holdline.model import live_ready
from holdline.runner import existing_review, receiving_request, run_case

configure_logging()
app = FastAPI(title="Holdline", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None)


def authenticate(authorization: str | None = Header(default=None)):
    if not authorization_ok(authorization):
        raise HTTPException(401, "unauthorized")


protected = [Depends(authenticate)]


@app.exception_handler(DependencyUnavailable)
async def unavailable(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": "3"})


@app.exception_handler(ReviewConflict)
async def conflict(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.middleware("http")
async def access_log(request, call_next):
    start = time.monotonic()
    request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if getattr(request.state, "review_id", None):
        response.headers["X-Review-ID"] = request.state.review_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    log_event(
        "http",
        request_id=request_id,
        review_id=getattr(request.state, "review_id", None),
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.monotonic() - start) * 1000),
    )
    return response


def review_identity(request: Request, idempotency_key: str | None = Header(default=None)) -> str:
    if idempotency_key is not None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", idempotency_key):
            raise HTTPException(
                400,
                "Idempotency-Key must contain 8 to 128 letters, numbers, dots, colons, underscores, or hyphens",
            )
        result = str(uuid5(NAMESPACE_URL, "holdline:" + idempotency_key))
    else:
        result = str(uuid4())
    request.state.review_id = result
    return result


def validate_case(body: CaseIn):
    if not known_shipment(body.shipment_id):
        raise HTTPException(404, "unknown shipment")
    if body.mode == "live" and not live_ready():
        raise HTTPException(
            409, "Live wording needs OPENAI_API_KEY and OPENAI_MODEL. Use rehearsal."
        )


@app.get("/health")
def health():
    return {"service": "api", "ok": True}


@app.get("/ready")
async def ready():
    import httpx

    checks = {}
    try:
        token()
        corpus_rules()
        shipments()
        checks["configuration"] = True
    except Exception:
        checks["configuration"] = False
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:

        async def check(name):
            try:
                return name, (await client.get(url(name) + "/health")).status_code == 200
            except httpx.HTTPError:
                return name, False

        checks.update(
            await asyncio.gather(
                *(check(n) for n in ["policy", "shipment", "disposition", "receiving", "mcp"])
            )
        )
    ok = all(checks.values())
    return JSONResponse(
        {
            "ready": ok,
            "checks": checks,
            "live_configured": live_ready(),
            "async_enabled": async_enabled(),
        },
        status_code=200 if ok else 503,
    )


@app.post("/cases", dependencies=protected)
async def create_case(body: CaseIn, review_id: str = Depends(review_identity)):
    validate_case(body)
    return await run_case(body.shipment_id, body.mode, review_id)


@app.get("/ledger", dependencies=protected)
async def ledger(after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    response = await receiving_request("GET", "/ledger", params={"after": after, "limit": limit})
    return response.json()


@app.get("/reviews/{review_id}", dependencies=protected)
async def review(review_id: str):
    from uuid import UUID

    try:
        UUID(review_id)
    except ValueError as exc:
        raise HTTPException(400, "review_id must be a UUID") from exc
    response = await receiving_request("GET", "/reviews/" + review_id)
    if response.status_code == 404:
        raise HTTPException(404, "review not found")
    return response.json()


@app.post("/jobs", status_code=202, dependencies=protected)
async def submit_job(body: CaseIn, review_id: str = Depends(review_identity)):
    if not async_enabled():
        raise HTTPException(
            409, "queued processing is disabled; use POST /cases or start the queue profile"
        )
    validate_case(body)
    await receiving_request("POST", "/jobs/" + review_id, json=body.model_dump())
    cached = await existing_review(review_id, body.shipment_id, body.mode)
    if cached:
        return {
            "review_id": review_id,
            "state": "complete",
            "result": cached,
            "status_url": "/jobs/" + review_id,
        }
    from app.worker import run_case_task

    try:
        await run_in_threadpool(
            lambda: run_case_task.apply_async(
                args=[body.shipment_id, body.mode, review_id], task_id=review_id, retry=False
            )
        )
    except Exception as exc:
        log_event("broker_unavailable", review_id=review_id, error=type(exc).__name__)
        raise DependencyUnavailable(
            "queue unavailable; retry with the same Idempotency-Key"
        ) from exc
    return {"review_id": review_id, "state": "pending", "status_url": "/jobs/" + review_id}


@app.get("/jobs/{review_id}", dependencies=protected)
async def job(review_id: str):
    from uuid import UUID

    try:
        UUID(review_id)
    except ValueError as exc:
        raise HTTPException(400, "review_id must be a UUID") from exc
    response = await receiving_request("GET", "/jobs/" + review_id)
    if response.status_code == 404:
        raise HTTPException(404, "job not found")
    body = response.json()
    return {k: v for k, v in body.items() if k != "request_hash"}


@app.get("/openapi.json", dependencies=protected)
def schema():
    return app.openapi()


@app.get("/", response_class=HTMLResponse)
def ui():
    return (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
