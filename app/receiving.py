from __future__ import annotations

import sqlite3
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from holdline.config import authorization_ok, configure_logging, log_event
from holdline.contracts import CaseIn, Review, ReviewConflict
from holdline.evidence import known_shipment
from holdline.ledger import (
    connect,
    get_job,
    get_review,
    list_dispositions,
    post_disposition,
    reserve_job,
    update_job,
)

configure_logging()


def authenticate(authorization: str | None = Header(default=None)):
    if not authorization_ok(authorization):
        raise HTTPException(401, "unauthorized")


app = FastAPI(
    title="Holdline receiving", version="2.0.0", docs_url=None, redoc_url=None, openapi_url=None
)
protected = [Depends(authenticate)]


def database():
    conn = None
    try:
        conn = connect()
        yield conn
    except (sqlite3.Error, psycopg.Error, ValueError) as exc:
        log_event("database_unavailable", error=type(exc).__name__)
        raise HTTPException(503, "ledger unavailable") from exc
    finally:
        if conn is not None:
            conn.close()


def check_id(review_id: str):
    try:
        UUID(review_id)
    except ValueError as exc:
        raise HTTPException(400, "review_id must be a UUID") from exc


@app.get("/health")
def health(conn=Depends(database)):
    conn.execute("SELECT 1")
    return {"service": "receiving", "ok": True}


@app.post("/dispositions", dependencies=protected)
def create_disposition(body: Review, conn=Depends(database)):
    if not known_shipment(body.shipment_id):
        raise HTTPException(404, "unknown shipment")
    existed = get_review(conn, body.review_id) is not None
    try:
        post_disposition(conn, body.model_dump())
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    row = get_review(conn, body.review_id)
    # The ledger commit and job completion share one durable result identity.
    update_job(conn, body.review_id, "complete")
    log_event("ledger_write", review_id=body.review_id, replayed=existed)
    return {**row, "replayed": existed}


@app.get("/reviews/{review_id}", dependencies=protected)
def review(review_id: str, conn=Depends(database)):
    check_id(review_id)
    row = get_review(conn, review_id)
    if row is None:
        raise HTTPException(404, "review not found")
    return row


@app.get("/ledger", dependencies=protected)
def ledger(
    after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), conn=Depends(database)
):
    rows = list_dispositions(conn, after, limit)
    return {"dispositions": rows, "next_after": rows[-1]["id"] if rows else after}


@app.post("/jobs/{review_id}", dependencies=protected)
def create_job(review_id: str, body: CaseIn, conn=Depends(database)):
    check_id(review_id)
    if not known_shipment(body.shipment_id):
        raise HTTPException(404, "unknown shipment")
    try:
        return reserve_job(conn, review_id, body.model_dump())
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/jobs/{review_id}", dependencies=protected)
def job(review_id: str, conn=Depends(database)):
    check_id(review_id)
    row = get_job(conn, review_id)
    if row is None:
        raise HTTPException(404, "job not found")
    result = get_review(conn, review_id)
    return {**row, "state": "complete" if result else row["state"], "result": result}


class JobUpdate(BaseModel):
    state: str
    error: str | None = None


@app.patch("/jobs/{review_id}", dependencies=protected)
def change_job(review_id: str, body: JobUpdate, conn=Depends(database)):
    check_id(review_id)
    if body.state not in {"pending", "running", "complete", "failed"} or body.error not in {
        None,
        "dependency_unavailable",
        "worker_failed",
    }:
        raise HTTPException(400, "invalid job update")
    if body.state == "complete" and get_review(conn, review_id) is None:
        raise HTTPException(409, "a completed job requires a ledger result")
    row = update_job(conn, review_id, body.state, body.error)
    if row is None:
        raise HTTPException(404, "job not found")
    return row
