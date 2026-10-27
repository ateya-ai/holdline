from __future__ import annotations

import json
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import a2a_pb2 as a2a
from google.protobuf.json_format import MessageToDict

from holdline.config import token


def to_dict(message):
    if isinstance(message, tuple):
        message = message[0]

    def numbers(value):
        # Protobuf Struct represents every JSON number as a double.
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {k: numbers(v) for k, v in value.items()}
        if isinstance(value, list):
            return [numbers(v) for v in value]
        return value

    return numbers(MessageToDict(message))


def _part_data(event: dict) -> list[dict]:
    artifact = event.get("artifactUpdate", event.get("artifact_update", {})).get("artifact", {})
    found = []
    for part in artifact.get("parts", []):
        if "data" in part and isinstance(part["data"], dict):
            found.append(part["data"])
    return found


def _state(event: dict) -> str:
    status = event.get("statusUpdate", event.get("status_update", {})).get("status", {})
    return str(status.get("state", ""))


async def collect_finding(base_url: str, payload: dict, bearer_token: str | None = None) -> dict:
    bearer = bearer_token or token()
    headers = {"Authorization": f"Bearer {bearer}"}
    timeout = httpx.Timeout(40.0, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, trust_env=False) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=base_url).get_agent_card()
        if not card.capabilities.streaming:
            raise RuntimeError("specialist does not advertise streaming")
        client = ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(card)
        request = a2a.SendMessageRequest(
            message=a2a.Message(
                message_id=str(uuid4()),
                role=a2a.ROLE_USER,
                parts=[a2a.Part(text=json.dumps(payload))],
            )
        )
        finding = None
        completed = False
        failed = False
        async for item in client.send_message(request):
            event = to_dict(item)
            for candidate in _part_data(event):
                finding = candidate
            state = _state(event)
            if "FAILED" in state:
                failed = True
            if "COMPLETED" in state:
                completed = True
        if failed or not completed or not isinstance(finding, dict):
            raise RuntimeError("specialist evidence is incomplete")
        return finding
