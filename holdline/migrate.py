"""Apply pending migrations without starting the application."""

from holdline.ledger import connect


def main():
    conn = connect()
    try:
        print(
            "Schema version",
            conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
