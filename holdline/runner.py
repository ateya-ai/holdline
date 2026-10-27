from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import uuid4

import httpx

from holdline.config import log_event, review_context, token, url
from holdline.contracts import DependencyUnavailable, Finding, Review, ReviewConflict
from specialists.protocol import collect_finding


async def receiving_request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=2), trust_env=False
        ) as client:
            response = await client.request(
                method,
                url("receiving") + path,
                headers={"Authorization": f"Bearer {token()}"},
                **kwargs,
            )
        if response.status_code == 409:
            raise ReviewConflict("idempotency key belongs to another request")
        if response.status_code not in {200, 201, 404}:
            raise DependencyUnavailable("receiving service unavailable")
        return response
    except httpx.HTTPError as exc:
        log_event("receiving_unavailable", error=type(exc).__name__)
        raise DependencyUnavailable("receiving service unavailable") from exc


def posted_result(row: dict, replayed: bool = False) -> dict:
    return {
        "review": row["payload"],
        "posted": True,
        "replayed": replayed,
        "ledger": {
            k: row[k] for k in ["id", "review_id", "shipment_id", "disposition", "created_at"]
        },
    }


async def existing_review(review_id: str, shipment_id: str, mode: str) -> dict | None:
    response = await receiving_request("GET", "/reviews/" + review_id)
    if response.status_code == 404:
        return None
    row = response.json()
    if row["payload"]["shipment_id"] != shipment_id or row["payload"]["mode"] != mode:
        raise ReviewConflict("idempotency key belongs to another shipment or mode")
    return posted_result(row, replayed=True)


async def _specialist(role: str, payload: dict) -> dict:
    async with asyncio.timeout(20):
        return await collect_finding(url(role), payload)


async def _run_case(shipment_id: str, mode: str, review_id: str) -> dict:
    cached = await existing_review(review_id, shipment_id, mode)
    if cached:
        return cached
    payload = {"shipment_id": shipment_id, "mode": mode, "review_id": review_id}

    async def collect(role):
        try:
            finding = Finding.model_validate(await _specialist(role, payload))
            if (finding.role, finding.shipment_id, finding.review_id) != (
                role,
                shipment_id,
                review_id,
            ):
                raise ValueError("specialist identity mismatch")
            return finding.model_dump()
        except Exception as exc:
            log_event("specialist_failed", role=role, error=type(exc).__name__)
            return Finding(
                role=role,
                shipment_id=shipment_id,
                review_id=review_id,
                verdict="ERROR",
                error="evidence_unavailable",
            ).model_dump()

    values = await asyncio.gather(collect("policy"), collect("shipment"))
    findings = dict(zip(("policy", "shipment"), values, strict=True))
    if all(f["verdict"] != "ERROR" for f in values) and (
        values[0]["policy_hash"] != values[1]["policy_hash"]
        or values[0]["shipment_hash"] != values[1]["shipment_hash"]
    ):
        # A policy update between calls must never combine two different reviews.
        findings = {
            role: Finding(
                role=role,
                shipment_id=shipment_id,
                review_id=review_id,
                verdict="ERROR",
                error="snapshot_mismatch",
            ).model_dump()
            for role in findings
        }
    try:
        produced = Review.model_validate(
            await _specialist("disposition", {**payload, "findings": deepcopy(findings)})
        )
        if (produced.review_id, produced.shipment_id, produced.mode) != (
            review_id,
            shipment_id,
            mode,
        ):
            raise ValueError("review identity mismatch")
        if {k: f.model_dump() for k, f in produced.findings.items()} != findings:
            raise ValueError("disposition changed the evidence")
    except Exception as exc:
        log_event("disposition_failed", error=type(exc).__name__)
        raise DependencyUnavailable(
            "disposition specialist unavailable or returned invalid evidence"
        ) from exc
    response = await receiving_request("POST", "/dispositions", json=produced.model_dump())
    if response.status_code != 200:
        raise DependencyUnavailable("receiving service unavailable")
    row = response.json()
    log_event(
        "disposition_posted",
        ledger_id=row["id"],
        shipment_id=shipment_id,
        disposition=row["disposition"],
    )
    return posted_result(row, replayed=row.get("replayed", False))


async def run_case(shipment_id: str, mode: str = "rehearsal", review_id: str | None = None) -> dict:
    review_id = review_id or str(uuid4())
    context = review_context.set(review_id)
    try:
        async with asyncio.timeout(55):
            return await _run_case(shipment_id, mode, review_id)
    except TimeoutError as exc:
        raise DependencyUnavailable("review deadline exceeded") from exc
    finally:
        review_context.reset(context)
