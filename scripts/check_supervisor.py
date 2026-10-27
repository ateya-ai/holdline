"""Verify the local supervisor's documented shutdown and crash behavior."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    for port in range(8741, 8747):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
    with tempfile.TemporaryDirectory(prefix="holdline-supervisor-") as tmp:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("HOLD_LINE_", "OPENAI_", "LANGSMITH_", "LANGCHAIN_"))
            and k != "DATABASE_URL"
        }
        env.update(
            HOLD_LINE_TOKEN="supervisor-check-only",
            HOLD_LINE_LOAD_DOTENV="false",
            HOLD_LINE_LEDGER=tmp + "/ledger.sqlite",
            HOLD_LINE_RUN_DIR=tmp + "/logs",
            PYTHONDONTWRITEBYTECODE="1",
        )
        for crash in [False, True]:
            with open(tmp + "/supervisor.log", "w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [sys.executable, "run.py"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    ready = False
                    with httpx.Client(trust_env=False, timeout=3) as client:
                        for _ in range(120):
                            if process.poll() is not None:
                                break
                            try:
                                if client.get("http://127.0.0.1:8741/ready").status_code == 200:
                                    ready = True
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(0.25)
                    if not ready:
                        raise RuntimeError("supervisor did not become ready")
                    if crash:
                        listing = subprocess.check_output(
                            ["ps", "-axo", "pid=,ppid=,command="], text=True
                        )
                        child = None
                        for line in listing.splitlines():
                            values = line.strip().split(maxsplit=2)
                            if (
                                len(values) == 3
                                and values[1] == str(process.pid)
                                and "mcp_tools.shipment_server" in values[2]
                            ):
                                child = int(values[0])
                                break
                        if child is None:
                            raise RuntimeError("MCP child not found")
                        os.kill(child, signal.SIGKILL)
                    else:
                        subprocess.run(
                            [sys.executable, "-m", "holdline.live_check"],
                            cwd=ROOT,
                            env=env,
                            check=True,
                        )
                        process.send_signal(signal.SIGTERM)
                    process.wait(timeout=20)
                    assert process.returncode == (1 if crash else 0)
                    for port in range(8741, 8747):
                        with socket.socket() as sock:
                            assert sock.connect_ex(("127.0.0.1", port)) != 0
                finally:
                    if process.poll() is None:
                        process.send_signal(signal.SIGTERM)
                        try:
                            process.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
    print("Supervisor smoke, clean shutdown, crash status and listener cleanup passed.")


if __name__ == "__main__":
    main()
