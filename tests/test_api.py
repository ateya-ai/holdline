from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import api
from holdline.contracts import DependencyUnavailable, ReviewConflict


@pytest.fixture
def client():
    return TestClient(api.app)


def test_api_input_guards(client):
    auth = {"Authorization": "Bearer test-token"}
    assert client.post("/cases", json={"shipment_id": "HL-2201"}).status_code == 401
    assert client.post("/cases", json={"shipment_id": "unknown"}, headers=auth).status_code == 404
    assert (
        client.post(
            "/cases", json={"shipment_id": "HL-2201", "mode": "invalid"}, headers=auth
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/cases", json={"shipment_id": "HL-2201", "mode": "live"}, headers=auth
        ).status_code
        == 409
    )
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/openapi.json", headers=auth).status_code == 200
    assert client.post("/jobs", json={"shipment_id": "HL-2201"}, headers=auth).status_code == 409


def test_review_identity_and_unavailable_response(client, monkeypatch):
    seen = []

    async def down(shipment_id, mode, review_id):
        seen.append(review_id)
        raise DependencyUnavailable("receiving service unavailable")

    monkeypatch.setattr(api, "run_case", down)
    auth = {"Authorization": "Bearer test-token", "Idempotency-Key": "same-review-123"}
    for _ in range(2):
        response = client.post("/cases", json={"shipment_id": "HL-2201"}, headers=auth)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "3"
        assert response.headers["X-Review-ID"] == seen[-1]
    assert seen[0] == seen[1]
    assert (
        client.post(
            "/cases", json={"shipment_id": "HL-2201"}, headers={**auth, "Idempotency-Key": "bad"}
        ).status_code
        == 400
    )


def test_ledger_transport_failure_maps_to_503(client, monkeypatch):
    async def down(*args, **kwargs):
        raise DependencyUnavailable("receiving service unavailable")

    monkeypatch.setattr(api, "receiving_request", down)
    assert client.get("/ledger", headers={"Authorization": "Bearer test-token"}).status_code == 503


def test_key_conflict_is_409(client, monkeypatch):
    async def conflict(*args):
        raise ReviewConflict("idempotency key belongs to another request")

    monkeypatch.setattr(api, "run_case", conflict)
    assert (
        client.post(
            "/cases",
            json={"shipment_id": "HL-2201"},
            headers={"Authorization": "Bearer test-token"},
        ).status_code
        == 409
    )


def test_unknown_job_is_404(client, monkeypatch):
    import httpx

    async def missing(*args, **kwargs):
        return httpx.Response(404, json={})

    monkeypatch.setattr(api, "receiving_request", missing)
    assert (
        client.get(
            "/jobs/" + str(uuid4()), headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 404
    )


def test_durable_job_registry(ledger):
    from holdline.ledger import reserve_job, update_job

    review_id = str(uuid4())
    body = {"shipment_id": "HL-2201", "mode": "rehearsal"}
    assert reserve_job(ledger, review_id, body)["state"] == "pending"
    assert reserve_job(ledger, review_id, body)["review_id"] == review_id
    with pytest.raises(ReviewConflict):
        reserve_job(ledger, review_id, {**body, "shipment_id": "HL-2202"})
    update_job(ledger, review_id, "complete")
    assert update_job(ledger, review_id, "running")["state"] == "complete"


def test_readiness_fails_on_bad_configuration(client, monkeypatch):
    import httpx

    async def healthy(request):
        return httpx.Response(200, json={"ok": True})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(healthy), **kwargs),
    )

    def invalid():
        raise ValueError("invalid configuration")

    monkeypatch.setattr(api, "corpus_rules", invalid)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["configuration"] is False
