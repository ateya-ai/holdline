"""Online SQLite backups and non-destructive restores.

For PostgreSQL use pg_dump/pg_restore as described in docs/operations.md.
"""

import argparse
import sqlite3
from pathlib import Path

from holdline.config import ledger_path, using_postgres


def backup(destination: Path):
    if using_postgres():
        raise ValueError("Use pg_dump for PostgreSQL backups")
    if destination.exists():
        raise FileExistsError("backup destination already exists")
    source = ledger_path()
    if not source.exists():
        raise FileNotFoundError("ledger does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup integrity check failed")


def restore(source: Path):
    if using_postgres():
        raise ValueError("Use pg_restore for PostgreSQL restores")
    destination = ledger_path()
    if destination.exists():
        raise FileExistsError("restore requires a new HOLD_LINE_LEDGER path")
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup integrity check failed")
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    (backup if args.operation == "backup" else restore)(args.path)
    print(args.operation.capitalize() + " verified.")
