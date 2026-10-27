from uuid import uuid4

import pytest

from app import worker


def test_unexpected_worker_failure_is_durably_failed(monkeypatch):
    updates = []

    async def receiving(method, path, **kwargs):
        updates.append(kwargs["json"])

    async def broken(*args):
        raise ValueError("invalid internal state")

    monkeypatch.setattr(worker, "receiving_request", receiving)
    monkeypatch.setattr(worker, "run_case", broken)
    with pytest.raises(ValueError):
        worker.run_case_task.run("HL-2201", "rehearsal", str(uuid4()))
    assert updates[-1] == {"state": "failed", "error": "worker_failed"}
