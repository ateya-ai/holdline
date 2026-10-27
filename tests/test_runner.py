from uuid import uuid4

import httpx
import pytest

from holdline import runner
from holdline.contracts import DependencyUnavailable, ReviewConflict
from holdline.decide import judge
from holdline.evidence import (
    fallback_explanation,
    policy_finding,
    rehearse,
    shipment_finding,
    shipment_record,
)


@pytest.fixture
def services(monkeypatch):
    store = {}
    calls = []

    async def receiving(method, path, **kwargs):
        if method == "GET":
            review_id = path.rsplit("/", 1)[-1]
            return (
                httpx.Response(200, json=store[review_id])
                if review_id in store
                else httpx.Response(404, json={})
            )
        payload = kwargs["json"]
        calls.append(payload)
        row = {
            "id": len(store) + 1,
            "review_id": payload["review_id"],
            "shipment_id": payload["shipment_id"],
            "disposition": payload["disposition"],
            "payload": payload,
            "created_at": "2026-10-26T00:00:00+00:00",
        }
        store[payload["review_id"]] = row
        return httpx.Response(200, json=row)

    async def specialist(role, payload):
        if role in {"policy", "shipment"}:
            fn = policy_finding if role == "policy" else shipment_finding
            return fn(shipment_record(payload["shipment_id"]), payload["review_id"])
        result = rehearse(payload["shipment_id"], payload["review_id"])
        result["findings"] = payload["findings"]
        result["disposition"] = judge(payload["findings"])
        result["explanation"] = fallback_explanation(result["disposition"], payload["findings"])
        return result

    monkeypatch.setattr(runner, "receiving_request", receiving)
    monkeypatch.setattr(runner, "_specialist", specialist)
    return store, calls, specialist


async def test_retries_return_saved_result(services):
    review_id = str(uuid4())
    first = await runner.run_case("HL-2201", review_id=review_id)
    second = await runner.run_case("HL-2201", review_id=review_id)
    assert first["ledger"]["id"] == second["ledger"]["id"]
    assert second["replayed"] is True
    assert len(services[1]) == 1
    with pytest.raises(ReviewConflict):
        await runner.run_case("HL-2202", review_id=review_id)


@pytest.mark.parametrize(
    "change",
    [
        {"shipment_id": "HL-2202"},
        {"disposition": "BLOCKED"},
        {"review_id": str(uuid4())},
        {"mode": "live"},
        {"release_executed": True},
    ],
)
async def test_faulty_disposition_never_posted(monkeypatch, services, change):
    original = services[2]

    async def faulty(role, payload):
        result = await original(role, payload)
        if role == "disposition":
            result.update(change)
        return result

    monkeypatch.setattr(runner, "_specialist", faulty)
    with pytest.raises(DependencyUnavailable):
        await runner.run_case("HL-2201")
    assert not services[1]


async def test_disposition_cannot_replace_findings(monkeypatch, services):
    original = services[2]

    async def faulty(role, payload):
        result = await original(role, payload)
        if role == "disposition":
            result["findings"]["policy"]["facts"] = "Untrusted replacement text"
        return result

    monkeypatch.setattr(runner, "_specialist", faulty)
    with pytest.raises(DependencyUnavailable):
        await runner.run_case("HL-2201")
    assert not services[1]


async def test_missing_policy_produces_incomplete(monkeypatch, services):
    original = services[2]

    async def down(role, payload):
        if role == "policy":
            raise ConnectionError("unreachable")
        return await original(role, payload)

    monkeypatch.setattr(runner, "_specialist", down)
    result = await runner.run_case("HL-2201")
    assert result["posted"]
    assert result["review"]["disposition"] == "INCOMPLETE"


async def test_disposition_down_never_posts(monkeypatch, services):
    original = services[2]

    async def down(role, payload):
        if role == "disposition":
            raise ConnectionError("unreachable")
        return await original(role, payload)

    monkeypatch.setattr(runner, "_specialist", down)
    with pytest.raises(DependencyUnavailable):
        await runner.run_case("HL-2201")
    assert not services[1]


async def test_receiving_transport_failure_is_sanitized(monkeypatch):
    async def down(self, request):
        raise httpx.ConnectError("secret connection details")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", down)
    with pytest.raises(DependencyUnavailable, match="receiving service unavailable"):
        await runner.receiving_request("GET", "/ledger")
