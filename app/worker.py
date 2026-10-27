import asyncio

from app.celery_app import app
from holdline.contracts import DependencyUnavailable
from holdline.runner import receiving_request, run_case


@app.task(bind=True, name="holdline.run_case", max_retries=3)
def run_case_task(self, shipment_id: str, mode: str, review_id: str) -> dict:
    async def execute():
        await receiving_request("PATCH", "/jobs/" + review_id, json={"state": "running"})
        try:
            result = await run_case(shipment_id, mode, review_id)
        except DependencyUnavailable:
            # Durable status contains an error code, never provider or credential details.
            await receiving_request(
                "PATCH",
                "/jobs/" + review_id,
                json={
                    "state": "pending" if self.request.retries < self.max_retries else "failed",
                    "error": "dependency_unavailable",
                },
            )
            raise
        except Exception:
            await receiving_request(
                "PATCH",
                "/jobs/" + review_id,
                json={"state": "failed", "error": "worker_failed"},
            )
            raise
        await receiving_request("PATCH", "/jobs/" + review_id, json={"state": "complete"})
        return result

    try:
        return asyncio.run(execute())
    except DependencyUnavailable as exc:
        raise self.retry(exc=exc, countdown=min(2**self.request.retries, 10)) from exc
