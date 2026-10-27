import itertools
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from holdline.config import authorization_ok
from holdline.contracts import ReviewConflict
from holdline.decide import judge
from holdline.evidence import rehearse
from holdline.ledger import connect, get_review, list_dispositions, post_disposition


@pytest.mark.parametrize(
    "shipment, expected",
    [
        ("HL-2201", "READY_FOR_REVIEW"),
        ("HL-2202", "BLOCKED"),
        ("HL-2203", "BLOCKED"),
        ("HL-2204", "BLOCKED"),
    ],
)
def test_business_cases(shipment, expected, ledger):
    result = rehearse(shipment)
    assert result["disposition"] == expected
    assert result["release_executed"] is False
    post_disposition(ledger, result)
    row = get_review(ledger, result["review_id"])
    assert row["created_at"]
    assert row["payload"] == result
    assert row["payload"]["findings"]["policy"]["policy_hash"]


@pytest.mark.parametrize(
    "policy, shipment", list(itertools.product(["CLEAR", "BLOCK", "ERROR", None], repeat=2))
)
def test_verdict_precedence(policy, shipment):
    expected = (
        "INCOMPLETE"
        if policy not in {"CLEAR", "BLOCK"} or shipment not in {"CLEAR", "BLOCK"}
        else ("BLOCKED" if "BLOCK" in (policy, shipment) else "READY_FOR_REVIEW")
    )
    assert judge({"policy": {"verdict": policy}, "shipment": {"verdict": shipment}}) == expected


def test_authentication():
    assert not authorization_ok(None)
    assert not authorization_ok("Bearer wrong")
    assert authorization_ok("Bearer test-token")


def test_idempotent_write_and_conflict(ledger):
    result = rehearse("HL-2201")
    first = post_disposition(ledger, result)
    assert post_disposition(ledger, result) == first
    assert len(list_dispositions(ledger)) == 1
    with pytest.raises(ReviewConflict):
        post_disposition(ledger, rehearse("HL-2202", result["review_id"]))
    assert len(list_dispositions(ledger)) == 1


def test_concurrent_retries_create_one_row():
    result = rehearse("HL-2201")

    def write(_):
        conn = connect()
        try:
            return post_disposition(conn, result)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        ids = list(pool.map(write, range(10)))
    assert len(set(ids)) == 1
    conn = connect()
    try:
        assert len(list_dispositions(conn)) == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    "change",
    [
        {"release_executed": True},
        {"disposition": "RELEASED"},
        {"mode": "invented"},
        {"shipment_id": "HL-2202"},
        {"review_id": "bad-id"},
        {"findings": {}},
        {"disposition": "BLOCKED"},
    ],
)
def test_invalid_review_never_reaches_ledger(change, ledger):
    result = {**rehearse("HL-2201"), **change}
    with pytest.raises((ValidationError, ValueError)):
        post_disposition(ledger, result)
    assert not list_dispositions(ledger)


def test_receiving_requires_auth_and_consistent_evidence():
    from app.receiving import app

    client = TestClient(app)
    auth = {"Authorization": "Bearer test-token"}
    body = rehearse("HL-2201")
    assert client.post("/dispositions", json=body).status_code == 401
    for change in [
        {"release_executed": True},
        {"disposition": "RELEASED"},
        {"disposition": "BLOCKED"},
        {"shipment_id": "unknown"},
        {"mode": "made-up"},
    ]:
        assert (
            client.post("/dispositions", json={**body, **change}, headers=auth).status_code == 422
        )
    first = client.post("/dispositions", json=body, headers=auth)
    assert first.status_code == 200
    second = client.post("/dispositions", json=body, headers=auth)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["payload"] == first.json()["payload"]
    assert client.get("/ledger", headers=auth).json()["dispositions"][0]["created_at"]


def test_pagination(ledger):
    for _ in range(3):
        post_disposition(ledger, rehearse("HL-2201"))
    first = list_dispositions(ledger, limit=2)
    second = list_dispositions(ledger, after=first[-1]["id"], limit=2)
    assert len(first) == 2 and len(second) == 1
    assert first[-1]["id"] < second[0]["id"]


def test_mcp_authentication():
    from mcp_tools.shipment_server import build_app

    with TestClient(build_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/mcp", json={}).status_code == 401
        assert (
            client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )


def test_specialist_discovery_and_authentication():
    from specialists.server import build_app

    client = TestClient(build_app("policy"))
    assert client.get("/health").status_code == 200
    assert client.get("/.well-known/agent-card.json").status_code == 200
    assert client.post("/", json={}).status_code == 401


def test_role_url_override(monkeypatch):
    from holdline.config import url

    monkeypatch.setenv("HOLD_LINE_POLICY_URL", "http://policy:8743/")
    assert url("policy") == "http://policy:8743"
