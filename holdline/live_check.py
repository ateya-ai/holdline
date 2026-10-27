"""Check all synthetic cases through the running API without a model call."""

import asyncio
from uuid import uuid4

import httpx

from holdline.config import token, url


async def main() -> int:
    headers = {"Authorization": "Bearer " + token()}
    async with httpx.AsyncClient(timeout=65, trust_env=False) as client:
        ready = await client.get(url("api") + "/ready")
        if ready.status_code != 200 or not ready.json().get("ready"):
            print("Stack is not ready. Check the service logs.")
            return 2
        for shipment, expected in [
            ("HL-2201", "READY_FOR_REVIEW"),
            ("HL-2202", "BLOCKED"),
            ("HL-2203", "BLOCKED"),
            ("HL-2204", "BLOCKED"),
        ]:
            key = "smoke-" + str(uuid4())
            response = await client.post(
                url("api") + "/cases",
                headers={**headers, "Idempotency-Key": key},
                json={"shipment_id": shipment, "mode": "rehearsal"},
            )
            response.raise_for_status()
            result = response.json()
            if (
                not result.get("posted")
                or result["review"]["disposition"] != expected
                or result["review"]["release_executed"] is not False
            ):
                print("Unexpected review result:", shipment)
                return 2
            replay = await client.post(
                url("api") + "/cases",
                headers={**headers, "Idempotency-Key": key},
                json={"shipment_id": shipment, "mode": "rehearsal"},
            )
            replay.raise_for_status()
            if (
                replay.json()["ledger"]["id"] != result["ledger"]["id"]
                or not replay.json()["replayed"]
            ):
                print("Retry did not return the original result:", shipment)
                return 2
            print(shipment, expected, "recorded; retry verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
        print("Smoke check failed:", type(exc).__name__)
        raise SystemExit(2) from exc
