import os
import sqlite3

import pytest

from holdline.evidence import rehearse
from holdline.ledger import connect, get_review, list_dispositions, post_disposition
from holdline.migrations import migrate


def test_legacy_sqlite_migration_preserves_rows():
    path = os.environ["HOLD_LINE_LEDGER"]
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id TEXT, disposition TEXT, release_executed INTEGER, payload TEXT)"
    )
    conn.execute(
        "INSERT INTO ledger VALUES (1, ?, ?, 0, ?)",
        ("old-shipment", "INCOMPLETE", '{"legacy":true}'),
    )
    conn.commit()
    conn.close()
    conn = connect()
    try:
        rows = list_dispositions(conn)
        assert rows[0]["payload"] == {"legacy": True}
        assert rows[0]["created_at"] and rows[0]["review_id"] == "legacy-1"
        post_disposition(conn, rehearse("HL-2201"))
        migrate(conn)
        assert len(list_dispositions(conn)) == 2
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
    finally:
        conn.close()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="explicit Postgres integration URL required"
)
def test_postgres_parity(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_POSTGRES_URL"])
    conn = connect()
    try:
        result = rehearse("HL-2201")
        first = post_disposition(conn, result)
        assert post_disposition(conn, result) == first
        assert get_review(conn, result["review_id"])["payload"] == result
        assert get_review(conn, result["review_id"])["created_at"]
    finally:
        conn.close()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="explicit Postgres integration URL required"
)
def test_legacy_postgres_migration():
    from uuid import uuid4

    import psycopg
    from psycopg import sql

    schema = "migration_" + uuid4().hex
    with psycopg.connect(os.environ["TEST_POSTGRES_URL"]) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        conn.execute(
            "CREATE TABLE ledger (id BIGSERIAL PRIMARY KEY, shipment_id TEXT, disposition TEXT, release_executed BOOLEAN, payload JSONB)"
        )
        conn.execute(
            "INSERT INTO ledger (shipment_id,disposition,release_executed,payload) VALUES ('legacy','INCOMPLETE',false,'{}')"
        )
        conn.commit()
        try:
            migrate(conn)
            rows = list_dispositions(conn)
            assert rows[0]["review_id"] == "legacy-1" and rows[0]["created_at"]
            result = rehearse("HL-2201")
            post_disposition(conn, result)
            assert get_review(conn, result["review_id"])["payload"] == result
        finally:
            conn.rollback()
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
