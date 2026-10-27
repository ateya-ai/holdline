from __future__ import annotations

import json
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor
from a2a.server.tasks import TaskUpdater
from a2a.types import a2a_pb2 as a2a
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Value

from holdline.config import log_event, review_context
from holdline.contracts import Finding, Review
from holdline.decide import judge
from holdline.evidence import fallback_explanation, policy_finding, shipment_finding, skill
from holdline.mcp_client import get_shipment
from holdline.model import explain


def _message(text: str) -> a2a.Message:
    return a2a.Message(message_id=str(uuid4()), role=a2a.ROLE_AGENT, parts=[a2a.Part(text=text)])


def _data_part(data: dict) -> a2a.Part:
    return a2a.Part(data=ParseDict(data, Value()))


class HoldlineExecutor(AgentExecutor):
    def __init__(self, role: str):
        self.role = role

    async def execute(self, context, event_queue):
        task_id = context.task_id or str(uuid4())
        context_id = context.context_id or str(uuid4())
        updater = TaskUpdater(event_queue, task_id, context_id)
        await event_queue.enqueue_event(
            a2a.Task(
                id=task_id,
                context_id=context_id,
                status=a2a.TaskStatus(state=a2a.TASK_STATE_SUBMITTED),
                history=[context.message],
            )
        )
        context_token = None
        try:
            payload = json.loads(context.get_user_input())
            mode = payload.get("mode", "rehearsal")
            context_token = review_context.set(payload.get("review_id"))
            log_event("specialist_started", role=self.role)
            if mode not in ("rehearsal", "live"):
                raise ValueError("Unknown mode")
            await updater.update_status(
                a2a.TASK_STATE_WORKING,
                _message(f"{self.role} started. Mode: {mode}."),
            )
            if self.role == "policy":
                record = await get_shipment(str(payload["shipment_id"]))
                result = policy_finding(record, payload["review_id"])
            elif self.role == "shipment":
                record = await get_shipment(str(payload["shipment_id"]))
                result = shipment_finding(record, payload["review_id"])
            else:
                result = await self._disposition(payload, mode)
            await updater.add_artifact([_data_part(result)], name="finding", last_chunk=True)
            await updater.complete(_message(f"{self.role} finished."))
        except Exception as exc:
            await updater.update_status(
                a2a.TASK_STATE_FAILED,
                _message(f"{type(exc).__name__}: the specialist could not finish."),
            )

        finally:
            if context_token is not None:
                review_context.reset(context_token)

    async def _disposition(self, payload: dict, mode: str) -> dict:
        findings = {
            k: Finding.model_validate(v).model_dump() for k, v in payload["findings"].items()
        }
        disposition = judge(findings)
        instructions = skill()
        fallback = fallback_explanation(disposition, findings)
        explanation, source = await explain(
            instructions["prompt"],
            json.dumps(
                {
                    "shipment_id": payload["shipment_id"],
                    "disposition": disposition,
                    "release_executed": False,
                    "findings": findings,
                }
            ),
            mode,
            fallback,
        )
        return Review(
            review_id=payload["review_id"],
            shipment_id=payload["shipment_id"],
            disposition=disposition,
            findings=findings,
            mode=mode,
            skill_hash=instructions["sha256"],
            explanation=explanation,
            explanation_source=source,
        ).model_dump()

    async def cancel(self, context, event_queue):
        await TaskUpdater(event_queue, context.task_id, context.context_id).update_status(
            a2a.TASK_STATE_CANCELED,
            _message("Task cancelled."),
        )
