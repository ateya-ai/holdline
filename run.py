"""Local supervisor. Container deployment starts one service per container."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from holdline.config import HOST, PORTS, celery_broker_url, log_event, token, url
from holdline.evidence import corpus_rules, shipments

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worker", action="store_true", help="also start Celery; requires a running Redis broker"
    )
    args = parser.parse_args()
    try:
        token()
        corpus_rules()
        shipments()
        for port in PORTS.values():
            with socket.socket() as sock:
                sock.bind((HOST, port))
        if args.worker:
            import redis

            redis.Redis.from_url(
                celery_broker_url(), socket_connect_timeout=2, socket_timeout=2
            ).ping()
            os.environ["HOLD_LINE_ASYNC_ENABLED"] = "true"
    except Exception as exc:
        print(
            f"Startup check failed ({type(exc).__name__}). Check your token, policy files, free ports, and Redis when using --worker.",
            file=sys.stderr,
        )
        return 1
    run_dir = Path(os.getenv("HOLD_LINE_RUN_DIR", str(ROOT / ".run")))
    run_dir.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    commands = {
        "mcp": [python, "-m", "mcp_tools.shipment_server"],
        **{
            role: [python, "-m", "specialists.server", role]
            for role in ["policy", "shipment", "disposition"]
        },
        **{
            role: [
                python,
                "-m",
                "uvicorn",
                "app." + ("api" if role == "api" else "receiving") + ":app",
                "--host",
                HOST,
                "--port",
                str(PORTS[role]),
                "--no-access-log",
            ]
            for role in ["receiving", "api"]
        },
    }
    if args.worker:
        commands["worker"] = [
            python,
            "-m",
            "celery",
            "-A",
            "app.celery_app:app",
            "worker",
            "--loglevel=INFO",
            "--concurrency=2",
            "--pool=threads",
        ]
        if os.name == "nt":
            commands["worker"] += ["--pool=solo"]
    processes, handles = {}, []
    stopped = False

    def stop(*_args):
        nonlocal stopped
        stopped = True

    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, stop)
    exit_code = 0
    try:
        for name, command in commands.items():
            handle = (run_dir / (name + ".log")).open("w", encoding="utf-8")
            handles.append(handle)
            processes[name] = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
        deadline = time.monotonic() + 45
        ready = False
        while not stopped:
            dead = {name: p.returncode for name, p in processes.items() if p.poll() is not None}
            if dead:
                log_event("child_exited", children=dead)
                exit_code = 1
                break
            if not ready:
                try:
                    response = httpx.get(url("api") + "/ready", timeout=3, trust_env=False)
                    ready = response.status_code == 200 and response.json().get("ready")
                except httpx.HTTPError:
                    pass
                if ready:
                    print("Holdline ready at " + url("api"), flush=True)
                    print(
                        "Rehearsal uses no model. Check: python -m holdline.live_check", flush=True
                    )
                    print("Logs: " + str(run_dir), flush=True)
                elif time.monotonic() >= deadline:
                    print("Startup timed out. Inspect logs in " + str(run_dir), file=sys.stderr)
                    exit_code = 1
                    break
            time.sleep(0.3)
    finally:
        for p in processes.values():
            if p.poll() is None:
                if os.name != "nt":
                    os.killpg(p.pid, signal.SIGTERM)
                else:
                    p.terminate()
        for p in processes.values():
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(p.pid, signal.SIGKILL)
                else:
                    p.kill()
                p.wait()
        for handle in handles:
            handle.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
