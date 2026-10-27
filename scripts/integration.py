"""Exercise real services, failures, retries, and optionally the durable queue.

Run from the repository root. The default uses a temporary SQLite ledger.
--external checks an already running container stack without stopping services.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, description, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except httpx.HTTPError, ValueError:
            pass
        time.sleep(0.25)
    raise RuntimeError("Timed out: " + description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true")
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    base = (
        os.getenv("HOLD_LINE_API_URL", "http://127.0.0.1:8741")
        if args.external
        else "http://127.0.0.1:8741"
    )
    env = os.environ.copy()
    for key in list(env):
        if (
            key.startswith("OPENAI_")
            or key.startswith("LANGSMITH_")
            or key.startswith("LANGCHAIN_")
            or (not args.external and key.startswith("HOLD_LINE_"))
        ):
            env.pop(key, None)
    token = os.getenv("HOLD_LINE_TOKEN") if args.external else "integration-" + str(uuid4())
    if not token:
        raise RuntimeError("HOLD_LINE_TOKEN must be exported for --external")
    auth = {"Authorization": "Bearer " + token}
    processes, handles = {}, []
    with tempfile.TemporaryDirectory(prefix="holdline-integration-") as tmp:
        env.update(
            HOLD_LINE_TOKEN=token,
            HOLD_LINE_LOAD_DOTENV="false",
            HOLD_LINE_LEDGER=tmp + "/ledger.sqlite",
            HOLD_LINE_RUN_DIR=tmp + "/logs",
            HOLD_LINE_ASYNC_ENABLED=str(args.queue).lower(),
            PYTHONDONTWRITEBYTECODE="1",
        )
        if args.postgres:
            env["DATABASE_URL"] = os.environ.get(
                "TEST_POSTGRES_URL", "postgresql://holdline:holdline@127.0.0.1:55432/holdline"
            )
        else:
            env.pop("DATABASE_URL", None)
        commands = {
            "mcp": [sys.executable, "-m", "mcp_tools.shipment_server"],
            **{
                role: [sys.executable, "-m", "specialists.server", role]
                for role in ["policy", "shipment", "disposition"]
            },
            **{
                role: [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app." + role + ":app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ]
                for role, port in [("receiving", 8742), ("api", 8741)]
            },
            "worker": [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "app.celery_app:app",
                "worker",
                "--loglevel=INFO",
                "--concurrency=1",
                "--pool=threads",
            ],
        }

        def start(name):
            handle = open(tmp + "/" + name + ".log", "a", encoding="utf-8")
            handles.append(handle)
            processes[name] = subprocess.Popen(
                commands[name],
                cwd=ROOT,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        def stop(name):
            p = processes[name]
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()

        try:
            if not args.external:
                for port in range(8741, 8747):
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", port))
                for name in ["mcp", "policy", "shipment", "disposition", "receiving", "api"]:
                    start(name)
            with httpx.Client(base_url=base, headers=auth, trust_env=False, timeout=65) as client:
                wait_for(lambda: client.get("/ready").status_code == 200, "stack readiness")

                def post(shipment, key=None, route="/cases"):
                    return client.post(
                        route,
                        headers={"Idempotency-Key": key or str(uuid4())},
                        json={"shipment_id": shipment, "mode": "rehearsal"},
                    )

                for sid, expected in [
                    ("HL-2201", "READY_FOR_REVIEW"),
                    ("HL-2202", "BLOCKED"),
                    ("HL-2203", "BLOCKED"),
                    ("HL-2204", "BLOCKED"),
                ]:
                    key = str(uuid4())
                    r = post(sid, key)
                    r.raise_for_status()
                    body = r.json()
                    assert body["posted"] and body["review"]["disposition"] == expected
                    assert body["review"]["release_executed"] is False
                    assert body["ledger"]["created_at"]
                    replay = post(sid, key)
                    replay.raise_for_status()
                    assert (
                        replay.json()["ledger"]["id"] == body["ledger"]["id"]
                        and replay.json()["replayed"]
                    )
                    conflict = post("HL-2202" if sid == "HL-2201" else "HL-2201", key)
                    assert conflict.status_code == 409
                print("PASS four business cases, saved evidence, retry identity, conflict handling")
                with httpx.Client(trust_env=False) as anonymous:
                    assert (
                        anonymous.post(base + "/cases", json={"shipment_id": "HL-2201"}).status_code
                        == 401
                    )
                    if not args.external:
                        assert (
                            anonymous.post("http://127.0.0.1:8746/mcp", json={}).status_code == 401
                        )
                assert client.post("/cases", json={"shipment_id": "unknown"}).status_code == 404
                assert (
                    client.post(
                        "/cases", json={"shipment_id": "HL-2201", "mode": "invalid"}
                    ).status_code
                    == 422
                )
                if not args.external:
                    assert (
                        client.post(
                            "/cases", json={"shipment_id": "HL-2201", "mode": "live"}
                        ).status_code
                        == 409
                    )
                key = str(uuid4())
                with ThreadPoolExecutor(max_workers=3) as pool:
                    responses = list(pool.map(lambda _: post("HL-2201", key), range(3)))
                assert all(r.status_code == 200 for r in responses)
                assert len({r.json()["ledger"]["id"] for r in responses}) == 1
                print("PASS authentication, input validation, concurrent duplicate requests")
                if args.queue:
                    key = str(uuid4())
                    queued = post("HL-2204", key, "/jobs")
                    queued.raise_for_status()
                    status = queued.json()["status_url"]
                    if not args.external:
                        assert client.get(status).json()["state"] == "pending"
                        start("worker")
                    complete = wait_for(
                        lambda: (
                            r.json()
                            if (r := client.get(status)).status_code == 200
                            and r.json()["state"] == "complete"
                            else None
                        ),
                        "queue result",
                    )
                    assert complete["result"]["disposition"] == "BLOCKED"
                    replay = post("HL-2204", key, "/jobs")
                    replay.raise_for_status()
                    assert replay.json()["state"] == "complete"
                    print("PASS queued submission before worker start, durable completion, replay")
                if not args.external:
                    for role in ["policy", "disposition", "receiving"]:
                        stop(role)
                        assert client.get("/ready").status_code == 503
                        response = post("HL-2201")
                        if role == "policy":
                            response.raise_for_status()
                            assert response.json()["review"]["disposition"] == "INCOMPLETE"
                        else:
                            assert response.status_code == 503
                        start(role)
                        wait_for(lambda: client.get("/ready").status_code == 200, role + " restart")
                    print("PASS unavailable policy, disposition and ledger; readiness and recovery")
        except Exception:
            if not args.external:
                for name in processes:
                    path = Path(tmp + "/" + name + ".log")
                    print("Service log:", name, file=sys.stderr)
                    print(path.read_text()[-5000:], file=sys.stderr)
            raise
        finally:
            for name in reversed(list(processes)):
                stop(name)
            for handle in handles:
                handle.close()
    print("Integration checks passed.")


if __name__ == "__main__":
    main()
