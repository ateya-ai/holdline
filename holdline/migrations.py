"""Small, transactional migrations for the two supported databases."""

from __future__ import annotations

import psycopg


def is_postgres(conn) -> bool:
    return isinstance(conn, psycopg.Connection)


def migrate(conn) -> None:
    pg = is_postgres(conn)
    try:
        if pg:
            conn.execute("SELECT pg_advisory_xact_lock(87428742)")
        else:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        if version < 1:
            identity = "BIGSERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
            payload_type = "JSONB" if pg else "TEXT"
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS ledger (id {identity}, shipment_id TEXT NOT NULL, disposition TEXT NOT NULL, release_executed {'BOOLEAN' if pg else 'INTEGER'} NOT NULL, payload {payload_type} NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            if pg:
                columns = {
                    row[0]
                    for row in conn.execute(
                        "SELECT column_name FROM information_schema.columns WHERE table_name='ledger' AND table_schema=current_schema()"
                    )
                }
            else:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(ledger)")}
            for name in ["created_at", "review_id", "request_hash"]:
                if name not in columns:
                    conn.execute(f"ALTER TABLE ledger ADD COLUMN {name} TEXT")
            conn.execute(
                "UPDATE ledger SET created_at = CAST(CURRENT_TIMESTAMP AS TEXT) WHERE created_at IS NULL"
            )
            conn.execute(
                "UPDATE ledger SET review_id = 'legacy-' || CAST(id AS TEXT) WHERE review_id IS NULL"
            )
            conn.execute(
                "UPDATE ledger SET request_hash = 'legacy-' || CAST(id AS TEXT) WHERE request_hash IS NULL"
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ledger_review_id ON ledger(review_id)")
            conn.execute(
                "INSERT INTO schema_migrations VALUES (1, CAST(CURRENT_TIMESTAMP AS TEXT))"
            )
        if version < 2:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs (review_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, request_payload TEXT NOT NULL, state TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state)")
            conn.execute(
                "INSERT INTO schema_migrations VALUES (2, CAST(CURRENT_TIMESTAMP AS TEXT))"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
