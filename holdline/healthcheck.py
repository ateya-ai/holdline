"""Per-role health probes for containers and process managers."""

import socket
import sys

import httpx

from holdline.config import PORTS


def main(role: str) -> int:
    if role == "worker":
        from app.celery_app import app

        return (
            0 if app.control.ping(destination=["celery@" + socket.gethostname()], timeout=3) else 1
        )
    path = "/ready" if role == "api" else "/health"
    try:
        response = httpx.get(f"http://127.0.0.1:{PORTS[role]}{path}", timeout=4, trust_env=False)
        return 0 if response.status_code == 200 else 1
    except httpx.HTTPError, KeyError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "api"))
