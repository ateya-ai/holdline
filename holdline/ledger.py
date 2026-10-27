from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

import psycopg

from holdline.config import database_url, ledger_path, using_postgres
from holdline.contracts import Review, ReviewConflict, request_hash
from holdline.migrations import is_postgres, migrate


def connect():
    if using_postgres():
        conn = psycopg.connect(
            database_url(), connect_timeout=3, options="-c statement_timeout=5000"
        )
    else:
        conn = sqlite3.connect(ledger_path(), timeout=5, check_same_thread=False)
    try:
        migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _sql(conn, query: str) -> str:
    return query.replace("?", "%s") if is_postgres(conn) else query


def _lock_review(conn, review_id: str) -> None:
    if is_postgres(conn):
        lock_id = int.from_bytes(hashlib.sha256(review_id.encode()).digest()[:8], signed=True)
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
    elif not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _check_identity(conn, review_id: str, fingerprint: str) -> None:
    for table in ("ledger", "jobs"):
        row = conn.execute(
            _sql(conn, f"SELECT request_hash FROM {table} WHERE review_id=?"), (review_id,)
        ).fetchone()
        if row and row[0] != fingerprint:
            raise ReviewConflict("idempotency key belongs to another shipment or mode")


def _entry(row) -> dict:
    payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
    return {
        "id": int(row[0]),
        "shipment_id": row[1],
        "disposition": row[2],
        "release_executed": bool(row[3]),
        "payload": payload,
        "created_at": str(row[5]),
        "review_id": row[6],
    }


def get_review(conn, review_id: str) -> dict | None:
    row = conn.execute(
        _sql(
            conn,
            "SELECT id, shipment_id, disposition, release_executed, payload, created_at, review_id FROM ledger WHERE review_id=?",
        ),
        (review_id,),
    ).fetchone()
    return _entry(row) if row else None


def post_disposition(conn, result: dict) -> int:
    review = Review.model_validate(result)
    result = review.model_dump()
    fingerprint = request_hash(review.shipment_id, review.mode)
    payload = json.dumps(result)
    query = "INSERT INTO ledger (shipment_id, disposition, release_executed, payload, review_id, request_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(review_id) DO NOTHING"
    if is_postgres(conn):
        query = query.replace("?, ?, ?, ?, ?, ?, ?", "?, ?, ?, ?::jsonb, ?, ?, ?")
    try:
        _lock_review(conn, review.review_id)
        _check_identity(conn, review.review_id, fingerprint)
        conn.execute(
            _sql(conn, query),
            (
                review.shipment_id,
                review.disposition,
                False,
                payload,
                review.review_id,
                fingerprint,
                datetime.now(UTC).isoformat(),
            ),
        )
        row = conn.execute(
            _sql(conn, "SELECT id, request_hash FROM ledger WHERE review_id=?"), (review.review_id,)
        ).fetchone()
        if row[1] != fingerprint:
            raise ReviewConflict("idempotency key belongs to another shipment or mode")
        conn.commit()
        return int(row[0])
    except Exception:
        conn.rollback()
        raise


def list_dispositions(conn, after: int = 0, limit: int = 50) -> list[dict]:
    if after < 0 or not 1 <= limit <= 100:
        raise ValueError("invalid pagination")
    rows = conn.execute(
        _sql(
            conn,
            "SELECT id, shipment_id, disposition, release_executed, payload, created_at, review_id FROM ledger WHERE id>? ORDER BY id LIMIT ?",
        ),
        (after, limit),
    ).fetchall()
    return [_entry(row) for row in rows]


def reserve_job(conn, review_id: str, body: dict) -> dict:
    fingerprint = request_hash(body["shipment_id"], body["mode"])
    now = datetime.now(UTC).isoformat()
    _lock_review(conn, review_id)
    try:
        _check_identity(conn, review_id, fingerprint)
    except ReviewConflict:
        conn.rollback()
        raise
    conn.execute(
        _sql(
            conn,
            "INSERT INTO jobs VALUES (?, ?, ?, 'pending', NULL, ?, ?) ON CONFLICT(review_id) DO NOTHING",
        ),
        (review_id, fingerprint, json.dumps(body), now, now),
    )
    job = get_job(conn, review_id)
    if job["request_hash"] != fingerprint:
        conn.rollback()
        raise ReviewConflict("idempotency key belongs to another shipment or mode")
    conn.commit()
    return job


def get_job(conn, review_id: str) -> dict | None:
    row = conn.execute(
        _sql(
            conn,
            "SELECT review_id, request_hash, request_payload, state, error, created_at, updated_at FROM jobs WHERE review_id=?",
        ),
        (review_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "review_id": row[0],
        "request_hash": row[1],
        "request": json.loads(row[2]),
        "state": row[3],
        "error": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }


def update_job(conn, review_id: str, state: str, error: str | None = None) -> dict | None:
    if state not in {"pending", "running", "complete", "failed"}:
        raise ValueError("invalid job state")
    # A duplicate delivery must never move a completed job backwards.
    conn.execute(
        _sql(
            conn,
            "UPDATE jobs SET state=?, error=?, updated_at=? WHERE review_id=? AND state <> 'complete'",
        ),
        (state, error, datetime.now(UTC).isoformat(), review_id),
    )
    conn.commit()
    return get_job(conn, review_id)
